"""
Threading utilities.

Currently most activities are performed on the same "foreground thread".
This thread is responsible for:
(1) running the GUI and
(2) mediating access to model elements (including the underlying database).
"""

from collections import deque
from collections.abc import Callable, Generator
from crystal.util.bulkheads import (
    capture_crashes_to_stderr, ensure_is_bulkhead_call,
)
from crystal.util.profile import create_profiled_callable
from enum import Enum
from functools import partial, wraps
import os
import sys
import threading
import traceback
from typing import cast, Deque, Optional, TypeVar
from typing_extensions import ParamSpec
import wx

# Whether to explicitly manage the queue of deferred foreground tasks,
# instead of letting wxPython manage the queue internally.
# 
# Can be useful for debugging, because when True the queue of deferred foreground tasks
# is directly inspectable by examining the "_fg_calls" variable in this module.
_DEBUG_FG_CALL_QUEUE = False

# If True, then the runtime of foreground tasks is tracked to ensure
# they are short. This is necessary to keep the UI responsive.
_PROFILE_FG_TASKS = os.environ.get('CRYSTAL_NO_PROFILE_FG_TASKS', 'False') != 'True'

# Maximum reasonable time that foreground tasks should take to complete.
# If profiling is enabled, warnings will be printed for tasks whose runtime
# exceeds this threshold.
_FG_TASK_RUNTIME_THRESHOLD = 1.0 # sec

# Whether to enforce that callables scheduled with fg_call_later()
# be decorated with @capture_crashes_to*.
_DEFERRED_FG_CALLS_MUST_CAPTURE_CRASHES = True
# Whether to enforce that callables scheduled with bg_call_later()
# be decorated with @capture_crashes_to*.
_DEFERRED_BG_CALLS_MUST_CAPTURE_CRASHES = True


_P = ParamSpec('_P')
_R = TypeVar('_R')


# ------------------------------------------------------------------------------
# Access Foreground Thread

_fg_thread = None  # type: Optional[threading.Thread]


def set_foreground_thread(fg_thread: threading.Thread | None) -> None:
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
            if not is_foreground_thread() and has_foreground_thread():
                raise AssertionError(
                    f'fg_affinity: Expected call on foreground thread: {func}')
            return func(*args, **kwargs)  # cr-traceback: ignore
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
            return func(*args, **kwargs)  # cr-traceback: ignore
        return wrapper
    else:
        return func


# ------------------------------------------------------------------------------
# Call on Foreground Thread

