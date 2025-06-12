from collections.abc import Callable
from concurrent.futures import Future
from crystal.tests.util.wait import wait_for
from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.xthreading import bg_call_later
from typing import TypeVar

_R = TypeVar('_R')


_DEFAULT_WAIT_TIMEOUT_FOR_UNIT = 4.0

async def bg_call_and_wait(callable: Callable[[], _R], *, timeout: float | None=None) -> _R:
    """
    Start the specified callable on a background thread and
    waits for it to finish running.
    
    The foreground thread IS released while waiting, so the callable can safely
    make calls to fg_call_later() and fg_call_and_wait() without deadlocking.
    """
    if timeout is None:
        timeout = _DEFAULT_WAIT_TIMEOUT_FOR_UNIT
    
    result_cell = Future()  # type: Future[_R]
    @capture_crashes_to_stderr
    def bg_task() -> None:
        result_cell.set_running_or_notify_cancel()
        try:
            result_cell.set_result(callable())
        except BaseException as e:
            result_cell.set_exception(e)
    bg_call_later(bg_task)
    # NOTE: Releases foreground thread while waiting
    await wait_for(
        lambda: result_cell.done() or None, timeout,
        message=lambda: f'Timed out waiting for {callable}',
        stacklevel_extra=1)
    return result_cell.result()
