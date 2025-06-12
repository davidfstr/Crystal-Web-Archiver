from crystal.util.xos import is_mac_os, is_windows
import ctypes
import os
import subprocess
import threading
from typing import Optional

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001  # prevents idle sleep
_ES_DISPLAY_REQUIRED = 0x00000002  # prevents screen sleep


class Caffeination:
    """
    Controls whether the system is prevented from idle sleeping.
    
    The screen is not kept awake during caffeination.
    """
    _lock = threading.Lock()
    _caffeine_count = 0
    _caffeinated = False
    _caffeinator = None  # type: Optional[subprocess.Popen]
    
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
        if is_mac_os():
            if caffeinated:
                assert cls._caffeinator is None
                cls._caffeinator = subprocess.Popen(
                    [
                        'caffeinate',
                        # Wait for Crystal process to terminate
                        '-w', str(os.getpid()),
                        # No idle sleep
                        '-i',
                        # No sleep while on A/C power
                        '-s'
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL)
                assert cls._caffeinator.poll() is None, \
                    'caffeinate process terminated immediately unexpectedly'
            else:
                assert cls._caffeinator is not None
                cls._caffeinator.terminate()
                cls._caffeinator.wait()
                cls._caffeinator = None
        elif is_windows():
            # See: https://docs.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate
            if caffeinated:
                ctypes.windll.kernel32.SetThreadExecutionState(  # type: ignore[attr-defined]
                    _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
            else:
                ctypes.windll.kernel32.SetThreadExecutionState(  # type: ignore[attr-defined]
                    _ES_CONTINUOUS)
        else:
            # TODO: Support on Linux.
            #       See the wakepy library for an example implementation.
            # 
            # Not supported
            return
        cls._caffeinated = caffeinated
