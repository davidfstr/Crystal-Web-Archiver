#!/usr/bin/env python
"""
Home of the main function, which starts the program.
"""

# TODO: Eliminate use of deprecated "annotation" future
from __future__ import annotations

# NOTE: Avoid importing anything outside the Python standard library
#       at the top-level of this module, including from the "crystal" package,
#       in case the import itself fails.
#       
#       Import failure is more common in py2app and py2exe contexts and
#       is easier to debug when it does NOT happen at the top-level.
#       
#       Therefore many imports in this file should occur directly within functions.
import argparse
import atexit
from collections.abc import Callable
import datetime
from io import TextIOBase
import locale
import os
import os.path
import sys
import threading
import time
import traceback
from typing import Any, cast, Never, Optional, ParamSpec, TypeVar, TYPE_CHECKING
from typing_extensions import override

if TYPE_CHECKING:
    from crystal.browser import MainWindow
    from crystal.model import Project
    from crystal.progress import OpenProjectProgressListener
    from crystal.shell import Shell
    import wx


_P = ParamSpec('_P')
_RT = TypeVar('_RT')


_project_path_to_open_soon: Optional[str] = None
# Interrupts prompt_for_prompt() to open _project_path_to_open_soon.
# None if prompt_for_prompt() is not running.
_interrupt_prompt_for_project_to_open_project: Optional[Callable[[], None]] = None


def main() -> Never:
    """
    Main function. Starts the program.
    """
    try:
        try:
            _main(sys.argv[1:])
        except SystemExit:
            raise
        except:
            # Bubble up other kinds of uncaught exceptions
            raise
        else:
            raise SystemExit()  # success
    except SystemExit as exit_command:
        # Record exit code
        from crystal.util.quitting import set_exit_code
        if exit_command.code is None:
            exit_code = getattr(os, 'EX_OK', 0)  # success
        elif isinstance(exit_command.code, int):
            exit_code = exit_command.code  # specific exit code
        else:
            exit_code = 1  # default error exit code
        set_exit_code(exit_code)
        
        raise


