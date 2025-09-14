from typing import TypeVar


IntStr = str
"""
A string that parses as an integer.

Useful for sending potentially large integer values to JavaScript,
where large integer values cannot be accurately represented in the
native number type.
"""


def intstr_from(integer: int) -> IntStr:
    """Creates an IntStr from an int."""
    return IntStr(str(integer))


_T = TypeVar('_T')

def not_none(value: _T | None) -> _T:
    assert value is not None
    return value
