from __future__ import annotations

import ast
import code
from collections.abc import Callable
from concurrent.futures import Future
from contextlib import closing
from crystal import __version__ as crystal_version
from crystal.model import Project
from crystal.tests.util.runner import run_test_coro
from crystal.util.ai_agents import ai_agent_detected, mcp_shell_server_detected
from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.headless import is_headless_mode
from crystal.util.pipes import create_selectable_pipe
from crystal.util.readers import InterruptableReader
from crystal.util.test_mode import tests_are_running
from crystal.util.xfunctools import partial2
import crystal.util.xsite as site
from crystal.util.xthreading import (
    bg_affinity, bg_call_later, fg_affinity, fg_call_and_wait, has_foreground_thread,
    NoForegroundThreadError,
)
from crystal.util.xtraceback import format_exception_for_terminal_user
from functools import partial
import getpass
import inspect
import os
import selectors
import signal
import sys
from threading import Lock, Thread
import time
import types
from typing import (
    Any, IO, Literal, Optional, TextIO, TypeAlias, TYPE_CHECKING,
    TypeVar, assert_never,
)
from typing_extensions import override

if TYPE_CHECKING:
    from crystal.browser import MainWindow


_R = TypeVar('_R')


# Additional time to wait after running a command
# to observe any immediately-scheduled asynchronous UI updates
_ASYNC_UI_UPDATE_DELAY = 50 / 1000  # secs

# Advise to AI agents RE how many milliseconds are best to wait for terminal output.
_OUTPUT_DELAY_MS_ADVISE = 'use 500 for UI actions, 200 for non-UI actions'


