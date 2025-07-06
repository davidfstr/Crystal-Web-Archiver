from crystal.util.xos import is_windows
import tempfile


def TemporaryDirectory(*args, **kwargs) -> tempfile.TemporaryDirectory:
    """
    Create a temporary directory that is automatically cleaned up when done.
    
    This is a wrapper around `tempfile.TemporaryDirectory` that ignores
    cleanup errors on Windows because Windows is more strict about
    deleting directories containing files that are still open.
    This behavior allows tests to ignore cleanup errors at the cost of
    leaving some temporary directories around if they are still in use.
    
    Non-test code should never use this function, as it is intended
    to be used in tests where cleanup errors can be ignored.
    Use `tempfile.TemporaryDirectory` directly in production code.
    """
    return tempfile.TemporaryDirectory(*args, **(kwargs | dict(
        # NOTE: If a file inside the temporary directory is still open,
        #       ignore_cleanup_errors=True will prevent Windows from raising,
        #       at the cost of leaving the temporary directory around
        ignore_cleanup_errors=True if is_windows() else False,
    )))
