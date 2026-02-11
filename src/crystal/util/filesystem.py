from crystal.util.xos import is_linux, is_mac_os, is_windows
import ctypes
import errno
import os


def replace_and_flush(src_filepath: str, dst_filepath: str) -> None:
    """
    Renames a file and ensures the rename is flushed to disk.
    If the destination file exists it will be replaced.
    
    If the filesystem on which the file resides does not support flushing
    then take no action when attempting to flush.
    
    Raises:
    - OSError -- if an I/O error occurred while flushing
    """
    if is_windows():
        from ctypes import wintypes  # type: ignore[import]
        
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)  # type: ignore[attr-defined]
        
        # Define MoveFileExW signature
        MoveFileExW = kernel32.MoveFileExW
        MoveFileExW.argtypes = [
            wintypes.LPCWSTR,   # lpExistingFileName
            wintypes.LPCWSTR,   # lpNewFileName
            wintypes.DWORD,     # dwFlags
        ]
        MoveFileExW.restype = wintypes.BOOL
        
        # Constants
        MOVEFILE_REPLACE_EXISTING = 0x1
        MOVEFILE_WRITE_THROUGH = 0x8  # flush rename to disk
        
        result = MoveFileExW(
            src_filepath,
            dst_filepath,
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
        if result == 0:
            # Raise an OSError with the Windows error code
            raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
    else:
        os.replace(src_filepath, dst_filepath)
        flush_renames_in_directory(os.path.dirname(dst_filepath))


def flush_renames_in_directory(parent_dirpath: str) -> None:
    """
    Ensures that all renames of files to locations directly within the specified
    parent directory are flushed to disk.
    
    If the operating system does not provide an API to bulk-flush renames
    in a directory - like Windows - then take no action.
    
    If the filesystem on which the parent directory resides does not support 
    flushing then take no action.
    
    If the specified parent directory does not exist, an OSError will be raised.
    
    Arguments:
    - parent_dirpath --
        Path to a directory containing zero or more recently renamed files.
    
    Raises:
    - OSError -- if an I/O error occurred while flushing
    """
    if is_windows():
        # Windows: Do nothing
        # 
        # - The os.rename() operation on Windows is backed by MoveFileExW (with flags=0).
        # - MoveFileExW documents that the MOVEFILE_WRITE_THROUGH flag should be used
        #   to flush *individual* moves to disk but does not document any way to
        #   efficiently flush *multiple* moves to disk.
        # - Flushing for every single file move would likely be inefficient,
        #   so Crystal does not attempt to flush large numbers of file moves
        #   on Windows at all.
        pass
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
