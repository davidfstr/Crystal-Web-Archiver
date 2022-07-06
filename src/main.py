#!/usr/bin/env python
"""
Home of the main function, which starts the program.
"""

from __future__ import annotations

# NOTE: Do not add any imports that fail under Python 2.x.
#       This would prevent the version-checking code from running.
#       
#       Therefore most imports in this file should occur directly within functions.
import os
import sys
try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False

if TYPE_CHECKING:
    from crystal.browser import MainWindow
    from crystal.model import Project
    from crystal.progress import OpenProjectProgressListener
    from typing import List, Optional
    import wx


_APP_NAME = 'Crystal Web Archiver'
_APP_AUTHOR = 'DaFoster'


def main(args: List[str]) -> None:
    """
    Main function. Starts the program.
    """
    _check_environment()
    
    # If running as Mac app or as Windows executable, redirect stdout and 
    # stderr to file, since these don't exist in these environments.
    # Use line buffering (buffering=1) so that prints are observable immediately.
    log_to_file = (
        (getattr(sys, 'frozen', None) == 'macosx_app' and 
            (sys.stdout is None or sys.stderr is None)) or
        (getattr(sys, 'frozen', None) == 'windows_exe')
    )
    if log_to_file:
        from appdirs import user_log_dir
        log_dirpath = user_log_dir(_APP_NAME, _APP_AUTHOR)
        os.makedirs(log_dirpath, exist_ok=True)
        
        sys.stdout = open(os.path.join(log_dirpath, 'stdout.log'), 'w', buffering=1)
        sys.stderr = open(os.path.join(log_dirpath, 'stderr.log'), 'w', buffering=1)
    
    # If running as Windows executable, also look for command line arguments
    # in a text file in the current directory
    if getattr(sys, 'frozen', None) == 'windows_exe':
        if os.path.exists('arguments.txt'):
            with open('arguments.txt', 'r') as f:
                args_line = f.read()
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
    import argparse
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
        'filepath',
        help='Optional. Path to a *.crystalproj to open.',
        type=str,
        default=None,
        nargs='?',
    )
    parsed_args = parser.parse_args(args)  # may raise SystemExit
    
    # Start shell if requested
    shell = _Shell() if parsed_args.shell else None
    
    # Start GUI subsystem
    import wx
    
    last_project = None  # type: Optional[Project]
    
    # Create wx.App and call app.OnInit(), opening the initial dialog
    class MyApp(wx.App):
        def __init__(self, *args, **kwargs):
            self._keepalive_frame = None
            self._did_finish_launch = False
            super().__init__(*args, **kwargs)
        
        def OnPreInit(self):
            # (May insert debugging code here in the future)
            pass
        
        def OnInit(self):
            # Workaround wxPython >4.0.7 plus Python 3.8 breaking locale
            # https://discuss.wxpython.org/t/wxpython4-1-1-python3-8-locale-wxassertionerror/35168
            if sys.platform.startswith('win') and sys.version_info >= (3, 8):
                import locale
                locale.setlocale(locale.LC_ALL, 'C')
            
            # Activate wx keepalive until self._finish_launch() is called
            self._keepalive_frame = wx.Frame(None, -1, 'Crystal Web Archiver')
            
            # Call self._finish_launch() after a short delay if it isn't
            # called in the meantime by MacOpenFile
            def wait_for_maybe_open_file():
                import time
                time.sleep(.2)
                
                if not self._did_finish_launch:
                    wx.CallAfter(lambda: self._finish_launch())
            import threading
            thread = threading.Thread(target=wait_for_maybe_open_file, daemon=False)
            thread.start()
            
            return True
        
        def MacOpenFile(self, filepath):
            if self._did_finish_launch:
                # Ignore attempts to open additional projects if one is already open
                pass
            else:
                self._finish_launch(filepath)
        
        def _finish_launch(self, filepath=None):
            # type: (Optional[str]) -> None
            self._did_finish_launch = True
            
            nonlocal last_project
            last_project = _did_launch(parsed_args, shell, filepath)
            
            # Deactivate wx keepalive
            self._keepalive_frame.Destroy()
    app = MyApp(redirect=False)
    
    # Run GUI
    while True:
        # Process main loop until no more windows or dialogs are open
        app.MainLoop()  # will raise SystemExit if user quits
        
        # Clean up
        if shell is not None:
            shell.detach()
        if last_project is not None:
            last_project.close()
            last_project = None
        
        # Re-launch, reopening the initial dialog
        last_project = _did_launch(parsed_args, shell)

