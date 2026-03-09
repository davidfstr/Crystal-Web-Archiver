"""Unit tests for netzipfile module."""

import sys
from typing import BinaryIO

from crystal.util import netzipfile
from crystal.util.netzipfile import NetZipFile, OpenRangeCallable
import io
import pytest
from unittest.mock import patch
import zipfile


# === Tests: open + read ===

def test_can_read_entry_given_zip64_stored_zip() -> None:
    entries = {'000': b'Alpha', '001': b'Beta', '00f': b'Pi'}
    data = _create_zip64_stored_zip(entries)
    nzf = NetZipFile(_create_open_range_func(data))

    assert nzf.open('000').read() == b'Alpha'
    assert nzf.open('001').read() == b'Beta'
    assert nzf.open('00f').read() == b'Pi'


def test_can_read_entry_given_non_zip64_stored_zip() -> None:
    entries = {'abc': b'hello world', 'def': b'goodbye'}
    data = _create_non_zip64_stored_zip(entries)
    nzf = NetZipFile(_create_open_range_func(data))

    assert nzf.open('abc').read() == b'hello world'
    assert nzf.open('def').read() == b'goodbye'


def test_can_read_entry_given_deflate_compressed_zip() -> None:
    content = b'The quick brown fox jumps over the lazy dog' * 100
    entries = {'compressed.txt': content}
    data = _create_deflate_zip(entries)
    nzf = NetZipFile(_create_open_range_func(data))

    assert nzf.open('compressed.txt').read() == content


def test_can_read_entry_given_bzip2_compressed_zip() -> None:
    content = b'The quick brown fox jumps over the lazy dog' * 100
    entries = {'compressed.txt': content}
    data = _create_bzip2_zip(entries)
    nzf = NetZipFile(_create_open_range_func(data))

    assert nzf.open('compressed.txt').read() == content


def test_can_read_entry_given_lzma_compressed_zip() -> None:
    content = b'The quick brown fox jumps over the lazy dog' * 100
    entries = {'compressed.txt': content}
    data = _create_lzma_zip(entries)
    nzf = NetZipFile(_create_open_range_func(data))

    assert nzf.open('compressed.txt').read() == content


@pytest.mark.skipif(
    sys.version_info < (3, 14),
    reason='compression.zstd is only available in Python 3.14+',
)
def test_can_read_entry_given_zstd_compressed_zip() -> None:
    content = b'The quick brown fox jumps over the lazy dog' * 100
    entries = {'compressed.txt': content}
    data = _create_zstd_zip(entries)
    nzf = NetZipFile(_create_open_range_func(data))

    assert nzf.open('compressed.txt').read() == content


def test_raises_key_error_when_try_read_missing_entry() -> None:
    entries = {'000': b'Alpha'}
    data = _create_zip64_stored_zip(entries)
    nzf = NetZipFile(_create_open_range_func(data))

    with pytest.raises(KeyError):
        nzf.open('nonexistent')


# === Tests: open + read: Efficiency ===

def test_given_average_case_zip_file_when_open_and_read_entry_then_2_reads_required() -> None:
    entries = {'000': b'Alpha', '001': b'Beta'}
    data = _create_zip64_stored_zip(entries)
    (open_range, call_count) = _create_counting_open_range_func(data)

    nzf = NetZipFile(open_range)
    assert call_count[0] == 1, 'Opening should cost 1 read (CD tail)'

    nzf.open('000').read()
    assert call_count[0] == 2, 'First entry read should cost 1 additional read'


def test_given_worst_case_zip_file_when_open_and_read_entry_then_4_reads_required() -> None:
    entries = {'000': b'Alpha'}
    data = _create_zip64_stored_zip(entries)
    (open_range, call_count) = _create_counting_open_range_func(data)

    with (
        # Force CD to not fit in tail buffer (triggers Read 1b).
        # Value must be large enough to contain the EOCD (22 bytes)
        # but small enough that the CD (49 bytes) doesn't fit
        patch.object(netzipfile, '_TAIL_READ_SIZE', 30),
        # Force local extra field overflow (triggers Read 2b)
        patch.object(netzipfile, '_MAX_LOCAL_EXTRA', 0),
    ):
        nzf = NetZipFile(open_range)
        assert call_count[0] == 2, \
            f'Opening should cost 2 reads (tail + exact CD), got {call_count[0]}'

        result = nzf.open('000').read()
        assert call_count[0] == 4, \
            f'Total should be 4 reads (2 open + 2 entry), got {call_count[0]}'
        assert result == b'Alpha'


def test_given_average_case_zip_file_already_open_when_read_entry_then_1_read_required() -> None:
    """
    Tests that given an already-open NetZipFile, when an entry is read,
    it requires 1 read call in the average/best case.
    """
    entries = {'000': b'Alpha', '001': b'Beta'}
    data = _create_zip64_stored_zip(entries)
    (open_range, call_count) = _create_counting_open_range_func(data)

    nzf = NetZipFile(open_range)
    nzf.open('000').read()
    count_after_first = call_count[0]

    nzf.open('001').read()
    assert call_count[0] == count_after_first + 1, \
        'Second entry should cost only 1 read (CD already cached)'


