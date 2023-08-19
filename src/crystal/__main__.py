#!/usr/bin/env python
"""
Home of the main function, which starts the program.
"""

from __future__ import annotations

# NOTE: Avoid importing anything outside the Python standard library
#       at the top-level of this module, in case the import itself fails.
#       Import failure is more common in py2app and py2exe contexts and
#       is easier to debug when it does NOT happen at the top-level.
#       
#       Therefore many imports in this file should occur directly within functions.
import argparse
import atexit
import datetime
import locale
import os
import os.path
import shutil
import sys
import threading
import time
try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False

if TYPE_CHECKING:
    from crystal.browser import MainWindow
    from crystal.model import Project
    from crystal.progress import OpenProjectProgressListener
    from crystal.shell import Shell
    from typing import List, Optional
    import wx


_APP_NAME = 'Crystal Web Archiver'
_APP_AUTHOR = 'DaFoster'


def main() -> None:
    """
    Main function. Starts the program.
    """
    _main(sys.argv[1:])


def _main(args: List[str]) -> None:
    _check_environment()
    
    # If running as Mac app or as Windows executable, redirect stdout and 
    # stderr to file, since these don't exist in these environments.
    # Use line buffering (buffering=1) so that prints are observable immediately.
    interactive = 'PS1' in os.environ
    log_to_file = (
        (getattr(sys, 'frozen', None) == 'macosx_app' and not interactive) or
        (getattr(sys, 'frozen', None) == 'windows_exe')
    )
    if log_to_file:
        from appdirs import user_log_dir
        log_dirpath = user_log_dir(_APP_NAME, _APP_AUTHOR)
        os.makedirs(log_dirpath, exist_ok=True)
        
        sys.stdout = open(
            os.path.join(log_dirpath, 'stdout.log'), 
            'w', encoding='utf-8', buffering=1)
        sys.stderr = open(
            os.path.join(log_dirpath, 'stderr.log'), 
            'w', encoding='utf-8', buffering=1)
    
    # If CRYSTAL_FAULTHANDLER == True or running from source,
    # enable automatic dumping of Python tracebacks if wx has a segmentation fault
    if (os.environ.get('CRYSTAL_FAULTHANDLER', 'False') == 'True' or
            getattr(sys, 'frozen', None) is None):
        import faulthandler
        faulthandler.enable()
    
    # If running as Windows executable, also load .py files and adjacent
    # resources from the "lib" directory. Notably "tzinfo" data.
    if getattr(sys, 'frozen', None) == 'windows_exe':
        sys.path.insert(0, os.path.join(os.path.dirname(sys.executable), 'lib'))
    
    # If running as Windows executable, also look for command line arguments
    # in a text file in the current directory
    if getattr(sys, 'frozen', None) == 'windows_exe':
        if os.path.exists('arguments.txt'):
            with open('arguments.txt', 'r', encoding='utf-8') as f:
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
    
    # Filter out strange "psn" argument (ex: '-psn_0_438379') that
    # macOS does sometimes pass upon first launch when run as a
    # binary downloaded from the internet.
    args = [a for a in args if not a.startswith('-psn_')]  # reinterpret
    
    # Parse CLI arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--shell',
        help='Start a CLI shell after opening a project.',
        action='store_true',
    )
    parser.add_argument(
        '--serve',
        help='Start serving the project immediately.',
        action='store_true',
    )
    parser.add_argument(
        '--cookie',
        help='HTTP Cookie header value when downloading resources.',
        type=str,
        default=None,
    )
    parser.add_argument(
        '--readonly',
        help='Whether to open the project as read-only.',
        action='store_true',
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
    parser.add_argument(
        '--test',
        help='Run automated tests.',
        action='store',
        nargs='*',
    )
    parser.add_argument(
        'filepath',
        help='Optional. Path to a *.crystalproj to open.',
        type=str,
        default=None,
        nargs='?',
    )
    parsed_args = parser.parse_args(args)  # may raise SystemExit
    
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
    
    # Start shell if requested
    if parsed_args.shell:
        from crystal.shell import Shell
        shell = Shell()
    else:
        shell = None
    
    # Start GUI subsystem
    import wx
    import wx.xml  # required by wx.richtext; use explicit import as hint to py2app
    import wx.richtext  # must import before wx.App object is created, according to wx.richtext module docstring
    
    @atexit.register
    def on_atexit() -> None:
        # Exit process immediately, without bothering to run garbage collection
        # or other cleanup processes that can take a long time
        os._exit(getattr(os, 'EX_OK', 0))
    
    last_project = None  # type: Optional[Project]
    did_quit_during_first_launch = False
    
    # 1. Create wx.App and call app.OnInit(), opening the initial dialog
    # 2. Initialize the foreground thread
    class MyApp(wx.App):
        def __init__(self, *args, **kwargs):
            self._keepalive_frame = None
            self._did_finish_launch = False
            super().__init__(*args, **kwargs)
        
        def OnPreInit(self):
            # (May insert debugging code here in the future)
            pass
        
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
            self._keepalive_frame = wx.Frame(None, -1, 'Crystal Web Archiver')
            
            # Call self._finish_launch() after a short delay if it isn't
            # called in the meantime by MacOpenFile
            def wait_for_maybe_open_file():
                time.sleep(.2)
                
                if not self._did_finish_launch:
                    wx.CallAfter(lambda: self._finish_launch())
            thread = threading.Thread(target=wait_for_maybe_open_file, daemon=False)
            thread.start()
            
            return True
        
        def MacOpenFile(self, filepath):
            if self._did_finish_launch:
                # Ignore attempts to open additional projects if one is already open
                pass
            else:
                self._finish_launch(filepath)
        
        def _finish_launch(self, filepath: Optional[str]=None) -> None:
            self._did_finish_launch = True
            
            try:
                nonlocal last_project
                last_project = _did_launch(parsed_args, shell, filepath)
            except SystemExit:
                nonlocal did_quit_during_first_launch
                did_quit_during_first_launch = True
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
    
    app = None  # type: Optional[wx.App]
    from crystal.util.xthreading import is_quitting, set_foreground_thread
    set_foreground_thread(threading.current_thread())
    try:
        app = MyApp(redirect=False)
        
        # Starts tests if requested
        # NOTE: Must do this after initializing the foreground thread
        if parsed_args.test is not None:
            from crystal.util.xthreading import bg_call_later, fg_call_later, is_foreground_thread
            assert is_foreground_thread()
            def bg_task():
                is_ok = False
                try:
                    from crystal.tests.index import run_tests
                    is_ok = run_tests(parsed_args.test)
                finally:
                    # TODO: How should failure be reported if NoForegroundThreadError?
                    fg_call_later(lambda: sys.exit(0 if is_ok else 1))
            bg_call_later(bg_task)
        
        # Run GUI
        while True:
            # Process main loop until no more windows or dialogs are open
            app.MainLoop()
            if did_quit_during_first_launch:
                break
            
            # Clean up
            if shell is not None:
                shell.detach()
            if last_project is not None:
                last_project.close()
                last_project = None
            
            # Quit?
            if is_quitting():
                break
            
            # Clear first-only launch arguments
            parsed_args.filepath = None
            
            # Re-launch, reopening the initial dialog
            last_project = _did_launch(parsed_args, shell)  # can raise SystemExit
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


def _check_environment():
    # Check for dependencies
    if not _running_as_bundle():
        try:
            import wx
        except ImportError:
            sys.exit(
                'This application requires wxPython to be installed. ' + 
                'Download it from http://wxpython.org/')
        
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            sys.exit(
                'This application requires BeautifulSoup to be installed. ' +
                'Download it from http://www.crummy.com/software/BeautifulSoup/')


def _running_as_bundle():
    """
    Returns whether we are running in a bundled environment,
    such as py2exe or py2app.
    """
    return hasattr(sys, 'frozen')


def _did_launch(
        parsed_args,
        shell: Optional[Shell],
        filepath: Optional[str]=None
        ) -> Project:
    """
    Raises:
    * SystemExit -- if the user quits
    """
    from crystal.progress import CancelOpenProject, OpenProjectProgressDialog
    
    # If project to open was passed on the command-line, use it
    if parsed_args.filepath is not None:
        filepath = parsed_args.filepath  # reinterpret
    
    # Open/create a project
    project: Optional[Project] = None
    window: MainWindow
    try:
        with OpenProjectProgressDialog() as progress_listener:
            # Export reference to progress_listener, if running tests
            if os.environ.get('CRYSTAL_RUNNING_TESTS', 'False') == 'True':
                from crystal import progress
                progress._active_progress_listener = progress_listener
            
            # Get a project
            project_kwargs = dict(
                readonly=parsed_args.readonly,
            )
            if filepath is None:
                # NOTE: Can raise SystemExit
                retry_on_cancel = True
                project = _prompt_for_project(progress_listener, **project_kwargs)
            else:
                # NOTE: Can raise CancelOpenProject
                retry_on_cancel = False
                project = _load_project(filepath, progress_listener, **project_kwargs)
            assert project is not None
            
            # Configure project
            project.request_cookie = parsed_args.cookie
            project.min_fetch_date = parsed_args.stale_before
            
            # Create main window
            from crystal.browser import MainWindow
            # NOTE: Can raise CancelOpenProject
            window = MainWindow(project, progress_listener)
    except CancelOpenProject:
        if project is not None:
            project.close()
        if retry_on_cancel:
            return _did_launch(parsed_args, shell, filepath)
        else:
            raise SystemExit()
    
    if shell is not None:
        shell.attach(project, window)
    
    # Start serving immediately if requested
    if parsed_args.serve:
        window.start_server()
    
    return project


def _prompt_for_project(
        progress_listener: OpenProjectProgressListener,
        **project_kwargs: object
        ) -> Project:
    """
    Raises:
    * SystemExit -- if the user quits rather than providing a project
    """
    from crystal.progress import CancelOpenProject
    from crystal.ui.BetterMessageDialog import BetterMessageDialog
    import wx
    
    def on_checkbox_clicked(event: wx.CommandEvent) -> None:
        # HACK: Simulate toggle of value during dispatch of wx.CHECKBOX event
        if os.environ.get('CRYSTAL_RUNNING_TESTS', 'False') == 'True':
            assert dialog._checkbox is not None
            dialog._checkbox.Value = not dialog._checkbox.Value
        
        readonly_checkbox_checked = dialog.IsCheckBoxChecked()
        create_button = dialog.FindWindowById(wx.ID_YES)
        create_button.Enabled = not readonly_checkbox_checked
    
    dialog = BetterMessageDialog(None,
        message='Create a new project or open an existing project?',
        title='Select a Project',
        # TODO: Make it possible to check/uncheck this box by pressing the R key,
        #       and draw underline under R letter to signal that such a
        #       keyboard shortcut exists
        checkbox_label='Open as &read only',
        on_checkbox_clicked=on_checkbox_clicked,
        style=wx.YES_NO,
        yes_label='&New Project',
        no_label='&Open',
        escape_is_cancel=True,
        name='cr-open-or-create-project')
    with dialog:
        dialog.SetAcceleratorTable(wx.AcceleratorTable([
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('N'), wx.ID_YES),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('O'), wx.ID_NO),
            # TODO: Cannot use a normal accelerator to toggle a checkbox.
            #       Workaround.
            #wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('R'), dialog._checkbox.Id),
        ]))
        
        while True:
            from crystal.util.wx_dialog import ShowModal
            choice = ShowModal(dialog)
            
            project_kwargs = {
                **project_kwargs,
                **dict(readonly=dialog.IsCheckBoxChecked()),
            }  # reinterpret
            
            if choice == wx.ID_YES:
                try:
                    return _prompt_to_create_project(dialog, progress_listener, **project_kwargs)
                except CancelOpenProject:
                    progress_listener.reset()
                    continue
            elif choice == wx.ID_NO:
                try:
                    return _prompt_to_open_project(dialog, progress_listener, **project_kwargs)
                except CancelOpenProject:
                    progress_listener.reset()
                    continue
            else:  # wx.ID_CANCEL
                raise SystemExit()


