from typing import TypeVar

_E = TypeVar('_E')


def dedup_list(xs: list[_E]) -> list[_E]:
    """
    Removes duplicates from the specified list,
    preserving the original order of elements.
    """
    return list(dict.fromkeys(xs))
