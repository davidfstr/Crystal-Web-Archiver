import math
import platform
from typing import List, Optional


# === OS Detection ===

def is_mac_os() -> bool:
    return (platform.system() == 'Darwin')


def is_windows() -> bool:
    return (platform.system() == 'Windows')


def is_linux() -> bool:
    return (platform.system() == 'Linux')


def windows_major_version() -> Optional[int]:
    """
    Returns the major version number of Windows, or None if unknown.
    
    Examples:
    * 7 -- Windows 7
    * 8 -- Windows 8, Windows 8.1
    * 10 -- Windows 10
    * None -- unknown Windows
    """
    if not is_windows():
        return None
    
    release_str = platform.release()
    try:
        release_number = float(release_str)
    except ValueError:
        return None
    else:
        return math.floor(release_number)


def mac_version() -> Optional[List[int]]:
    if not is_mac_os():
        return None
    
    return [int(x) for x in platform.mac_ver()[0].split('.')]


# === wxPython Backend Detection ===

def is_wx_gtk() -> bool:
    return is_linux()
