from concurrent.futures import Future
from concurrent.futures._base import (  # type: ignore[attr-defined]  # private API
    CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED, RUNNING
)
import threading
from typing import Any, Generic, TypeVar
from typing_extensions import override


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
        # TODO: Consider being more strict by eliminating the following special case
        # HACK: Permit timeout=None when self.done() to accomodate existing
        #       code that unsafely calls Future.result(timeout=None)
        #       in a context it believes the Future will always be done.
        if (timeout is None and 
                not self.done() and 
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
