import platform
import subprocess

def can_set_package():
    """
    Returns whether the 'set_package' command is supported on this platform.
    """
    is_mac_os_x = (platform.system() == 'Darwin')
    return is_mac_os_x

def set_package(dir_path, is_package=True):
    """
    Marks the specified directory as a 'package', meaning that it will
    appear as a file in the native file manager (ex: Finder or Windows Explorer).
    
    This is currently only implemented on Mac OS X. Calling this on other systems will
    have no effect.
    
    Returns True if successful, False otherwise.
    """
    
    # Don't even try if it isn't likely to work
    if not can_set_package():
        return False
    
    try:
        subprocess.check_call([
            '/usr/bin/SetFile', '-a', 'B' if is_package else 'b', dir_path])
    except:
        return False
    else:
        return True
