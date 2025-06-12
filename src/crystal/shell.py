from __future__ import annotations

import code
from crystal import __version__ as crystal_version
from crystal.browser import MainWindow
from crystal.model import Project
import crystal.util.xsite as site
from crystal.util.xthreading import (
    bg_affinity, fg_call_and_wait, has_foreground_thread,
    NoForegroundThreadError,
)
import os
import sys
import threading
from typing import Optional
from typing_extensions import override


class Shell:
    def __init__(self) -> None:
        if not has_foreground_thread():
            raise ValueError('Expected there to be a foreground thread when starting a Shell')
        
        # Setup proxy variables for shell
        _Proxy._patch_help()
        self._project_proxy = _Proxy(f'<unset {Project.__module__}.{Project.__name__} proxy>')
        self._window_proxy = _Proxy(f'<unset {MainWindow.__module__}.{MainWindow.__name__} proxy>')
        
        # Ensure help(), exit(), and quit() are available,
        # even when running as a frozen .app or .exe
        site.sethelper()  # help
        site.setquit()  # quit, exit
        
        self._ensure_guppy_available()
        
        threading.Thread(target=self._run, daemon=False).start()
    
    @staticmethod
    def _ensure_guppy_available() -> None:
        # Explicitly import guppy to tell py2app and py2exe to include it
        # when building a binary
        try:
            import guppy
            import guppy.heapy
            import guppy.heapy.Classifiers
            import guppy.heapy.Doc
            import guppy.heapy.ImpSet
            import guppy.heapy.OutputHandling
            import guppy.heapy.Part
            import guppy.heapy.Path
            import guppy.heapy.RefPat
            import guppy.heapy.Target
            import guppy.heapy.UniSet
            import guppy.heapy.Use
            import guppy.heapy.View
        except ImportError:
            pass
    
    def _run(self) -> None:
        # Define exit instructions,
        # based on site.setquit()'s definition in Python 3.8
        if os.sep == '\\':
            eof = 'Ctrl-Z plus Return'
        else:
            eof = 'Ctrl-D (i.e. EOF)'
        exit_instructions = 'Use {}() or {} to exit'.format('exit', eof)
        
        python_version = '.'.join([str(x) for x in sys.version_info[:3]])
        try:
            fg_interact(
                banner=(
                    f'Crystal {crystal_version} (Python {python_version})\n'
                    'Type "help" for more information.\n'
                    'Variables "project" and "window" are available.\n'
                    f'{exit_instructions}.'
                ),
                local=dict(
                    project=self._project_proxy,
                    window=self._window_proxy,
                ),
                exitmsg='now waiting for all windows to close...',
            )
        except SystemExit:
            pass
    
    def attach(self, project: Project, window: MainWindow) -> None:
        self._project_proxy._initialize_proxy(project, reinit_okay=True)
        self._window_proxy._initialize_proxy(window, reinit_okay=True)
    
    def detach(self) -> None:
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


def fg_interact(banner=None, local=None, exitmsg=None):
    """
    Similar to code.interact(), but evaluates code on the foreground thread.
    """
    console = _FgInteractiveConsole(local)
    try:
        import readline
    except ImportError:
        pass
    try:
        console.interact(banner, exitmsg='')
    finally:
        if not _main_loop_has_exited():
            console.write('%s\n' % exitmsg)


class _FgInteractiveConsole(code.InteractiveConsole):
    """
    Similar to code.InteractiveConsole, but evaluates code on the foreground thread.
    
    Will also execute a startup file specified in $PYTHONSTARTUP if defined.
    """
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._first_input = True
    
    @override
    @bg_affinity
    def raw_input(self, *args, **kwargs) -> str:
        if self._first_input:
            # Try to execute startup file specified in $PYTHONSTARTUP
            startup_filepath = os.environ.get('PYTHONSTARTUP')
            if startup_filepath is not None and os.path.isfile(startup_filepath):
                with open(startup_filepath, 'rb') as file:
                    code_bytes = file.read()
                code = compile(code_bytes, startup_filepath, 'exec')
                self.runcode(code)
            
            self._first_input = False
        return super().raw_input(*args, **kwargs)
    
    @override
    def runcode(self, code) -> None:
        def fg_runcode():
            super(_FgInteractiveConsole, self).runcode(code)
        
        if _main_loop_has_exited():
            fg_runcode()
        else:
            try:
                fg_call_and_wait(
                    fg_runcode,
                    # Don't complain if fg_runcode() takes a long time to run.
                    # For example the help() command blocks for a long time.
                    profile=False)
            except NoForegroundThreadError:
                fg_runcode()
    
    @override
    def showtraceback(self) -> None:
        # Force default behavior of printing the most recent traceback to
        # the console, even if sys.excepthook has been overridden
        old_excepthook = sys.excepthook  # capture
        sys.excepthook = sys.__excepthook__
        try:
            super().showtraceback()
        finally:
            sys.excepthook = old_excepthook


def _main_loop_has_exited() -> bool:
    return not has_foreground_thread()
