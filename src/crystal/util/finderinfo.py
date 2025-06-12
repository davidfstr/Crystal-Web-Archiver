"""
A FinderInfo is a structure used to store certain macOS-specific file metadata.

References:
- http://dubeiko.com/development/FileSystems/HFSPLUS/tn1150.html#FinderInfo
- https://arstechnica.com/gadgets/2013/10/os-x-10-9/9/
"""
from crystal.util.xos import is_mac_os

_EMPTY = b'\x00' * 32


# Empirically-determined bit that is set when "Hide extension" is enabled
# for a file in the Finder
HIDE_FILE_EXTENSION = (
    b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x00\x00\x00\x00'
    b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
)


# === Get/Set FinderInfo ===

def get(filepath: str) -> bytes:
    assert is_mac_os()
    
    import xattr  # don't import at top-level because only available on macOS
    
    try:
        return xattr.getxattr(filepath, xattr.XATTR_FINDERINFO_NAME)
    except OSError as e:
        if e.errno == 93:  # 'Attribute not found'
            return _EMPTY
        else:
            raise


def set(filepath: str, finderinfo: bytes) -> None:
    assert is_mac_os()
    
    import xattr  # don't import at top-level because only available on macOS
    
    if finderinfo == _EMPTY:
        try:
            xattr.removexattr(filepath, xattr.XATTR_FINDERINFO_NAME)
        except OSError as e:
            if e.errno == 93:  # 'Attribute not found'
                pass
            else:
                raise
    else:
        xattr.setxattr(filepath, xattr.XATTR_FINDERINFO_NAME, finderinfo)


# === Hide File Extension ===

def set_hide_file_extension(itempath: str, hide: bool) -> None:
    old_fi = get(itempath)
    if hide:
        new_fi = or_(old_fi, HIDE_FILE_EXTENSION)
    else:
        new_fi = and_(old_fi, not_(HIDE_FILE_EXTENSION))
    set(itempath, new_fi)


def get_hide_file_extension(itempath: str) -> bool:
    fi = get(itempath)
    return and_(fi, HIDE_FILE_EXTENSION) != _EMPTY


# === Bitwise Operations ===

def and_(finderinfo1: bytes, finderinfo2: bytes) -> bytes:
    return bytes([a & b for (a, b) in zip(finderinfo1, finderinfo2)])

def or_(finderinfo1: bytes, finderinfo2: bytes) -> bytes:
    return bytes([a | b for (a, b) in zip(finderinfo1, finderinfo2)])

def not_(finderinfo: bytes) -> bytes:
    return bytes([a ^ 0b11111111 for a in finderinfo])