def test_given_worst_case_zip_file_already_open_when_read_entry_then_2_reads_required() -> None:
    entries = {'000': b'Alpha', '001': b'Beta'}
    data = _create_zip64_stored_zip(entries)
    (open_range, call_count) = _create_counting_open_range_func(data)

    # Open with normal settings (1 read for CD)
    nzf = NetZipFile(open_range)
    # Read first entry with normal settings (1 read)
    nzf.open('000').read()
    count_after_first = call_count[0]

    # Force local extra field overflow (triggers Read 2b)
    with patch.object(netzipfile, '_MAX_LOCAL_EXTRA', 0):
        result = nzf.open('001').read()
        assert call_count[0] == count_after_first + 2, \
            f'Worst-case entry read should cost 2 reads, got {call_count[0] - count_after_first}'
        assert result == b'Beta'


def test_can_read_all_entries_from_an_average_pack16_zip_file() -> None:
    # NOTE: Simulate a full Pack16 zip with 16 entries
    pack_data = [
        'Alpha', 'Beta', 'Gamma', 'Delta',
        'Epsilon', 'Zeta', 'Eta', 'Theta',
        'Iota', 'Kappa', 'Lambda', 'Mu',
        'Nu', 'Xi', 'Omicron', 'Pi',
    ]
    entries = {f'00{i:x}': data.encode() for (i, data) in enumerate(pack_data)}
    data = _create_zip64_stored_zip(entries)
    nzf = NetZipFile(_create_open_range_func(data))

    for (i, expected) in enumerate(pack_data):
        name = f'00{i:x}'
        assert nzf.open(name).read() == expected.encode()


def test_given_average_case_pack16_zip_file_when_open_and_read_all_entries_then_17_reads_required() -> None:
    entries = {f'00{i:x}': f'data{i}'.encode() for i in range(16)}
    data = _create_zip64_stored_zip(entries)
    (open_range, call_count) = _create_counting_open_range_func(data)

    nzf = NetZipFile(open_range)
    for i in range(16):
        nzf.open(f'00{i:x}')

    # NOTE: Opening + 16 entries = 1 + 16 = 17 reads
    assert call_count[0] == 17, \
        f'Expected 17 reads (1 CD + 16 entries), got {call_count[0]}'


# === Tests: size ===

def test_can_size_entry_given_zip64_stored_zip() -> None:
    entries = {'000': b'Alpha', '001': b'Beta', '00f': b'Pi'}
    data = _create_zip64_stored_zip(entries)
    (open_range, call_count) = _create_counting_open_range_func(data)

    nzf = NetZipFile(open_range)
    assert call_count[0] == 1, 'Opening should cost 1 read (CD tail)'

    assert nzf.size('000') == len(b'Alpha')
    assert nzf.size('001') == len(b'Beta')
    assert nzf.size('00f') == len(b'Pi')
    assert call_count[0] == 1, 'size() should require no additional reads'


def test_raises_key_error_when_try_size_missing_entry() -> None:
    entries = {'000': b'Alpha'}
    data = _create_zip64_stored_zip(entries)
    nzf = NetZipFile(_create_open_range_func(data))

    with pytest.raises(KeyError):
        nzf.size('nonexistent')


# === Utility ===

def _create_zip64_stored_zip(entries: dict[str, bytes]) -> bytes:
    """Build a ZIP64 uncompressed zip file in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for (name, data) in entries.items():
            zinfo = zipfile.ZipInfo(name)
            zinfo.compress_type = zipfile.ZIP_STORED
            with zf.open(zinfo, 'w', force_zip64=True) as entry:
                entry.write(data)
    return buf.getvalue()


def _create_non_zip64_stored_zip(entries: dict[str, bytes]) -> bytes:
    """Build a standard (non-ZIP64) uncompressed zip file in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as zf:
        for (name, data) in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _create_deflate_zip(entries: dict[str, bytes]) -> bytes:
    """Build a deflate-compressed zip file in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=False) as zf:
        for (name, data) in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _create_bzip2_zip(entries: dict[str, bytes]) -> bytes:
    """Build a bzip2-compressed zip file in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_BZIP2, allowZip64=False) as zf:
        for (name, data) in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _create_lzma_zip(entries: dict[str, bytes]) -> bytes:
    """Build an LZMA-compressed zip file in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_LZMA, allowZip64=False) as zf:
        for (name, data) in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _create_zstd_zip(entries: dict[str, bytes]) -> bytes:
    """Build a zstandard-compressed zip file in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_ZSTANDARD, allowZip64=False) as zf:
        for (name, data) in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _create_open_range_func(data: bytes) -> OpenRangeCallable:
    """
    Create an OpenRangeCallable that reads from an in-memory bytes buffer.

    Supports negative start (last N bytes) and inclusive end.
    """
    def open_range(start: int, end: int | None = None) -> BinaryIO:
        if start < 0:
            return io.BytesIO(data[start:])
        assert end is not None
        return io.BytesIO(data[start:end + 1])
    return open_range


def _create_counting_open_range_func(data: bytes):
    """
    Like _create_open_range_func but also counts calls.

    Returns (open_range, call_count) where call_count is a list
    with a single int element (mutable counter).
    """
    call_count = [0]
    inner = _create_open_range_func(data)
    def open_range(start: int, end: int | None = None) -> BinaryIO:
        call_count[0] += 1
        return inner(start, end)
    return (open_range, call_count)
