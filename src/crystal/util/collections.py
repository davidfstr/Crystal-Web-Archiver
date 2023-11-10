from typing import Any, Callable, Generic, List, overload, Sequence, TypeVar, Union


_E = TypeVar('_E')


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
        '_len_func',
        '_cached_prefix',
    )
    
    def __init__(self,
            createitem_func: Callable[[int], _E],
            materializeitem_func: Callable[[_E], None],
            len_func: Callable[[], int]):
        """
        Arguments:
        * createitem_func -- Creates the item at the specified index in this sequence.
        * materializeitem_func -- Called after a newly created item is contained in this sequence.
        * len_func -- Returns the length of this sequence, including any unmaterialized items.
        """
        self._createitem_func = createitem_func
        self._materializeitem_func = materializeitem_func
        self._len_func = len_func
        self._cached_prefix = []  # type: List[_E]
    
    @property
    def cached_prefix(self) -> Sequence[_E]:
        return self._cached_prefix
    
    @overload
    def __getitem__(self, index: int) -> _E:
        ...
    @overload
    def __getitem__(self, index: slice) -> Sequence[_E]:
        ...
    def __getitem__(self, index: Union[int, slice]):
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
        while index >= len(self._cached_prefix):
            child = self._createitem_func(len(self._cached_prefix))
            self._cached_prefix.append(child)
            self._materializeitem_func(child)
        return self._cached_prefix[index]
    
    def __len__(self) -> int:
        return self._len_func()
    
    # NOTE: Assumes that each item of this list is unique.
    #       Therefore that a created item must be in the created prefix of
    #       this list if it is anywhere in this list at all.
    def __contains__(self, item: object) -> bool:
        return item in self._cached_prefix


class CustomSequence(Generic[_E], Sequence[_E]):
    """A Sequence."""
    
    # Optimize per-instance memory use
    __slots__ = (
        '_getitem_func',
        '_len_func',
    )
    
    def __init__(self, getitem_func: Callable[[int], _E], len_func: Callable[[], int]):
        self._getitem_func = getitem_func
        self._len_func = len_func
    
    @overload
    def __getitem__(self, index: int) -> _E:
        ...
    @overload
    def __getitem__(self, index: slice) -> Sequence[_E]:
        ...
    def __getitem__(self, index):
        if isinstance(index, slice):
            if index.start is not None and index.start < 0:
                raise ValueError('Negative indexes in slice not supported')
            if index.stop is not None and index.stop < 0:
                raise ValueError('Negative indexes in slice not supported')
            return [self[i] for i in range(index.start or 0, index.stop or len(self), index.step or 1)]
        if not isinstance(index, int):
            raise ValueError(f'Invalid index: {index!r}')
        if index < 0:
            raise ValueError('Negative indexes not supported')
        return self._getitem_func(index)
    
    def __len__(self) -> int:
        return self._len_func()