class Shell:
    def __init__(self) -> None:
        """
        Creates a new shell but does not start it.
        
        Start the shell by calling start().
        """
        self._started = False
        self._stopping = False
        self._shell_thread = None  # type: Optional[Thread]
        
        # Setup proxy variables for shell
        _Proxy._patch_help()
        self._project_proxy = _Proxy(f'<unset Project proxy>')
        self._window_proxy = _Proxy(f'<unset MainWindow proxy>')
        
        # Ensure help(), exit(), and quit() are available,
        # even when running as a frozen .app or .exe
        site.sethelper()  # help
        site.setquit()  # quit, exit
        
        self._ensure_guppy_available()
    
    @staticmethod
    def _ensure_guppy_available() -> None:
        # Explicitly import guppy to tell py2app and py2exe to include it
        # when building a binary
        try:
            import guppy  # type: ignore[reportMissingImports]
            import guppy.heapy  # type: ignore[reportMissingImports]
            import guppy.heapy.Classifiers  # type: ignore[reportMissingImports]
            import guppy.heapy.Doc  # type: ignore[reportMissingImports]
            import guppy.heapy.ImpSet  # type: ignore[reportMissingImports]
            import guppy.heapy.OutputHandling  # type: ignore[reportMissingImports]
            import guppy.heapy.Part  # type: ignore[reportMissingImports]
            import guppy.heapy.Path  # type: ignore[reportMissingImports]
            import guppy.heapy.RefPat  # type: ignore[reportMissingImports]
            import guppy.heapy.Target  # type: ignore[reportMissingImports]
            import guppy.heapy.UniSet  # type: ignore[reportMissingImports]
            import guppy.heapy.Use  # type: ignore[reportMissingImports]
            import guppy.heapy.View  # type: ignore[reportMissingImports]
        except ImportError:
            pass
    
    @classmethod
    def handles_ctrl_c(cls) -> bool:
        """
        Whether the shell handles Ctrl-C internally.
        
        If it does not handle it internally, the CALLER of Shell is
        responsible for implementing Ctrl-C handling.
        """
        return _CrystalInteractiveConsole.handles_ctrl_c()
    
    def start(self, *, wait_for_banner: bool = True) -> None:
        """
        Starts the shell in a separate thread.
        """
        if self._started:
            return
        
        if not has_foreground_thread():
            raise ValueError('Expected there to be a foreground thread when starting a Shell')
        
        banner_printed = Future()  # type: Future[Literal[True]]
        
        # NOTE: Keep the process alive while the shell is running
        self._shell_thread = bg_call_later(
            partial2(self._run, banner_printed),
            name='Shell.run',
            daemon=False,
        )
        self._started = True
        
        # Wait for banner to be printed
        if wait_for_banner:
            banner_printed._cr_declare_no_deadlocks = True  # type: ignore[attr-defined]
            banner_printed.result()
    
    def is_running(self) -> bool:
        """
        Returns True if the shell thread is currently running, False otherwise.
        """
        if not self._started:
            return False
        if self._shell_thread is None:
            return False
        return self._shell_thread.is_alive()
    
    def join(self) -> None:
        """
        Waits for the shell thread to stop running.
        """
        if not self.is_running():
            return
        assert self._shell_thread is not None
        self._shell_thread.join()
    
    def stop_soon(self) -> None:
        """
        Requests that the shell exit.
        """
        if not self.is_running():
            return
        
        # Interrupt the shell REPL
        self._stopping = True
        os.kill(os.getpid(), signal.SIGINT)
    
    @capture_crashes_to_stderr
    @bg_affinity
    def _run(self, banner_printed: Future[Literal[True]]) -> None:
        # Define exit instructions,
        # based on site.setquit()'s definition in Python 3.8
        if os.sep == '\\':
            eof = 'Ctrl-Z plus Return'
        else:
            eof = 'Ctrl-D (i.e. EOF)'
        exit_instructions = 'Use {}() or {} to exit'.format('exit', eof)
        
        if ai_agent_detected() and not is_headless_mode():
            from crystal.ui.nav import T
            from crystal.util.controls import click, screenshot, TreeItem
            from crystal.tests.util.wait import wait_for
            import wx
            
            agent_instructions = (
                'AI agents:\n'
                '- Use `T` to view/control the UI. Learn more with `help(T)`.\n'
                '- Use `click(window)` to click a button.\n'
                '- Use `await screenshot()` to capture the UI as an image.\n'
                '- Run multi-line code with exec(): exec("for i in range(5):\\n    print(i)")\n'
                # TODO: Wait until agents _regularly_ try to run async code before 
                #       spending banner space explaining how to do so.
                #'- For async multi-line code: use exec() to define async def, then await it.\n'
                '- Use Python control flow (for/while loops, if statements, etc.) to batch operations.\n'
            ) + (
                'terminal_operate users:\n'
                f'- output_delay_ms: {_OUTPUT_DELAY_MS_ADVISE}\n'
                '- Multi-line inputs are truncated to first line only. Use a single-line exec() for multi-line inputs.\n'
                '- Type an empty line using "input": " " (1 space)\n'
                if mcp_shell_server_detected()
                else ''
            )
            agent_locals = dict(
                # Referenced in agent instructions
                T=T,
                click=partial2(click, sync=False),
                screenshot=screenshot,
                
                # Referenced in help(T)
                wait_for=wait_for,
                
                # Referenced in CodeExpressions returned/printed by Navigators
                wx=wx,
                TreeItem=TreeItem,
            )
        else:
            agent_instructions = ''
            agent_locals = {}
        
        # Disable use of pager by help(...) if AI agent detected
        if ai_agent_detected():
            # NOTE: Setting MANPAGER rather than PAGER because the former has
            #       higher priority, according to pydoc documentation
            os.environ['MANPAGER'] = 'cat'
        
        python_version = '.'.join([str(x) for x in sys.version_info[:3]])
        try:
            fg_interact(
                banner=(
                    f'Crystal {crystal_version} (Python {python_version})\n'
                    'Type "help" for more information.\n'
                    'Variables "project" and "window" are available.\n'
                    f'{agent_instructions}'
                    f'{exit_instructions}.'
                ),
                local=dict(
                    project=self._project_proxy,
                    window=self._window_proxy,
                    **agent_locals,
                ),
                exitmsg='now waiting for all windows to close...',
                banner_printed=banner_printed,
                shell_stopping_func=lambda: self._stopping,
            )
        except SystemExit:
            pass
    
    def attach(self, project: Project | None, window: MainWindow | None) -> None:
        """
        Initializes the "project" and "window" variables in the shell.
        """
        self._project_proxy._initialize_proxy(project, reinit_okay=True, unset_okay=True)
        self._window_proxy._initialize_proxy(window, reinit_okay=True, unset_okay=True)
    
    def detach(self) -> None:
        """
        Uninitializes the "project" and "window" variables in the shell.
        """
        self._project_proxy._initialize_proxy(None, reinit_okay=True, unset_okay=True)
        self._window_proxy._initialize_proxy(None, reinit_okay=True, unset_okay=True)


