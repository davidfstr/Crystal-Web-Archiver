from functools import wraps
import os
from typing import Callable, ParamSpec, TypeVar
from unittest import SkipTest


_P = ParamSpec('_P')
_R = TypeVar('_R')


def _mark(label: str) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """
    Creates a decorator that marks tests with the specified label.
    
    If the label is included in the environment variable
    CRYSTAL_EXCLUDE_TESTS_MARKED then it will be skipped by `crystal test`.
    """
    def marked(func: Callable[_P, _R]) -> Callable[_P, _R]:
        @wraps(func)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            if label in os.environ.get('CRYSTAL_EXCLUDE_TESTS_MARKED', '').split(','):
                raise SkipTest(f'marked {label!r}')
            return func(*args, **kwargs)
        return wrapped
    return marked


# Test decorators that mark the test with the same-named label
slow = _mark('slow')
slow.__doc__ = (
    """
    Marks a test that is unusually slow.
    
    Slow tests will be skipped by many types of continuous integration jobs.
    """
)


def serial_only(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """
    Marks a test that only works properly when run in serial.
    
    For example, focus-related tests that use SetFocus and HasFocus generally
    must run in serial to be able to detect focus states correctly.
    """
    @wraps(func)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        from crystal.util.test_mode import is_parallel
        if is_parallel():
            raise SkipTest(f'marked @serial_only but tests are running in parallel')
        return func(*args, **kwargs)
    serial_only.test_names.append(func.__name__)  # type: ignore[attr-defined]
    return wrapped
serial_only.test_names = []  # type: ignore[attr-defined]
