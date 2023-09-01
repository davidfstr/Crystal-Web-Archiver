from crystal.util.xos import is_mac_os
import os
import wx


def ShowModal(dialog: wx.Dialog) -> int:
    # HACK: ShowModal sometimes hangs on macOS while running automated tests,
    #       as admitted by the wxPython test suite in test_dialog.py.
    #       So simulate its effect in a way that does NOT hang while running tests.
    if is_mac_os() and os.environ.get('CRYSTAL_RUNNING_TESTS', 'False') == 'True':
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
