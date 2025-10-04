
from ast import literal_eval
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import re
from crystal.tests.util.asserts import assertEqual, assertIn
from crystal.tests.util.screenshots import take_error_screenshot
from crystal.tests.util.wait import DEFAULT_WAIT_PERIOD, DEFAULT_WAIT_TIMEOUT, HARD_TIMEOUT_MULTIPLIER, WaitTimedOut
from crystal.tests.util.windows import MainWindow
from crystal.util.xos import is_asan, is_windows
from select import select
import textwrap
import time
from typing import Any, Literal, Optional
import warnings
from io import TextIOBase
import os
import subprocess
import sys
from unittest import SkipTest


PROJECT_PROXY_REPR_STR = '<unset crystal.model.Project proxy>\n'
WINDOW_PROXY_REPR_STR = '<unset crystal.browser.MainWindow proxy>\n'


# ------------------------------------------------------------------------------
# Run CLI

def run_crystal(args: list[str]) -> subprocess.CompletedProcess[str]:
    """
    Run Crystal CLI with the given arguments and return the result.
    
    Raises:
    * SkipTest -- if Crystal CLI cannot be used in the current environment
    
    See also:
    * crystal_running() -- Use when Crystal is not expected to exit immediately.
    """
    with crystal_running(args=args, discrete_stderr=True) as crystal:
        (stdout_data, stderr_data) = crystal.communicate()
        return subprocess.CompletedProcess(
            args=args,
            returncode=crystal.returncode,
            stdout=stdout_data,
            stderr=stderr_data
        )


# ------------------------------------------------------------------------------
# Start CLI

