"""
Pack16 format utilities for bundling revision files into zip archives.

The Pack16 format stores groups of 16 consecutive revisions together in
uncompressed ZIP64 archives to improve storage efficiency on systems with
large minimum object sizes (e.g., AWS S3 Glacier with 128 KB minimum).
"""

from crystal.util.filesystem import rename_and_flush
import os
import tempfile
from zipfile import ZipFile, ZIP_STORED


def create_pack_file(
        revision_files: dict[str, str],
        dest_path: str,
        tmp_dir: str) -> None:
    """
    Creates an uncompressed ZIP64 file from a mapping of entry names to source file paths.

    Arguments:
    * revision_files -- mapping from entry name (e.g., '01a') to source filepath
    * dest_path -- final destination path for the pack file
    * tmp_dir -- temporary directory to write the pack file before moving it

    The pack file is written atomically:
    1. Write to tmp_dir
    2. fsync the file
    3. Move to dest_path using rename_and_flush

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
                dir=tmp_dir,
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
            rename_and_flush(tmp_filepath, dest_path)
        except FileNotFoundError:
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            rename_and_flush(tmp_filepath, dest_path)
    except:
        # Clean up temp file if operation failed
        if tmp_filepath is not None:
            try:
                os.remove(tmp_filepath)
            except FileNotFoundError:
                pass
        raise
