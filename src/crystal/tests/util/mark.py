from functools import wraps
import os
from typing import Callable, ParamSpec, TypeVar
from unittest import SkipTest

from crystal.util.test_mode import is_parallel
from crystal.util.xos import is_ci, is_linux, is_mac_os


_P = ParamSpec('_P')
_R = TypeVar('_R')


# ------------------------------------------------------------------------------
# slow

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


# ------------------------------------------------------------------------------
# serial_only

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


# ------------------------------------------------------------------------------
# Focus-Sensitive Tests

def reacts_to_focus_changes(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """
    Marks a test which tests behavior that depends on observing focus changes.
    """
    # Add a @serial_only decorator to the function before this decorator,
    # because focus changes can only be reliably observed when a test is running
    # in serial as the frontmost foreground process
    func = serial_only(func)
    
    @wraps(func)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        if not should_check_focused_windows():
            raise SkipTest(
                f'tests behavior which reacts to focus changes, '
                f'but focus changes cannot be observed reliably in this environment')
        return func(*args, **kwargs)
    return wrapped


def should_check_focused_windows() -> bool:
    """
    Returns whether automated tests that have an option of skipping
    focus-related assertion checks should skip those checks.
    """
    # Disable focus checking in:
    # - headless environments like macOS and Linux CI,
    #   where no control ever reports being focused
    # - local environments like macOS and Linux,
    #   where wiggling the mouse can cause inconsistent focus statuses
    return not (
        (is_ci() or not is_ci()) and  # i.e., True
        (is_mac_os() or is_linux())
    )


# ------------------------------------------------------------------------------
