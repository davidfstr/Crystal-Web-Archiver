from collections.abc import Iterator
from contextlib import contextmanager
from crystal.util.xos import is_linux, is_mac_os, is_windows
import ctypes
import errno
import os
import sys
from threading import Lock
from typing import BinaryIO, Literal
from weakref import WeakValueDictionary


# TODO: Consider standardizing on IO[bytes] rather than on BinaryIO interface,
#       which is easy to confuse with BytesIO concrete implementation
def open_nonexclusive(filepath: str, mode: Literal['rb', 'wb'] = 'rb') -> BinaryIO:
    """Opens a binary file, allowing concurrent writes from other processes."""
    if sys.platform == 'win32':  # is_windows()
        import ctypes
        import msvcrt
        from ctypes import wintypes
        
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        FILE_SHARE_READ = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        FILE_SHARE_DELETE = 0x00000004
        OPEN_EXISTING = 3
        CREATE_ALWAYS = 2
        FILE_ATTRIBUTE_NORMAL = 0x80
        
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        
        # Define CreateFileW signature
        CreateFileW = kernel32.CreateFileW
        CreateFileW.argtypes = [
            wintypes.LPCWSTR,   # lpFileName
            wintypes.DWORD,     # dwDesiredAccess
            wintypes.DWORD,     # dwShareMode
            ctypes.c_void_p,    # lpSecurityAttributes
            wintypes.DWORD,     # dwCreationDisposition
            wintypes.DWORD,     # dwFlagsAndAttributes
            wintypes.HANDLE,    # hTemplateFile
        ]
        CreateFileW.restype = wintypes.HANDLE
        
        # Define CloseHandle signature (for cleanup on error)
        CloseHandle = kernel32.CloseHandle
        CloseHandle.argtypes = [wintypes.HANDLE]
        CloseHandle.restype = wintypes.BOOL
        
        if mode == 'rb':
            desired_access = GENERIC_READ
            creation_disposition = OPEN_EXISTING
            os_flags = os.O_RDONLY | os.O_BINARY
        elif mode == 'wb':
            desired_access = GENERIC_WRITE
            creation_disposition = CREATE_ALWAYS
            os_flags = os.O_WRONLY | os.O_BINARY
        else:
            raise ValueError(f'Unsupported mode: {mode}')
        
        handle = CreateFileW(
            filepath,
            desired_access,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            creation_disposition,
            FILE_ATTRIBUTE_NORMAL,
            None
        )
        INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
        if handle == INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())
        
        # Convert Windows HANDLE to file descriptor.
        # If this fails, must close the handle to avoid leaking it.
        try:
            fd = msvcrt.open_osfhandle(handle, os_flags)
        except:
            CloseHandle(handle)
            raise
        
        # At this point, fd owns the handle. Convert fd to Python file object.
        # If this fails, must close the fd (which also closes the handle).
        try:
            return os.fdopen(fd, mode)
        except:
            os.close(fd)
            raise
    else:
        return open(filepath, mode)