@contextmanager
def crystal_running(*, args=[], env_extra={}, discrete_stderr: bool=False, reopen_projects_enabled: bool=False) -> Iterator[subprocess.Popen]:
    """
    Context which starts "crystal" upon enter
    and cleans up the associated process upon exit.
    
    Arguments:
    * discrete_stderr --
        if True, stderr is kept separate from stdout;
        if False, stderr is merged into stdout.
    * reopen_projects_enabled --
        if True, allows auto-reopening of untitled projects;
        if False, disables auto-reopening (default for subprocess tests).
    
    Raises:
    * SkipTest -- if Crystal CLI cannot be used in the current environment
    
    See also:
    * run_crystal() -- Use when Crystal is expected to exit immediately.
    * crystal_running_with_banner() -- Use when detailed verification of banner lines is needed.
    """
    _ensure_can_use_crystal_cli()
    
    # Determine how to run Crystal on command line
    crystal_command: list[str]
    python = sys.executable
    if getattr(sys, 'frozen', None) == 'macosx_app':
        python_neighbors = os.listdir(os.path.dirname(python))
        (crystal_binary_name,) = (n for n in python_neighbors if 'crystal' in n.lower())
        crystal_binary = os.path.join(os.path.dirname(python), crystal_binary_name)
        crystal_command = [crystal_binary]
    else:
        crystal_command = [python, '-m', 'crystal']
    
    crystal = subprocess.Popen(
        [*crystal_command, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE if discrete_stderr else subprocess.STDOUT,
        encoding='utf-8',
        env={
            **os.environ,
            **{
                'CRYSTAL_FAULTHANDLER': 'True',
                
                # Prevent Python warnings from being mixed into output
                'PYTHONWARNINGS': 'ignore',
                
                # Prevent profiling warnings from being mixed into output
                # TODO: Recommend renaming to avoid (double-)negatives
                'CRYSTAL_NO_PROFILE_FG_TASKS': 'True',
                'CRYSTAL_NO_PROFILE_GC': 'True',
                'CRYSTAL_NO_PROFILE_RECORD_LINKS': 'True',
                'CRYSTAL_NO_SCREENSHOT_MESSAGES': 'True',
                
                # Disable auto-reopening of untitled projects during subprocess tests
                # unless explicitly enabled for testing the reopen functionality
                **({} if reopen_projects_enabled else {'CRYSTAL_NO_REOPEN_PROJECTS': 'True'}),
            },
            **env_extra
        })
    try:
        assert isinstance(crystal.stdout, TextIOBase)
        
        yield crystal
    finally:
        assert crystal.stdin is not None
        crystal.stdin.close()
        assert crystal.stdout is not None
        crystal.stdout.close()
        crystal.kill()
        crystal.wait()


BannerLineType = Literal[
    # --shell
    "version",
    "help",
    "variables",
    "exit",
    "prompt",

    # --serve
    "server_started",
    "ctrl_c"
]

@dataclass
class BannerMetadata:
    server_url: str | None = None

# Matches lines ending with '\n' or not, or the fragment '>>> '
_LINE_OR_PROMPT_RE = re.compile(r'.*?\n|>>> |.+$')

@contextmanager
def crystal_running_with_banner(
        *, args=[],
        expects=list[BannerLineType],
        reopen_projects_enabled: bool=False,
        ) -> Iterator[tuple[subprocess.Popen, BannerMetadata]]:
    """
    Context which starts "crystal" upon enter
    and cleans up the associated process upon exit.
    
    Additionally, reads the banner lines which Crystal prints when it starts
    and checks that they match the expected lines.
    
    Arguments:
    * reopen_projects_enabled --
        if True, allows auto-reopening of untitled projects;
        if False, disables auto-reopening (default for subprocess tests).
    
    Raises:
    * SkipTest -- if Crystal CLI cannot be used in the current environment
    
    See also:
    * crystal_running_with_banner() -- Use when detailed verification of banner lines is NOT needed.
    """
    banner_metadata = BannerMetadata()
    
    with crystal_running(args=args, reopen_projects_enabled=reopen_projects_enabled) as crystal:
        assert isinstance(crystal.stdout, TextIOBase)
        
        lines_found = []  # type: list[str]
        expects_found = []  # type: list[BannerLineType]
        expects_remaining = list(expects)
        def found(expect: BannerLineType | None, line: str) -> None:
            if expect is not None:
                try:
                    expects_remaining.remove(expect)
                except ValueError:
                    raise AssertionError(
                        f'Unexpected banner line: {line!r} (type={expect!r}). '
                        f'Read before: {"".join(lines_found)!r}. '
                        f'Trailing output: {drain(crystal.stdout)!r} '
                        f'Still expecting: {expects_remaining!r}'
                    ) from None
                expects_found.append(expect)
            lines_found.append(line)
            
            if expect == "server_started":
                url_match = re.search(r'http://[\d.:]+', line)
                assert url_match is not None, f"Could not find server URL in: {line!r}"
                banner_metadata.server_url = url_match.group(0)

        next_lines = []
        while True:
            if len(expects_remaining) == 0:
                break
            
            if len(next_lines) == 0:
                try:
                    (lines_str, _) = read_until(crystal.stdout, ('\n', '>>> '), _drain_diagnostic=False)
                except ReadUntilTimedOut as e:
                    raise e.plus(
                        f' Read before: {"".join(lines_found)!r} '
                        f'Trailing output: {drain(crystal.stdout)!r} '
                        f'Still expecting: {expects_remaining!r}'
                    ) from None
                
                # 1. Split lines_str after each '\n', retaining the '\n' at the end of each line
                # 2. Split lines_str at each '>>> '
                lines = re.findall(_LINE_OR_PROMPT_RE, lines_str)
                assert len(lines) > 0, "Expected read_until() to return at least one line"
                next_lines.extend(lines)
            line = next_lines.pop(0)
            
            # ex: 'Crystal 1.11.0 (Python 3.12.2)'
            if line.startswith('Crystal '):
                found("version", line)
            # ex: 'Type "help" for more information.'
            elif '"help"' in line:
                found("help", line)
            # ex: 'Variables "project" and "window" are available.'
            elif '"project"' in line and '"window"' in line:
                found("variables", line)
            # ex: 'Use exit() or Ctrl-D (i.e. EOF) to exit.'
            elif 'exit()' in line:
                found("exit", line)
            elif line == '>>> ':
                found("prompt", line)
            # ex: 'Server started at: http://127.0.0.1:2797'
            elif line.startswith('Server started at: '):
                found("server_started", line)
            # ex: 'Press Ctrl-C to stop.'
            elif 'Ctrl-C' in line:
                found("ctrl_c", line)
            elif 'Traceback (most recent call last):' in line:
                raise AssertionError(f"Unexpected error in output:\n{line + drain(crystal.stdout)}")
            else:
                # Unknown line
                found(None, line)

        yield (crystal, banner_metadata)


def _ensure_can_use_crystal_cli() -> None:
    """
    Raises:
    * SkipTest -- if Crystal CLI cannot be used in the current environment
    """
    if is_windows():
        # NOTE: Windows doesn't provide stdout for graphical processes,
        #       which is needed by the current implementation.
        #       Workaround is possible with run_exe.py but time-consuming to implement.
        raise SkipTest('not supported on Windows; graphical subprocesses are mute')
    if is_asan():
        # NOTE: ASan slows down many operations, causing shell operations to
        #       spuriously fail timeout checks, even when
        #       CRYSTAL_GLOBAL_TIMEOUT_MULTIPLIER is used
        raise SkipTest('too slow when run with Address Sanitizer')


@contextmanager
def crystal_shell(*, args=[], env_extra={}, reopen_projects_enabled: bool=False) -> Iterator[tuple[subprocess.Popen, str]]:
    """
    Context which starts "crystal --shell" upon enter
    and cleans up the associated process upon exit.
    
    Arguments:
    * reopen_projects_enabled --
        if True, allows auto-reopening of untitled projects;
        if False, disables auto-reopening (default for subprocess tests).
    
    Raises:
    * SkipTest -- if Crystal CLI cannot be used in the current environment
    """
    with crystal_running(args=['--shell', *args], env_extra=env_extra, reopen_projects_enabled=reopen_projects_enabled) as crystal:
        assert isinstance(crystal.stdout, TextIOBase)
        (banner, _) = read_until(
            crystal.stdout, '\n>>> ',
            timeout=4.0  # 2.0s isn't long enough for macOS test runners on GitHub Actions
        )
        assertIn('Crystal', banner)
        yield (crystal, banner)


# ------------------------------------------------------------------------------
# Interact

_VSC_ESCAPE_SEQUENCE = '\x1b]633;E;0\x07\x1b]633;A\x07'


def py_eval(
        python: subprocess.Popen,
        py_code: str,
        stop_suffix: str | tuple[str, ...] | None=None,
        *, timeout: float | None=None) -> str:
    """
    Evaluates the provided Python code in the specified Crystal process
    and returns anything printed to stdout.
    
    A single line of code with an expression will implicitly print its repr().
    
    If you run multiple lines of code and you need to read the result of an
    expression, remember to wrap the expression in a print() statement.
    For example:
    
        untitled_project_path = py_eval_literal(crystal, textwrap.dedent('''\
            from crystal.util.unsaved_project import get_unsaved_untitled_project_path
            print(repr(get_unsaved_untitled_project_path()))
            '''
        ))

    If you need to execute any code that waits on parts of the user interface,
    you'll need to run the waits in a separate thread. Use py_eval_await(),
    or implement the following pattern manually:
    
        py_eval(crystal, textwrap.dedent('''\
            from crystal.tests.util.runner import run_test
            from threading import Thread
            
            async def check_foobar():
                ocd = await OpenOrCreateDialog.wait_for()
                ...
            
            result_cell = [Ellipsis]
            def get_result(result_cell):
                result_cell[0] = run_test(lambda: check_foobar())
                print('OK')
            
            t = Thread(target=lambda: get_result(result_cell))
            t.start()
            '''
        ), stop_suffix=_OK_THREAD_STOP_SUFFIX, timeout=8.0)
    
    Key elements of the above example:
    - `run_test` -- Run async code using test utilities
    - `print('OK')` -- Signal that the code has finished executing
    - `_OK_THREAD_STOP_SUFFIX` -- Wait for the code to finish executing
    - `timeout=...` -- Pick an appropriate timeout
    
    > TODO: Rewrite occurrences of the above verbose pattern to use py_eval_await() instead.
    
    See also:
    - py_eval_literal()
    - py_eval_await()
    """
    if '\n' in py_code:
        # Execute multi-line code as a single line
        py_code = f'exec({py_code!r})'  # reinterpret
    if stop_suffix is None:
        stop_suffix = '>>> '
    
    assert isinstance(python.stdin, TextIOBase)
    assert isinstance(python.stdout, TextIOBase)
    python.stdin.write(f'{py_code}\n'); python.stdin.flush()
    (result, found_stop_suffix) = read_until(
        python.stdout, stop_suffix, timeout=timeout, stacklevel_extra=1)
    result_no_suffix = result[:-len(found_stop_suffix)]
    if os.environ.get('TERM_PROGRAM') == 'vscode':
        # HACK: VS Code inserts terminal integration escape sequences (OSC 633).
        #       Remove them.
        result_no_suffix = result_no_suffix.removesuffix(_VSC_ESCAPE_SEQUENCE)
    return result_no_suffix


def py_eval_literal(
        python: subprocess.Popen,
        py_code: str,
        *, timeout: float|None=None,
        ) -> Any:
    """
    Similar to py_eval() but always returns the parsed repr() of the expression
    printed by the code.
    """
    expr_str = py_eval(python, py_code, timeout=timeout)
    if expr_str == '':
        # HACK: Try again
        assert isinstance(python.stdout, TextIOBase)
        (result_str, _) = read_until(python.stdout, '>>> ', timeout=timeout)
        expr_str = result_str.removesuffix('>>> ')
    try:
        return literal_eval(expr_str)
    except SyntaxError as e:
        raise SyntaxError(
            f'{e} '
            f'Tried to parse: {expr_str!r} '
            f'Trailing output: {drain(python)!r}'
        ) from None


def py_eval_await(
        python: subprocess.Popen,
        define_async_func_code: str,
        func_name: str,
        func_args: Sequence[str]=(),
        *, timeout: float|None=None,
        ) -> str:
    """
    Evaluates an async function in the specified Crystal process
    and returns anything printed to stdout.
    
    Usage:
    
        stdout_str = py_eval_await(crystal, textwrap.dedent('''\
            from crystal.tests.util.windows import OpenOrCreateDialog
            
            async def crystal_task(arg1: str) -> None:
                ocd = await OpenOrCreateDialog.wait_for()
                ...
            '''
        ), 'crystal_task', [arg1])
    
    See also:
    - py_eval_await_literal()
    """
    py_eval(python, define_async_func_code)
    stdout_str = py_eval(python, textwrap.dedent(f'''\
        from crystal.tests.util.runner import run_test
        from threading import Thread
        
        result_cell = [Ellipsis]
        def get_result(result_cell):
            result_cell[0] = run_test(lambda: {func_name}(*{repr(func_args)}))
            print('OK')
        
        t = Thread(target=lambda: get_result(result_cell))
        t.start()
        '''
    ), stop_suffix=_OK_THREAD_STOP_SUFFIX, timeout=timeout)
    stdout_str = stdout_str.removeprefix(_VSC_ESCAPE_SEQUENCE)
    stdout_str = stdout_str.removeprefix('>>>')
    return stdout_str


def py_eval_await_literal(
        python: subprocess.Popen,
        define_async_func_code: str,
        func_name: str,
        *args,
        **kwargs,
        ) -> Any:
    """
    Similar to py_eval_await() but always returns the parsed repr() of the expression
    printed by the code.
    """
    expr_str = py_eval_await(python, define_async_func_code, func_name, *args, **kwargs)
    try:
        return literal_eval(expr_str)
    except SyntaxError as e:
        raise SyntaxError(
            f'{e} '
            f'Tried to parse: {expr_str!r} '
            f'Trailing output: {drain(python)!r}'
        ) from None


def read_until(
        stream: TextIOBase,
        stop_suffix: str | tuple[str, ...],
        timeout: float | None=None,
        *, period: float | None=None,
        stacklevel_extra: int=0,
        _expect_timeout: bool=False,
        _drain_diagnostic: bool=True,
        ) -> tuple[str, str]:
    """
    Reads from the specified stream until the provided `stop_suffix`
    is read at the end of the stream or the timeout expires.
    
    Note that this method will read until SOME occurrence of the stop suffix
    is read, not necessarily the FIRST occurrence. So the returned read buffer
    may actually contain multiple occurrences of the stop suffix.
    
    Raises:
    * ReadUntilTimedOut -- if the timeout expires before `stop_suffix` is read
    """
    try:
        return _read_until_inner(
            stream, stop_suffix, timeout=timeout, period=period,
            stacklevel_extra=1 + stacklevel_extra, _expect_timeout=_expect_timeout)
    except ReadUntilTimedOut as e:
        if _drain_diagnostic:
            raise e.plus(f' Trailing output: {drain(stream)!r}') from None
        else:
            raise

def _read_until_inner(
        stream: TextIOBase,
        stop_suffix: str | tuple[str, ...],
        timeout: float | None=None,
        *, period: float | None=None,
        stacklevel_extra: int=0,
        _expect_timeout: bool=False,
        ) -> tuple[str, str]:
    if isinstance(stop_suffix, str):
        stop_suffix = (stop_suffix,)
    if os.environ.get('TERM_PROGRAM') == 'vscode' and '>>> ' in stop_suffix:
        # HACK: VS Code inserts terminal integration escape sequences (OSC 633).
        #       Weaken pattern match to ignore them.
        stop_suffix += ('>>>',)
    if timeout is None:
        timeout = DEFAULT_WAIT_TIMEOUT
    if period is None:
        period = DEFAULT_WAIT_PERIOD
    
    soft_timeout = timeout
    hard_timeout = timeout * HARD_TIMEOUT_MULTIPLIER
    
    stop_suffix_bytes_choices = [s.encode(stream.encoding) for s in stop_suffix]
    
    read_buffer = b''
    found_stop_suffix = None  # type: Optional[str]
    start_time = time.time()
    hard_timeout_exceeded = False
    try:
        delta_time = 0.0
        while True:
            # 1. Wait for stream to be ready to read or hit EOF
            # 2. Read stream (if became ready)
            # 3. Look for an acceptable `stop_suffix` at the end of everything read so far
            remaining_time = hard_timeout - delta_time
            assert remaining_time > 0
            (rlist_ready, _, xlist_ready) = select(
                [stream],
                [],
                [stream],
                remaining_time)
            did_time_out = (len(rlist_ready) + len(xlist_ready) == 0)
            if did_time_out:
                # Look for an acceptable "stop suffix"
                # Special case: '' is always an acceptable `stop_suffix`
                if '' in stop_suffix:
                    found_stop_suffix = ''
            else:
                # Read stream
                # NOTE: Append uses quadratic performance.
                #       Not using for large amounts of text so I don't care.
                read_buffer += stream.buffer.read1(1024)  # type: ignore[attr-defined]  # arbitrary
                
                # Look for an acceptable "stop suffix"
                for (i, s_bytes) in enumerate(stop_suffix_bytes_choices):
                    if read_buffer.endswith(s_bytes):
                        found_stop_suffix = stop_suffix[i]
                        break
            if found_stop_suffix is not None:
                # Done
                break
            
            # If hard timeout exceeded then raise
            delta_time = time.time() - start_time
            if did_time_out or delta_time >= hard_timeout:
                if not _expect_timeout:
                    # Screenshot the timeout error
                    take_error_screenshot()
                
                hard_timeout_exceeded = True
                read_so_far = read_buffer.decode(stream.encoding)
                raise ReadUntilTimedOut(
                    f'Timed out after {timeout:.1f}s while '
                    f'reading until {stop_suffix!r}. '
                    f'Read so far: {read_so_far!r}',
                    read_so_far)
    finally:
        # If soft timeout exceeded then warn before returning
        if not hard_timeout_exceeded:
            delta_time = time.time() - start_time
            if delta_time > soft_timeout:
                warnings.warn(
                    ('Soft timeout exceeded (%.1fs > %.1fs) while '
                    'reading until %r.') % (
                        delta_time,
                        soft_timeout,
                        stop_suffix
                    ),
                    stacklevel=(2 + stacklevel_extra))
            
    return (read_buffer.decode(stream.encoding), found_stop_suffix)


class ReadUntilTimedOut(WaitTimedOut):
    def __init__(self, message: str, read_so_far: str) -> None:
        super().__init__(message)
        self.read_so_far = read_so_far
    
    @property
    def message(self) -> str:
        return self.args[0]
    
    def plus(self, message_suffix: str) -> 'ReadUntilTimedOut':
        return ReadUntilTimedOut(
            f'{self.message} {message_suffix}',
            self.read_so_far)


_DEFAULT_DRAIN_TTL = min(DEFAULT_WAIT_TIMEOUT, 2.0)

def drain(stream: TextIOBase | subprocess.Popen, ttl: float | None=None) -> str:
    """
    Reads as much as possible from the specified stream for the specified
    TTL duration and returns it.
    
    Often useful for debugging _read_until() failures.
    """
    if ttl is None:
        ttl = _DEFAULT_DRAIN_TTL
    
    if isinstance(stream, subprocess.Popen):
        stream2 = stream.stdout
        assert isinstance(stream2, TextIOBase)
        stream = stream2  # reinterpret
    
    EOT = '\4'  # End of Transmission; an unlikely character to occur in the wild
    try:
        read_until(stream, EOT, ttl, _expect_timeout=True, _drain_diagnostic=False)
    except ReadUntilTimedOut as e:
        return e.read_so_far
    else:
        raise ValueError('Actually encountered EOT while reading stream!')


# ------------------------------------------------------------------------------
# Windows

_OK_THREAD_STOP_SUFFIX = (
    # If thread finishes after the "t.start()" fully completes and writes the next '>>> ' prompt
    'OK\n',
    # If thread finishes before the "t.start()" fully completes and writes the next '>>> ' prompt
    'OK\n>>> ',
    # If the next '>>> ' prompt is written in the middle of "OK" + "\n" being printed.
    'OK>>> \n',
    # TODO: Determine how this empiricially observed situation is possible
    'OK\n>>> >>> ',
)

def create_new_empty_project(crystal: subprocess.Popen) -> None:
    # NOTE: Uses private API, including the entire crystal.tests package
    py_eval(crystal, textwrap.dedent('''\
        if True:
            from crystal.tests.util.runner import run_test
            from crystal.tests.util.windows import OpenOrCreateDialog
            import os
            import tempfile
            from threading import Thread
            #
            async def create_new_project():
                ocd = await OpenOrCreateDialog.wait_for()
                mw = await ocd.create_and_leave_open()
                #
                return mw
            #
            result_cell = [Ellipsis]
            def get_result(result_cell):
                result_cell[0] = run_test(lambda: create_new_project())
                print('OK')
            #
            t = Thread(target=lambda: get_result(result_cell))
            t.start()
        '''),
        stop_suffix=_OK_THREAD_STOP_SUFFIX,
        # NOTE: 6.0 was observed to sometimes not be long enough on macOS
        timeout=8.0
    )
    assertEqual(
        "<class 'crystal.tests.util.windows.MainWindow'>\n",
        py_eval(crystal, 'type(result_cell[0])'))


def close_open_or_create_dialog(crystal: subprocess.Popen, *, after_delay: float | None=None) -> None:
    # NOTE: Uses private API, including the entire crystal.tests package
    py_eval(crystal, textwrap.dedent(f'''\
        if True:
            from crystal.tests.util.runner import bg_sleep, run_test
            from crystal.tests.util.windows import OpenOrCreateDialog
            from threading import Thread
            #
            async def close_ocd():
                ocd = await OpenOrCreateDialog.wait_for()
                if {after_delay} != None:
                    await bg_sleep({after_delay})
                ocd.open_or_create_project_dialog.Close()
                #
                print('OK')
            #
            t = Thread(target=lambda: run_test(close_ocd))
            t.start()
        '''), stop_suffix=_OK_THREAD_STOP_SUFFIX if after_delay is None else '')


def wait_for_main_window(crystal: subprocess.Popen) -> None:
    # NOTE: Uses private API, including the entire crystal.tests package
    py_eval(crystal, textwrap.dedent(f'''\
        if True:
            from crystal.tests.util.runner import run_test
            from crystal.tests.util.windows import MainWindow
            from threading import Thread
            #
            async def wait_for_main_window():
                mw = await MainWindow.wait_for()
                #
                print('OK')
            #
            t = Thread(target=lambda: run_test(wait_for_main_window))
            t.start()
        '''),
        stop_suffix=_OK_THREAD_STOP_SUFFIX,
        timeout=MainWindow.CLOSE_TIMEOUT,
    )


def close_main_window(crystal: subprocess.Popen, *, after_delay: float | None=None) -> None:
    # NOTE: Uses private API, including the entire crystal.tests package
    py_eval(crystal, textwrap.dedent(f'''\
        if True:
            from crystal.tests.util.runner import bg_sleep, run_test
            from crystal.tests.util.windows import MainWindow
            from threading import Thread
            #
            async def close_main_window():
                mw = await MainWindow.wait_for()
                if {after_delay} != None:
                    await bg_sleep({after_delay})
                await mw.close()
                #
                print('OK')
            #
            t = Thread(target=lambda: run_test(close_main_window))
            t.start()
        '''),
        stop_suffix=_OK_THREAD_STOP_SUFFIX if after_delay is None else '',
        timeout=MainWindow.CLOSE_TIMEOUT,
    )


@contextmanager
def delay_between_downloads_minimized(crystal: subprocess.Popen) -> Iterator[None]:
    # NOTE: Uses private API, including the entire crystal.tests package
    py_eval(crystal, 'from crystal.tests.util.downloads import delay_between_downloads_minimized as D')
    py_eval(crystal, 'download_ctx = D()')
    py_eval(crystal, 'download_ctx.__enter__()')
    try:
        yield
    finally:
        py_eval(crystal, 'download_ctx.__exit__(None, None, None)')


# ------------------------------------------------------------------------------
# Exit

def wait_for_crystal_to_exit(
        crystal: subprocess.Popen,
        *, timeout: float,
        stacklevel_extra: int=0
        ) -> None:
    assert isinstance(crystal.stdout, TextIOBase)
    
    start_time = time.time()  # capture
    try:
        crystal.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            crystal.wait(timeout=(timeout * HARD_TIMEOUT_MULTIPLIER) - timeout)
        except subprocess.TimeoutExpired:
            raise WaitTimedOut(
                f'Timed out waiting for Crystal to exit. '
                f'Trailing output: {drain(crystal.stdout)!r} '
            ) from None
        else:
            delta_time = time.time() - start_time
            warnings.warn(
                ('Soft timeout exceeded (%.1fs > %.1fs) while '
                'waiting for Crystal to exit') % (
                    delta_time,
                    timeout,
                ),
                stacklevel=(2 + stacklevel_extra))


# ------------------------------------------------------------------------------
