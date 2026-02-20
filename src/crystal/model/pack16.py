"""
Pack16 format utilities for bundling revision files into zip archives.

The Pack16 format stores groups of 16 consecutive revisions together in
uncompressed ZIP64 archives to improve storage efficiency on systems with
large minimum object sizes (e.g., AWS S3 Glacier with 128 KB minimum).
"""

from crystal.util.filesystem import open_nonexclusive, replace_and_flush
from crystal.util.xio import Reader, Writer
import os
import shutil
import sys
import tempfile
from typing import IO, BinaryIO, Self
from zipfile import ZipFile, ZipInfo, ZIP_STORED


def create_pack_file(
        revision_files: dict[str, str],
        dest_filepath: str,
        tmp_dirpath: str,
        retain_empty_pack_file_if_errors: bool = False,
        ) -> set[str]:
    """
    Creates an uncompressed ZIP64 file from a mapping of entry names to
    source file paths, atomically.

    If a source file cannot be read (I/O error), it is skipped and a warning
    is printed to stderr. The caller can compare the returned set against the
    input keys to determine which files were skipped.

    Arguments:
    * revision_files -- mapping from entry name (e.g., '01a') to source filepath
    * dest_filepath -- final destination path for the pack file
    * tmp_dirpath -- temporary directory to write the pack file before moving it
    * retain_empty_pack_file_if_errors -- if True, still creates an empty 
      pack file even when all reads fail, which can be useful as a 
      migration skip-marker; default False

    Returns:
    * The set of entry names that were successfully packed.
      Empty set if no files were packed (either no input files or all reads failed).

    Raises:
    * OSError -- if could not write pack file
    """
    if not revision_files:
        # No files to pack. Don't create an empty pack file.
        return set()
    
    good_entry_names = set()
    dev_null = _DevNullWriter()
    
    tmp_filepath = None
    try:
        with tempfile.NamedTemporaryFile(
                mode='wb',
                suffix='.zip',
                dir=tmp_dirpath,
                delete=False,
                ) as tmp_file:
            tmp_filepath = tmp_file.name
            
            # 1. Write a zip file containing the revision body files, uncompressed
            # 2. Scan all the source files for I/O errors
            zip_file_ok = True
            with ZipFile(tmp_file, 'w', compression=ZIP_STORED, allowZip64=True) as zf:
                for (entry_name, source_filepath) in revision_files.items():
                    spy_source_file = None
                    try:
                        source_file = open(source_filepath, 'rb')
                        spy_source_file = _ErrorObservingReader(source_file)
                        with source_file:
                            dest_file = (
                                zf.open(ZipInfo(entry_name), 'w', force_zip64=True)
                                if zip_file_ok
                                else dev_null
                            )
                            with dest_file:
                                shutil.copyfileobj(spy_source_file, dest_file)
                    except OSError as e:
                        if spy_source_file is None or spy_source_file.last_error is not None:
                            # Open/read error from source_file
                            print(
                                f'WARNING: Could not read revision file {source_filepath}: {e}. '
                                    f'Skipping from pack.',
                                file=sys.stderr)
                            
                            # 1. Stop trying to write the zip file.
                            # 2. Continue scanning source files for I/O errors.
                            zip_file_ok = False
                        else:
                            # Open/write error to dest_file. Abort.
                            raise
                    else:
                        good_entry_names.add(entry_name)
            
            # If an I/O error occurred while reading one of the revision body files,
            # retry writing the zip file, but only with the revision body files with no errors
            if not zip_file_ok:
                # Rewind and clear the first partially written zip file
                tmp_file.seek(0)
                tmp_file.truncate()
                
                with ZipFile(tmp_file, 'w', compression=ZIP_STORED, allowZip64=True) as zf:
                    for (entry_name, source_filepath) in revision_files.items():
                        if entry_name not in good_entry_names:
                            continue
                        spy_source_file = None
                        try:
                            source_file = open(source_filepath, 'rb')
                            spy_source_file = _ErrorObservingReader(source_file)
                            with source_file:
                                dest_file = zf.open(ZipInfo(entry_name), 'w', force_zip64=True)
                                with dest_file:
                                    shutil.copyfileobj(spy_source_file, dest_file)
                        except OSError as e:
                            if spy_source_file is None or spy_source_file.last_error is not None:
                                # Open/read error from source_file
                                
                                # This source file was read successfully before,
                                # so something strange is going on. Abort.
                                raise
                            else:
                                # Open/write error to dest_file. Abort.
                                raise
                zip_file_ok = True

            keep_pack_file = good_entry_names or retain_empty_pack_file_if_errors
            if keep_pack_file:
                # Ensure data is flushed to stable storage
                os.fsync(tmp_file.fileno())
        
        if keep_pack_file:
            # Move to final location.
            # Create parent directory if needed.
            try:
                replace_and_flush(tmp_filepath, dest_filepath)
            except FileNotFoundError:
                os.makedirs(os.path.dirname(dest_filepath), exist_ok=True)
                replace_and_flush(tmp_filepath, dest_filepath)
        else:
            os.remove(tmp_filepath)
    except:
        # Clean up temp file if operation failed
        if tmp_filepath is not None:
            try:
                os.remove(tmp_filepath)
            except FileNotFoundError:
                pass
        raise

    return good_entry_names


