#!/usr/bin/env python
"""
Home of the main function, which starts the program.
"""

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
from contextlib import contextmanager
import datetime
import locale
import os
import os.path
import shutil
import subprocess
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
    from typing import Iterator, List, Optional
    import wx


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
    interactive = 'TERM' in os.environ
    log_to_file = (
        (getattr(sys, 'frozen', None) == 'macosx_app' and not interactive) or
        (getattr(sys, 'frozen', None) == 'windows_exe')
    )
    if log_to_file:
        from appdirs import user_log_dir
        from crystal import APP_AUTHOR, APP_NAME
        
        log_dirpath = user_log_dir(APP_NAME, APP_AUTHOR)
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
    
    from crystal.util.xos import is_linux
    
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
    if is_linux():
        parser.add_argument(
            '--install-to-desktop',
            help='Install this app to the desktop.',
            action='store_true',
        )
    parser.add_argument(
        'filepath',
        # NOTE: Duplicates: Project.FILE_EXTENSION, Project.LAUNCHER_FILE_EXTENSION
        help='Optional. Path to a *.crystalproj or *.crystalopen to open.',
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
    
    # --install-to-desktop, if requested
    if is_linux() and parsed_args.install_to_desktop:
        _install_to_desktop()
        sys.exit()
    
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
            from crystal import APP_NAME
            
            self._keepalive_frame = None
            self._did_finish_launch = False
            super().__init__(*args, **kwargs)
            
            # macOS: Define app name used by the "Quit X" and "Hide X" menuitems
            self.SetAppDisplayName(APP_NAME)
        
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
        if parsed_args.test is not None:
            from crystal.util.xthreading import bg_call_later, fg_call_later, has_foreground_thread
            assert has_foreground_thread(), (
                'Expected foreground thread to be running before starting tests, '
                'because tests expect to be able to schedule callables on '
                'the foreground thread'
            )
            
            # Immediately enter testing mode
            os.environ['CRYSTAL_RUNNING_TESTS'] = 'True'
            
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


def _install_to_desktop() -> None:
    """Install the Crystal application to the desktop. (Linux only)"""
    from crystal import resources
    from crystal.util import gio
    from crystal.util.xos import is_linux
    import glob
    
    if not is_linux():
        raise ValueError()
    
    # Ensure not running as root (unless is actually the root user)
    running_as_root_user = (os.geteuid() == 0)
    is_root_user = (os.getuid() == 0)
    if running_as_root_user and not is_root_user:
        print('*** --install-to-desktop should not be run as root or with sudo')
        sys.exit(1)
    
    # Install .desktop file to ~/.local/share/applications
    # 
    # NOTE: Only .desktop files opened from this directory will show their
    #       icon in the dock correctly.
    if True:
        # Format .desktop file in memory
        with resources.open_text('crystal.desktop', encoding='utf-8') as f:
            desktop_file_content = f.read()
        if os.path.basename(sys.executable) in ['python', 'python3']:
            crystal_executable = f'{sys.executable} -m crystal'
        else:
            crystal_executable = sys.executable
        desktop_file_content = desktop_file_content.replace(
            '__CRYSTAL_PATH__', crystal_executable)
        desktop_file_content = desktop_file_content.replace(
            '__APPICON_PATH__', resources.get_filepath('appicon.png'))
        
        apps_dirpath = os.path.expanduser('~/.local/share/applications')
        os.makedirs(apps_dirpath, exist_ok=True)
        with open(f'{apps_dirpath}/crystal.desktop', 'w') as f:
            f.write(desktop_file_content)
        
        subprocess.run([
            'update-desktop-database',
            os.path.expanduser('~/.local/share/applications')
        ], check=True)
    
    # Install symlink to .desktop file on ~/Desktop, if possible
    desktop_dirpath = os.path.expanduser('~/Desktop')
    if os.path.isdir(desktop_dirpath) and not os.path.exists(f'{desktop_dirpath}/crystal.desktop'):
        subprocess.run([
            'ln', '-s',
            f'{apps_dirpath}/crystal.desktop',
            f'{desktop_dirpath}/crystal.desktop',
        ], check=True)
        
        # Mark .desktop symlink on desktop as "Allow Launching" on Ubuntu 22+
        # https://askubuntu.com/questions/1218954/desktop-files-allow-launching-set-this-via-cli
        try:
            gio.set(f'{desktop_dirpath}/crystal.desktop', 'metadata::trusted', 'true')
        except gio.GioNotAvailable:
            pass
        except gio.UnrecognizedGioAttributeError:
            # For example Kubuntu 22 does not recognize this attribute
            pass
        else:
            subprocess.run([
                'chmod', 'a+x',
                f'{desktop_dirpath}/crystal.desktop',
            ], check=True)
    
    # Install .crystalopen MIME type definition
    mime_dirpath = os.path.expanduser('~/.local/share/mime')
    os.makedirs(f'{mime_dirpath}/packages', exist_ok=True)
    with open(f'{mime_dirpath}/packages/application-vnd.crystal-opener.xml', 'w') as dst_file:
        with resources.open_text('application-vnd.crystal-opener.xml', encoding='utf-8') as src_file:
            shutil.copyfileobj(src_file, dst_file)
    subprocess.run(['update-mime-database', mime_dirpath], check=True)
    
    # Install .crystalopen file icon
    if True:
        # Locate places where MIME icons are installed, in global theme directories
        mime_icon_dirpaths = []
        with _cwd_set_to('/usr/share/icons'):
            for mime_icon_filepath in glob.iglob('**/text-plain.*', recursive=True):
                mime_icon_dirpath = os.path.dirname(mime_icon_filepath)
                if mime_icon_dirpath not in mime_icon_dirpaths:
                    mime_icon_dirpaths.append(mime_icon_dirpath)
        
        # Install new MIME icons, in local theme directories
        if len(mime_icon_dirpaths) == 0:
            print('*** Unable to locate places to install MIME icons')
        else:
            local_icons_dirpath = os.path.expanduser('~/.local/share/icons')
            for mime_icon_dirpath in mime_icon_dirpaths:
                mime_icon_abs_dirpath = os.path.join(local_icons_dirpath, mime_icon_dirpath)
                os.makedirs(mime_icon_abs_dirpath, exist_ok=True)
                
                # Install PNG icon for MIME type
                with open(f'{mime_icon_abs_dirpath}/application-vnd.crystal-opener.png', 'wb') as dst_file:
                    # TODO: Read/cache source icon once, so that don't need to many times...
                    with resources.open_binary('application-vnd.crystal-opener.png') as src_file:
                        shutil.copyfileobj(src_file, dst_file)
                
                # Install SVG icon for MIME type,
                # because at least KDE on Kubuntu 22 seems to ignore PNG icons
                with open(f'{mime_icon_abs_dirpath}/application-vnd.crystal-opener.svg', 'wb') as dst_file:
                    # TODO: Read/cache source icon once, so that don't need to many times...
                    with resources.open_binary('application-vnd.crystal-opener.svg') as src_file:
                        shutil.copyfileobj(src_file, dst_file)
            
            # NOTE: At least on Ubuntu 22 it seems the icon caches don't need
            #       to be explicitly updated to pick up the new icon type
            #       immediately, which is good because it may not be possible
            #       to sudo.
            #subprocess.run(['sudo', 'update-icon-caches', *glob.glob('/usr/share/icons/*')], check=True)
    
    # Install .crystalproj folder icon
    if True:
        # Determine icon names for regular folder, which actually resolve to an icon
        try:
            regular_folder_dirpath = os.path.dirname(__file__)
            p = subprocess.run(
                ['gio', 'info', '--attributes', 'standard::icon', regular_folder_dirpath],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError:
            # GIO not available
            pass
        else:
            icon_names: List[str]
            gio_lines = p.stdout.decode('utf-8').split('\n')
            for line in gio_lines:
                line = line.strip()  # reinterpret
                if line.startswith('standard::icon:'):
                    line = line[len('standard::icon:'):]  # reinterpret
                    icon_names = [x.strip() for x in line.strip().split(',')]
                    break
            else:
                icon_names = []
            
            # Locate places where folder icons are installed, in global theme directories
            folder_icon_dirpaths = []
            if len(icon_names) != 0:
                with _cwd_set_to('/usr/share/icons'):
                    for (root_dirpath, dirnames, filenames) in os.walk('.'):
                        for filename in filenames:
                            (filename_without_ext, _) = os.path.splitext(filename)
                            if filename_without_ext in icon_names:
                                if root_dirpath not in folder_icon_dirpaths:
                                    folder_icon_dirpaths.append(root_dirpath)
            
            # Install new folder icons, in local theme directories
            if len(folder_icon_dirpaths) == 0:
                print('*** Unable to locate places to install folder icons')
            else:
                local_icons_dirpath = os.path.expanduser('~/.local/share/icons')
                for folder_icon_dirpath in folder_icon_dirpaths:
                    folder_icon_abs_dirpath = os.path.join(local_icons_dirpath, folder_icon_dirpath)
                    os.makedirs(folder_icon_abs_dirpath, exist_ok=True)
                    
                    # Install PNG icon for folder type
                    with open(f'{folder_icon_abs_dirpath}/crystalproj.png', 'wb') as dst_file:
                        # TODO: Read/cache source icon once, so that don't need to 123 times...
                        with resources.open_binary('docicon.png') as src_file:
                            shutil.copyfileobj(src_file, dst_file)
                    
                    # Install SVG icon for folder type,
                    # because at least KDE on Kubuntu 22 seems to ignore PNG icons
                    with open(f'{folder_icon_abs_dirpath}/crystalproj.svg', 'wb') as dst_file:
                        # TODO: Read/cache source icon once, so that don't need to 123 times...
                        with resources.open_binary('docicon.svg') as src_file:
                            shutil.copyfileobj(src_file, dst_file)


@contextmanager
def _cwd_set_to(dirpath: str) -> 'Iterator[None]':
    old_cwd = os.getcwd()
    os.chdir(dirpath)
    try:
        yield
    finally:
        os.chdir(old_cwd)


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
    from crystal.util.wx_bind import bind
    from crystal.util.xos import is_linux, is_mac_os, is_windows
    import wx
    
    project_path = None  # type: Optional[str]
    
    class OpenAsDirectoryHook(wx.FileDialogCustomizeHook):
        def AddCustomControls(self, customizer: wx.FileDialogCustomize):  # override
            self.button = customizer.AddButton('Open Directory...')
            bind(self.button, wx.EVT_BUTTON, self._on_open_directory)
        
        def _on_open_directory(self, event: wx.CommandEvent) -> None:
            nonlocal project_path
            #nonlocal file_dialog
            
            file_dialog_filepath = file_dialog.GetPath()
            # NOTE: wx.FileDialog.GetPath() returns '' on Linux/wxGTK if viewing
            #       and empty directory.
            if file_dialog_filepath != '' and os.path.exists(file_dialog_filepath):
                file_dialog_dirpath = os.path.dirname(file_dialog_filepath)  # type: Optional[str]
            else:
                file_dialog_dirpath = None
            
            dir_dialog = wx.DirDialog(parent,
                message='Choose a project',
                style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST)
            if file_dialog_dirpath is not None:
                dir_dialog.SetPath(file_dialog_dirpath)
            with dir_dialog:
                if not dir_dialog.ShowModal() == wx.ID_OK:
                    return
                project_path = dir_dialog.GetPath()  # capture
            
            assert not is_mac_os(), 'wx.FileDialog.EndModal() does not work on macOS'
            file_dialog.EndModal(wx.ID_OK)
    
    file_dialog_customize_hook = OpenAsDirectoryHook()
    file_dialog = wx.FileDialog(parent,
        message='Choose a project',
        wildcard='Projects (%(wc)s;%(wc2)s)|%(wc)s;%(wc2)s' % {
            # If projects appear as files, then can open directly
            'wc': '*' + Project.FILE_EXTENSION,
            # If projects appear as directories, then must open contained launcher file
            'wc2': '*' + Project.LAUNCHER_FILE_EXTENSION,
        },
        style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
    # Offer ability to open .crystalproj directories on Linux and Windows,
    # where they were historically created without a .crystalopen file.
    if is_linux() or is_windows():
        file_dialog.SetCustomizeHook(file_dialog_customize_hook)
    with file_dialog:
        if not file_dialog.ShowModal() == wx.ID_OK:
            raise CancelOpenProject()
        if project_path is None:
            project_path = file_dialog.GetPath()
        assert project_path is not None
    del file_dialog_customize_hook  # keep hook alive until after dialog closed
    
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
