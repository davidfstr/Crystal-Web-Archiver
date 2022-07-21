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


# If True, then the runtime of foreground tasks is tracked to ensure
# they are short. This is necessary to keep the UI responsive.
_PROFILE_FG_TASKS = True

# Maximum reasonable time that foreground tasks should take to complete.
# If profiling is enabled, warnings will be printed for tasks whose runtime
# exceeds this threshold.
_FG_TASK_RUNTIME_THRESHOLD = 1.0 # sec


def is_foreground_thread() -> bool:
    return _foreground_thread_exists() and wx.IsMainThread()


def _foreground_thread_exists() -> bool:
    return wx.GetApp() is not None


def _create_profiled_callable(callable, *args):
    """
    Decorates the specified callable such that it prints
    a warning to the console if its runtime is long.
    """
    def profiled_callable():
        import time
        start_time = time.time()
        try:
            callable(*args)
        finally:
            end_time = time.time()
            delta_time = end_time - start_time
            if delta_time > _FG_TASK_RUNTIME_THRESHOLD:
                root_callable = callable
                while hasattr(root_callable, 'callable'):
                    root_callable = root_callable.callable
                
                import inspect
                try:
                    file = inspect.getsourcefile(root_callable)
                except Exception:
                    file = '?'
                try:
                    start_line_number = inspect.getsourcelines(root_callable)[-1]
                except Exception:
                    start_line_number = '?'
                print("*** Foreground task took %.02fs to execute: %s @ [%s:%s]" % (
                    delta_time, root_callable,
                    file,
                    start_line_number))
    return profiled_callable


# TODO: Consider renaming this to 'fg_call_soon' and have the
#       (force == True) variant still be called 'fg_call_later'.
#       This new naming stresses that the "soon" variant could
#       potentially call the argument immediately whereas the
#       "later" variant will never do that.
def fg_call_later(callable, force=False, *args):
    """
    Schedules the argument to be called on the foreground thread.
    This should be called by background threads that need to access the UI or model.
    
    If the current thread is the foreground thread, the argument is executed immediately
    unless the 'force' parameter is True.
    """
    if _PROFILE_FG_TASKS:
        callable = _create_profiled_callable(callable, *args);
        args=()
    
    if not _foreground_thread_exists() or (wx.IsMainThread() and not force):
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
    if not _foreground_thread_exists() or wx.IsMainThread():
        return callable(*args)
    else:
        condition = threading.Condition()
        callable_done = [False]
        callable_result = [None]
        callable_exc_info = [None]
        
        def fg_task():
            # Run task
            try:
                callable_result[0] = callable(*args)
            except BaseException as e:
                callable_exc_info[0] = sys.exc_info()
            
            # Send signal
            with condition:
                callable_done[0] = True
                condition.notify()
        fg_task.callable = callable
        fg_call_later(fg_task)
        
        # Wait for signal
        with condition:
            while not callable_done[0]:
                condition.wait()
        
        # Reraise callable's exception, if applicable
        if callable_exc_info[0] is not None:
            exc_info = callable_exc_info[0]
            raise exc_info[1].with_traceback(exc_info[2])
        
        return callable_result[0]


def bg_call_later(callable, daemon=False, *args):
    """
    Calls the argument on a new background thread.
    
    Arguments:
    daemon -- if True, forces the background thread to be a daemon,
              and not prevent program termination while it is running.
    """
    thread = threading.Thread(target=callable, args=args)
    if daemon:
        thread.daemon = True
    thread.start()