def _prompt_to_create_project(
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
    import wx
    
    dialog = wx.FileDialog(parent,
        message='',
        wildcard='*' + Project.FILE_EXTENSION,
        style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
    with dialog:
        if not dialog.ShowModal() == wx.ID_OK:
            raise CancelOpenProject()
        
        project_path = dialog.GetPath()
        if not project_path.endswith(Project.FILE_EXTENSION):
            project_path += Project.FILE_EXTENSION
    
    if os.path.exists(project_path):
        shutil.rmtree(project_path)
    return Project(project_path, progress_listener, **project_kwargs)  # type: ignore[arg-type]


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
    from crystal.util.xos import project_appears_as_package_file
    import wx
    
    if project_appears_as_package_file():
        # If projects appear as files, use a file selection dialog
        dialog = wx.FileDialog(parent,
            message='Choose a project',
            wildcard='Projects (%(wc)s)|%(wc)s' % {'wc': '*' + Project.FILE_EXTENSION},
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
    else:
        # If projects appear as directories, use a directory selection dialog
        dialog = wx.DirDialog(parent,
            message='Choose a project',
            style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST)
    with dialog:
        if not dialog.ShowModal() == wx.ID_OK:
            raise CancelOpenProject()
        
        project_path = dialog.GetPath()
    
    if not os.path.exists(project_path):
        raise AssertionError
    if not Project.is_valid(project_path):
        from crystal.ui.BetterMessageDialog import BetterMessageDialog
        
        dialog = BetterMessageDialog(None,
            message='The selected directory is not a valid project.',
            title='Invalid Project',
            style=wx.OK,
            name='cr-invalid-project')
        with dialog:
            dialog.ShowModal()
        raise CancelOpenProject()
    
    return Project(project_path, progress_listener, **project_kwargs)  # type: ignore[arg-type]


def _load_project(
        project_path: str,
        progress_listener: OpenProjectProgressListener,
        **project_kwargs: object
        ) -> Project:
    """
    Raises:
    * CancelOpenProject
    """
    from crystal.model import Project
    
    # TODO: If errors while loading a project (ex: bad format),
    #       present them to the user nicely
    return Project(project_path, progress_listener, **project_kwargs)  # type: ignore[arg-type]


# ------------------------------------------------------------------------------

if __name__ == '__main__':
    main()
