from crystal.tests.util.skip import skipTest
from crystal.util.xos import is_linux, is_windows
from functools import wraps
import platform
from unittest import TestCase


# ------------------------------------------------------------------------------
# Utility: Skip on Windows

def skip_on_windows(func=lambda: None):
    """Decorator for tests that should be skipped on Windows."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if is_windows():
            skipTest('not supported on Windows')
        func(*args, **kwargs)
    return wrapper


# ------------------------------------------------------------------------------