def replace_and_flush(
        src_filepath: str,
        dst_filepath: str,
        *, nonatomic_ok: bool = False,
        ) -> None:
    """
    Renames a file and ensures the rename is flushed to disk.
    If the destination file exists it will be replaced.
    
    If the filesystem on which the file resides does not support flushing
    then take no action when attempting to flush.
    
    Callers that opt-in to nonatomic_ok=True behavior should be prepared
    to repair interrupted replace operations, which may transiently rename
    the (dst_filepath) to (dst_filepath + replace_and_flush.RENAME_SUFFIX).
    For an example of how to do a repair, see how ResourceRevision.open()
    uses nonatomic_ok=True and replace_destination_locked().
    
    Arguments:
    * src_filepath -- path to source file to rename
    * dst_filepath -- path to destination
    * nonatomic_ok -- if True, allows non-atomic replacement on Windows when
        destination file is open (uses rename-aside strategy). If False (default),
        raises PermissionError if destination is open.
    
    Raises:
    * FileNotFoundError -- if source file does not exist
    * PermissionError -- if destination is open and nonatomic_ok=False
    * OSError -- if an I/O error occurred while flushing
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
        ERROR_ACCESS_DENIED = 5
        
        # Try to replace
        result = MoveFileExW(
            src_filepath,
            dst_filepath,
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
        if result == 0:
            error_code = ctypes.get_last_error()  # type: ignore[attr-defined]
            
            # ERROR_ACCESS_DENIED can occur when destination file is open
            # even with FILE_SHARE_DELETE
            if not (error_code == ERROR_ACCESS_DENIED and nonatomic_ok):
                # Either not ERROR_ACCESS_DENIED, or caller doesn't allow nonatomic
                raise ctypes.WinError(error_code)  # type: ignore[attr-defined]
            
            # Use rename-aside strategy to avoid data loss if crash occurs between steps:
            # 1. Rename dst to dst+RENAME_SUFFIX (preserves old data)
            # 2. Move src to dst (new data in place)
            # 3. Delete dst+RENAME_SUFFIX (cleanup)
            with replace_destination_locked(dst_filepath):
                movedaside_dst_filepath = dst_filepath + replace_and_flush.RENAME_SUFFIX  # type: ignore[attr-defined]
                
                # Step 1: Rename aside (will succeed if file opened with FILE_SHARE_DELETE)
                try:
                    result = MoveFileExW(
                        dst_filepath,
                        movedaside_dst_filepath,
                        # NOTE: MOVEFILE_REPLACE_EXISTING so that any stale
                        #       movedaside_dst_filepath is deleted
                        MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
                    )
                    if result == 0:
                        raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
                except Exception:
                    # Raise original MoveFileExW error
                    raise ctypes.WinError(error_code)  # type: ignore[attr-defined]
                try:
                    # Step 2: Move new file into place
                    result = MoveFileExW(
                        src_filepath,
                        dst_filepath,
                        MOVEFILE_WRITE_THROUGH,
                    )
                    if result == 0:
                        raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]
                except:
                    # Rollback rename aside
                    try:
                        MoveFileExW(movedaside_dst_filepath, dst_filepath, MOVEFILE_WRITE_THROUGH)
                    except:
                        # Best effort. Ignore errors.
                        pass
                    raise
                else:
                    # Step 3: Delete old file
                    try:
                        os.remove(movedaside_dst_filepath)
                    except OSError as e:
                        # Cleanup failed, although new file is in place. Warn and continue.
                        print(
                            f'WARNING: Failed to cleanup temporary file {movedaside_dst_filepath!r}: {e}',
                            file=sys.stderr)
                    return
    else:
        os.replace(src_filepath, dst_filepath)
        flush_renames_in_directory(os.path.dirname(dst_filepath))

# Suffix used when renaming aside a file being replaced
replace_and_flush.RENAME_SUFFIX = '.replacing'  # type: ignore[attr-defined]


_mutex_for_replace_destination_lock = Lock()
_mutex_for_replace_destination = WeakValueDictionary()  # type: WeakValueDictionary[str, Lock]

@contextmanager
def replace_destination_locked(dst_filepath: str) -> Iterator[None]:
    """
    Context in which either (1) a non-atomic replace_and_flush() operation or
    (2) a repair of one, is allowed
    """
    with _mutex_for_replace_destination_lock:
        mutex = _mutex_for_replace_destination.get(dst_filepath)
        if mutex is None:
            mutex = Lock()
            _mutex_for_replace_destination[dst_filepath] = mutex
    with mutex:
        yield


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
    * parent_dirpath --
        Path to a directory containing zero or more recently renamed files.
    
    Raises:
    * OSError -- if an I/O error occurred while flushing
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


def fine_grained_mtimes_available() -> bool:
    """
    Returns whether the current OS/filesystem supports fine-grained modification times
    that can reliably distinguish between file operations happening in quick succession.
    
    Returns:
    * False on Windows (where NTFS has ~10ms granularity and FAT has 2-second granularity)
    * True on Unix-like systems (where modern filesystems typically have nanosecond granularity)
    """
    return not is_windows()


_UnsupportedErrno = object()
