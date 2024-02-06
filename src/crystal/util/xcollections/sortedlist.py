from overrides import overrides
from sortedcontainers import SortedList


class BlackHoleSortedList(SortedList):
    """
    A SortedList that is always empty. Silently ignores requests to add items.
    """
    def __init__(self, iterable=None, key=None):
        super().__init__()
    
    @overrides
    def add(self, value):
        pass
    
    @overrides
    def update(self, iterable):
        pass
    
    @overrides
    def __iadd__(self, other):
        return self
    
    @overrides
    def __imul__(self, num):
        return self


BLACK_HOLE_SORTED_LIST = BlackHoleSortedList()
