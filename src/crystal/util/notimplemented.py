import sys
from typing import TYPE_CHECKING

__all__ = ['NotImplemented', 'NotImplementedType']


# 1. Define NotImplementedType, the type of NotImplemented
# 2. Define NotImplemented
if sys.version_info >= (3, 10):
    from types import NotImplementedType
    NotImplemented = NotImplemented  # export
else:
    # https://github.com/python/typing/issues/684#issuecomment-548203158
    if TYPE_CHECKING:
        from enum import Enum
        class NotImplementedType(Enum):
            NotImplemented = 'NotImplemented'
        NotImplemented = NotImplementedType.NotImplemented
    else:
        NotImplementedType = type(NotImplemented)
        NotImplemented = NotImplemented  # export