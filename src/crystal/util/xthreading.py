"""
Threading utilities.

Currently most activities are performed on the same "foreground thread".
This thread is responsible for:
(1) running the GUI and
(2) mediating access to model elements (including the underlying database).
"""

from collections import deque
from collections.abc import Callable, Generator, Iterator
from concurrent.futures import Future
from contextlib import contextmanager, nullcontext
from crystal.util.bulkheads import (
    capture_crashes_to_stderr, ensure_is_bulkhead_call,
)
from crystal.util.profile import create_profiled_callable
from crystal.util.quitting import is_quitting
from crystal.util.xfunctools import partial2
from crystal.util.xos import is_windows
from enum import Enum
from functools import wraps
import os
import signal
import sys
import threading
import time
import traceback
from typing import Any, assert_never, cast, Deque, Optional, Protocol, TypeVar
from typing_extensions import ParamSpec
import wx

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


# NOTE: _expect is used by automated tests when patching this function
def is_foreground_thread(*, _expect: bool | None=None) -> bool:
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
            if is_foreground_thread(_expect=False):
                raise AssertionError(
                    f'bg_affinity: Expected call on not foreground thread: {func}')
            return func(*args, **kwargs)  # cr-traceback: ignore
        return wrapper
    else:
        return func


# ------------------------------------------------------------------------------
# Thread Trampolines

def fg_trampoline(func: Callable[_P, None]) -> Callable[_P, None]:
    """
    Alters the decorated function to run on the foreground thread soon.
    """
    @wraps(func)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> None:
        if is_foreground_thread():
            func(*args, **kwargs)
        else:
            fg_call_later(partial2(func, *args, **kwargs))
    return wrapper


# ------------------------------------------------------------------------------
# Call on Foreground Thread

# Queue of deferred foreground callables to run
_deferred_fg_calls = deque()  # type: Deque[Callable[[], None]]
_deferred_fg_calls_paused = False

