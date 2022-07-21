from contextlib import contextmanager
from typing import Callable, Iterator, NoReturn


def is_wrapped_object_deleted_error(e: Exception) -> bool:
    e_str = str(e)
    return (
        isinstance(e, RuntimeError) and
        e_str.startswith('wrapped C/C++ object of type ') and
        e_str.endswith(' has been deleted')
    )


@contextmanager
def wrapped_object_deleted_error_ignored() -> Iterator[None]:
    try:
        yield
    except Exception as e:
        if is_wrapped_object_deleted_error(e):
            pass
        else:
            raise


@contextmanager
def wrapped_object_deleted_error_raising(raiser: Callable[[], NoReturn]) -> Iterator[None]:
    try:
        yield
    except Exception as e:
        if is_wrapped_object_deleted_error(e):
            raiser()
        else:
            raise
            

class WindowDeletedError(Exception):
    """Raises when code attempts to manipulate a wx.Window that has been deleted."""
    pass
