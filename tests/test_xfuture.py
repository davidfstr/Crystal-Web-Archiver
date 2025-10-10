from concurrent.futures import CancelledError, Future, InvalidStateError
from crystal.util.xfutures import InterruptableFuture


def test_can_cancel_interruptable_future_that_is_running() -> None:
    future = InterruptableFuture()  # type: Future[str]
    
    # Thread A: Start task
    running = future.set_running_or_notify_cancel()
    assert running
    
    # Thread B: Cancel
    cancelled = future.cancel()
    assert cancelled
    
    # Thread A: Finish task
    future.set_result('done')  # ignored
    
    assert future.cancelled()
    try:
        future.result()
    except CancelledError:
        pass  # expected
    else:
        raise AssertionError('Expected result() to raise CancelledError')
    try:
        future.exception()
    except CancelledError:
        pass  # expected
    else:
        raise AssertionError('Expected exception() to raise CancelledError')


def test_still_cannot_double_complete_an_interruptable_future() -> None:
    future = InterruptableFuture()  # type: Future[str]
    
    running = future.set_running_or_notify_cancel()
    assert running
    
    future.set_result('done1')
    
    try:
        future.set_result('done2')
    except InvalidStateError:
        pass  # expected
    else:
        raise AssertionError('Expected second set_result() to raise InvalidStateError')
