"""
Contains utility functions for manipulating the UI.
"""

# Initialize wx, if not already done
import wx

# Single global app object
APP = wx.PySimpleApp()

_EVT_CALLNOW_ID = wx.NewId()

class _CallNowEvent(wx.PyEvent):
    def __init__(self, callable):
        wx.PyEvent.__init__(self)
        self.SetEventType(_EVT_CALLNOW_ID)
        self.callable = callable

def ui_call_later(callable):
    """
    Calls the argument on the UI thread.
    This should be used for any operation that needs to access UI elements.
    """
    wx.PostEvent(APP, _CallNowEvent(callable))

# ------------------------------------------------------------------------------

def _OnCallNow(event):
    event.callable()
APP.Connect(-1, -1, _EVT_CALLNOW_ID, _OnCallNow)