class _ErrorObservingReader(Reader):
    """Wraps a reader, capturing any exceptions it raises."""
    
    def __init__(self, base: Reader) -> None:
        self._base = base
        self.last_error = None  # type: Exception | None
    
    def read(self, size: int = -1, /) -> bytes:
        try:
            if size == -1:
                return self._base.read()
            else:
                return self._base.read(size)
        except Exception as e:
            self.last_error = e
            raise


class _DevNullWriter(Writer):
    """Writer that discards all data written to it."""
    def write(self, data: bytes, /) -> int:
        return len(data)
    
    def __enter__(self) -> Self:
        return self
    
    def __exit__(self, *args) -> None:
        pass


def open_pack_entry(pack_file: str | BinaryIO, entry_name: str) -> 'ZipEntryReader':
    """
    Opens a specific entry from a pack zip file, returning a file-like object.

    The returned file-like object keeps the ZipFile open until the stream is closed.

    Arguments:
    * pack_file -- path or a file-like object for the pack zip file
    * entry_name -- name of the entry to read (e.g., '01a')

    Returns:
    * A file-like object for reading the entry

    Raises:
    * ZipEntryNotFoundError -- if entry is not found in the pack file
    * OSError -- if could not read pack file
    """
    if isinstance(pack_file, str):
        pack_fileobj = open_nonexclusive(pack_file, 'rb')
    else:
        pack_fileobj = pack_file
    try:
        zip_file = ZipFile(pack_fileobj, 'r')
        try:
            try:
                entry_file = zip_file.open(entry_name, 'r')
            except KeyError:
                raise ZipEntryNotFoundError(
                    f'There is no item named {entry_name!r} in the archive'
                ) from None
            return ZipEntryReader(zip_file, entry_file, zip_fileobj=pack_fileobj)
        except:
            zip_file.close()
            raise
    except:
        pack_fileobj.close()
        raise


class ZipEntryNotFoundError(Exception):
    pass


class ZipEntryReader:
    """
    A zip entry file-like object. Keeps its containing ZipFile open.
    """
    def __init__(self,
            zip_file: ZipFile,
            entry_file: IO[bytes],
            zip_fileobj: IO[bytes] | None = None,
            ) -> None:
        self._zip_file = zip_file
        self._entry_file = entry_file
        self._zip_fileobj = zip_fileobj

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
            try:
                self._zip_file.close()
            finally:
                if self._zip_fileobj is not None:
                    self._zip_fileobj.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_) -> None:
        self.close()


def rewrite_pack_without_entry(
        pack_filepath: str,
        entry_name: str,
        tmp_dirpath: str) -> None:
    """
    Rewrites a pack zip file with one entry removed, atomically.
    
    If the pack does not contain the named entry then no action will be taken.

    If the pack becomes empty after removal, the pack file is deleted entirely.

    Arguments:
    * pack_filepath -- path to the pack zip file to rewrite
    * entry_name -- name of the entry to remove (e.g., '01a')
    * tmp_dirpath -- temporary directory to write the new pack file before moving it

    Raises:
    * OSError -- if could not read or write pack file
    """
    # Rewrite the pack file without the deleted entry.
    # - Stream-copy entries directly without buffering to memory
    # - Count entries as we go to determine if pack becomes empty
    tmp_filepath = None
    try:
        with tempfile.NamedTemporaryFile(
                mode='wb',
                suffix='.zip',
                dir=tmp_dirpath,
                delete=False,
                ) as tmp_file:
            tmp_filepath = tmp_file.name

            # Stream-copy each entry (except the deleted one)
            # from source zip to destination zip
            entry_count = 0
            with open_nonexclusive(pack_filepath) as pack_fileobj, \
                    ZipFile(pack_fileobj, 'r') as source_zf, \
                    ZipFile(tmp_file, 'w', compression=ZIP_STORED, allowZip64=True) as dest_zf:
                for name in source_zf.namelist():
                    if name == entry_name:
                        continue
                    with source_zf.open(name, mode='r') as source_entry, \
                            dest_zf.open(name, mode='w') as dest_entry:
                        shutil.copyfileobj(source_entry, dest_entry)
                    entry_count += 1

            # Ensure data is flushed to stable storage
            # (if it will actually be used as the new pack file later)
            if entry_count != 0:
                os.fsync(tmp_file.fileno())

        if entry_count == 0:
            # Delete the old pack file instead of replacing it
            os.remove(tmp_filepath)
            os.remove(pack_filepath)
        else:
            # Move new pack file to final location, replacing old pack file
            replace_and_flush(tmp_filepath, pack_filepath, nonatomic_ok=True)
    except:
        # Clean up temp file if operation failed
        if tmp_filepath is not None:
            try:
                os.remove(tmp_filepath)
            except FileNotFoundError:
                pass
        raise
