"""
Contains utility functions for manipulating the UI.
"""

# Initialize wx, if not already done
import wx

# Single global app object
APP = wx.PySimpleApp()

def ui_call_later(callable):
    """
    Calls the argument on the UI thread.
    This should be used for any operation that needs to access UI elements.
    """
    wx.CallAfter(callable)