def fg_call_later(
        callable: Callable[_P, None],
        # TODO: Give `args` the type `_P` once that can be spelled in Python's type system.
        #       Currently only a `*args` parameter can be annotated with `_P.args`.
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
    
    is_fg_thread_now = is_foreground_thread()
    if is_fg_thread_now != is_fg_thread:
        print(
            f'*** Thread type changed unexpectedly: '
            f'was fg_thread={is_fg_thread}, now fg_thread={is_fg_thread_now}', file=sys.stderr)
        is_fg_thread = is_fg_thread_now  # reinterpret
    if is_fg_thread and not force_later:
        callable(*args)  # type: ignore[call-arg]
        return
    
    if len(args) != 0:
        (callable, args) = (partial2(callable, *args), ())  # reinterpret
    _deferred_fg_calls.append(callable)
    with is_quitting_or_has_deferred_fg_calls_condition:
        is_quitting_or_has_deferred_fg_calls_condition.notify_all()
    
    # In headless mode, don't use wx.CallAfter since there's no wx main loop.
    # The headless main loop will call _run_deferred_fg_calls() periodically.
    from crystal.util.headless import is_headless_mode
    if is_headless_mode():
        return
    
    try:
        # NOTE: wx.CallAfter can be used on any thread
        # NOTE: Schedules a wx.PyEvent with category wx.EVT_CATEGORY_UI
        wx.CallAfter(_run_deferred_fg_calls)
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


@contextmanager
def fg_calls_paused() -> Iterator[None]:
    """
    Context in which dispatching of deferred foreground calls is temporarily paused.
    """
    global _deferred_fg_calls_paused
    old_enabled = _deferred_fg_calls_paused
    _deferred_fg_calls_paused = True
    try:
        yield
    finally:
        _deferred_fg_calls_paused = old_enabled


@capture_crashes_to_stderr
def _run_deferred_fg_calls() -> bool:
    """
    Runs all deferred foreground callables that were scheduled by fg_call_later().
    Returns whether any callables were run.
    """
    if _deferred_fg_calls_paused:
        # NOTE: wx.CallLater can be used on the foreground thread only
        # NOTE: Schedules a wx.TimerEvent with category wx.EVT_CATEGORY_TIMER
        wx.CallLater(1, _run_deferred_fg_calls)
        return False
    
    # Don't run more than the number of calls that were initially scheduled
    # to avoid an infinite loop in case a type of callable always
    # schedules at least one callable of the same type.
    max_calls_to_run = len(_deferred_fg_calls)  # capture
    for _ in range(max_calls_to_run):
        try:
            cur_fg_call = _deferred_fg_calls.popleft()  # type: Callable[[], None]
        except IndexError:
            break
        else:
            try:
                # NOTE: If _DEFERRED_FG_CALLS_MUST_CAPTURE_CRASHES is True
                #       then it should be impossible for this to raise an exception
                #       because ensure_is_bulkhead_call() should have been called
                #       on the callable before it was added to the queue.
                cur_fg_call()
            except Exception:
                traceback.print_exc()
                # (keep running other calls)
    return max_calls_to_run > 0


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
        return callable(*args)  # type: ignore[call-arg]  # cr-traceback: ignore
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
                callable_result = callable(*args)  # type: ignore[call-arg]  # cr-traceback: ignore
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
    
    # On Windows, initialize COM on every thread so that finalizers
    # interacting with wxPython COM objects do not print the warning
    # "Windows fatal exception: code 0x800401f0"
    if is_windows():
        callable = _com_initialized()(partial2(callable, *args))  # reinterpret
        args = ()  # reinterpret
    
    thread = threading.Thread(target=callable, args=args, daemon=daemon)
    thread.start()
    return thread


@contextmanager
def _com_initialized() -> Iterator[None]:
    assert is_windows(), 'COM initialization is only needed on Windows'
    import ctypes
    ole32 = ctypes.CDLL('ole32.dll')
    ole32.CoInitialize(None)
    try:
        yield
    finally:
        ole32.CoUninitialize()


# ------------------------------------------------------------------------------
# Wait on Foreground Thread

@fg_affinity
def fg_wait_for(condition_func: Callable[[], bool], *, timeout: float | None, poll_interval: float) -> None:
    """
    Waits for the specified condition to become true, in the foreground thread.
    The foreground thread is held while waiting.
    
    Events are processed in the wx event loop while waiting,
    to avoid deadlocks in the wx event loop.
    
    Raises:
    * TimeoutError -- if the condition does not become true within the specified timeout
    """
    start_time = time.monotonic()  # capture
    app = wx.GetApp()
    loop = app.GetTraits().CreateEventLoop() if app is not None else None
    with (wx.EventLoopActivator(loop) if app is not None else nullcontext()):
        while True:
            if condition_func():
                break
            if timeout is not None and (time.monotonic() - start_time) > timeout:
                raise TimeoutError(
                    f'fg_wait_for: Timed out waiting for condition: {condition_func}')
            # Process any enqueued foreground callables
            _run_deferred_fg_calls()
            # Process one wx event
            # NOTE: It is unsafe to keep calling Dispatch() in a loop
            #       while there are pending events because some OS 
            #       event loops always appear to have pending events.
            #       Therefore we only process one event per iteration.
            if loop is not None and loop.Pending():
                loop.Dispatch()
            if poll_interval > 0:
                time.sleep(poll_interval)


# ------------------------------------------------------------------------------
# Thread Switching Coroutines

class SwitchToThread(Enum):
    BACKGROUND = 1
    FOREGROUND = 2


def start_thread_switching_coroutine(
        first_command: SwitchToThread,
        coro: Generator[SwitchToThread, None, _R],
        /, capture_crashes_to_deco: Callable[[Callable[[], None]], Callable[[], None]] | None = None,
        *, uses_future_result: bool = False,
        ) -> Future[_R]:
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
    
    Arguments:
    * first_command -- thread which the coroutine starts running on
    * coro -- thread-switching coroutine to run
    * capture_crashes_to_deco -- 
        capture_crashes_to* decorator for handling exceptions raised by the coroutine.
        May be None iff uses_future_result is True.
    * uses_future_result --
        whether the caller promises to always check the returned Future for
        a result or an exception
    
    Returns a Future that will be given the result of running the coroutine
    or the exception that the coroutine raised.
    """
    bubble_exceptions_to_deco: bool
    if capture_crashes_to_deco is None:
        if not uses_future_result:
            raise ValueError('If uses_future_result=False then a capture_crashes_to_deco is required')
        
        bubble_exceptions_to_deco = False
        capture_crashes_to_deco = capture_crashes_to_stderr  # reinterpret
    else:
        bubble_exceptions_to_deco = True
    
    future = Future()  # type: Future[_R]
    running = future.set_running_or_notify_cancel()
    assert running
    
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
                    future.set_result(e.value)
                    return
                except BaseException as e:
                    future.set_exception(e)
                    if bubble_exceptions_to_deco:
                        raise
                    return
            assert command == SwitchToThread.BACKGROUND
            
            first_command = command  # reinterpret
        fg_task()
        if future.done():
            return future
    
    # Run remainder of coroutine on a new background thread
    @capture_crashes_to_deco
    def bg_task() -> None:
        try:
            result = run_thread_switching_coroutine(first_command, coro)
        except BaseException as e:
            future.set_exception(e)
            if bubble_exceptions_to_deco:
                raise
        else:
            future.set_result(result)
    bg_call_later(bg_task)
    
    return future


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
# Foreground Coroutines

class FgCommand(Enum):
    GET_CONTINUE_SOON_FUNC = 1
    SUSPEND_UNTIL_CONTINUE = 2


class ContinueSoonFunc(Protocol):
    def __call__(self, return_value: Any = None) -> None: ...


@fg_affinity
def start_fg_coroutine(
        coro: Generator[FgCommand, ContinueSoonFunc | Any, None],
        capture_crashes_to_deco: Callable[[Callable[..., None]], Callable[..., None]],
        ) -> None:
    """
    Starts and drives a foreground coroutine that yields FgCommand instructions.
    The coroutine is resumed when the provided ContinueSoonFunc is called.
    
    Arguments:
    * coro -- the coroutine to run, which yields FgCommand instructions.
    * capture_crashes_to_deco -- 
        a decorator that captures exceptions raised by the coroutine
        and does something with them, such as printing a traceback.
        Is usually one of the @capture_crashes_to* decorators.
    """
    @capture_crashes_to_deco
    @fg_affinity
    def step(send_value: Any) -> None:
        try:
            command = coro.send(send_value)
        except StopIteration:
            return

        if command == FgCommand.GET_CONTINUE_SOON_FUNC:
            # Provide a function that, when called, schedules the next step
            def continue_soon(return_value: Any=None) -> None:
                """Calls the next step of the coroutine."""
                fg_call_later(partial2(step, return_value))
            step(continue_soon)
        elif command == FgCommand.SUSPEND_UNTIL_CONTINUE:
            # Suspend until continue_soon is called
            pass
        else:
            assert_never(command)
    step(None)


# ------------------------------------------------------------------------------
# Headless Main Loop

is_quitting_or_has_deferred_fg_calls_condition = threading.Condition()

@capture_crashes_to_stderr
def run_headless_main_loop() -> None:
    """
    Runs a headless main loop that processes foreground calls without
    using wx's MainLoop().
    """
    # Simulate wx MainLoop()'s handling of Ctrl-C:
    # Exit the process with exit code 130.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    
    with is_quitting_or_has_deferred_fg_calls_condition:
        while True:
            is_quitting_or_has_deferred_fg_calls_condition.wait_for(
                lambda: is_quitting() or len(_deferred_fg_calls) > 0,
                timeout=None,  # infinite
            )
            
            _run_deferred_fg_calls()  # if there are any
            if is_quitting():
                break


# ------------------------------------------------------------------------------
