from collections.abc import Callable, Iterator
from contextlib import contextmanager
import os
from typing import NoReturn

# Whether RuntimeError('wrapped C/C++ object of type ... has been deleted')
# (or its sibling WindowDeletedError) is silently ignored.
# 
# It is unsafe to ignore these errors in general because they are raised
# on only a best effort basis when a use-after-free error in C/C++ would
# normally have happened and either crashed the process immediately
# or corrupted memory, crashing the process later.
IGNORE_USE_AFTER_FREE = (
    os.environ.get('CRYSTAL_IGNORE_USE_AFTER_FREE', 'False') == 'True'
)


def is_wrapped_object_deleted_error(e: Exception) -> bool:
    e_str = str(e)
    return (
        isinstance(e, RuntimeError) and
        e_str.startswith('wrapped C/C++ object of type ') and
        e_str.endswith(' has been deleted')
    )


@contextmanager
def wrapped_object_deleted_error_ignored() -> Iterator[None]:
    if IGNORE_USE_AFTER_FREE:
        try:
            yield
        except Exception as e:
            if is_wrapped_object_deleted_error(e):
                pass
            else:
                raise
    else:
        # May raise errors matching is_wrapped_object_deleted_error()
        yield


@contextmanager
def wrapped_object_deleted_error_raising(
        raiser: Callable[[], NoReturn] | None=None
        ) -> Iterator[None]:
    if IGNORE_USE_AFTER_FREE:
        if raiser is None:
            def default_raiser() -> NoReturn:
                raise WindowDeletedError()
            raiser = default_raiser
        try:
            yield
        except Exception as e:
            if is_wrapped_object_deleted_error(e):
                raiser()
            else:
                raise
    else:
        # May raise errors matching is_wrapped_object_deleted_error()
        yield
            

class WindowDeletedError(Exception):
    """Raises when code attempts to manipulate a wx.Window that has been deleted."""
