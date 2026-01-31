import errno
import os
from crystal.util import windows_filesystem
from crystal.util.xos import is_linux, is_mac_os, is_windows
from typing import Callable


def flush_rename_of_file(
        filepath: str,
        win_filesystem_known_to_support_journaling: bool,
        ) -> None:
    """
    Ensures that a rename of the specified file is flushed to disk.
    
    If the filesystem on which the file resides does not support flushing then take no action.
    
    If the parent directory of the specified file does not exist,
    an OSError will be raised. It is OK if the specified file itself does not exist. 
    
    The parent directory of the specified file must exist,
    although the file itself may not exist.
    
    Arguments:
    - filepath --
        Path to a recently renamed file.
    - win_filesystem_known_to_support_journaling --
        If Windows, whether (filesystem_supports_journaling(filepath) or False).
        If not Windows, False.
    
    Raises:
    - OSError -- if an I/O error occurred while flushing
    """
    flush_renames_in_directory(
        lambda: os.path.dirname(filepath),
        win_filesystem_known_to_support_journaling
    )


def flush_renames_in_directory(
        parent_dirpath: str | Callable[[], str],
        win_filesystem_known_to_support_journaling: bool,
        ) -> None:
    """
    Ensures that all renames of files to locations directly within the specified
    parent directory are flushed to disk.
    
    If the filesystem on which the parent directory resides does not support 
    flushing then take no action.
    
    If the specified parent directory does not exist, an OSError will be raised.
    
    Arguments:
    - parent_dirpath --
        Path to a directory containing zero or more recently renamed files.
    - win_filesystem_known_to_support_journaling --
        If Windows, whether (filesystem_supports_journaling(parent_dirpath) or False).
        If not Windows, False.
    
    Raises:
    - OSError -- if an I/O error occurred while flushing
    """
    # Ensure os.rename() is flushed to disk:
    # - Windows:
    #     - On NTFS/ReFS filesystem, journaling provides durability guarantee,
    #       without any further operations. ✅
    #     - On ExFAT/FAT filesystem, there is no journaling.
    #       Therefore rename is NOT durable without flushing.
    #       We use FlushFileBuffers to flush the directory. ✅
    #     - On Samba/network filesystem, durability is NOT guaranteed even
    #       with flushing. ⚠️
    # - macOS/Linux:
    #     - fsync the parent directory of the renamed file
    if is_windows():
        # Windows: Flush directory only if filesystem lacks journaling
        if win_filesystem_known_to_support_journaling:
            return
        if callable(parent_dirpath):
            parent_dirpath = parent_dirpath()  # reinterpret
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
        if callable(parent_dirpath):
            parent_dirpath = parent_dirpath()  # reinterpret
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