def fg_call_later(
        callable: Callable[_P, None],
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
    
    if _DEFERRED_FG_CALLS_MUST_CAPTURE_CRASHES:
        ensure_is_bulkhead_call(callable)
    
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
            if _DEBUG_FG_CALL_QUEUE:
                if len(args) == 0:
                    _fg_call_later_in_order(callable)
                else:
                    _fg_call_later_in_order(partial(callable, *args))
            else:
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


_fg_calls = deque()  # type: Deque[Callable[[], None]]

def _fg_call_later_in_order(callable: Callable[[], None]) -> None:
    _fg_calls.append(callable)
    wx.CallAfter(_do_fg_calls)

def _do_fg_calls() -> None:
    while True:
        try:
            cur_fg_call = _fg_calls.popleft()  # type: Callable[[], None]
        except IndexError:
            break
        try:
            cur_fg_call()
        except Exception:
            # Print traceback of any unhandled exception
            traceback.print_exc()


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
        return callable(*args)  # cr-traceback: ignore
    else:
        event = threading.Event()
        callable_started = False
        callable_result = None
        callable_exc_info = None
        
        waiting_calling_thread = threading.current_thread()  # capture
        
        @capture_crashes_to_stderr
        def fg_task() -> None:
            nonlocal callable_started, callable_result, callable_exc_info
            
            callable_started = True
            
            # Run task
            fg_thread = threading.current_thread()
            setattr(fg_thread, '_cr_waiting_calling_thread', waiting_calling_thread)
            try:
                callable_result = callable(*args)  # cr-traceback: ignore
            except BaseException as e:
                callable_exc_info = sys.exc_info()
            finally:
                setattr(fg_thread, '_cr_waiting_calling_thread', None)
            
            # Send signal
            event.set()
        fg_task.callable = callable  # type: ignore[attr-defined]
        fg_call_later(fg_task, profile=profile)
        
        # Wait for signal
        while True:
            if not callable_started:
                if event.wait(timeout=1.0):
                    break
                if not has_foreground_thread():
                    # Presumably the foreground thread did shutdown
                    # while fg_call_later was scheduling a callable
                    # that now will never actually run
                    raise NoForegroundThreadError()
            else:
                if event.wait():
                    break
        
        # Reraise callable's exception, if applicable
        if callable_exc_info is not None:
            exc_info = callable_exc_info
            assert exc_info[1] is not None
            raise exc_info[1].with_traceback(exc_info[2])  # cr-traceback: ignore
        
        return cast(_R, callable_result)


class NoForegroundThreadError(ValueError):
    pass


@fg_affinity
def fg_waiting_calling_thread() -> threading.Thread | None:
    """
    If the current task running on the foreground thread was scheduled
    by a call to fg_call_and_wait(), returns the thread that made that call.
    Otherwise returns None.
    """
    fg_thread = threading.current_thread()
    return getattr(fg_thread, '_cr_waiting_calling_thread', None)


# ------------------------------------------------------------------------------
# Call on Background Thread

def bg_call_later(
        callable: Callable[_P, None],
        # TODO: Give `args` the type `_P` once that can be spelled in Python's type system
        *, args=(),
        daemon: bool=False,
        ) -> threading.Thread:
    """
    Calls the specified callable on a new background thread.
    
    Arguments:
    * callable -- the callable to run.
    * args -- the arguments to provide to the callable.
    * daemon -- 
        if True, forces the background thread to be a daemon,
        and not prevent program termination while it is running.
    """
    if _DEFERRED_BG_CALLS_MUST_CAPTURE_CRASHES:
        ensure_is_bulkhead_call(callable)
    thread = threading.Thread(target=callable, args=args, daemon=daemon)
    thread.start()
    return thread


# ------------------------------------------------------------------------------
# Thread Switching Coroutines

class SwitchToThread(Enum):
    BACKGROUND = 1
    FOREGROUND = 2


def start_thread_switching_coroutine(
        first_command: SwitchToThread,
        coro: Generator[SwitchToThread, None, _R],
        capture_crashes_to_deco: Callable[[Callable[[], None]], Callable[[], None]],
        /,
        ) -> None:
    """
    Starts the specified thread-switching-coroutine on a new background thread.
    
    A thread-switching-coroutine starts executing on the thread given by `first_command`.
    Whenever the coroutine wants to switch to a different thread it yields
    a new `SwitchToThread` command. A coroutine may ask to switch to the
    same thread it was running on before without any effect.
    
    If the caller is running on the foreground thread and the prefix of the
    thread-switching-coroutine is configured to execute on the foreground thread
    (when first_command == SwitchToThread.FOREGROUND and subsequent yields
    also say SwitchToThread.FOREGROUND), then that prefix is run to completion
    synchronously before this method returns.
    """
    # If is foreground thread, immediately run any prefix of the coroutine
    # that wants to be on the foreground thread
    if is_foreground_thread():
        @capture_crashes_to_deco
        def fg_task() -> None:
            nonlocal first_command
            
            command = first_command
            while command == SwitchToThread.FOREGROUND:
                try:
                    command = next(coro)
                except StopIteration as e:
                    return
            assert command == SwitchToThread.BACKGROUND
            
            first_command = command  # reinterpret
        fg_task()
    
    # Run remainder of coroutine on a new background thread
    @capture_crashes_to_deco
    def bg_task() -> None:
        run_thread_switching_coroutine(first_command, coro)
    bg_call_later(bg_task)


@bg_affinity
def run_thread_switching_coroutine(
        first_command: SwitchToThread,
        coro: Generator[SwitchToThread, None, _R],
        /,
        ) -> _R:
    """
    Runs the specified thread-switching-coroutine on the caller's
    background thread until it completes.
    
    A thread-switching-coroutine starts executing on the thread given by `first_command`.
    Whenever the coroutine wants to switch to a different thread it yields
    a new `SwitchToThread` command. A coroutine may ask to switch to the
    same thread it was running on before without any effect.
    
    Raises if the caller is not running on a background thread.
    """
    command = first_command
    while True:
        if command == SwitchToThread.BACKGROUND:
            run_next = _CALL_NOW
        elif command == SwitchToThread.FOREGROUND:
            run_next = fg_call_and_wait
        else:
            raise AssertionError()
        try:
            command = run_next(lambda: next(coro))  # cr-traceback: ignore
        except StopIteration as e:
            return e.value


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
