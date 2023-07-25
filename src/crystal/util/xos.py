import math
import platform
from typing import Optional


# === Feature Detection ===

def project_appears_as_package_file():
    """
    Returns whether *.crystalproj items appear as package files on this platform.
    
    In particular on macOS the CFBundleDocumentTypes property list key defines
    that *.crystalproj items as LSTypeIsPackage=true, which causes all such
    items to appear as package files rather than as directories.
    """
    return is_mac_os()


def wx_resize_border_is_invisible() -> bool:
    """
    Returns whether the wx.RESIZE_BORDER style applied to a wx.Frame causes
    a resizable border to appear that is visible, as opposed to one that is invisible.
    """
    if is_mac_os():  # macOS 10.14+
        return True
    elif is_windows():  # Windows *
        major_version = windows_major_version()
        if major_version is None:  # unknown Windows
            pass
        elif major_version in [7, 8]:  # Windows 7, Windows 8
            # Windows 7 and 8 add a visible border on all edges
            return False
        elif major_version >= 10:  # Windows 10+
            # Windows 10 adds a visible border on the top edge only
            return False
        else:  # unknown Windows
            pass
        # Unknown Windows
        return False
    elif is_linux():  # Ubuntu 22.04+
        return True
    
    # Default, assuming a newer OS
    return True


# === OS Detection ===

def is_mac_os() -> bool:
    return (platform.system() == 'Darwin')


def is_windows() -> bool:
    return (platform.system() == 'Windows')


def is_linux() -> bool:
    return (platform.system() == 'Linux')


def is_wx_gtk() -> bool:
    return is_linux()


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
