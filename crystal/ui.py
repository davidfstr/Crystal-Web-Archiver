"""
Contains utility functions for manipulating the UI.
"""

import wx

_EVT_CALLUI_ID = wx.NewId()

class _CallUIEvent(wx.PyEvent):
    def __init__(self, callable):
        wx.PyEvent.__init__(self)
        self.SetEventType(_EVT_CALLUI_ID)
        self.callable = callable

def ui_call_later(callable):
    """
    Calls the argument on the UI thread.
    This should be used for any operation that needs to access UI elements.
    """
    wx.PostEvent(APP, _CallUIEvent(callable))

# ------------------------------------------------------------------------------

# Single global app object
APP = wx.PySimpleApp()

def _OnCallUI(event):
    event.callable()
APP.Connect(-1, -1, _EVT_CALLUI_ID, _OnCallUI)