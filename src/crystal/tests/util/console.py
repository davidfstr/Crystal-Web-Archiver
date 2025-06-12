from collections.abc import Callable, Iterator
from contextlib import contextmanager, redirect_stdout
import io
import sys
from typing import cast, TextIO


@contextmanager
def console_output_copied() -> Iterator[io.StringIO]:
    buffer = io.StringIO()
    stdout_and_buffer = cast(TextIO, _MultiplexedWriteOnlyTextIO([sys.stdout, buffer]))
    with redirect_stdout(stdout_and_buffer):
        yield buffer


_WRITE_CALLABLE_ATTRS = [
    # IOBase
    'close', 'flush', 'seek', 'truncate', 'writelines',
    # BufferedIOBase
    'write',
    # TextIOBase
    # (no additional attributes)
]

class _MultiplexedWriteOnlyTextIO:
    def __init__(self, bases: list[TextIO]) -> None:
        if not len(bases) >= 1:
            raise ValueError()
        self._bases = bases
    
    def __getattr__(self, attr_name: str):
        if attr_name in _WRITE_CALLABLE_ATTRS:
            return _MultiplexedCallable([
                getattr(base, attr_name)
                for base in self._bases
            ])
        else:
            return getattr(self._bases[0], attr_name)


class _MultiplexedCallable:
    def __init__(self, bases: list[Callable]) -> None:
        if not len(bases) >= 1:
            raise ValueError()
        self._bases = bases
    
    def __call__(self, *args, **kwargs):
        result = self._bases[0](*args, **kwargs)
        for other_base in self._bases[1:]:
            other_base(*args, **kwargs)
        return result
