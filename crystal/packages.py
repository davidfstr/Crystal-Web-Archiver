import subprocess

def set_package(dir_path, is_package=True):
    """
    Marks the specified directory as a 'package', meaning that it will
    appear as a file in the native file manager (ex: Finder or Windows Explorer).
    
    This is currently only implemented on Mac OS X. Calling this on other systems will
    have no effect.
    
    Returns True if successful, False otherwise.
    """
    
    try:
        subprocess.check_call([
            '/usr/bin/SetFile', '-a', 'B' if is_package else 'b', dir_path])
    except:
        return False
    else:
        return True