class _Proxy:
    _unset_repr: str
    _value: Optional[object]
    
    @staticmethod
    def _patch_help() -> None:
        """Patch help() such that it understands _Proxy objects."""
        import pydoc
        old_resolve = pydoc.resolve  # capture
        def new_resolve(thing, *args, **kwargs):
            if isinstance(thing, _Proxy):
                if thing._value is None:
                    return old_resolve(thing, *args, **kwargs)  # the _Proxy itself
                else:
                    return old_resolve(thing._value, *args, **kwargs)
            else:
                return old_resolve(thing, *args, **kwargs)
        pydoc.resolve = new_resolve  # monkeypatch
    
    def __init__(self, unset_repr: str) -> None:
        super().__setattr__('_unset_repr', unset_repr)
        super().__setattr__('_value', None)
    
    def _initialize_proxy(self,
            value,
            *, reinit_okay: bool=False,
            unset_okay: bool=False,
            ) -> None:
        if value is None:
            if not unset_okay:
                raise ValueError('Must initialize proxy with non-None value')
        if self._value is not None:
            if not reinit_okay:
                raise ValueError('Proxy already initialized')
        super().__setattr__('_value', value)
    
    def __repr__(self) -> str:
        value = self._value  # cache
        if value is None:
            return self._unset_repr
        else:
            return repr(value)
    
    def __dir__(self):
        value = self._value  # cache
        if value is None:
            return super().__dir__()
        else:
            return dir(value)
    
    def __setattr__(self, attr_name: str, attr_value):
        value = self._value  # cache
        if value is None:
            raise AttributeError
        else:
            setattr(value, attr_name, attr_value)
    
    def __getattr__(self, attr_name: str):
        value = self._value  # cache
        if value is None:
            raise AttributeError
        else:
            return getattr(value, attr_name)


@bg_affinity
def fg_interact(
        banner=None,
        local=None,
        exitmsg=None,
        banner_printed: Future[Literal[True]] | None = None,
        shell_stopping_func: Callable[[], bool] = lambda: False,
        ) -> None:
    """
    Runs Crystal's interactive shell, on a background thread,
    with code still evaluated on the foreground thread.
    
    See _CrystalInteractiveConsole's docstring for full information
    about the features and capabilities of Crystal's shell.
    """
    
    console = _CrystalInteractiveConsole(
        local,
        banner_printed=banner_printed,
        shell_stopping_func=shell_stopping_func,
    )
    with closing(console):
        try:
            console.interact(banner, exitmsg='')
        finally:
            if not _main_loop_has_exited():
                if is_headless_mode() or ai_agent_detected():
                    # Exit the entire process when the shell exits
                    os._exit(0)
                else:
                    console.write('%s\n' % exitmsg)


ConsoleImplementation: TypeAlias = Literal[
    # Advanced Python REPL
    # - Used whenever possible when Python >= 3.13
    # - Ctrl-C interrupt prints "KeyboardInterrupt"
    # - Supports line editing (with arrow keys, etc)
    'py_repl',
    
    # Basic Python REPL, but no Ctrl-C support
    # - Used when Python <= 3.12 or PYTHON_BASIC_REPL=1
    # - Ctrl-C interrupt exits program,
    #   assuming caller implements that behavior for Ctrl-C
    # - Supports line editing (with arrow keys, etc) when readline available
    'basic_repl',
    
    # Basic Python REPL, with Ctrl-C support but no line editing
    # - Currently unused (except by automated tests)
    # - Ctrl-C interrupt prints "KeyboardInterrupt"
    # - Does NOT support line editing (with arrow keys, etc)
    'basic_repl_interruptible',
    
    # Standard stream based REPL, which only echos complete input lines
    # - Used when running under MCP shell-server (terminal_operate),
    #   regardless of Python version
    #     - Suppresses automatic echo to avoid newline injection issues
    #     - Writes everything to a consistent stream (stdout) to reduce
    #       output delay from 150ms -> 60ms (40% improvement)
    # - Ctrl-C interrupt prints "KeyboardInterrupt"
    #     - BUT ignores Ctrl-C if typed while waiting for input at prompt
    # - Does NOT support line editing (with arrow keys, etc)
    'stdio_buffered',
]

