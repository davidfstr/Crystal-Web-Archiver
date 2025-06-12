from crystal.util.xos import is_wx_gtk
import wx


def SetFocus(window: wx.Window, previously_focused: wx.Window | None) -> wx.Window:
    """
    Replacement for wx.Window.SetFocus() that works properly even on Linux.
    
    Returns the window that was focused.
    """
    if is_wx_gtk():
        # Simulate focus and blur events, 
        # since wxGTK's SetFocus() doesn't appear to have any effect
        
        # Keep focus state in UI up-to-date so that UI doesn't issue
        # its own focus/blur events unexpectedly later
        window.SetFocus()
        
        # Simulate blur event
        if previously_focused is not None:
            event = wx.FocusEvent(wx.EVT_KILL_FOCUS.typeId, previously_focused.GetId())
            event.SetEventObject(previously_focused)
            assert event.GetEventObject().GetId() == previously_focused.GetId()
            event.SetWindow(window)  # yes, the next window
            previously_focused.HandleWindowEvent(event)
        
        # Simulate focus event
        event = wx.FocusEvent(wx.EVT_SET_FOCUS.typeId, window.GetId())
        event.SetEventObject(window)
        assert event.GetEventObject().GetId() == window.GetId()
        event.SetWindow(previously_focused)  # yes, the previous window
        window.HandleWindowEvent(event)
    else:
        window.SetFocus()
    
    return window