def _check_environment():
    # Check Python version
    py3 = hasattr(sys, 'version_info') and sys.version_info >= (3,0)
    if not py3:
        sys.exit('This application requires Python 3.x.')
    
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
        shell: Optional[_Shell],
        filepath: Optional[str]=None
        ) -> Project:
    """
    Raises:
    * SystemExit -- if the user quits
    """
    
    # If project to open was passed on the command-line, use it
    if parsed_args.filepath is not None:
        filepath = parsed_args.filepath  # reinterpret
    
    # Open/create a project
    project: Project
    window: MainWindow
    from crystal.progress import OpenProjectProgressDialog
    with OpenProjectProgressDialog() as progress_listener:
        # Get a project
        project_kwargs = dict(
            readonly=parsed_args.readonly,
        )
        if filepath is None:
            project = _prompt_for_project(progress_listener, **project_kwargs)
        else:
            project = _load_project(filepath, progress_listener, **project_kwargs)
        assert project is not None
        
        # Configure project
        project.request_cookie = parsed_args.cookie
        
        # Create main window
        from crystal.browser import MainWindow
        window = MainWindow(project, progress_listener)
    
    if shell is not None:
        shell.attach(project, window)
    
    # Start serving immediately if requested
    if parsed_args.serve:
        project.start_server()
    
    return project

class _Shell(object):
    def __init__(self) -> None:
        # Setup proxy variables for shell
        from crystal.model import Project
        from crystal.browser import MainWindow
        _Proxy.patch_help()
        self._project_proxy = _Proxy(f'<unset {Project.__module__}.{Project.__name__} proxy>')
        self._window_proxy = _Proxy(f'<unset {MainWindow.__module__}.{MainWindow.__name__} proxy>')
        
        # Define exit instructions,
        # based on site.setquit()'s definition in Python 3.8
        if os.sep == '\\':
            eof = 'Ctrl-Z plus Return'
        else:
            eof = 'Ctrl-D (i.e. EOF)'
        exit_instructions = 'Use %s() or %s to exit' % ('exit', eof)
        
        from crystal import __version__ as crystal_version
        from sys import version_info as python_version_info
        python_version = '.'.join([str(x) for x in python_version_info[:3]])
        
        import code
        import threading
        threading.Thread(
            target=lambda: code.interact(
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
                exitmsg='now waiting for main window to close...',
            ),
            daemon=False,
        ).start()
    
    def attach(self, project: Project, window: MainWindow) -> None:
        self._project_proxy.initialize_proxy(project, reinit_okay=True)
        self._window_proxy.initialize_proxy(window, reinit_okay=True)
    
    def detach(self) -> None:
        self._project_proxy.initialize_proxy(None, reinit_okay=True, unset_okay=True)
        self._window_proxy.initialize_proxy(None, reinit_okay=True, unset_okay=True)