class _CrystalInteractiveConsole(code.InteractiveConsole):
    """
    Extends code.InteractiveConsole with several capabilities:
    - Background Operation: Runs on a background thread
      (to avoid blocking the foreground thread), while still
      excuting code on the foreground thread
    - Async Support: Supports top-level await expressions, similar to
      asyncio.AsyncIOInteractiveConsole, that use Crystal's internal
      awaitable testing utilities. Awaitables that rely on the
      asyncio event loop are NOT supported.
    - Simplified Tracebacks: Noisy Crystal-internal frames are omitted
      from tracebacks, using format_exception_for_terminal_user
    - Multi-Line Editing & Paste: Similar to
      _pyrepl.simple_interact.run_multiline_interactive_console
    - PYTHONSTARTUP: Will execute a startup file specified in $PYTHONSTARTUP
      if defined, similar to sys._baserepl() and _pyrepl.main.interactive_console
    - AI Agent Assistance: When an AI agent is detected:
        - UI changes are detected and printed automatically
          when caused by a command the agent ran
        - Warnings are printed for common agent mistakes
    
    Partially supports:
    - Color
        - Colored prompts and code syntax highlighting from pyrepl is available
        - Colored tracebacks, from _pyrepl.console.InteractiveColoredConsole
          and traceback.format_exception(..., colorize=True), are NOT yet supported
    
    Retains:
    - Line Editing Support: Left/right arrow keys can be used to edit within a line
    - Ctrl-C Interruption Support: When handles_ctrl_c=True, handles Ctrl-C
      specially to support typical KeyboardInterrupt behavior of a Python REPL.
      Otherwise the caller should provide its own Ctrl-C handling
    """
    # For implementation() == 'basic_repl_interruptible' only
    _interruptible_stdin: InterruptableReader | None
    
    # For implementation() == 'py_repl' only
    _pyrepl_multiline_input: Callable[[], str] | None
    _pyrepl_interrupted: bool
    _pyrepl_is_active: bool
    _output_handler: _OutputBuffer | None
    _original_stdout: TextIO | None
    _original_stderr: TextIO | None
    
    def __init__(self,
            *args,
            banner_printed: Future[Literal[True]] | None = None,
            shell_stopping_func: Callable[[], bool] = lambda: False,
            **kwargs
            ) -> None:
        super().__init__(*args, **kwargs)
        self._first_write = True
        self._first_input = True
        self.banner_printed = banner_printed or Future()  # type: Future[Literal[True]]
        self._shell_stopping_func = shell_stopping_func
        
        # Track whether help(T) has been called (for AI agents)
        self._help_t_called = False
        self._help_t_warning_printed = False
        
        # Allow top-level await in code lines
        self.compile.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
        
        if self.implementation() == 'basic_repl':
            # Try to enable readline support for line editing (with arrow keys, etc)
            try:
                import readline
            except ImportError:
                pass
        
        if self.implementation() == 'py_repl':
            import _pyrepl.readline
            from _pyrepl.simple_interact import (
                _more_lines,
                _strip_final_indent,
            )
            
            # Emulate _pyrepl.simple_interact.run_multiline_interactive_console
            more_lines = partial(_more_lines, self)  # cache
            ps1 = getattr(sys, 'ps1', '>>> ')  # capture, cache
            ps2 = getattr(sys, 'ps2', '... ')  # capture, cache
            self._pyrepl_multiline_input = lambda: _strip_final_indent(
                _pyrepl.readline.multiline_input(more_lines, ps1, ps2)
            )
        else:
            self._pyrepl_multiline_input = None
        self._pyrepl_interrupted = False
        
        self._open()
    
    def _open(self) -> None:
        # Create interrupt pipe for handling Ctrl-C,
        # in non-blocking mode so that it can be used with signal.set_wakeup_fd()
        self._interrupt_pipe = create_selectable_pipe(blocking=False)
        
        if self.implementation() == 'basic_repl_interruptible':
            # Wrap stdin in InterruptableReader
            self._interruptible_stdin = InterruptableReader(
                sys.stdin,
                self._interrupt_pipe.readable_end
            )
        else:
            self._interruptible_stdin = None
        
        # Buffer writes to stdout/stderr while pyrepl is active
        # to prevent garbled output from non-shell threads
        if self.implementation() == 'py_repl':
            self._pyrepl_is_active = False
            self._output_handler = _OutputBuffer()
            
            # Wrap stdout and stderr to defer output
            if True:
                self._original_stdout = sys.stdout
                sys.stdout = _DeferredWriter(
                    self._original_stdout,
                    self._output_handler,
                    lambda: self._pyrepl_is_active
                )  # type: ignore[assignment]
                
                self._original_stderr = sys.stderr
                sys.stderr = _DeferredWriter(
                    self._original_stderr,
                    self._output_handler,
                    lambda: self._pyrepl_is_active
                )  # type: ignore[assignment]
        else:
            self._output_handler = None
            self._original_stdout = None
            self._original_stderr = None
        
        # Customize how unhandled exceptions are printed
        self._old_sys_excepthook = sys.excepthook
        sys.excepthook = lambda *args: self._sys_excepthook(*args)
    
    def close(self) -> None:
        sys.excepthook = self._old_sys_excepthook
        
        # Restore original stdout/stderr
        if self._original_stdout is not None:
            sys.stdout = self._original_stdout
        if self._original_stderr is not None:
            sys.stderr = self._original_stderr
        
        # Clean up interrupt pipe
        try:
            self._interrupt_pipe.readable_end.close()
        except OSError:
            pass
        try:
            self._interrupt_pipe.writable_end.close()
        except OSError:
            pass
    
    # === REPL ===
    
    @classmethod
    def implementation(cls) -> ConsoleImplementation:
        """
        Console implementation style to use.
        
        See ConsoleImplementation for more information.
        """
        # Allow tests to force a particular implemenation
        if (impl := os.environ.get('CRYSTAL_CONSOLE_IMPL')) is not None:
            return impl  # type: ignore[return-value]  # don't validate
        
        # Should 'stdio_buffered' be used?
        if mcp_shell_server_detected() and not tests_are_running():
            return 'stdio_buffered'
        
        # Is pyrepl usable and should it be used?
        if sys.version_info >= (3, 13):
            # _pyrepl module only available in Python 3.13+
            
            # NOTE: Duplicates asyncio/__main__.py logic to determine
            #       whether pyrepl should be used
            if os.getenv('PYTHON_BASIC_REPL'):
                # Honor Python's PYTHON_BASIC_REPL environment variable to
                # force the use of the basic REPL
                CAN_USE_PYREPL = False
            else:
                # NOTE: Notably, cannot use pyrepl if stdin is not a TTY
                from _pyrepl.main import CAN_USE_PYREPL  # type: ignore[no-redef]
            if CAN_USE_PYREPL:
                return 'py_repl'
        
        # Fallback to basic REPL
        return 'basic_repl'
    
    @override
    @bg_affinity  # expects to run on a background thread
    def interact(self, banner=None, exitmsg=None):
        super().interact(banner=banner, exitmsg=exitmsg)
    
    # === Read ===
    
    @override
    @bg_affinity
    def raw_input(self, prompt: str = '') -> str:
        """
        Reads a line from standard input, minus the trailing newline.
        
        Raises:
        * EOFError -- if the user pressed Ctrl-D to close standard input
        * KeyboardInterrupt -- if the user pressed Ctrl-C to interrupt the program
        """
        if self._first_input:
            fg_call_and_wait(lambda: self._configure_ctrl_c_to_interrupt_stdin_readline())
            
            # Configure default Reader, if using pyrepl
            if self.implementation() == 'py_repl':
                from _pyrepl.commands import Command
                from _pyrepl.console import Event
                import _pyrepl.readline
                
                # NOTE: _get_reader() may alter signal handlers during its first call,
                #       which must be done on the foreground thread
                reader = fg_call_and_wait(lambda: _pyrepl.readline._get_reader())
                
                # Register custom InterruptCommand
                class InterruptCommand(Command):
                    def do(self) -> None:
                        self.finish = True
                reader.commands['interrupt-from-thread'] = InterruptCommand
                
                # Track when pyrepl is active
                if True:
                    super_prepare = reader.prepare
                    def prepare():
                        super_prepare()
                        self._pyrepl_is_active = True
                    reader.prepare = prepare
                    
                    super_restore = reader.restore
                    def restore(*, _cr_keep_active: bool = False):
                        super_restore()
                        if not _cr_keep_active:
                            self._pyrepl_is_active = False
                    reader.restore = restore
                
                # Add hook to check whether Ctrl-C pressed,
                # every 100ms in the Python 3.14 pyrepl implementation
                super_run_hooks = reader.run_hooks
                def run_hooks() -> None:
                    # Output flush hook
                    if self._output_handler is not None:
                        self._output_handler.flush_to_console(reader)
                    
                    # Interrupt hook
                    try:
                        self._interrupt_pipe.readable_end.read(1)
                    except BlockingIOError:
                        # No Ctrl-C
                        pass
                    else:
                        # Ctrl-C
                        self._pyrepl_interrupted = True
                        reader.console.event_queue.insert(
                            Event(evt='interrupt-from-thread', data='', raw=b'')
                        )
                    
                    # Other hooks
                    super_run_hooks()
                reader.run_hooks = run_hooks
            
            # Try to execute startup file specified in $PYTHONSTARTUP
            startup_filepath = os.environ.get('PYTHONSTARTUP')
            if startup_filepath is not None and os.path.isfile(startup_filepath):
                with open(startup_filepath, 'rb') as file:
                    code_bytes = file.read()
                code = compile(code_bytes, startup_filepath, 'exec')
                self.runcode(code)
            
            self._first_input = False
        
        # When running under MCP shell-server (terminal_operate):
        # - Disallow direct multi-line input because terminal_operate
        #   never sends any data after the first \n
        if mcp_shell_server_detected() and prompt == sys.ps2:  # '... ' usually
            if 'exec(' in ''.join(self.buffer):
                sys.stdout.write(
                    '🤖 Multi-line exec() call detected. '
                    'terminal_operate silently truncates multi-line input to first line only. '
                    'Use only a single line with exec() to run multi-line inputs.\n'
                )
            else:
                sys.stdout.write(
                    '🤖 Multi-line input without exec() detected. '
                    'terminal_operate silently truncates multi-line input to first line only. '
                    'Use exec() to run multi-line inputs as a single line.\n'
                )
            
            # Cancel further attempts to read remainder of multi-line input
            self.resetbuffer()
            return ''
        
        impl = self.implementation()
        if impl == 'stdio_buffered':
            # Write prompt
            sys.stdout.write(prompt)
            sys.stdout.flush()
            
            # Read input without echoing
            # TODO: Support Ctrl-C interrupt while waiting for input
            try:
                line = getpass.getpass(prompt='', stream=sys.stdout)
            except EOFError:
                # Handle Ctrl-D
                sys.stdout.write('\n')
                raise
            
            # Echo the complete input line all at once
            sys.stdout.write(f'{line}\n')
            return line
        elif impl == 'basic_repl':
            # NOTE: Loses the Ctrl-C interruptability support provided by self._interruptible_stdin
            #       (as defined by 'basic_repl_interruptible' code),
            #       but regains line editing (like arrow key navigation)
            return input(prompt)
        elif impl == 'basic_repl_interruptible':
            assert self._interruptible_stdin is not None
            
            # Write prompt
            sys.stdout.write(prompt)
            sys.stdout.flush()
            
            try:
                line = self._interruptible_stdin.readline()
            except InterruptedError:
                self._interruptible_stdin.clear_interrupt()
                
                if self._shell_stopping_func():
                    raise EOFError()
                else:
                    raise KeyboardInterrupt()
            else:
                if not line:
                    # Handle Ctrl-D
                    raise EOFError()
                return line.removesuffix('\n')
        elif impl == 'py_repl':
            assert self._pyrepl_multiline_input is not None
            
            line = self._pyrepl_multiline_input()
            if self._pyrepl_interrupted:
                self._pyrepl_interrupted = False
                
                if self._shell_stopping_func():
                    raise EOFError()
                else:
                    # Move cursor back up, because caller assumes that cursor
                    # was not moved down when a KeyboardInterrupt happens,
                    # which is incorrect for pyrepl
                    sys.stdout.write('\x1b[A')
                    sys.stdout.flush()
                    
                    raise KeyboardInterrupt()
            return line
        else:
            assert_never(impl)
    
    # === Eval ===
    
    @override
    def runsource(self, source: str, filename: str = '<input>', symbol: str = 'single') -> bool:
        if ai_agent_detected():
            normalized_source = source.strip().replace(' ', '').replace('\t', '')
            
            # Strongly encourage any AI agent to read help(T) if it tries to use T
            if normalized_source == 'help(T)':
                self._help_t_called = True
            elif normalized_source == 'T' and not self._help_t_called and not self._help_t_warning_printed:
                self.write('🤖 T accessed but help(T) not read. Recommend reading help(T).\n')
                self._help_t_warning_printed = True
            
            # Warn if comment-only input detected, because it could be a multi-line input
            if normalized_source.startswith('#'):
                self.write('🤖 Comment-only input detected. Is this a multi-line input?\n')
                if mcp_shell_server_detected():
                    self.write(
                        '🤖 '
                        'terminal_operate silently truncates multi-line input to first line only. '
                        'Use only a single line with exec() to run multi-line inputs.\n'
                    )
        
        return super().runsource(source, filename, symbol)
    
    # NOTE: Uses a similar implementation pattern as
    #       AsyncIOInteractiveConsole.runcode() from asyncio/__main__.py
    #       to support executing code with top-level await
    @override
    @bg_affinity
    def runcode(self, code: types.CodeType) -> None:
        # Capture snapshot before executing code (for AI agents only)
        if ai_agent_detected():
            from crystal.ui.nav import T
            snap_before = self._fg_call_and_wait_noprofile(lambda: T.snapshot())  # capture
        
        #@fg_affinity
        def fg_run_code() -> Any:
            self._configure_ctrl_c_to_raise_keyboardinterrupt_on_fg_thread()
            try:
                # Check for unhandled Ctrl-C before executing code
                if self._consume_any_ctrl_c_queued_for_stdin_readline():
                    raise KeyboardInterrupt()
                
                # Ensure __builtins__ is available to prevent KeyError
                # during coroutine cleanup if a coroutine is created but not awaited
                if '__builtins__' not in self.locals:
                    self.locals['__builtins__'] = __builtins__  # type: ignore[index]
                
                func = types.FunctionType(code, self.locals)  # type: ignore[arg-type]
                try:
                    return func()  # cr-traceback: ignore
                except SystemExit:
                    raise
                except BaseException:
                    self.showtraceback()
                    return None
            finally:
                self._configure_ctrl_c_to_interrupt_stdin_readline()
        coro = self._fg_call_and_wait_noprofile(fg_run_code)
        
        if not inspect.iscoroutine(coro):
            result = coro
        else:
            try:
                result = run_test_coro(  # cr-traceback: ignore
                    coro,  # type: ignore[arg-type]
                    fg_call_and_wait_func=self._fg_call_and_wait_noprofile
                )
            except BaseException:
                self.showtraceback()
                return None
        
        # Capture snapshot after executing code and show diff (for AI agents only)
        if ai_agent_detected():
            from crystal.ui.nav import Snapshot, T
            
            # Wait for a short grace period to detect 
            # immediately-scheduled asynchronous UI updates
            time.sleep(_ASYNC_UI_UPDATE_DELAY)
            
            snap_after = self._fg_call_and_wait_noprofile(lambda: T.snapshot())  # capture
            diff = Snapshot.diff(snap_before, snap_after, name='S')
            
            # Store the diff in the shell's locals as 'S'
            self.locals['S'] = diff  # type: ignore[index]
            
            if diff:
                # Format the diff output
                [header_line, *rest_lines] = repr(diff).split('\n')
                self.write(f'🤖 UI changed at: {header_line.removeprefix("# ")}\n')
                for line in rest_lines:
                    self.write(f'  {line}\n')  # 2-space indentation
        
        return result
    
    @staticmethod
    def _fg_call_and_wait_noprofile(callable: Callable[[], _R], *, profile: bool = False) -> _R:
        assert profile == False
        if _main_loop_has_exited():
            return callable()
        else:
            try:
                return fg_call_and_wait(  # cr-traceback: ignore
                    callable,
                    # Don't complain if callable() takes a long time to run.
                    # For example the help() command blocks for a long time.
                    profile=profile)
            except NoForegroundThreadError:
                return callable()
    
    # === Print ===
    
    @override
    def write(self, data: str) -> None:
        if self._first_write:
            self._first_write = False
            self.banner_printed.set_result(True)
        super().write(data)
    
    # === Handle Raised Exceptions ===
    
    def _sys_excepthook(self, typ, value, tb):
        # Print nicely-formatted tracebacks
        self.write(format_exception_for_terminal_user(value))
    
    # === Ctrl-C Signal Handling ===
    
    @classmethod
    def handles_ctrl_c(cls) -> bool:
        """Whether the console handles Ctrl-C internally."""
        # NOTE: See ConsoleImplementation for detailed information about how
        #       different implementations handle Ctrl-C.
        return cls.implementation() != 'basic_repl'
    
    # NOTE: Python only allows signals to be reconfigured on the main thread
    @fg_affinity
    def _configure_ctrl_c_to_interrupt_stdin_readline(self) -> None:
        if not self.handles_ctrl_c():
            return
        
        # When SIGINT occurs, write byte(signal.SIGINT) to
        # the interrupt pipe to wake up the InterruptableReader
        # wrapping sys.stdin
        signal.signal(signal.SIGINT, lambda signum, frame: None)
        signal.set_wakeup_fd(self._interrupt_pipe.writable_end.fileno())
    
    # NOTE: Python only allows signals to be reconfigured on the main thread
    @fg_affinity
    def _configure_ctrl_c_to_raise_keyboardinterrupt_on_fg_thread(self) -> None:
        if not self.handles_ctrl_c():
            return
        
        signal.signal(signal.SIGINT, signal.default_int_handler)
        signal.set_wakeup_fd(-1)
    
    def _consume_any_ctrl_c_queued_for_stdin_readline(self) -> bool:
        """
        Returns whether a Ctrl-C (SIGINT) was received.
        """
        if not self.handles_ctrl_c():
            return False
        
        interrupt_pipe = self._interrupt_pipe  # cache
        with selectors.DefaultSelector() as selector:
            selector.register(interrupt_pipe.readable_end.fileno(), selectors.EVENT_READ)
            events = selector.select(timeout=0)
            if events:
                # Drain the interrupt pipe
                interrupt_pipe.readable_end.read(1024)
                
                return True
            else:
                return False


