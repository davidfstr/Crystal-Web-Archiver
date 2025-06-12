from collections.abc import Callable, Sequence
from typing import Generic, TypeVar

_E1 = TypeVar('_E1')
_E2 = TypeVar('_E2')


class lazymap(Generic[_E2], Sequence[_E2]):
    """
    Lazily-computed read-only list where each element is equal to an element
    of a base list after being passed through a key transformation function.
    """
    def __init__(self, base: list[_E1], key: Callable[[_E1], _E2]) -> None:
        self._base = base
        self._key = key
    
    def __getitem__(self, index):
        if isinstance(index, slice):
            raise NotImplementedError()
        return self._key(self._base[index])
    
    def __len__(self) -> int:
        return len(self._base)
