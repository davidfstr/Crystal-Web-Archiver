from collections.abc import Iterator
from contextlib import contextmanager
import os
import sys
import tempfile


@contextmanager
def NamedTemporaryFile(
        *args,
        delete: bool=True,
        delete_on_close: bool=True,
        **kwargs,
        ) -> Iterator[tempfile._TemporaryFileWrapper]:
    """
    Extends NamedTemporaryFile with the Python 3.12's behavior of
    having separate {delete, delete_on_close} parameters.
    """
    if sys.version_info[:2] >= (3, 12):
        kwargs['delete'] = delete
        kwargs['delete_on_close'] = delete_on_close
        with tempfile.NamedTemporaryFile(*args, **kwargs) as f:
            yield f
    else:  # Python 3.11
        kwargs['delete'] = delete_on_close
        with tempfile.NamedTemporaryFile(*args, **kwargs) as f:
            try:
                yield f
            finally:
                if delete and not delete_on_close:
                    try:
                        os.remove(f.name)
                    except Exception:
                        # Ignore exceptions on close
                        pass
