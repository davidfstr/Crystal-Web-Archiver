import sys
if sys.version_info >= (3, 14):
    from io import Reader, Writer  # reexport
else:
    from types import GenericAlias
    from typing import Protocol


    # Backport from Python 3.14 to 3.11
    class Reader(Protocol):
        """Protocol for simple I/O reader instances.

        This protocol only supports blocking I/O.
        """

        __slots__ = ()

        def read(self, size=..., /):
            """Read data from the input stream and return it.

            If *size* is specified, at most *size* items (bytes/characters) will be
            read.
            """
            ...

        __class_getitem__ = classmethod(GenericAlias)  # type: ignore


    # Backport from Python 3.14 to 3.11
    class Writer(Protocol):
        """Protocol for simple I/O writer instances.

        This protocol only supports blocking I/O.
        """

        __slots__ = ()

        def write(self, data, /):
            """Write *data* to the output stream and return the number of items written."""
            ...

        __class_getitem__ = classmethod(GenericAlias)  # type: ignore
