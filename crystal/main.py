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
    py2_7_or_better = hasattr(sys, 'version_info') and sys.version_info >= (2,7)
    py3 = hasattr(sys, 'version_info') and sys.version_info >= (3,0)
    if not py2_7_or_better:
        exit('This application requires Python 2.7 or later.')
    if py3:
        exit('This application cannot run under Python 3.x. Try Python 2.7 instead.')
    
    # Check for wx
    if not _running_as_bundle():
        try:
            import wxversion
        except ImportError:
            exit(
                'This application requires wxPython to be installed. ' + 
                'Download it from http://wxpython.org/')
        else:
            # Check version and display dialog to user if an upgrade is needed.
            # If a dialog is displayed, the application will exit automatically.
            wxversion.ensureMinimal('2.8')
        
        try:
            import wx
        except ImportError:
            is_64bits = sys.maxsize > 2**32
            if is_64bits:
                python_bitness = '64-bit'
            else:
                python_bitness = '32-bit'
            
            exit(
                'wxPython found but couldn\'t be loaded. ' +
                'Your Python is %s. Are you sure wxPython is %s?' %
                    (python_bitness, python_bitness))

def _running_as_bundle():
    """
    Returns whether we are running in a bundled environment,
    such as py2exe or py2app.
    """
    # TODO: Update this logic once bundling tools have been selected.
    #       I think py2exe's logic is: hasattr(sys, 'frozen')
    return False

def _prompt_for_project():
    from crystal.ui.BetterMessageDialog import BetterMessageDialog
    import wx
    
    dialog = BetterMessageDialog(None,
        message='Open an existing project or create a new project?',
        title='Actions | Crystal',
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
    import os.path
    import wx
    
    dialog = wx.DirDialog(parent,
        message='',
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