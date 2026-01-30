"""
Windows-specific filesystem operations.
"""

from crystal.util.xos import is_windows
import ctypes
import os


# === Filesystem Detection ===

def filesystem_supports_journaling(path: str) -> bool | None:
    """
    Returns whether the filesystem at the given path supports journaling,
    or None if that information is unknown.
    """
    if not is_windows():
        raise ValueError('Can only be called on Windows')
    
    fs_type = _get_windows_filesystem_type(path)
    if fs_type is None:
        # Unknown filesystem: assume conservatively that it does not support journaling
        return False
    
    fs_type_upper = fs_type.upper()
    if fs_type_upper in ('NTFS', 'REFS'):
        # Journaled filesystem
        return True
    elif fs_type_upper in ('FAT', 'FAT32', 'EXFAT'):
        # Non-journaled filesystem
        return False
    else:
        # Unknown filesystem
        return None


def _get_windows_filesystem_type(path: str) -> str | None:
    r"""
    Returns the filesystem type for the given path on Windows (e.g., 'NTFS', 'FAT32', 'exFAT').
    Returns None if the filesystem type cannot be determined.
    
    Works with both local paths (C:\path) and UNC paths (\\server\share\path).
    """
    if not is_windows():
        raise ValueError('Can only be called on Windows')
    
    from ctypes import wintypes  # type: ignore[import]
    
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)  # type: ignore[attr-defined]
    
    # Define GetVolumeInformationW signature
    GetVolumeInformationW = kernel32.GetVolumeInformationW
    GetVolumeInformationW.argtypes = [
        wintypes.LPCWSTR,   # lpRootPathName
        wintypes.LPWSTR,    # lpVolumeNameBuffer
        wintypes.DWORD,     # nVolumeNameSize
        ctypes.POINTER(wintypes.DWORD),  # lpVolumeSerialNumber
        ctypes.POINTER(wintypes.DWORD),  # lpMaximumComponentLength
        ctypes.POINTER(wintypes.DWORD),  # lpFileSystemFlags
        wintypes.LPWSTR,    # lpFileSystemNameBuffer
        wintypes.DWORD,     # nFileSystemNameSize
    ]
    GetVolumeInformationW.restype = wintypes.BOOL
    
    # Get the volume root path for GetVolumeInformationW.
    # 
    # GetVolumeInformationW expects:
    # - For local drives: 'C:\' (drive_letter:\)
    # - For UNC paths: '\\server\share\' (UNC share path)
    (drive, _) = os.path.splitdrive(os.path.abspath(path))
    if drive.startswith('\\\\'):
        # UNC path (\\server\share\path).
        # Drive is in the format '\\server\share'.
        root_path = drive + '\\'
    else:
        # Local drive path (C:\path).
        # Drive is in the format 'C:'.
        root_path = drive + '\\'
    
    # Call GetVolumeInformationW
    fs_name_buffer = ctypes.create_unicode_buffer(256)
    result = GetVolumeInformationW(
        root_path,
        None,  # lpVolumeNameBuffer (not needed)
        0,     # nVolumeNameSize
        None,  # lpVolumeSerialNumber (not needed)
        None,  # lpMaximumComponentLength (not needed)
        None,  # lpFileSystemFlags (not needed)
        fs_name_buffer,
        ctypes.sizeof(fs_name_buffer)
    )
    if result:
        return fs_name_buffer.value
    else:
        return None


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
