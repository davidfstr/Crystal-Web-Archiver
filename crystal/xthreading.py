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

def _wx_main_thread_exists():
    return wx.GetApp() is not None

def fg_call_later(callable, *args):
    """
    Schedules the argument to be called on the foreground thread.
    This should be called by background threads that need to access the UI or model.
    """
    if _ASSUME_CURRENT_THREAD_IS_FOREGROUND or not _wx_main_thread_exists() or wx.Thread_IsMain():
        callable(*args)
    else:
        wx.CallAfter(callable, *args)

def fg_call_and_wait(callable, *args):
    """
    Calls the argument on the foreground thread and waits for it to complete.
    This should be called by background threads that need to access the UI or model.
    
    Returns the result of the callable.
    If the callable raises an exception, it will be reraised by this method.
    """
    if _ASSUME_CURRENT_THREAD_IS_FOREGROUND or not _wx_main_thread_exists() or wx.Thread_IsMain():
        return callable(*args)
    else:
        condition = threading.Condition()
        callable_result = [None]
        callable_exc_info = [None]
        
        def fg_task():
            # Run task
            try:
                callable_result[0] = callable(*args)
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

def bg_call_later(callable, *args):
    """
    Calls the argument on a new background thread.
    """
    threading.Thread(target=callable, args=args).start()
