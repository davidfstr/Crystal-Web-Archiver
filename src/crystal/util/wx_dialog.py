from crystal import resources
from crystal.util.xos import is_kde_or_non_gnome, is_mac_os, is_windows
import os
import wx


def ShowModal(dialog: wx.Dialog) -> int:
    """
    Replacement for wx.Dialog.ShowModel() that works properly even when
    running automated tests.
    """
    is_running_tests = os.environ.get('CRYSTAL_RUNNING_TESTS', 'False') == 'True'
    
    if is_running_tests and isinstance(dialog, wx.MessageDialog):
        # A wx.MessageDialog opened with ShowModal cannot be interacted
        # with via wx.FindWindowByName() and similar functions on macOS.
        # So don't allow such a dialog to be shown while tests are running.
        raise AssertionError(
            f'Attempted to call ShowModal on wx.MessageDialog {dialog.Name!r} '
            f'while running an automated test, which would hang the test. '
            f'Please patch ShowModal to return an appropriate result.')
    
    # HACK: ShowModal sometimes hangs on macOS while running automated tests,
    #       as admitted by the wxPython test suite in test_dialog.py.
    #       So simulate its effect in a way that does NOT hang while running tests.
    if is_running_tests and is_mac_os():
        dialog.SetReturnCode(0)
        dialog.Show()
        
        loop = wx.GetApp().GetTraits().CreateEventLoop()
        with wx.EventLoopActivator(loop):
            while dialog.GetReturnCode() == 0:
                loop.Dispatch()
                if not dialog.IsShown() and dialog.GetReturnCode() == 0:
                    dialog.SetReturnCode(wx.ID_CANCEL)
        
        return dialog.GetReturnCode()
    else:
        return dialog.ShowModal()


def position_dialog_initially(dialog: wx.Dialog) -> None:
    """
    Reposition the specified dialog by a default offset relative to
    its parent window.
    
    Different operating systems open dialogs at various positions
    relative to their parent window. This function standardizes
    the behavior across different operating systems. Native behavior:
    - macOS 10.14: (0, 0) offset
    - Windows 7: (200, 200) offset
    - Windows 10: (150, 200) offset
    - Ubuntu 22: (100, 100) offset
    """
    if dialog.Parent is None:
        return
    new_position = dialog.Parent.Position
    new_position.x += (150 // 2)
    new_position.y += (200 // 2)
    # NOTE: Linux sometimes ignores repositioning requests,
    #       especially if Wayland is being used rather than X11
    dialog.Position = new_position


def set_dialog_or_frame_icon_if_appropriate(tlw: wx.TopLevelWindow) -> None:
    # 1. Windows: Define app icon in the top-left corner
    # 2. KDE: Define app icon in the top-left corner and in the dock
    if is_windows() or is_kde_or_non_gnome():
        tlw.SetIcons(wx.IconBundle(resources.open_binary('appicon.ico')))
