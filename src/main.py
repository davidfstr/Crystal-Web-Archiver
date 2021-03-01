#!/usr/bin/env python
"""
Home of the main function, which starts the program.
"""

# NOTE: Do not add any imports that fail under Python 1.x.
#       This would prevent the version-checking code from running.
#       
#       Therefore most imports in this file should occur directly within functions.
import sys
from sys import exit

def main(args):
    """
    Main function. Starts the program.
    """
    _check_environment()
    
    # If running as Windows executable, redirect stdout and stderr
    # to file, since these don't exist for normal Windows programs
    import sys
    if hasattr(sys, 'frozen') and sys.frozen == 'windows_exe':
        try:
            sys.stdout = open('stdout.log', 'w')
            sys.stderr = open('stderr.log', 'w')
        except:
            # Fallback on py2exe's default behavior of writing
            # the stderr to its own logfile in the same directory,
            # albeit with a "See the logfile for details" message
            # upon application exit.
            # 
            # Failure here is most likely due to running from a locked volume.
            pass
    
    # Ensure the main package can be imported
    import os
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
    app = wx.PySimpleApp(redirect=False)
    
    # Get a project
    if len(args) == 0:
        project = _prompt_for_project()
    elif len(args) == 1:
        project = _load_project(args[0])
    if project is None:
        raise AssertionError
    
    # Create main window
    from crystal.browser import MainWindow
    window = MainWindow(project);
    
    # Run GUI
    wx.GetApp().MainLoop()

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

def _prompt_for_project():
    from crystal.ui.BetterMessageDialog import BetterMessageDialog
    import wx
    
    dialog = BetterMessageDialog(None,
        message='Open an existing project or create a new project?',
        title='Select a Project',
        style=wx.YES_NO,
        yes_label='Open',
        no_label='Create')
    choice = dialog.ShowModal()
    
    try:
        if choice == wx.ID_YES:
            return _prompt_to_open_project(dialog)
        elif choice == wx.ID_NO:
            return _prompt_to_create_project(dialog)
        else:
            exit()
    finally:
        dialog.Destroy()

def _prompt_to_create_project(parent):
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
    return Project(project_path)

def _prompt_to_open_project(parent):
    from crystal.model import Project
    from crystal.packages import can_set_package
    import os.path
    import wx
    
    if can_set_package():
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
    
    return Project(project_path)

def _load_project(project_path):
    from crystal.model import Project
    import os.path
    
    if not os.path.exists(project_path):
        exit('File not found: %s' % project_path)
    
    # TODO: If errors while loading a project (ex: bad format),
    #       present them to the user nicely
    return Project(project_path)

# ----------------------------------------------------------------------------------------

if __name__ == '__main__':
    main(sys.argv[1:])