import sys
from typing import TYPE_CHECKING

__all__ = ['Ellipsis', 'EllipsisType']


# 1. Define EllipsisType, the type of Ellipsis
# 2. Define Ellipsis
if sys.version_info >= (3, 10):
    from types import EllipsisType
    Ellipsis = Ellipsis  # export
else:
    # https://github.com/python/typing/issues/684#issuecomment-548203158
    if TYPE_CHECKING:
        from enum import Enum
        class EllipsisType(Enum):
            Ellipsis = '...'
        Ellipsis = EllipsisType.Ellipsis
    else:
        EllipsisType = type(Ellipsis)
        Ellipsis = Ellipsis  # export