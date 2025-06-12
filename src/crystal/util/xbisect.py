from collections.abc import Callable
from crystal.util.lazymap import lazymap
from sortedcontainers import SortedKeyList, SortedList
from typing import Generic, TypeVar

_E1 = TypeVar('_E1')
_E2 = TypeVar('_E2')


def bisect_key_right(
        a: 'SortedList[_E1]',
        x: _E2,
        order_preserving_key: Callable[[_E1], _E2]
        ) -> int:
    """
    Locate the insertion point for `x` in `a` to maintain sorted order,
    returning an insertion point which comes after (to the right of) any
    existing entries of x in a.
    
    `order_preserving_key` specifies a key function of one argument that 
    is used to extract a comparison key from each element in the array.
    To support searching complex records, the key function is not applied
    to the `x` value.
    
    When applying `order_preserving_key` to every element of `a` in order,
    it must result in a list that is itself sorted. If this condition is
    not true then the bisection result is undefined.
    """
    return _LazySortedKeyListAdapter(a, order_preserving_key).bisect_key_right(x)


class _LazySortedKeyListAdapter(Generic[_E1]):  # behaves like a SortedKeyList[_E1]
    def __init__(self,
            a: 'SortedList[_E1]',
            order_preserving_key: Callable[[_E1], _E2]
            ) -> None:
        self._a = a
        
        # Define internals of SortedKeyList
        self._maxes = lazymap(
            a._maxes,
            key=order_preserving_key
        )
        self._keys = lazymap(
            a._lists,
            key=lambda sublist: lazymap(
                sublist,
                key=order_preserving_key
            )
        )
    
    def __getattr__(self, attr_name: str):
        # Obtain remaining internals of SortedKeyList from the base SortedList
        return getattr(self._a, attr_name)
    
    def bisect_key_right(self, x: _E2) -> int:
        return SortedKeyList.bisect_key_right(self, x)
