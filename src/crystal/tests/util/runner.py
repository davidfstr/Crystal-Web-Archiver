from __future__ import annotations

import asyncio
from crystal.util.xthreading import fg_call_and_wait, is_foreground_thread
import time
from typing import (
    Awaitable, Callable, Dict, Generic, Optional, TYPE_CHECKING, TypeVar, Union
)
import urllib.request
import urllib.error

if TYPE_CHECKING:
    from crystal.tests.util.server import WebPage


_T = TypeVar('_T')


# ------------------------------------------------------------------------------
# Test Runner

def run_test(async_test_func: Callable[[], Awaitable[None]]) -> None:
    if is_foreground_thread():
        raise ValueError(
            'run_test() does not support being called on the foreground thread')
    
    test_co = async_test_func()  # should be a Generator[Command, None, None]
    last_command_result = None  # type: Union[object, Exception]
    while True:
        try:
            command = fg_call_and_wait(
                lambda: test_co.send(last_command_result)  # type: ignore[attr-defined]
            )
        except StopIteration:
            break
        if not isinstance(command, Command):
            raise ValueError(
                'Async test function did yield something that was '
                f'not a Command: {command!r}')
        try:
            last_command_result = command.run()
        except Exception as e:
            last_command_result = e


@asyncio.coroutine
def bg_sleep(  # type: ignore[misc]  # ignore non-Generator return type here
        duration: float
        ) -> Awaitable[None]:  # or Generator[Command, object, None]
    """
    Switch to a background thread, sleep for the specified duration, and
    then resume this foreground thread.
    """
    assert is_foreground_thread()
    
    none_or_error = yield SleepCommand(duration)
    if none_or_error is None:
        return
    elif isinstance(none_or_error, Exception):
        raise none_or_error
    else:
        raise AssertionError()


@asyncio.coroutine
def bg_fetch_url(  # type: ignore[misc]  # ignore non-Generator return type here
    url: str,
    *, headers: Optional[Dict[str, str]]=None,
    timeout: float,
    ) -> Awaitable[WebPage]:  # or Generator[Command, object, WebPage]
    """
    Switch to a background thread, fetch the specified URL, and
    then resume this foreground thread.
    """
    from crystal.tests.util.server import WebPage
    
    assert is_foreground_thread()
    
    page_or_error = yield FetchUrlCommand(url, headers, timeout)
    if isinstance(page_or_error, WebPage):
        return page_or_error
    elif isinstance(page_or_error, Exception):
        raise page_or_error
    else:
        raise AssertionError()


class Command(Generic[_T]):  # abstract
    def run(self) -> _T:
        raise NotImplementedError()


class SleepCommand(Command[None]):
    def __init__(self, delay: float) -> None:
        self._delay = delay
    
    def run(self) -> None:
        assert not is_foreground_thread()
        
        time.sleep(self._delay)


class FetchUrlCommand(Command['WebPage']):
    def __init__(self, url: str, headers: Optional[Dict[str, str]], timeout: float) -> None:
        self._url = url
        self._headers = headers
        self._timeout = timeout
    
    def run(self) -> WebPage:
        from crystal.tests.util.server import WebPage
        
        assert not is_foreground_thread()
        
        try:
            response_stream = urllib.request.urlopen(
                urllib.request.Request(
                    self._url,
                    headers=(self._headers or {})
                ),
                timeout=self._timeout)
        except urllib.error.HTTPError as e:
            response_stream = e
        with response_stream as response:
            response_text = response.read().decode('utf-8')
        return WebPage(response_stream.status, response_text)


# ------------------------------------------------------------------------------