"""
Threading utilities.

Currently most activities are performed on the same "foreground thread".
This thread is responsible for:
(1) running the GUI and
(2) mediating access to model elements (including the underlying database).
"""

import threading
import wx

def fg_call_later(callable):
    """
    Calls the argument on the foreground thread.
    This should be called by background threads that need to access the UI or model.
    """
    if wx.Thread_IsMain():
        callable()
    else:
        wx.CallAfter(callable)

def bg_call_later(callable):
    """
    Calls the argument on a new background thread.
    """
    threading.Thread(target=callable).start()
