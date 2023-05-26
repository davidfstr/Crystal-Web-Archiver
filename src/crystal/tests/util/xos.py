from functools import wraps
import platform
from unittest import SkipTest, TestCase


skipTest = TestCase().skipTest


# ------------------------------------------------------------------------------
# Utility: Skip on Windows

def skip_on_windows(func=lambda: None):
    """Decorator for tests that should be skipped on Windows."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if platform.system() == 'Windows':
            skipTest('not supported on Windows')
        func(*args, **kwargs)
    return wrapper


# ------------------------------------------------------------------------------
