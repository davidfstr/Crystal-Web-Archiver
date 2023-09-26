import os
import sys
from typing import List


class ListenableMixin:
    """
    Mixin for objects that have a listener list.
    """
    _WARN_IF_LEAKING_LISTENERS = \
        os.environ.get('CRYSTAL_LEAKING_LISTENER_WARNINGS', 'False') == 'True'
    
    # Optimize per-instance memory use, since some subclasses have very many objects
    __slots__ = (
        'listeners',
    )
    
    def __init__(self, *args, **kwargs) -> None:
        self.listeners = []  # type: List[object]
        super().__init__(*args, **kwargs)
    
    def __del__(self) -> None:
        if hasattr(self, '_WARN_IF_LEAKING_LISTENERS') and self._WARN_IF_LEAKING_LISTENERS:
            if hasattr(self, 'listeners') and self.listeners is not None:
                if len(self.listeners) != 0:
                    print(
                        f'*** Listenable object {self!r} still had listeners '
                            f'when it was finalized: {self.listeners!r}',
                        file=sys.stderr)
        if hasattr(super(), '__del__'):
            super().__del__()  # type: ignore[misc]
