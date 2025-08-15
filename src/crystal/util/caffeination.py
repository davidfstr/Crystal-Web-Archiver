import contextlib
import threading
from typing import Any, Optional
import wakepy
import warnings


class Caffeination:
    """
    Controls whether the system is prevented from idle sleeping.
    
    The screen is not kept awake during caffeination.
    """
    _lock = threading.Lock()
    _caffeine_count = 0
    _caffeinated = False
    _wakepy_keeper = None  # type: Optional[Any]
    _caffeination_unavailable = False
    
    @classmethod
    def add_caffeine(cls) -> None:
        with cls._lock:
            old_caffeine_count = cls._caffeine_count  # capture
            cls._caffeine_count += 1
            if old_caffeine_count == 0:
                cls._set_caffeinated(True)
    
    @classmethod
    def remove_caffeine(cls) -> None:
        with cls._lock:
            cls._caffeine_count -= 1
            assert cls._caffeine_count >= 0
            new_caffeine_count = cls._caffeine_count  # capture
            if new_caffeine_count == 0:
                cls._set_caffeinated(False)
    
    @classmethod
    def _set_caffeinated(cls, caffeinated: bool) -> None:
        if caffeinated == cls._caffeinated:
            return
        
        if caffeinated:
            assert cls._wakepy_keeper is None
            if cls._caffeination_unavailable:
                cls._wakepy_keeper = contextlib.nullcontext()
            else:
                cls._wakepy_keeper = wakepy.keep.running()
            try:
                cls._wakepy_keeper.__enter__()  # type: ignore[attr-defined]
            except Exception as e:
                warnings.warn(
                    f'Unable to caffeinate: {e}. '
                    f'Will no longer try to caffeinate until quit.')
                cls._caffeination_unavailable = True
                
                cls._wakepy_keeper = contextlib.nullcontext()
                cls._wakepy_keeper.__enter__()
        else:
            assert cls._wakepy_keeper is not None
            cls._wakepy_keeper.__exit__(None, None, None)
            cls._wakepy_keeper = None
        
        cls._caffeinated = caffeinated
