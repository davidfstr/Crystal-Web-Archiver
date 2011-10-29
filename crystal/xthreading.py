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
    Schedules the argument to be called on the foreground thread.
    This should be called by background threads that need to access the UI or model.
    """
    if wx.Thread_IsMain():
        callable()
    else:
        wx.CallAfter(callable)

def fg_call_and_wait(callable):
    """
    Calls the argument on the foreground thread and waits for it to complete.
    This should be called by background threads that need to access the UI or model.
    """
    if wx.Thread_IsMain():
        callable()
    else:
        condition = threading.Condition()
        callable_exception = [None]
        
        def fg_task():
            # Run task
            try:
                callable()
            except BaseException as e:
                callable_exception[0] = e
            
            # Send signal
            condition.acquire()
            condition.notify()
            condition.release()
        fg_call_later(fg_task)
        
        # Wait for signal
        condition.acquire()
        condition.wait()
        condition.release()
        
        # Reraise callable's exception, if applicable
        if callable_exception[0] is not None:
            raise callable_exception[0]
        

def bg_call_later(callable):
    """
    Calls the argument on a new background thread.
    """
    threading.Thread(target=callable).start()