class _Proxy(object):
    _unset_repr: str
    _value: 'Optional[object]'
    
    @staticmethod
    def patch_help() -> None:
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
    
    def initialize_proxy(self,
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

def _prompt_for_project(progress_listener, **project_kwargs):
    # type: (OpenProjectProgressListener, object) -> Project
    """
    Raises:
    * SystemExit -- if the user quits rather than providing a project
    """
    from crystal.ui.BetterMessageDialog import BetterMessageDialog
    import wx
    
    def on_checkbox_clicked(event: wx.CommandEvent) -> None:
        readonly_checkbox_checked = dialog.IsCheckBoxChecked()
        create_button = dialog.FindWindowById(wx.ID_NO)
        create_button.Enabled = not readonly_checkbox_checked
    
    dialog = BetterMessageDialog(None,
        message='Open an existing project or create a new project?',
        title='Select a Project',
        checkbox_label='Open as read only',
        on_checkbox_clicked=on_checkbox_clicked,
        style=wx.YES_NO,
        yes_label='Open',
        no_label='Create',
        escape_is_cancel=True)
    
    if dialog.IsCheckBoxChecked():
        project_kwargs = {
            **project_kwargs,
            **dict(readonly=True),
        }  # reinterpret
    
    try:
        while True:
            choice = dialog.ShowModal()
            
            if dialog.IsCheckBoxChecked():
                project_kwargs = {
                    **project_kwargs,
                    **dict(readonly=True),
                }  # reinterpret
            
            if choice == wx.ID_YES:
                try:
                    return _prompt_to_open_project(dialog, progress_listener, **project_kwargs)
                except SystemExit:
                    continue
            elif choice == wx.ID_NO:
                try:
                    return _prompt_to_create_project(dialog, progress_listener, **project_kwargs)
                except SystemExit:
                    continue
            else:  # wx.ID_CANCEL
                sys.exit()
    finally:
        dialog.Destroy()

def _prompt_to_create_project(parent, progress_listener, **project_kwargs):
    # type: (wx.Window, OpenProjectProgressListener, object) -> Project
    """
    Raises:
    * SystemExit -- if the user cancels the prompt early
    """
    from crystal.model import Project
    import os.path
    import shutil
    import wx
    
    dialog = wx.FileDialog(parent,
        message='',
        wildcard='*' + Project.FILE_EXTENSION,
        style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
    if not dialog.ShowModal() == wx.ID_OK:
        sys.exit()
    
    project_path = dialog.GetPath()
    if not project_path.endswith(Project.FILE_EXTENSION):
        project_path += Project.FILE_EXTENSION
    dialog.Destroy()
    
    if os.path.exists(project_path):
        shutil.rmtree(project_path)
    return Project(project_path, progress_listener, **project_kwargs)  # type: ignore[arg-type]

def _prompt_to_open_project(parent, progress_listener, **project_kwargs):
    # type: (wx.Window, OpenProjectProgressListener, object) -> Project
    """
    Raises:
    * SystemExit -- if the user cancels the prompt early
    """
    from crystal.model import Project
    from crystal.os import project_appears_as_package_file
    import os.path
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
    if not dialog.ShowModal() == wx.ID_OK:
        sys.exit()
    
    project_path = dialog.GetPath()
    dialog.Destroy()
    
    if not os.path.exists(project_path):
        raise AssertionError
    if not Project.is_valid(project_path):
        from crystal.ui.BetterMessageDialog import BetterMessageDialog
        
        dialog = BetterMessageDialog(None,
            message='The selected directory is not a valid project.',
            title='Invalid Project',
            style=wx.OK)
        dialog.ShowModal()
        dialog.Destroy()
        sys.exit()
    
    return Project(project_path, progress_listener, **project_kwargs)  # type: ignore[arg-type]

def _load_project(project_path, progress_listener, **project_kwargs):
    # type: (str, OpenProjectProgressListener, object) -> Project
    from crystal.model import Project
    import os.path
    
    if not os.path.exists(project_path):
        sys.exit('File not found: %s' % project_path)
    
    # TODO: If errors while loading a project (ex: bad format),
    #       present them to the user nicely
    return Project(project_path, progress_listener, **project_kwargs)  # type: ignore[arg-type]

# ----------------------------------------------------------------------------------------

if __name__ == '__main__':
    main(sys.argv[1:])
