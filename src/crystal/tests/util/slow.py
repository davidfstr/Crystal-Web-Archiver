from functools import wraps
import os
from typing import Callable, ParamSpec, TypeVar
from unittest import SkipTest


_P = ParamSpec('_P')
_R = TypeVar('_R')


def slow(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """Decorator that skips tests marked 'slow' via CRYSTAL_EXCLUDE_TESTS_MARKED."""
    @wraps(func)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        if 'slow' in os.environ.get('CRYSTAL_EXCLUDE_TESTS_MARKED', '').split(','):
            raise SkipTest("marked 'slow'")
        return func(*args, **kwargs)
    return wrapped
