from crystal.util import windows_filesystem
from crystal.util.xos import is_linux, is_mac_os, is_windows
import errno
import os


def flush_rename_of_file(filepath: str) -> None:
    """
    Ensures that a rename of the specified file is flushed to disk.
    
    If the filesystem on which the file resides does not support flushing then take no action.
    
    If the parent directory of the specified file does not exist,
    an OSError will be raised. It is OK if the specified file itself does not exist. 
    
    Arguments:
    - filepath --
        Path to a recently renamed file.
    
    Raises:
    - OSError -- if an I/O error occurred while flushing
    """
    flush_renames_in_directory(os.path.dirname(filepath))


def flush_renames_in_directory(parent_dirpath: str) -> None:
    """
    Ensures that all renames of files to locations directly within the specified
    parent directory are flushed to disk.
    
    If the filesystem on which the parent directory resides does not support 
    flushing then take no action.
    
    If the specified parent directory does not exist, an OSError will be raised.
    
    Arguments:
    - parent_dirpath --
        Path to a directory containing zero or more recently renamed files.
    
    Raises:
    - OSError -- if an I/O error occurred while flushing
    """
    # Ensure os.rename() is flushed to disk:
    # - Windows:
    #     - FlushFileBuffers the parent directory of the renamed file
    # - macOS/Linux:
    #     - fsync the parent directory of the renamed file
    if is_windows():
        # Windows: Always flush the parent directory
        try:
            windows_filesystem.flush_directory(parent_dirpath)
        except OSError as e:
            if e.errno in (
                    errno.EINVAL,
                    errno.ENOTSUP,
                    getattr(errno, 'ENOSYS', _UnsupportedErrno)):
                # Filesystem does not support flushing. Ignore.
                pass
            else:
                raise
    elif is_mac_os() or is_linux():
        # POSIX: Always fsync the parent directory
        dir_fd = os.open(parent_dirpath, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        except OSError as e:
            if e.errno in (
                    errno.EINVAL,
                    errno.ENOTSUP,
                    getattr(errno, 'ENOSYS', _UnsupportedErrno)):
                # Filesystem does not support fsync. Ignore.
                pass
            else:
                raise
        finally:
            os.close(dir_fd)
    else:
        raise NotImplementedError()


_UnsupportedErrno = object()
