from contextlib import redirect_stderr
from crystal.tests.util.asserts import assertEqual, assertIn, assertNotIn
import gc
from io import StringIO
from concurrent.futures import CancelledError, Future, InvalidStateError
from crystal.util.xfutures import InterruptableFuture, warn_if_result_not_read


# === Test: InterruptableFuture ===

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


# === Test: warn_if_result_not_read ===

def test_warn_if_result_not_read_prints_warning_when_result_not_read() -> None:
    with redirect_stderr(StringIO()) as captured_stderr:
        future = Future()  # type: Future[int]
        future = warn_if_result_not_read(future)
        future.set_result(42)
        
        # Delete the future and force garbage collection
        del future; gc.collect()
        
        # Check that warning was printed
        assertIn("WARNING: Future's result was never read:", captured_stderr.getvalue())


def test_warn_if_result_not_read_no_warning_when_result_read() -> None:
    with redirect_stderr(StringIO()) as captured_stderr:
        future = Future()  # type: Future[int]
        future = warn_if_result_not_read(future)
        future.set_result(42)
        
        # Read the result
        assertEqual(42, future.result(timeout=0))
        
        # Delete the future and force garbage collection
        del future; gc.collect()
        
        # Check that no warning was printed
        assertNotIn("WARNING: Future's result was never read:", captured_stderr.getvalue())


def test_warn_if_result_not_read_no_warning_when_exception_checked() -> None:
    with redirect_stderr(StringIO()) as captured_stderr:
        future = Future()  # type: Future[int]
        future = warn_if_result_not_read(future)
        future.set_result(42)
        
        # Check exception
        assertEqual(None, future.exception(timeout=0))
        
        # Delete the future and force garbage collection
        del future; gc.collect()
        
        # Check that no warning was printed
        assertNotIn("WARNING: Future's result was never read:", captured_stderr.getvalue())


def test_warn_if_result_not_read_no_warning_when_callback_added() -> None:
    with redirect_stderr(StringIO()) as captured_stderr:
        future = Future()  # type: Future[int]
        future = warn_if_result_not_read(future)
        future.set_result(42)
        
        # Add a callback
        callback_called = False
        def callback(f: Future[int]) -> None:
            nonlocal callback_called
            callback_called = True
        future.add_done_callback(callback)
        assert callback_called is True
        
        # Delete the future and force garbage collection
        del future; gc.collect()
        
        # Check that no warning was printed
        assertNotIn("WARNING: Future's result was never read:", captured_stderr.getvalue())

