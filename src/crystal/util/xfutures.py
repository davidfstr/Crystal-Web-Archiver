from concurrent.futures import Future
from concurrent.futures._base import (  # type: ignore[attr-defined]  # private API
    CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED, RUNNING
)
import sys
import threading
import weakref
from typing import Any, Generic, TypeVar
from typing_extensions import override


_F = TypeVar('_F', bound=Future)
_R = TypeVar('_R')


class InterruptableFuture(Generic[_R], Future[_R]):
    """
    An InterruptableFuture supports cancellation while it is running,
    unlike a regular Future.
    
    If an InterruptableFuture is cancelled while it is running,
    it will ignore subsequent calls to set_result() and set_exception().
    """
    _condition: threading.Condition
    _state: str
    
    def __init__(self) -> None:
        super().__init__()
        self._ignore_set_result_and_set_exception = False
    
    @override
    def cancel(self) -> bool:  # replace original implementation completely
        """
        Cancel the future if possible.

        Returns True if the future was cancelled, False otherwise. A future
        cannot be cancelled if it has already completed.
        """
        with self._condition:  # type: ignore[attr-defined]  # private API
            # NOTE: A normal Future would fail to cancel if it was in the RUNNING state
            if self._state in [RUNNING]:
                self._ignore_set_result_and_set_exception = True
            
            if self._state in [FINISHED]:
                return False
            
            if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                return True

            self._state = CANCELLED
            self._condition.notify_all()

        self._invoke_callbacks()  # type: ignore[attr-defined]  # private API
        return True
    
    @override
    def set_result(self, result: _R) -> None:
        """
        Sets the return value of work associated with the future.

        If this future was cancelled while RUNNING, no action is taken.
        """
        with self._condition:
            if self._ignore_set_result_and_set_exception:
                return
        super().set_result(result)
    
    @override
    def set_exception(self, exception: BaseException | None) -> None:
        """
        Sets the result of the future as being the given exception.

        If this future was cancelled while RUNNING, no action is taken.
        """
        with self._condition:
            if self._ignore_set_result_and_set_exception:
                return
        super().set_exception(exception)


def patch_future_result_to_check_for_deadlock() -> None:
    """
    Patches Future.result() to raise if called in an unsafe way on the
    foreground thread.
    """
    from crystal.util.xthreading import is_foreground_thread
    
    super_result = Future.result
    def result(self, timeout: float | None = None) -> Any:
        if (timeout is None and 
                not getattr(self, '_cr_declare_no_deadlocks', False) and
                is_foreground_thread()):
            raise RuntimeError(
                'Calling Future.result() from the foreground thread '
                'without a timeout is likely to cause a deadlock.\n'
                '\n'
                'Use timeout=0 if a result is expected immediately. '
                'Use "await wait_for_future(future)" if calling from an async test.'
            )
        return super_result(self, timeout)
    Future.result = result  # type: ignore[method-assign]


def warn_if_result_not_read(future: _F, future_description: str | None = None) -> _F:
    """
    Alters the specified Future to print a warning to stderr if its result
    is never read before the Future is finalized.
    """
    if future_description is None:
        future_description = repr(future)  # capture
    
    result_was_read = False
    
    original_result = future.result
    def wrapped_result(*args, **kwargs):
        nonlocal result_was_read
        result_was_read = True
        return original_result(*args, **kwargs)
    future.result = wrapped_result  # type: ignore[method-assign]
    
    original_exception = future.exception
    def wrapped_exception(*args, **kwargs):
        nonlocal result_was_read
        result_was_read = True
        return original_exception(*args, **kwargs)
    future.exception = wrapped_exception  # type: ignore[method-assign]
    
    original_add_done_callback = future.add_done_callback
    def wrapped_add_done_callback(*args, **kwargs):
        nonlocal result_was_read
        result_was_read = True
        return original_add_done_callback(*args, **kwargs)
    future.add_done_callback = wrapped_add_done_callback  # type: ignore[method-assign]
    
    # Register a finalizer to check if result was read
    # NOTE: Cannot access `future` itself in this finalizer
    def check_result_was_read() -> None:
        if not result_was_read:
            print(
                f"WARNING: Future's result was never read: {future_description}",
                file=sys.stderr)
    weakref.finalize(future, check_result_was_read)
    
    return future