def _main(args: list[str]) -> None:
    # If running as Mac app or as Windows executable, redirect stdout and 
    # stderr to file, since these don't exist in these environments.
    # Use line buffering (buffering=1) so that prints are observable immediately.
    interactive = 'TERM' in os.environ
    log_to_file = (
        (getattr(sys, 'frozen', None) == 'macosx_app' and not interactive) or
        (getattr(sys, 'frozen', None) == 'windows_exe')
    )
    if log_to_file:
        from crystal.util.xappdirs import user_log_dir
        log_dirpath = user_log_dir()
        assert os.path.exists(log_dirpath)
        
        sys.stdout = sys.stderr = open(
            os.path.join(log_dirpath, 'stdouterr.log'), 
            'w', encoding='utf-8', buffering=1)
    
    # If CRYSTAL_FAULTHANDLER == True or running from source,
    # enable automatic dumping of Python tracebacks if wx has a segmentation fault
    if (os.environ.get('CRYSTAL_FAULTHANDLER', 'False') == 'True' or
            getattr(sys, 'frozen', None) is None):
        import faulthandler
        faulthandler.enable()
    
    # Print uncaught exceptions
    if True:
        # Print uncaught exceptions raised by Thread.run()
        def threading_excepthook(args) -> None:
            from crystal.util import cli
            
            err_file = sys.stderr
            print(cli.TERMINAL_FG_RED, end='', file=err_file)
            print('Exception in background thread:', file=err_file)
            traceback.print_exception(
                args.exc_type, args.exc_value, args.exc_traceback,
                file=err_file)
            print(cli.TERMINAL_RESET, end='', file=err_file)
            err_file.flush()
        threading.excepthook = threading_excepthook
        
        # Print uncaught exceptions raised in the main thread
        def sys_excepthook(exc_type, exc_value, exc_traceback) -> None:
            from crystal.util import cli
            
            err_file = sys.stderr
            print(cli.TERMINAL_FG_RED, end='', file=err_file)
            print('Exception in main thread:', file=err_file)
            traceback.print_exception(
                exc_type, exc_value, exc_traceback,
                file=err_file)
            print(cli.TERMINAL_RESET, end='', file=err_file)
            err_file.flush()
        sys.excepthook = sys_excepthook
        
        # Print exceptions occurring in unraisable contexts
        def sys_unraisablehook(args) -> None:
            from crystal.util import cli
            
            err_file = sys.stderr
            print(cli.TERMINAL_FG_RED, end='', file=err_file)
            print('Exception in unraisable context:', file=err_file)
            traceback.print_exception(
                args.exc_type, args.exc_value, args.exc_traceback,
                file=err_file)
            print(cli.TERMINAL_RESET, end='', file=err_file)
            err_file.flush()
        sys.unraisablehook = sys_unraisablehook
    
    # If running as Windows executable, also load .py files and adjacent
    # resources from the "lib" directory. Notably "tzinfo" data.
    if getattr(sys, 'frozen', None) == 'windows_exe':
        sys.path.insert(0, os.path.join(os.path.dirname(sys.executable), 'lib'))
    
    # If running as Windows executable, also look for command line arguments
    # in a text file in the current directory
    if getattr(sys, 'frozen', None) == 'windows_exe':
        if os.path.exists('arguments.txt'):
            with open('arguments.txt', encoding='utf-8') as f:
                args_line = f.read()
            # TODO: Consider using shlex.split() here to support quoted arguments
            args = args_line.strip().split(' ')  # reinterpret
    
    # 1. Enable terminal colors on Windows, by wrapping stdout and stderr
    # 2. Strip colorizing ANSI escape sequences when printing to a log file
    import colorama
    colorama.init()
    
    # Ensure the main package can be imported
    try:
        import crystal
    except ImportError:
        # Maybe it's in the current directory?
        sys.path.append(os.getcwd())
        try:
            import crystal
        except ImportError:
            sys.exit('Can\'t find the main "crystal" package on your Python path.')
    
    # Initialize global configuration
    from crystal.util.xurllib import patch_urlparse_to_never_raise_valueerror
    patch_urlparse_to_never_raise_valueerror()
    
    # Filter out strange "psn" argument (ex: '-psn_0_438379') that
    # macOS does sometimes pass upon first launch when run as a
    # binary downloaded from the internet.
    args = [a for a in args if not a.startswith('-psn_')]  # reinterpret
    
    from crystal.server import _DEFAULT_SERVER_HOST, _DEFAULT_SERVER_PORT
    from crystal.util.xos import is_linux

    # Parse CLI arguments
    parser = argparse.ArgumentParser(
        description='Crystal: A tool for archiving websites in high fidelity.',
        add_help=False,
    )
    parser.add_argument(
        '--readonly',
        help='Open projects as read-only by default rather than as writable.',
        action='store_true',
    )
    parser.add_argument(
        '--no-readonly',
        help='Open projects as writable by default rather than as read-only.',
        action='store_true',
    )
    parser.add_argument(
        '--serve',
        help='Start serving opened projects immediately.',
        action='store_true',
    )
    parser.add_argument(
        '--port', '-p',
        help=f'Specify the port to bind to when using --serve (default: {_DEFAULT_SERVER_PORT}).',
        type=int,
        default=None,
    )
    parser.add_argument(
        '--host',
        help=f'Specify the host to bind to when using --serve (default: {_DEFAULT_SERVER_HOST}).',
        type=str,
        default=None,
    )
    parser.add_argument(
        '--shell',
        help='Start a CLI shell when running Crystal.',
        action='store_true',
    )
    parser.add_argument(
        '--headless',
        help='Avoid showing any GUI. Must be combined with --serve or --shell.',
        action='store_true',
    )
    parser.add_argument(
        '--cookie',
        help='An HTTP Cookie header value to send when downloading resources.',
        type=str,
        default=None,
    )
    parser.add_argument(
        '--stale-before',
        help=(
            'If specified then any resource revision older than this datetime '
            'will be considered stale and a new revision will be downloaded '
            'if a download of the related resource is requested. '
            
            'Can be an ISO date like "2022-07-17", "2022-07-17T12:47:42", '
            'or "2022-07-17T12:47:42+00:00".'
        ),
        type=datetime.datetime.fromisoformat,
        default=None,
    )
    if is_linux():
        parser.add_argument(
            '--install-to-desktop',
            help='Install this app to the Linux desktop environment.',
            action='store_true',
        )
    parser.add_argument(
        '--help', '-h',
        action='help',
        help='Show this help message and exit.'
    )
    parser.add_argument(
        '--test',
        help=argparse.SUPPRESS,  # 'Run automated tests.'
        action='store',
        nargs='*',
    )
    parser.add_argument(
        'project_filepath',
        # NOTE: Duplicates: Project.FILE_EXTENSION, Project.OPENER_FILE_EXTENSION
        help='Optional. Path to a *.crystalproj or *.crystalopen to open immediately.',
        type=str,
        default=None,
        nargs='?',
    )
    parsed_args = parser.parse_args(args)  # may raise SystemExit
    
    # Validate CLI arguments
    if (parsed_args.port is not None or parsed_args.host is not None) and not parsed_args.serve:
        # NOTE: Error message format and exit code are similar to those used by argparse
        print('error: --port and --host can only be used with --serve', file=sys.stderr)
        sys.exit(2)
    
    if parsed_args.headless and not (parsed_args.serve or parsed_args.shell):
        # NOTE: Error message format and exit code are similar to those used by argparse
        print('error: --headless must be combined with --serve or --shell', file=sys.stderr)
        sys.exit(2)
    
    if parsed_args.headless and parsed_args.serve and parsed_args.project_filepath is None:
        # NOTE: Error message format and exit code are similar to those used by argparse
        print('error: --headless --serve requires a project file path', file=sys.stderr)
        sys.exit(2)
    
    # Interpret --stale-before datetime as in local timezone if no UTC offset specified
    if parsed_args.stale_before is not None:
        from crystal.util.xdatetime import datetime_is_aware
        if not datetime_is_aware(parsed_args.stale_before):
            from tzlocal import get_localzone
            parsed_args.stale_before = parsed_args.stale_before.replace(
                tzinfo=get_localzone())  # reinterpret
    
    # Profile garbage collection
    from crystal.util.xgc import PROFILE_GC, start_profiling_gc
    if PROFILE_GC:
        start_profiling_gc()
    
    # --install-to-desktop, if requested
    if is_linux() and parsed_args.install_to_desktop:
        from crystal.install import install_to_linux_desktop_environment
        install_to_linux_desktop_environment()
        sys.exit()
    
    # Start GUI subsystem
    import wx
    import wx.richtext  # must import before wx.App object is created, according to wx.richtext module docstring
    import wx.xml  # required by wx.richtext; use explicit import as hint to py2app
    
    @atexit.register
    def on_atexit() -> None:
        """Called when the main thread and all non-daemon threads have exited."""

        from crystal.util.quitting import get_exit_code
        exit_code = get_exit_code()
        if exit_code is None:
            # Main thread did not set an exit code. Assume a bug.
            exit_code = 1  # default error exit code
        
        # Exit process immediately, without bothering to run garbage collection
        # or other cleanup processes that can take a long time
        os._exit(exit_code)
    
    # Set headless mode, before anybody tries to call fg_call_later
    from crystal.util.headless import set_headless_mode
    set_headless_mode(parsed_args.headless)
    
    # Create shell if requested. But don't start it yet.
    if parsed_args.shell:
        from crystal.shell import Shell
        shell = Shell()
    else:
        shell = None
    
    last_window = None  # type: Optional[MainWindow]
    systemexit_during_first_launch = None  # type: Optional[SystemExit]
    
    # 1. Create wx.App and call app.OnInit(), opening the initial dialog
    # 2. Initialize the foreground thread
    from crystal.util.bulkheads import capture_crashes_to_stderr
    from crystal.util.xthreading import fg_affinity
    class MyApp(wx.App):
        def __init__(self, *args, **kwargs):
            from crystal import APP_NAME
            from crystal.util.wx_bind import bind
            
            self._keepalive_frame = None
            self._did_finish_launch = False
            super().__init__(*args, **kwargs)
            
            # macOS: Define app name used by the "Quit X" and "Hide X" menuitems
            self.SetAppDisplayName(APP_NAME)
            
            # Listen for OS logout
            bind(self, wx.EVT_QUERY_END_SESSION, self._on_query_end_session)
            bind(self, wx.EVT_END_SESSION, self._on_end_session)
        
        @override
        def OnPreInit(self):
            # (May insert debugging code here in the future)
            pass
        
        @capture_crashes_to_stderr
        @override
        def OnInit(self):
            # If running as Mac .app, LC_CTYPE may be set to the default locale
            # instead of LANG. So copy any such locale to LANG.
            # 
            # Python documentation suggests that other variables may also
            # contain locale information: https://docs.python.org/3/library/locale.html#locale.getdefaultlocale
            if 'LANG' not in os.environ:
                for alternate_lang_var in ['LC_ALL', 'LC_CTYPE', 'LANGUAGE']:
                    if alternate_lang_var in os.environ:
                        os.environ['LANG'] = os.environ[alternate_lang_var]
                        break
            
            if sys.platform.startswith('win') and sys.version_info >= (3, 8):
                # Workaround wxPython >4.0.7 plus Python 3.8 breaking locale
                # https://discuss.wxpython.org/t/wxpython4-1-1-python3-8-locale-wxassertionerror/35168
                locale.setlocale(locale.LC_ALL, 'C')
            else:
                # Auto-detect appropriate locale based on os.environ['LANG']
                locale.setlocale(locale.LC_ALL, '')
            
            # Activate wx keepalive until self._finish_launch() is called
            self._keepalive_frame = wx.Frame(None, -1, 'Crystal')
            
            # Call self._finish_launch() after a short delay if it isn't
            # called in the meantime by MacOpenFile
            def wait_for_maybe_open_file():
                time.sleep(float(os.environ.get('CRYSTAL_OPEN_FILE_DELAY', '.2')))
                
                if not self._did_finish_launch:
                    from crystal.util.xthreading import fg_call_later
                    fg_call_later(self._finish_launch)
            thread = threading.Thread(target=wait_for_maybe_open_file, daemon=False)
            thread.start()
            
            return True
        
        # TODO: Migrate to use the non-deprecated MacOpenFiles interface,
        #       which accepts *multiple* files to open at the same time.
        @capture_crashes_to_stderr
        @override
        def MacOpenFile(self, filepath):
            if self._did_finish_launch:
                # App is already running
                
                # Open the project at the next available opportunity
                global _project_path_to_open_soon
                _project_path_to_open_soon = filepath
                
                # If the open/create dialog is currently showing,
                # interrupt it to observe the project we are requesting
                # to open and open it.
                global _interrupt_prompt_for_project_to_open_project
                if _interrupt_prompt_for_project_to_open_project is not None:
                    _interrupt_prompt_for_project_to_open_project()
                
                # If a project window is open, try to close it.
                # After it closes the open/create dialog will prepare to appear
                # again, observe the project we are requesting to open,
                # and open it.
                nonlocal last_window
                current_window = last_window  # capture
                if current_window is not None:
                    success = current_window.try_close()
                    if not success:
                        # Cancel the open operation
                        _project_path_to_open_soon = None
            else:
                # App is starting
                self._finish_launch(filepath)
        
        @capture_crashes_to_stderr
        def _finish_launch(self, filepath: str | None=None) -> None:
            from crystal.util.xthreading import start_fg_coroutine
            start_fg_coroutine(
                self._do_finish_launch(filepath),  # type: ignore[arg-type]
                _capture_crashes_to_stderr_and_capture_systemexit_to_quit)
        
        async def _do_finish_launch(self, filepath: str | None) -> None:
            self._did_finish_launch = True
            
            try:
                nonlocal last_window
                last_window = await _did_launch(parsed_args, shell, filepath)
            except SystemExit as e:
                nonlocal systemexit_during_first_launch
                systemexit_during_first_launch = e
                return
            except Exception:
                # wx doesn't like it when exceptions escape functions invoked
                # directly on the foreground thread. So just handle here.
                import traceback
                traceback.print_exc()
                return
            finally:
                # Deactivate wx keepalive
                self._keepalive_frame.Destroy()
        
        @capture_crashes_to_stderr
        @fg_affinity
        def _on_query_end_session(self, event: wx.CloseEvent) -> None:
            """
            Called when the OS is about to log out the user or shut down the system.
            Can veto the event to prevent logout/shutdown.
            """
            current_window = last_window  # capture
            if current_window is not None:
                # 1. Try to close the window
                # 2. Prompt to save the project if untitled and dirty
                did_not_cancel = current_window.try_close(
                    # If must prompt to save, then cancel logout/shutdown
                    will_prompt_to_save=lambda: event.Veto()
                )
                if not did_not_cancel:
                    # User cancelled the prompt to save, so don't allow logout/shutdown
                    # NOTE: This veto is probably redundant with the earlier veto
                    event.Veto()
                    return
            
            # Allow the logout/shutdown to proceed
            event.Skip()
        
        @capture_crashes_to_stderr
        @fg_affinity
        def _on_end_session(self, event: wx.CloseEvent) -> None:
            """
            Called when the session is ending and can't be stopped.
            Cleans up resources but does not try to prevent log out or shut down.
            """
            from crystal.util.quitting import set_is_quitting
            set_is_quitting()
            
            # Allow the logout/shutdown to proceed
            event.Skip()
    
    app = None  # type: Optional[wx.App]
    from crystal.util.quitting import is_quitting
    from crystal.util.xthreading import set_foreground_thread
    set_foreground_thread(threading.current_thread())
    try:
        # (Don't insert anything between set_foreground_thread() and MyApp())
        if not parsed_args.headless:
            # Queue call of app.OnInit() and _did_launch() after main loop starts
            # NOTE: Shows the dock icon on macOS
            app = MyApp(redirect=False)
        else:
            # Queue call of _did_launch() after main loop starts
            from crystal.util.xthreading import start_fg_coroutine
            start_fg_coroutine(
                _did_launch(parsed_args, shell),  # type: ignore[arg-type]
                _capture_crashes_to_stderr_and_capture_systemexit_to_quit)
        
        # Start shell if requested
        if shell is not None:
            shell.start(wait_for_banner=True)
        
        # Starts tests if requested
        if parsed_args.test is not None:
            from crystal.util.xthreading import (
                bg_call_later, has_foreground_thread,
            )
            assert has_foreground_thread(), (
                'Expected foreground thread to be running before starting tests, '
                'because tests expect to be able to schedule callables on '
                'the foreground thread'
            )
            
            # Immediately enter testing mode
            from crystal.util.test_mode import set_tests_are_running
            set_tests_are_running()
            
            from crystal.util.tqdm_debug import patch_tqdm_to_debug_deadlocks
            patch_tqdm_to_debug_deadlocks(on_deadlock='keep_trying')
            
            # Block until test-related modules are done loading,
            # before starting bg_task() on background thread
            from crystal.tests.index import run_tests
            from crystal.util.bulkheads import capture_crashes_to_stderr

            # NOTE: Any unhandled exception will probably call os._exit(1)
            #       before reaching this decorator.
            @capture_crashes_to_stderr
            def bg_task():
                # (Don't import anything here, because strange things can
                #  happen if the foreground thread tries to import the
                #  same new modules at the same time. Instead put
                #  any needed imports directly before starting bg_task.)
                
                is_ok = False
                try:
                    is_ok = run_tests(parsed_args.test)
                finally:
                    exit_code = 0 if is_ok else 1
                    os._exit(exit_code)
            bg_call_later(bg_task)
        
        # 1. Run main loop
        # 2. Clean up
        # 3. Repeat if not is_quitting()
        if parsed_args.headless:  # headless mode
            # Run main loop until is_quitting() or no more fg calls are left
            from crystal.util.xthreading import run_headless_main_loop
            # NOTE: If Ctrl-C is pressed while this loop is running,
            #       then the process will exit immediately with code 130,
            #       without calling atexit handlers.
            run_headless_main_loop()
            if systemexit_during_first_launch is not None:
                raise systemexit_during_first_launch
            
            # Clean up
            if shell is not None:
                shell.detach()
        else:  # not headless mode
            assert app is not None
            while True:
                # Run main loop until no more windows or dialogs are open
                # NOTE: If Ctrl-C is pressed while this loop is running,
                #       then the process will exit immediately with code 130,
                #       without calling atexit handlers.
                app.MainLoop()
                if systemexit_during_first_launch is not None:
                    raise systemexit_during_first_launch
                
                # Clean up
                if shell is not None:
                    shell.detach()
                if last_window is not None:
                    # TODO: Implement Project.closed so that this assertion can be checked
                    #assert last_window.project.closed, (
                    #    'Expected project to already be fully closed '
                    #    'during the MainLoop by MainWindow'
                    #)
                    last_window = None
                
                # Quit?
                if is_quitting():
                    break
                
                # Clear first-only launch arguments
                parsed_args.project_filepath = None
                
                # Re-launch, reopening the initial dialog
                from crystal.util.xthreading import start_fg_coroutine
                async def relaunch():
                    nonlocal last_window
                    last_window = await _did_launch(parsed_args, shell)  # can raise SystemExit
                start_fg_coroutine(
                    relaunch(),
                    _capture_crashes_to_stderr_and_capture_systemexit_to_quit)
    except SystemExit as e:
        if e.code not in [None, 0]:
            # Exit with error
            raise
        else:
            # Exit normally
            pass
    finally:
        # Stop any further events from being scheduled on the main loop
        set_foreground_thread(None)
    
    # Drain any lingering events from the main loop
    if app is not None:
        if app.HasPendingEvents():
            app.ProcessPendingEvents()
            if app.HasPendingEvents():
                print('Warning: Exiting app while some pending events still exist')