class _DeferredWriter:
    """
    Wraps stdout or stderr to redirect writes to an _OutputBuffer.
    """
    
    def __init__(self,
            original: IO[str],
            output_buffer: _OutputBuffer,
            is_active_func: Callable[[], bool]
            ) -> None:
        self._original = original
        self._output_buffer = output_buffer
        self._is_active_func = is_active_func
    
    def write(self, s: str) -> int:
        if self._is_active_func():
            # Queue for later flush
            self._output_buffer.add(s)
            return len(s)
        else:
            # Write immediately
            return self._original.write(s)
    
    def flush(self) -> None:
        if self._is_active_func():
            # No effect
            pass
        else:
            # Flush immediately
            self._original.flush()
    
    def __getattr__(self, name: str):
        # Delegate all other attributes to the original
        return getattr(self._original, name)


class _OutputBuffer:  # an IO[str], conceptually
    """
    Thread-safe handler for queuing output from non-shell threads
    when pyrepl is active, to prevent garbled output.
    """
    
    def __init__(self) -> None:
        self._lock = Lock()
        self._messages = []  # type: list[str]
    
    def add(self, s: str) -> None:
        """Queue a message to be flushed later."""
        if not s:
            return
        with self._lock:
            self._messages.append(s)
    
    def flush_to_console(self, reader) -> None:
        """
        Flush all queued messages to the console.
        
        Temporarily exits raw mode, prints messages, and re-enters raw mode.
        """
        with self._lock:
            if not self._messages:
                return
            messages = self._messages.copy()
            self._messages.clear()
        
        # Save the user's partial input
        saved_buffer = reader.buffer.copy()
        saved_pos = reader.pos
        saved_paste_mode = reader.paste_mode
        
        # Clear any partial input from the display before printing queued messages
        reader.buffer[:] = []
        reader.pos = 0
        reader.paste_mode = False
        reader.dirty = True
        reader.refresh()
        
        # Exit raw mode so output displays correctly
        # NOTE: Use _cr_keep_active=True to prevent concurrent prints to
        #       {sys.__stdout__, sys.__stderr__} before the next call to prepare()
        reader.restore(_cr_keep_active=True)
        
        # Print all queued messages.
        # If output doesn't end with a newline, add one to ensure
        # the next-printed prompt appears in the leftmost column.
        assert sys.__stdout__ is not None
        if not messages or not messages[-1].endswith('\n'):
            messages.append('\n')
        sys.__stdout__.write(''.join(messages))
        sys.__stdout__.flush()
        
        # Re-enter raw mode
        reader.prepare()
        
        # Restore the user's partial input
        reader.buffer[:] = saved_buffer
        reader.pos = saved_pos
        reader.paste_mode = saved_paste_mode
        reader.dirty = True
        
        # Force redraw of the prompt so the user knows pyrepl is waiting for input
        reader.refresh()


def _main_loop_has_exited() -> bool:
    return not has_foreground_thread()
