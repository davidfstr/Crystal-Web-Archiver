"""
Threading utilities.

Currently most activities are performed on the same "foreground thread".
This thread is responsible for:
(1) running the GUI and
(2) mediating access to model elements (including the underlying database).
"""

import sys
import threading
import wx

# Useful to set to True for interactive sessions in the interpreter
# when it isn't desirable to create a wx.App object.
_ASSUME_CURRENT_THREAD_IS_FOREGROUND = False

def fg_call_later(callable):
    """
    Schedules the argument to be called on the foreground thread.
    This should be called by background threads that need to access the UI or model.
    """
    if _ASSUME_CURRENT_THREAD_IS_FOREGROUND or wx.Thread_IsMain():
        callable()
    else:
        wx.CallAfter(callable)

def fg_call_and_wait(callable):
    """
    Calls the argument on the foreground thread and waits for it to complete.
    This should be called by background threads that need to access the UI or model.
    
    Returns the result of the callable.
    If the callable raises an exception, it will be reraised by this method.
    """
    if _ASSUME_CURRENT_THREAD_IS_FOREGROUND or wx.Thread_IsMain():
        callable()
    else:
        condition = threading.Condition()
        callable_result = [None]
        callable_exc_info = [None]
        
        def fg_task():
            # Run task
            try:
                callable_result[0] = callable()
            except BaseException as e:
                callable_exc_info[0] = sys.exc_info()
            
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
        if callable_exc_info[0] is not None:
            exc_info = callable_exc_info[0]
            raise exc_info[1], None, exc_info[2]
        
        return callable_result[0]
        

def bg_call_later(callable):
    """
    Calls the argument on a new background thread.
    """
    threading.Thread(target=callable).start()