async def _did_launch(
        parsed_args,
        shell: Shell | None,
        filepath: str | None=None
        ) -> MainWindow | None:
    """
    Raises:
    * SystemExit -- if the user quits
    """
    from crystal.model import Project
    from crystal.progress import CancelOpenProject, OpenProjectProgressDialog
    from crystal.server import _DEFAULT_SERVER_HOST, _DEFAULT_SERVER_PORT
    from crystal.util.ports import is_port_in_use_error
    from crystal.util.test_mode import tests_are_running

    # If MacOpenFile queued a project to be opened, open it
    global _project_path_to_open_soon
    if _project_path_to_open_soon is not None and filepath is None:
        filepath = _project_path_to_open_soon  # reinterpret
        _project_path_to_open_soon = None  # consume

    # If project to open was passed on the command-line, use it
    if parsed_args.project_filepath is not None and filepath is None:
        filepath = parsed_args.project_filepath  # reinterpret
    
    # Open/create a project
    project: Project | None = None
    window: MainWindow | None = None
    try:
        # In headless mode without a project, skip project operations
        if parsed_args.headless and filepath is None:
            # No project to open in headless shell mode
            project = None
        else:
            with OpenProjectProgressDialog() as progress_listener:
                # Export reference to progress_listener, if running tests
                if tests_are_running():
                    from crystal import progress
                    progress._active_progress_listener = progress_listener
                
                # Calculate whether to open as readonly
                effective_readonly: bool
                if parsed_args.readonly:
                    # Explicitly --readonly
                    effective_readonly = True
                elif parsed_args.no_readonly:
                    # Explicitly --no-readonly
                    effective_readonly = False
                else:
                    host = parsed_args.host or _DEFAULT_SERVER_HOST
                    if host == '127.0.0.1':
                        # Serving to localhost. Default to writable.
                        effective_readonly = False
                    else:
                        # Serving to a remote host. Default to read-only.
                        effective_readonly = True
                
                # Get a project
                project_kwargs = dict(
                    readonly=effective_readonly,
                )  # type: dict[str, Any]
                if filepath is None:
                    from crystal.app_preferences import app_prefs
                    last_untitled_project_path = app_prefs.unsaved_untitled_project_path
                    reopen_projects_disabled = os.environ.get('CRYSTAL_NO_REOPEN_PROJECTS', 'False') == 'True'
                    if (last_untitled_project_path is not None and 
                            os.path.exists(last_untitled_project_path) and
                            not reopen_projects_disabled):
                        # Try to open the last untitled project
                        try:
                            # NOTE: Can raise CancelOpenProject
                            retry_on_cancel = True
                            project = _load_project(
                                last_untitled_project_path,
                                progress_listener,
                                is_untitled=True,
                                is_dirty=True,
                                **project_kwargs
                            )
                        except:
                            # If user cancels opening the untitled project,
                            # or if the project fails to open for any other reason
                            # (like corruption on disk), clear the record of
                            # the untitled project so the user can open
                            # something else
                            from crystal.app_preferences import app_prefs
                            del app_prefs.unsaved_untitled_project_path
                            raise
                    else:
                        # NOTE: Can raise SystemExit
                        retry_on_cancel = True
                        project = await _prompt_for_project(progress_listener, **project_kwargs)
                else:
                    # NOTE: Can raise CancelOpenProject
                    retry_on_cancel = False
                    project = _load_project(filepath, progress_listener, **project_kwargs)
                assert project is not None
                
                # Configure project
                project.request_cookie = parsed_args.cookie
                project.min_fetch_date = parsed_args.stale_before
                
                # Create main window (unless in headless mode)
                if not parsed_args.headless:
                    from crystal.browser import MainWindow
                    # NOTE: Can raise CancelOpenProject
                    window = MainWindow(project, progress_listener)
    except CancelOpenProject:
        if project is not None:
            project.close()
        if retry_on_cancel:
            return await _did_launch(parsed_args, shell, filepath)
        else:
            raise SystemExit()
    
    if shell is not None:
        shell.attach(project, window)

    # Start serving immediately if requested
    if parsed_args.serve:
        if project is None:
            # NOTE: Error message format and exit code are similar to those used by argparse
            print('error: --serve requires a project to be opened', file=sys.stderr)
            sys.exit(2)
        
        try:
            if window is not None:  # not headless mode
                window.start_server(port=parsed_args.port, host=parsed_args.host)
            else:  # headless mode
                from crystal.server import ProjectServer
                project_server = ProjectServer(
                    project,
                    port=parsed_args.port,
                    host=parsed_args.host,
                    # TODO: Alter ProjectServer to accept the more-general TextIO
                    #       instead of insisting on a TextIOBase
                    stdout=cast(TextIOBase, sys.stdout),
                    # NOTE: Print special exit instruction in headless mode
                    exit_instruction='Press Ctrl-C to stop.',
                    wait_for_banner=True,
                )
        except Exception as e:
            if window is not None:
                # NOTE: Also closes the project it manages
                window.close()
            elif project is not None:
                project.close()
            
            if is_port_in_use_error(e):
                port = parsed_args.port or _DEFAULT_SERVER_PORT
                host = parsed_args.host or _DEFAULT_SERVER_HOST
                print(f'*** Cannot start server on {host}:{port} - address already in use', file=sys.stderr)
            else:
                print(f'*** Cannot start server', file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
            raise SystemExit(1)
    
    return window


async def _prompt_for_project(
        progress_listener: OpenProjectProgressListener,
        **project_kwargs: object
        ) -> Project:
    """
    Raises:
    * SystemExit -- if the user quits rather than providing a project
    """
    from crystal.progress import CancelOpenProject
    from crystal.ui.BetterMessageDialog import BetterMessageDialog
    from crystal.util.wx_bind import bind
    from crystal.util.xos import is_mac_os
    import wx
    
    readonly_default = bool(project_kwargs.get('readonly', False))
    
    def on_checkbox_clicked(event: wx.CommandEvent | None = None) -> None:
        readonly_checkbox_checked = dialog.IsCheckBoxChecked()
        create_button = dialog.FindWindow(id=wx.ID_YES)
        create_button.Enabled = not readonly_checkbox_checked
    
    def on_char_hook(event: wx.KeyEvent) -> None:
        key_code = event.GetKeyCode()
        if (key_code == ord('R') or key_code == ord('r')) and \
                event.GetModifiers() in (wx.MOD_ALT, wx.MOD_CONTROL):
            # Toggle the checkbox when Alt+R or Ctrl+R is pressed
            assert dialog._checkbox is not None
            # NOTE: Calls on_checkbox_clicked() internally
            dialog.CheckBoxChecked = not dialog.CheckBoxChecked
            
            # Focus the checkbox manually on macOS to prevent dialog from losing focus
            if is_mac_os():
                dialog._checkbox.SetFocus()
        else:
            event.Skip()
    
    dialog = BetterMessageDialog(None,
        message='Create a new project or open an existing project?',
        title='Select a Project',
        checkbox_label='Open as &read only',
        checkbox_checked=readonly_default,
        on_checkbox_clicked=on_checkbox_clicked,
        style=wx.YES_NO,
        yes_label='&New Project',
        no_label='&Open',
        escape_is_cancel=True,
        name='cr-open-or-create-project')
    with dialog:
        def interrupt_dialog_to_open_project() -> None:
            import wx
            wx.PostEvent(dialog, wx.CommandEvent(
                wx.wxEVT_COMMAND_BUTTON_CLICKED,
                wx.ID_NO  # "Open" button
            ))
        
        global _interrupt_prompt_for_project_to_open_project
        _interrupt_prompt_for_project_to_open_project = interrupt_dialog_to_open_project
        try:
            # Set initial state of Create button based on checkbox state
            on_checkbox_clicked()
            
            # Configure Ctrl+R (and Alt+R) key to toggle readonly checkbox.
            # NOTE: Use wx.EVT_CHAR_HOOK rather than wx.EVT_KEY_DOWN so that
            #       works on macOS where wx.EVT_KEY_DOWN does not work in dialogs.
            dialog.Bind(wx.EVT_CHAR_HOOK, on_char_hook)

            dialog.SetAcceleratorTable(wx.AcceleratorTable([
                wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('N'), wx.ID_YES),
                wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('O'), wx.ID_NO),
            ]))
            
            while True:
                from crystal.util.wx_dialog import ShowModalAsync
                choice = await ShowModalAsync(dialog)
                
                project_kwargs = {
                    **project_kwargs,
                    **dict(readonly=dialog.IsCheckBoxChecked()),
                }  # reinterpret
                
                try:
                    if choice == wx.ID_YES:  # New Project
                        return _create_untitled_project(dialog, progress_listener, **project_kwargs)
                    elif choice == wx.ID_NO:  # Open
                        # If MacOpenFile queued a project to be opened, open it
                        global _project_path_to_open_soon
                        if _project_path_to_open_soon is not None:
                            filepath = _project_path_to_open_soon
                            _project_path_to_open_soon = None  # consume
                            return _load_project(
                                filepath,
                                progress_listener,
                                **project_kwargs)  # type: ignore[arg-type]
                        
                        return _prompt_to_open_project(dialog, progress_listener, **project_kwargs)
                    elif choice == wx.ID_CANCEL:
                        raise SystemExit()
                    else:
                        raise AssertionError()
                except CancelOpenProject:
                    progress_listener.reset()
                    continue
        finally:
            _interrupt_prompt_for_project_to_open_project = None


