"""
Subset of the concurrent.futures module, backpointed from Python 3.2 SVN (2011-11-17) to
Python 2.7.
"""

try:
    from concurrent.futures import futures
except ImportError:
    import logging
    import threading
    
    # Possible future states (for internal use by the futures package).
    PENDING = 'PENDING'
    RUNNING = 'RUNNING'
    # The future was cancelled by the user...
    CANCELLED = 'CANCELLED'
    # ...and _Waiter.add_cancelled() was called by a worker.
    CANCELLED_AND_NOTIFIED = 'CANCELLED_AND_NOTIFIED'
    FINISHED = 'FINISHED'
    
    # Logger for internal use by the futures package.
    LOGGER = logging.getLogger("concurrent.futures")
    
    class Future(object):
        """Represents the result of an asynchronous computation."""
    
        def __init__(self):
            """Initializes the future. Should not be called by clients."""
            self._condition = threading.Condition()
            self._state = PENDING
            self._result = None
            self._exception = None
            self._waiters = []
            self._done_callbacks = []
    
        def _invoke_callbacks(self):
            for callback in self._done_callbacks:
                try:
                    callback(self)
                except Exception:
                    LOGGER.exception('exception calling callback for %r', self)
    
        def __repr__(self):
            with self._condition:
                if self._state == FINISHED:
                    if self._exception:
                        return '<Future at %s state=%s raised %s>' % (
                            hex(id(self)),
                            _STATE_TO_DESCRIPTION_MAP[self._state],
                            self._exception.__class__.__name__)
                    else:
                        return '<Future at %s state=%s returned %s>' % (
                            hex(id(self)),
                            _STATE_TO_DESCRIPTION_MAP[self._state],
                            self._result.__class__.__name__)
                return '<Future at %s state=%s>' % (
                        hex(id(self)),
                       _STATE_TO_DESCRIPTION_MAP[self._state])
    
        def cancel(self):
            """Cancel the future if possible.
    
            Returns True if the future was cancelled, False otherwise. A future
            cannot be cancelled if it is running or has already completed.
            """
            with self._condition:
                if self._state in [RUNNING, FINISHED]:
                    return False
    
                if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                    return True
    
                self._state = CANCELLED
                self._condition.notify_all()
    
            self._invoke_callbacks()
            return True
    
        def cancelled(self):
            """Return True if the future has cancelled."""
            with self._condition:
                return self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]
    
        def running(self):
            """Return True if the future is currently executing."""
            with self._condition:
                return self._state == RUNNING
    
        def done(self):
            """Return True of the future was cancelled or finished executing."""
            with self._condition:
                return self._state in [CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED]
    
        def __get_result(self):
            if self._exception:
                raise self._exception
            else:
                return self._result
    
        def add_done_callback(self, fn):
            """Attaches a callable that will be called when the future finishes.
    
            Args:
                fn: A callable that will be called with this future as its only
                    argument when the future completes or is cancelled. The callable
                    will always be called by a thread in the same process in which
                    it was added. If the future has already completed or been
                    cancelled then the callable will be called immediately. These
                    callables are called in the order that they were added.
            """
            with self._condition:
                if self._state not in [CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED]:
                    self._done_callbacks.append(fn)
                    return
            fn(self)
    
        def result(self, timeout=None):
            """Return the result of the call that the future represents.
    
            Args:
                timeout: The number of seconds to wait for the result if the future
                    isn't done. If None, then there is no limit on the wait time.
    
            Returns:
                The result of the call that the future represents.
    
            Raises:
                CancelledError: If the future was cancelled.
                TimeoutError: If the future didn't finish executing before the given
                    timeout.
                Exception: If the call raised then that exception will be raised.
            """
            with self._condition:
                if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                    raise CancelledError()
                elif self._state == FINISHED:
                    return self.__get_result()
    
                self._condition.wait(timeout)
    
                if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                    raise CancelledError()
                elif self._state == FINISHED:
                    return self.__get_result()
                else:
                    raise TimeoutError()
    
        def exception(self, timeout=None):
            """Return the exception raised by the call that the future represents.
    
            Args:
                timeout: The number of seconds to wait for the exception if the
                    future isn't done. If None, then there is no limit on the wait
                    time.
    
            Returns:
                The exception raised by the call that the future represents or None
                if the call completed without raising.
    
            Raises:
                CancelledError: If the future was cancelled.
                TimeoutError: If the future didn't finish executing before the given
                    timeout.
            """
    
            with self._condition:
                if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                    raise CancelledError()
                elif self._state == FINISHED:
                    return self._exception
    
                self._condition.wait(timeout)
    
                if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
                    raise CancelledError()
                elif self._state == FINISHED:
                    return self._exception
                else:
                    raise TimeoutError()
    
        # The following methods should only be used by Executors and in tests.
        def set_running_or_notify_cancel(self):
            """Mark the future as running or process any cancel notifications.
    
            Should only be used by Executor implementations and unit tests.
    
            If the future has been cancelled (cancel() was called and returned
            True) then any threads waiting on the future completing (though calls
            to as_completed() or wait()) are notified and False is returned.
    
            If the future was not cancelled then it is put in the running state
            (future calls to running() will return True) and True is returned.
    
            This method should be called by Executor implementations before
            executing the work associated with this future. If this method returns
            False then the work should not be executed.
    
            Returns:
                False if the Future was cancelled, True otherwise.
    
            Raises:
                RuntimeError: if this method was already called or if set_result()
                    or set_exception() was called.
            """
            with self._condition:
                if self._state == CANCELLED:
                    self._state = CANCELLED_AND_NOTIFIED
                    for waiter in self._waiters:
                        waiter.add_cancelled(self)
                    # self._condition.notify_all() is not necessary because
                    # self.cancel() triggers a notification.
                    return False
                elif self._state == PENDING:
                    self._state = RUNNING
                    return True
                else:
                    LOGGER.critical('Future %s in unexpected state: %s',
                                    id(self.future),
                                    self.future._state)
                    raise RuntimeError('Future in unexpected state')
    
        def set_result(self, result):
            """Sets the return value of work associated with the future.
    
            Should only be used by Executor implementations and unit tests.
            """
            with self._condition:
                self._result = result
                self._state = FINISHED
                for waiter in self._waiters:
                    waiter.add_result(self)
                self._condition.notify_all()
            self._invoke_callbacks()
    
        def set_exception(self, exception):
            """Sets the result of the future as being the given exception.
    
            Should only be used by Executor implementations and unit tests.
            """
            with self._condition:
                self._exception = exception
                self._state = FINISHED
                for waiter in self._waiters:
                    waiter.add_exception(self)
                self._condition.notify_all()
            self._invoke_callbacks()