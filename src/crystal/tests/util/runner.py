from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Generator
from crystal.util.xthreading import bg_affinity, fg_affinity, fg_call_and_wait
import sys
import time
import traceback
from types import coroutine, FrameType
from typing import Generic, TYPE_CHECKING, TypeVar, Union
import urllib.error
import urllib.request

if TYPE_CHECKING:
    from crystal.tests.util.server import WebPage


_T = TypeVar('_T')


# ------------------------------------------------------------------------------
# Test Runner

@bg_affinity
def run_test(test_func: Callable[[], Awaitable[_T]] | Callable[[], _T]) -> _T:
    """
    Runs the specified test function.
    
    If the test function is async then it is run on the foreground thread.
    
    If the test function is sync then it is run on the (current) background thread.
    """
    test_co = test_func()  # if async func then should be a Generator[Command, None, _T]
    if not asyncio.iscoroutine(test_co):
        return test_co  # type: ignore[return-value]
    last_command_result = None  # type: Union[object, Exception]
    while True:
        try:
            command = fg_call_and_wait(
                lambda: test_co.send(last_command_result),  # type: ignore[attr-defined, union-attr]
                profile=False
            )
        except StopIteration as e:
            return e.value
        if not isinstance(command, Command):
            raise ValueError(
                'Async test function did yield something that was '
                f'not a Command: {command!r}')
        try:
            last_command_result = command.run()
        except Exception as e:
            last_command_result = e


@coroutine
@fg_affinity
def bg_sleep(
        duration: float
        ) -> Generator[Command, object, None]:
    """
    Switch to a background thread, sleep for the specified duration (in seconds), and
    then resume this foreground thread.
    """
    none_or_error = yield SleepCommand(duration)
    if none_or_error is None:
        return
    elif isinstance(none_or_error, Exception):
        raise none_or_error
    else:
        raise AssertionError()


@coroutine
@fg_affinity
def bg_fetch_url(
        url: str,
        *, headers: dict[str, str] | None=None,
        timeout: float | None=None,
        method: str='GET',
        data: bytes | None=None,
        follow_redirects: bool=True,
        ) -> Generator[Command, object, WebPage]:
    """
    Switch to a background thread, fetch the specified URL, and
    then resume this foreground thread.
    """
    from crystal.tests.util.server import WebPage
    from crystal.tests.util.wait import DEFAULT_WAIT_TIMEOUT
    
    if timeout is None:
        timeout = DEFAULT_WAIT_TIMEOUT
    
    page_or_error = yield FetchUrlCommand(url, headers, timeout, method, data, follow_redirects)
    if isinstance(page_or_error, WebPage):
        return page_or_error
    elif isinstance(page_or_error, Exception):
        raise page_or_error
    else:
        raise AssertionError()


@coroutine
@fg_affinity
def pump_wx_events() -> Generator[Command, object, None]:
    """
    Process all pending events on the wx event queue.
    
    Caution: If fg_wait_for() is called while this command is running,
    it is possible that only *some* pending events will be processed
    after pump_wx_events() returns, rather than all of them.
    """
    yield PumpWxEventsCommand()


@coroutine
@fg_affinity
def bg_breakpoint() -> Generator[Command, object, None]:
    """
    Stops the program in the debugger, with the foreground thread released,
    allowing the user to interact with the UI while the debugger has the program paused.
    
    Example usage:
        from crystal.tests.util.runner import bg_breakpoint
        await bg_breakpoint()
    """
    yield BreakpointCommand(sys._getframe(1))


class Command(Generic[_T]):  # abstract
    def run(self) -> _T:
        raise NotImplementedError()


class SleepCommand(Command[None]):
    def __init__(self, delay: float) -> None:
        self.delay = delay  # in seconds
    
    @bg_affinity
    def run(self) -> None:
        time.sleep(self.delay)


class FetchUrlCommand(Command['WebPage']):
    def __init__(self,
            url: str,
            headers: dict[str, str] | None,
            timeout: float,
            method: str='GET',
            data: bytes | None=None,
            follow_redirects: bool=True
            ) -> None:
        self._url = url
        self._headers = headers
        self._timeout = timeout
        self._method = method
        self._data = data
        self._follow_redirects = follow_redirects
    
    @bg_affinity
    def run(self) -> WebPage:
        from crystal.tests.util.server import WebPage
        
        try:
            request = urllib.request.Request(
                self._url,
                data=self._data,
                headers=(self._headers or {}),
                method=self._method
            )
            
            if self._follow_redirects:
                # Use default behavior (follows redirects)
                response_stream = urllib.request.urlopen(request, timeout=self._timeout)
            else:
                # Create opener that doesn't follow redirects
                class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, req, fp, code, msg, headers, newurl):
                        return None  # Don't follow redirects
                
                opener = urllib.request.build_opener(NoRedirectHandler)
                response_stream = opener.open(request, timeout=self._timeout)
        except urllib.error.HTTPError as e:
            response_stream = e
        with response_stream as response:
            response_bytes = response.read()
        return WebPage(
            self._url,
            response_stream.status,
            response_stream.headers,
            response_bytes,
        )


class PumpWxEventsCommand(Command[None]):
    @bg_affinity
    def run(self) -> None:
        fg_call_and_wait(lambda: None)


class BreakpointCommand(Command[None]):
    def __init__(self, frame: FrameType) -> None:
        self._frame = frame
    
    @bg_affinity
    def run(self) -> None:
        print('Breakpoint hit at:')
        traceback.print_stack(self._frame)
        
        import pdb
        pdb.set_trace()


# ------------------------------------------------------------------------------