def _create_untitled_project(
        parent: wx.Window,
        progress_listener: OpenProjectProgressListener,
        **project_kwargs: object
        ) -> Project:
    from crystal.model import Project
    from crystal.progress import LoadUrlsProgressDialog
    
    return Project(
        None,  # untitled
        progress_listener, 
        LoadUrlsProgressDialog(),
        **project_kwargs  # type: ignore[arg-type]
    )


def _prompt_to_open_project(
        parent: wx.Window,
        progress_listener: OpenProjectProgressListener,
        **project_kwargs: object
        ) -> Project:
    """
    Raises:
    * CancelOpenProject -- if the user cancels the prompt early
    """
    from crystal.model import Project
    from crystal.progress import CancelOpenProject
    from crystal.util.wx_bind import bind
    from crystal.util.wx_dialog import position_dialog_initially, ShowModal
    from crystal.util.xos import is_linux, is_mac_os, is_windows
    import wx
    
    project_path = None  # type: Optional[str]
    
    class OpenAsDirectoryHook(wx.FileDialogCustomizeHook):
        def AddCustomControls(self, customizer: wx.FileDialogCustomize):  # override
            self.open_dir_button = customizer.AddButton('Open Directory')  # type: wx.FileDialogButton
            self.open_dir_button.Disable()
            bind(self.open_dir_button, wx.EVT_BUTTON, self._on_open_directory)
        
        def UpdateCustomControls(self) -> None:  # override
            selected_itempath = file_dialog.GetPath()
            selected_itemname = os.path.basename(selected_itempath)
            project_is_selected = (
                os.path.exists(selected_itempath) and (
                    selected_itemname.endswith(Project.FILE_EXTENSION) or
                    selected_itemname.endswith(Project.OPENER_FILE_EXTENSION)
                )
            )
            if project_is_selected:
                self.open_dir_button.Enable()
            else:
                self.open_dir_button.Disable()
        
        def _on_open_directory(self, event: wx.CommandEvent) -> None:
            nonlocal project_path
            #nonlocal file_dialog
            
            project_path = file_dialog.GetPath()
            assert not (is_mac_os() or is_windows()), (
                'wx.FileDialog.EndModal() does not dismiss dialog '
                'on macOS or Windows'
            )
            file_dialog.EndModal(wx.ID_OK)
    
    file_dialog_customize_hook = OpenAsDirectoryHook()
    file_dialog = wx.FileDialog(parent,
        message='Choose a project',
        wildcard='Projects ({wc};{wc2})|{wc};{wc2}'.format(
            # If projects appear as files, then can open directly
            wc='*' + Project.FILE_EXTENSION,
            # If projects appear as directories, then must open contained opener file
            wc2='*' + Project.OPENER_FILE_EXTENSION,
        ),
        style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
    # Offer ability to open .crystalproj directories on Linux,
    # where they were historically created without a .crystalopen file.
    # 
    # NOTE: On Windows it is possible to double-click a .crystalproj directory
    #       to open it in Crystal even if it has no .crystalopen file.
    #       So no special support for opening a .crystalproj directory
    #       needs to be provided here.
    if is_linux():
        file_dialog.SetCustomizeHook(file_dialog_customize_hook)
    with file_dialog:
        if not file_dialog.ShowModal() == wx.ID_OK:
            raise CancelOpenProject()
        if project_path is None:
            project_path = file_dialog.GetPath()
        assert project_path is not None
    del file_dialog_customize_hook  # keep hook alive until after dialog closed
    
    if not os.path.exists(project_path):
        raise AssertionError()
    if not Project.is_valid(project_path):
        _show_invalid_project_dialog()
        raise CancelOpenProject()
    
    assert '_show_modal_func' not in project_kwargs
    return _load_project(
        project_path,
        progress_listener,
        **project_kwargs)  # type: ignore[arg-type]


def _load_project(
        project_path: str,
        progress_listener: OpenProjectProgressListener,
        # NOTE: Used by automated tests
        *, _show_modal_func: Optional[Callable[[wx.Dialog], int]]=None,
        **project_kwargs: object
        ) -> Project:
    """
    Raises:
    * CancelOpenProject
    """
    from crystal.model import Project, ProjectFormatError, ProjectReadOnlyError, ProjectTooNewError
    from crystal.progress import CancelOpenProject, LoadUrlsProgressDialog
    from crystal.util.wx_dialog import position_dialog_initially
    import wx
    
    if _show_modal_func is None:
        from crystal.util.wx_dialog import ShowModal as _show_modal_func
    assert _show_modal_func is not None  # help mypy
    
    try:
        return Project(project_path, progress_listener, LoadUrlsProgressDialog(), **project_kwargs)  # type: ignore[arg-type]
    except ProjectReadOnlyError:
        # TODO: Present this error to the user nicely
        raise
    except ProjectFormatError:
        _show_invalid_project_dialog(
            project_is_likely_corrupted=True,
            _show_modal_func=_show_modal_func)
        raise CancelOpenProject()
    except ProjectTooNewError:
        dialog = wx.MessageDialog(None,
            message=(
                'This project was created by a newer version of Crystal '
                'and cannot be opened by this version of Crystal.'
            ),
            caption='Project Too New',
            style=wx.ICON_ERROR|wx.OK,
        )
        dialog.Name = 'cr-project-too-new'
        with dialog:
            position_dialog_initially(dialog)
            _show_modal_func(dialog)
        raise CancelOpenProject()
    except CancelOpenProject:
        raise


def _show_invalid_project_dialog(
        *, project_is_likely_corrupted: bool=False,
        # NOTE: Used by automated tests
        _show_modal_func: Optional[Callable[[wx.Dialog], int]]=None,
        ) -> None:
    from crystal.util.wx_dialog import (
        position_dialog_initially, set_dialog_or_frame_icon_if_appropriate,
    )
    import wx
    
    if _show_modal_func is None:
        from crystal.util.wx_dialog import ShowModal as _show_modal_func
    assert _show_modal_func is not None  # help mypy
    
    extra = ' and may be corrupted' if project_is_likely_corrupted else ''
    
    dialog = wx.MessageDialog(None,
        message=f'The selected file or directory is not a valid project{extra}.',
        caption='Invalid Project',
        style=wx.ICON_ERROR|wx.OK,
    )
    dialog.Name = 'cr-invalid-project'
    with dialog:
        position_dialog_initially(dialog)
        _show_modal_func(dialog)


def _capture_crashes_to_stderr_and_capture_systemexit_to_quit(
        func: Callable[_P, _RT]
        ) -> Callable[_P, _RT | None]:
    """
    A variant of @capture_crashes_to_stderr that captures crashes
    but interprets SystemExit exceptions as a normal request to quit.
    """
    from crystal.util.bulkheads import capture_crashes_to_stderr
    @capture_crashes_to_stderr
    def bulkhead_call(*args: _P.args, **kwargs: _P.kwargs) -> _RT | None:
        try:
            return func(*args, **kwargs)  # cr-traceback: ignore
        except SystemExit:
            from crystal.util.quitting import set_is_quitting
            set_is_quitting()
            return None
    return bulkhead_call


# ------------------------------------------------------------------------------

if __name__ == '__main__':
    main()
