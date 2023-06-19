from contextlib import contextmanager
import inspect
import sys
import time
from typing import Callable, Iterator, Union


@contextmanager
def warn_if_slow(
        title: str,
        max_duration: float,
        message: Union[Callable[[], str], str],
        *, enabled: bool=True
        ) -> Iterator[None]:
    if not enabled:
        yield
        return
    
    start_time = time.time()
    try:
        yield
    finally:
        end_time = time.time()
        delta_time = end_time - start_time
        if delta_time > max_duration:
            message_str = message() if callable(message) else message
            assert isinstance(message_str, str)
            print("*** %s took %.02fs to execute: %s" % (
                title,
                delta_time,
                message_str,
            ), file=sys.stderr)


def create_profiled_callable(title: str, max_duration: float, callable, *args):
    """
    Decorates the specified callable such that it prints
    a warning to the console if its runtime is long.
    """
    def profiled_callable():
        start_time = time.time()
        try:
            callable(*args)
        finally:
            end_time = time.time()
            delta_time = end_time - start_time
            if delta_time > max_duration:
                root_callable = callable
                while hasattr(root_callable, 'callable'):
                    root_callable = root_callable.callable
                
                try:
                    file = inspect.getsourcefile(root_callable)
                except Exception:
                    file = '?'
                try:
                    start_line_number = inspect.getsourcelines(root_callable)[-1]
                except Exception:
                    start_line_number = '?'
                print("*** %s took %.02fs to execute: %s @ [%s:%s]" % (
                    title,
                    delta_time,
                    root_callable,
                    file,
                    start_line_number
                ), file=sys.stderr)
    return profiled_callable
