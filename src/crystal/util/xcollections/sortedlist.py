from sortedcontainers import SortedList
from typing_extensions import override


class BlackHoleSortedList(SortedList):
    """
    A SortedList that is always empty. Silently ignores requests to add items.
    """
    def __init__(self, iterable=None, key=None):
        super().__init__()
    
    @override
    def add(self, value):
        pass
    
    @override
    def update(self, iterable):
        pass
    
    @override
    def __iadd__(self, other):
        return self
    
    @override
    def __imul__(self, num):
        return self


BLACK_HOLE_SORTED_LIST = BlackHoleSortedList()
