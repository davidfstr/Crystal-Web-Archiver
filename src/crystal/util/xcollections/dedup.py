from typing import List, TypeVar


_E = TypeVar('_E')


def dedup_list(xs: List[_E]) -> List[_E]:
    """
    Removes duplicates from the specified list,
    preserving the original order of elements.
    """
    return list(dict.fromkeys(xs))
