"""
Contains utility functions for manipulating the UI.
"""

import wx

def ui_call_later(callable):
    """
    Calls the argument on the UI thread.
    This should be used for any operation that needs to access UI elements.
    """
    if wx.Thread_IsMain():
        callable()
    else:
        wx.CallAfter(callable)
