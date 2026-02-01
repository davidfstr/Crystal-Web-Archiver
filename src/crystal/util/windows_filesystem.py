"""
Windows-specific filesystem operations.
"""

from crystal.util.xos import is_windows
import ctypes


# === Filesystem Operations ===

def flush_directory(dirpath: str) -> None:
    """
    Flushes pending I/O to a directory on Windows using FlushFileBuffers.
    
    Raises:
    * OSError -- if the directory cannot be flushed
    """
    if not is_windows():
        raise ValueError('Can only be called on Windows')
    
    from ctypes import wintypes  # type: ignore[import]
    
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)  # type: ignore[attr-defined]
    
    # Define CreateFileW signature
    CreateFileW = kernel32.CreateFileW
    CreateFileW.argtypes = [
        wintypes.LPCWSTR,   # lpFileName
        wintypes.DWORD,     # dwDesiredAccess
        wintypes.DWORD,     # dwShareMode
        wintypes.LPVOID,    # lpSecurityAttributes
        wintypes.DWORD,     # dwCreationDisposition
        wintypes.DWORD,     # dwFlagsAndAttributes
        wintypes.HANDLE,    # hTemplateFile
    ]
    CreateFileW.restype = wintypes.HANDLE
    
    # Define FlushFileBuffers signature
    FlushFileBuffers = kernel32.FlushFileBuffers
    FlushFileBuffers.argtypes = [wintypes.HANDLE]
    FlushFileBuffers.restype = wintypes.BOOL
    
    # Define CloseHandle signature
    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL
    
    # Constants
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000  # Required to open directories
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
    
    # Open the directory
    handle = CreateFileW(
        dirpath,
        GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        None
    )
    if handle == INVALID_HANDLE_VALUE:
        raise OSError(
            ctypes.get_last_error(),  # type: ignore[attr-defined]
            f'Failed to open directory: {dirpath}'
        )
    try:
        # Flush the directory
        result = FlushFileBuffers(handle)
        if not result:
            raise OSError(
                ctypes.get_last_error(),  # type: ignore[attr-defined]
                f'Failed to flush directory: {dirpath}'
            )
    finally:
        # Close the directory
        CloseHandle(handle)
