"""
Pack16 format utilities for bundling revision files into zip archives.

The Pack16 format stores groups of 16 consecutive revisions together in
uncompressed ZIP64 archives to improve storage efficiency on systems with
large minimum object sizes (e.g., AWS S3 Glacier with 128 KB minimum).
"""

from crystal.util.filesystem import rename_and_flush
import os
import tempfile
from typing import IO, Self
from zipfile import ZipFile, ZIP_STORED


def create_pack_file(
        revision_files: dict[str, str],
        dest_filepath: str,
        tmp_dirpath: str) -> None:
    """
    Creates an uncompressed ZIP64 file from a mapping of entry names to
    source file paths, atomically.

    Arguments:
    * revision_files -- mapping from entry name (e.g., '01a') to source filepath
    * dest_filepath -- final destination path for the pack file
    * tmp_dirpath -- temporary directory to write the pack file before moving it

    Raises:
    * OSError -- if could not write pack file
    """
    if not revision_files:
        # No files to pack. Don't create an empty zip.
        return

    tmp_filepath = None
    try:
        with tempfile.NamedTemporaryFile(
                mode='wb',
                suffix='.zip',
                dir=tmp_dirpath,
                delete=False,
                ) as tmp_file:
            tmp_filepath = tmp_file.name
            
            # Write a zip file containing the revision body files, uncompressed
            with ZipFile(tmp_file, 'w', compression=ZIP_STORED, allowZip64=True) as zf:
                for (entry_name, source_filepath) in revision_files.items():
                    zf.write(source_filepath, arcname=entry_name)

            # Ensure data is flushed to stable storage
            os.fsync(tmp_file.fileno())
        
        # Move to final location.
        # Create parent directory if needed.
        try:
            rename_and_flush(tmp_filepath, dest_filepath)
        except FileNotFoundError:
            os.makedirs(os.path.dirname(dest_filepath), exist_ok=True)
            rename_and_flush(tmp_filepath, dest_filepath)
    except:
        # Clean up temp file if operation failed
        if tmp_filepath is not None:
            try:
                os.remove(tmp_filepath)
            except FileNotFoundError:
                pass
        raise


def open_pack_entry(pack_path: str, entry_name: str) -> 'ZipEntryReader':
    """
    Opens a specific entry from a pack zip file, returning a file-like object.

    The returned file-like object keeps the ZipFile open until the stream is closed.

    Arguments:
    * pack_path -- path to the pack zip file
    * entry_name -- name of the entry to read (e.g., '01a')

    Returns:
    * A file-like object for reading the entry

    Raises:
    * ZipEntryNotFoundError -- if entry is not found in the pack file
    * OSError -- if could not read pack file
    """
    zip_file = ZipFile(pack_path, 'r')
    try:
        try:
            entry_file = zip_file.open(entry_name, 'r')
        except KeyError:
            raise ZipEntryNotFoundError(
                f'There is no item named {entry_name!r} in the archive'
            ) from None
        return ZipEntryReader(zip_file, entry_file)
    except:
        zip_file.close()
        raise


class ZipEntryNotFoundError(Exception):
    pass


class ZipEntryReader:
    """
    A zip entry file-like object. Keeps its containing ZipFile open.
    """
    def __init__(self, zip_file: ZipFile, entry_file: IO[bytes]) -> None:
        self._zip_file = zip_file
        self._entry_file = entry_file

    def read(self, size: int = -1) -> bytes:
        return self._entry_file.read(size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._entry_file.seek(offset, whence)

    def tell(self) -> int:
        return self._entry_file.tell()

    def close(self) -> None:
        try:
            self._entry_file.close()
        finally:
            self._zip_file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_) -> None:
        self.close()
