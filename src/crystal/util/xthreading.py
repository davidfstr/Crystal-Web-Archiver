"""
Threading utilities.

Currently most activities are performed on the same "foreground thread".
This thread is responsible for:
(1) running the GUI and
(2) mediating access to model elements (including the underlying database).
"""

from crystal.util.profile import create_profiled_callable
import os
import sys
import threading
from typing import Callable, cast, Optional, TypeVar
import wx


# If True, then the runtime of foreground tasks is tracked to ensure
# they are short. This is necessary to keep the UI responsive.
_PROFILE_FG_TASKS = os.environ.get('CRYSTAL_NO_PROFILE_FG_TASKS', 'False') != 'True'

# Maximum reasonable time that foreground tasks should take to complete.
# If profiling is enabled, warnings will be printed for tasks whose runtime
# exceeds this threshold.
_FG_TASK_RUNTIME_THRESHOLD = 1.0 # sec


# ------------------------------------------------------------------------------
# Access Foreground Thread

_fg_thread = None  # type: Optional[threading.Thread]


def set_foreground_thread(fg_thread: Optional[threading.Thread]) -> None:
    global _fg_thread
    _fg_thread = fg_thread


def is_foreground_thread() -> bool:
    """
    Returns whether the current thread is the foreground thread
    (with the active wx.App object).
    """
    # NOTE: It has been observed that wx.IsMainThread() is unreliable,
    #       returning True for all threads, when there is no running main loop.
    #       Therefore Crystal keeps track of the main thread itself.
    return threading.current_thread() == _fg_thread


def has_foreground_thread() -> bool:
    """
    Returns whether any foreground thread exists.
    
    If it doesn't exist, it may not have been created yet or it may have exited.
    """
    return _fg_thread is not None


# ------------------------------------------------------------------------------
# Call on Foreground Thread


# TODO: Alter signature to pass `args` as a direct kwarg,
#       since it is difficult to use as a splat when there are other positional args
# TODO: Consider renaming this to 'fg_call_soon' and have the
#       (force == True) variant still be called 'fg_call_later'.
#       This new naming stresses that the "soon" variant could
#       potentially call the argument immediately whereas the
#       "later" variant will never do that.
def fg_call_later(callable, force: bool=False, no_profile: bool=False, *args) -> None:
    """
    Schedules the argument to be called on the foreground thread.
    This should be called by background threads that need to access the UI or model.
    
    If the current thread is the foreground thread, the argument is executed immediately
    unless the 'force' parameter is True.
    
    Raises:
    * NoForegroundThreadError
    """
    if not has_foreground_thread():
        raise NoForegroundThreadError()
    
    is_fg_thread = is_foreground_thread()  # cache
    
    if _PROFILE_FG_TASKS and not no_profile and not is_fg_thread:
        callable = create_profiled_callable(
            'Slow foreground task',
            _FG_TASK_RUNTIME_THRESHOLD,
            callable, *args
        )
        args=()
    
    if is_fg_thread and not force:
        callable(*args)
    else:
        try:
            wx.CallAfter(callable, *args)
        except Exception as e:
            if not has_foreground_thread():
                raise NoForegroundThreadError()
            
            # ex: RuntimeError: wrapped C/C++ object of type PyApp has been deleted
            if str(e) == 'wrapped C/C++ object of type PyApp has been deleted':
                raise NoForegroundThreadError()
            # ex: AssertionError: No wx.App created yet
            elif str(e) == 'No wx.App created yet':
                raise NoForegroundThreadError()
            else:
                raise


_R = TypeVar('_R')

# TODO: Alter signature to pass `args` as a direct kwarg,
#       since it is difficult to use as a splat when there are other positional args
def fg_call_and_wait(callable: Callable[..., _R], no_profile: bool=False, *args) -> _R:
    """
    Calls the argument on the foreground thread and waits for it to complete.
    This should be called by background threads that need to access the UI or model.
    
    Returns the result of the callable.
    If the callable raises an exception, it will be reraised by this method.
    
    Raises:
    * NoForegroundThreadError
    """
    if not has_foreground_thread():
        raise NoForegroundThreadError()
    
    if is_foreground_thread():
        return callable(*args)
    else:
        condition = threading.Condition()
        callable_done = False
        callable_result = None
        callable_exc_info = None
        
        def fg_task() -> None:
            nonlocal callable_done, callable_result, callable_exc_info
            
            # Run task
            try:
                callable_result = callable(*args)
            except BaseException as e:
                callable_exc_info = sys.exc_info()
            
            # Send signal
            with condition:
                callable_done = True
                condition.notify()
        fg_task.callable = callable  # type: ignore[attr-defined]
        fg_call_later(fg_task, no_profile=no_profile)
        
        # Wait for signal
        with condition:
            while not callable_done:
                condition.wait()
        
        # Reraise callable's exception, if applicable
        if callable_exc_info is not None:
            exc_info = callable_exc_info
            assert exc_info[1] is not None
            raise exc_info[1].with_traceback(exc_info[2])
        
        return cast(_R, callable_result)


class NoForegroundThreadError(ValueError):
    pass


# ------------------------------------------------------------------------------
# Call on Background Thread

# TODO: Alter signature to pass `args` as a direct kwarg,
#       since it is difficult to use as a splat when there are other positional args
def bg_call_later(callable: Callable[..., None], daemon: bool=False, *args) -> None:
    """
    Calls the argument on a new background thread.
    
    Arguments:
    * daemon -- 
        if True, forces the background thread to be a daemon,
        and not prevent program termination while it is running.
    """
    thread = threading.Thread(target=callable, args=args)
    if daemon:
        thread.daemon = True
    thread.start()


# ------------------------------------------------------------------------------
# Quitting

_is_quitting = False


def is_quitting() -> bool:
    return _is_quitting


def set_is_quitting() -> None:
    global _is_quitting
    _is_quitting = True


# ------------------------------------------------------------------------------
