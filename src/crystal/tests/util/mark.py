from functools import wraps
import os
from typing import Callable, ParamSpec, TypeVar
from unittest import SkipTest


_P = ParamSpec('_P')
_R = TypeVar('_R')


def mark(label: str) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
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
slow = mark('slow')
