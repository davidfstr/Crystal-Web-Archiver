#!/usr/bin/env python
"""
Home of the main function, which starts the program.
"""

# NOTE: Do not add any imports that fail under Python 2.x.
#       This would prevent the version-checking code from running.
#       
#       Therefore most imports in this file should occur directly within functions.
import os
import sys
from sys import exit
try:
    from typing import TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False

if TYPE_CHECKING:
    from crystal.model import Project
    from crystal.progress import OpenProjectProgressListener
    from typing import Optional
    import wx


_APP_NAME = 'Crystal Web Archiver'
_APP_AUTHOR = 'DaFoster'


def main(args):
    """
    Main function. Starts the program.
    """
    _check_environment()
    
    # If running as Mac app or as Windows executable, redirect stdout and 
    # stderr to file, since these don't exist in these environments.
    # Use line buffering (buffering=1) so that prints are observable immediately.
    if hasattr(sys, 'frozen') and sys.frozen in ['macosx_app', 'windows_exe']:
        from appdirs import user_log_dir
        log_dirpath = user_log_dir(_APP_NAME, _APP_AUTHOR)
        os.makedirs(log_dirpath, exist_ok=True)
        
        sys.stdout = open(os.path.join(log_dirpath, 'stdout.log'), 'w', buffering=1)
        sys.stderr = open(os.path.join(log_dirpath, 'stderr.log'), 'w', buffering=1)
    
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
            exit('Can\'t find the main "crystal" package on your Python path.')
    
    # Start GUI subsystem
    import wx
    
    # Run GUI
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
            
            # Filter out strange "psn" argument (ex: '-psn_0_438379') that
            # macOS does sometimes pass upon first launch when run as a
            # binary downloaded from the internet.
            nonlocal args
            args = [a for a in args if not a.startswith('-psn_')]
            
            # Parse CLI arguments
            import argparse
            parser = argparse.ArgumentParser()
            parser.add_argument(
                '--server',
                help='Start a server on localhost to serve the project.',
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
            
            # If project to open passed on the command-line, use it
            if parsed_args.filepath is not None:
                filepath = args[0]
            
            from crystal.progress import OpenProjectProgressDialog
            with OpenProjectProgressDialog() as progress_listener:
                # Get a project
                if filepath is None:
                    project = _prompt_for_project(progress_listener)
                else:
                    project = _load_project(filepath, progress_listener)
                assert project is not None
                
                # Create main window
                from crystal.browser import MainWindow
                window = MainWindow(project, progress_listener)
            
            # Start serving immediately if requested
            if parsed_args.server:
                project.start_server()
            
            # Deactivate wx keepalive
            self._keepalive_frame.Destroy()
    app = MyApp(redirect=False)
    app.MainLoop()

def _check_environment():
    # Check Python version
    py3 = hasattr(sys, 'version_info') and sys.version_info >= (3,0)
    if not py3:
        exit('This application requires Python 3.x.')
    
    # Check for dependencies
    if not _running_as_bundle():
        try:
            import wx
        except ImportError:
            exit(
                'This application requires wxPython to be installed. ' + 
                'Download it from http://wxpython.org/')
        
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            exit(
                'This application requires BeautifulSoup to be installed. ' +
                'Download it from http://www.crummy.com/software/BeautifulSoup/')

def _running_as_bundle():
    """
    Returns whether we are running in a bundled environment,
    such as py2exe or py2app.
    """
    return hasattr(sys, 'frozen')

def _prompt_for_project(progress_listener):
    # type: (OpenProjectProgressListener) -> Project
    from crystal.ui.BetterMessageDialog import BetterMessageDialog
    import wx
    
    dialog = BetterMessageDialog(None,
        message='Open an existing project or create a new project?',
        title='Select a Project',
        style=wx.YES_NO,
        yes_label='Open',
        no_label='Create',
        escape_is_cancel=True)
    choice = dialog.ShowModal()
    
    try:
        if choice == wx.ID_YES:
            return _prompt_to_open_project(dialog, progress_listener)
        elif choice == wx.ID_NO:
            return _prompt_to_create_project(dialog, progress_listener)
        else:  # wx.ID_CANCEL
            exit()
    finally:
        dialog.Destroy()

def _prompt_to_create_project(parent, progress_listener):
    # type: (wx.Window, OpenProjectProgressListener) -> Project
    from crystal.model import Project
    import os.path
    import shutil
    import wx
    
    dialog = wx.FileDialog(parent,
        message='',
        wildcard='*' + Project.FILE_EXTENSION,
        style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
    if not dialog.ShowModal() == wx.ID_OK:
        exit()
    
    project_path = dialog.GetPath()
    if not project_path.endswith(Project.FILE_EXTENSION):
        project_path += Project.FILE_EXTENSION
    dialog.Destroy()
    
    if os.path.exists(project_path):
        shutil.rmtree(project_path)
    return Project(project_path, progress_listener)

def _prompt_to_open_project(parent, progress_listener):
    # type: (wx.Window, OpenProjectProgressListener) -> Project
    from crystal.model import Project
    from crystal.packages import project_appears_as_package_file
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
        exit()
    
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
        exit()
    
    return Project(project_path, progress_listener)

def _load_project(project_path, progress_listener):
    # type: (str, OpenProjectProgressListener) -> Project
    from crystal.model import Project
    import os.path
    
    if not os.path.exists(project_path):
        exit('File not found: %s' % project_path)
    
    # TODO: If errors while loading a project (ex: bad format),
    #       present them to the user nicely
    return Project(project_path, progress_listener)

# ----------------------------------------------------------------------------------------

if __name__ == '__main__':
    main(sys.argv[1:])
