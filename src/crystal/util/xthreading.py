"""
Threading utilities.

Currently most activities are performed on the same "foreground thread".
This thread is responsible for:
(1) running the GUI and
(2) mediating access to model elements (including the underlying database).
"""

from crystal.util.profile import create_profiled_callable
from enum import Enum
from functools import wraps
import os
import sys
import threading
from typing import Callable, cast, Generator, Optional, TypeVar
from typing_extensions import ParamSpec
import wx


# If True, then the runtime of foreground tasks is tracked to ensure
# they are short. This is necessary to keep the UI responsive.
_PROFILE_FG_TASKS = os.environ.get('CRYSTAL_NO_PROFILE_FG_TASKS', 'False') != 'True'

# Maximum reasonable time that foreground tasks should take to complete.
# If profiling is enabled, warnings will be printed for tasks whose runtime
# exceeds this threshold.
_FG_TASK_RUNTIME_THRESHOLD = 1.0 # sec


_P = ParamSpec('_P')
_R = TypeVar('_R')


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
# Thread Affinity

def fg_affinity(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """
    Marks the decorated function as needing to be called from the
    foreground thread only.
    
    Calling the decorated function from an inappropriate thread will immediately
    raise an AssertionError.
    
    The following kinds of manipulations need to happen on the foreground thread:
    - wxPython calls, except for wx.CallAfter
    - SQLite calls
    """
    if __debug__:  # no -O passed on command line?
        @wraps(func)
        def wrapper(*args, **kwargs):
            assert is_foreground_thread()
            return func(*args, **kwargs)
        return wrapper
    else:
        return func


def bg_affinity(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """
    Marks the decorated function as needing to be called from a
    background thread only, and in particular not from the foreground thread.
    
    Calling the decorated function from an inappropriate thread will immediately
    raise an AssertionError.
    
    The following kinds of manipulations need to happen on background threads:
    - Blocking I/O (except for database I/O)
    - Long-running tasks that would block the UI if run on the foreground thread
    """
    if __debug__:  # no -O passed on command line?
        @wraps(func)
        def wrapper(*args, **kwargs):
            assert not is_foreground_thread()
            return func(*args, **kwargs)
        return wrapper
    else:
        return func


# ------------------------------------------------------------------------------
# Call on Foreground Thread

def fg_call_later(
        callable: Callable[_P, _R],
        # TODO: Give `args` the type `_P` once that can be spelled in Python's type system
        *, args=(),
        profile: bool=True,
        force_later: bool=False,
        ) -> None:
    """
    Schedules the specified callable to be called on the foreground thread,
    either immediately if the caller is already running on the foreground thread,
    or later if the caller is running on a different thread.
    
    Background threads should use this method when accessing the UI or model.
    
    Arguments:
    * callable -- the callable to run.
    * args -- the arguments to provide to the callable.
    * profile -- 
        whether to profile the callable's runtime.
        True by default so that warnings are printed for slow foreground tasks.
    * force_later --
        whether to force scheduling the callable later, even if the caller is
        already running on the foreground thread.
    
    Raises:
    * NoForegroundThreadError
    """
    if not has_foreground_thread():
        raise NoForegroundThreadError()
    
    is_fg_thread = is_foreground_thread()  # cache
    
    if _PROFILE_FG_TASKS and profile and not is_fg_thread:
        callable = create_profiled_callable(
            'Slow foreground task',
            _FG_TASK_RUNTIME_THRESHOLD,
            callable, *args
        )
        args=()
    
    if is_fg_thread and not force_later:
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


def fg_call_and_wait(
        callable: Callable[_P, _R],
        # TODO: Give `args` the type `_P` once that can be spelled in Python's type system
        *, args=(),
        profile: bool=True
        ) -> _R:
    """
    Calls the specified callable on the foreground thread and waits for it to complete,
    returning the result of the callable, including any raised exception.

    Background threads should use this method when accessing the UI or model.
    
    Arguments:
    * callable -- the callable to run.
    * args -- the arguments to provide to the callable.
    * profile -- 
        whether to profile the callable's runtime.
        True by default so that warnings are printed for slow foreground tasks.
    
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
        fg_call_later(fg_task, profile=profile)
        
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

def bg_call_later(
        callable: Callable[_P, None],
        # TODO: Give `args` the type `_P` once that can be spelled in Python's type system
        *, args=(),
        daemon: bool=False,
        ) -> None:
    """
    Calls the specified callable on a new background thread.
    
    Arguments:
    * callable -- the callable to run.
    * args -- the arguments to provide to the callable.
    * daemon -- 
        if True, forces the background thread to be a daemon,
        and not prevent program termination while it is running.
    """
    thread = threading.Thread(target=callable, args=args, daemon=daemon)
    thread.start()


# ------------------------------------------------------------------------------
# Thread Switching Coroutines

class SwitchToThread(Enum):
    BACKGROUND = 1
    FOREGROUND = 2


@bg_affinity
def run_thread_switching_coroutine(coro: Generator[SwitchToThread, None, _R]) -> _R:
    run_next = _CALL_NOW
    while True:
        try:
            command = run_next(lambda: next(coro))
        except StopIteration as e:
            return e.value
        if command == SwitchToThread.BACKGROUND:
            run_next = _CALL_NOW
        elif command == SwitchToThread.FOREGROUND:
            run_next = fg_call_and_wait
        else:
            raise AssertionError()


_CALL_NOW = lambda f: f()


# ------------------------------------------------------------------------------
# Quitting

_is_quitting = False


def is_quitting() -> bool:
    return _is_quitting


def set_is_quitting() -> None:
    global _is_quitting
    _is_quitting = True


# ------------------------------------------------------------------------------
