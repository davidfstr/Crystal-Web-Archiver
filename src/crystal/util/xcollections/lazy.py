from collections.abc import Callable, Iterator, Sequence
from enum import Enum
from typing import Generic, List, Literal, overload, TypeVar, Union

_E = TypeVar('_E')


class UnmaterializedItem(Enum):
    VALUE = None

class AppendableLazySequence(Generic[_E], Sequence[_E]):
    """
    Sequence that lazily populates itself upon access, which is designed to be
    accessed sequentially starting from the first element.
    
    Wraps an underlying sequence that may be appended to but not modified
    in any other way.
    """
    
    # Optimize per-instance memory use, since there may be very many Task objects
    # that contain a AppendableLazySequence
    __slots__ = (
        '_createitem_func',
        '_materializeitem_func',
        '_unmaterializeitem_func',
        '_len_func',
        '_cached_prefix',
    )
    
    def __init__(self,
            createitem_func: Callable[[int], _E],
            materializeitem_func: Callable[[_E], None],
            unmaterializeitem_func: Callable[[_E], None],
            len_func: Callable[[], int]):
        """
        Arguments:
        * createitem_func -- Creates the item at the specified index in this sequence.
        * materializeitem_func -- Called after a newly created item is contained in this sequence.
        * unmaterializeitem_func -- Destroys the specified item in this sequence.
        * len_func -- Returns the length of this sequence, including any unmaterialized items.
        """
        self._createitem_func = createitem_func
        self._materializeitem_func = materializeitem_func
        self._unmaterializeitem_func = unmaterializeitem_func
        self._len_func = len_func
        self._cached_prefix = []  # type: List[Union[_E, UnmaterializedItem]]
    
    @property
    def cached_prefix_len(self) -> int:
        """
        Returns the length of the prefix of this sequence containing
        materialized items.
        """
        return len(self._cached_prefix)
    
    @overload
    def __getitem__(self, index: int) -> _E:
        ...
    @overload
    def __getitem__(self, index: int, unmaterialized_ok: Literal[True]) -> _E | UnmaterializedItem:
        ...
    @overload
    def __getitem__(self, index: slice) -> Sequence[_E]:
        ...
    def __getitem__(self, index: int | slice, unmaterialized_ok: bool=False):
        """
        Returns the item at the specified index, materializing it if necessary.
        
        Raises:
        * UnmaterializedItemError --
            if specified item was explicitly unmaterialized
        """
        if isinstance(index, slice):
            if index.start is not None and index.start < 0:
                raise ValueError('Negative indexes in slice not supported')
            if index.stop is not None and index.stop < 0:
                raise ValueError('Negative indexes in slice not supported')
            # Greedily expand the slice
            # NOTE: Might return a lazy slice in the future
            return [self[i] for i in range(index.start or 0, index.stop or len(self), index.step or 1)]
        if not isinstance(index, int):
            raise ValueError(f'Invalid index: {index!r}')
        if index < 0:
            index += len(self)
            if index < 0:
                raise IndexError()
        if index >= len(self):
            raise IndexError()
        while index >= len(self._cached_prefix):
            child = self._createitem_func(len(self._cached_prefix))
            self._cached_prefix.append(child)
            self._materializeitem_func(child)
        item = self._cached_prefix[index]
        if isinstance(item, UnmaterializedItem):
            if unmaterialized_ok:
                return item
            # NOTE: In the future it MIGHT be desirable to allow rematerializing
            #       items that were once materialized, by enabling the False
            #       case of the following if-statement
            if True:
                # Disallow access to unmaterialized items that were once materialized
                raise UnmaterializedItemError()
            else:
                # Recreate unmaterialized item that was previously materialized
                item = self._cached_prefix[index] = self._createitem_func(index)
                assert not isinstance(item, UnmaterializedItem)
        return item
    
    def unmaterialize(self, index: int) -> None:
        """
        Marks the specified index of this sequence as not expecting access in
        the future.
        """
        if index < 0:
            index += len(self)
            if index < 0:
                raise IndexError()
        if index >= len(self):
            raise IndexError()
        if index < len(self._cached_prefix):
            item = self._cached_prefix[index]
            if not isinstance(item, UnmaterializedItem):
                self._unmaterializeitem_func(item)
                self._cached_prefix[index] = UnmaterializedItem.VALUE
    
    def __len__(self) -> int:
        return self._len_func()
    
    # NOTE: Assumes that each item of this list is unique.
    #       Therefore a created item must be in the created prefix of
    #       this list if it is anywhere in this list at all.
    def __contains__(self, item: object) -> bool:
        return item in self._cached_prefix
    
    def materialized_items(self) -> Iterator[_E]:
        items = []
        for item in self._cached_prefix:
            if not isinstance(item, UnmaterializedItem):
                items.append(item)
        return iter(items)


class UnmaterializedItemError(ValueError):
    def __init__(self) -> None:
        super().__init__('Cannot access item that was explicitly unmaterialized')

