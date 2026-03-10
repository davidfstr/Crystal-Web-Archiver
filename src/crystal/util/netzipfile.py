"""
Optimized reader for zip file entries accessed via range GETs.

Designed for reading Pack16 .zip file entries from remote storage (e.g. S3)
where minimizing the number of read requests is critical for performance.

Performance:
- Opening the zip (parsing the central directory): 1 read (best/average), 2 reads (worst)
- Reading one entry: 1 read (best/average), 2 reads (worst)
- Total per entry: 2 reads (best/average), 4 reads (worst, with CD not yet cached)
"""

from __future__ import annotations

import bz2
import io
import lzma
import struct
from typing import BinaryIO, Literal, Protocol
import zlib

try:
    import compression.zstd as _zstd  # Python 3.14+
except ImportError:
    _zstd = None  # type: ignore[assignment]


# === Public API ===

class OpenRangeCallable(Protocol):
    def __call__(self, start: int, end: int | None = None) -> BinaryIO:
        """
        Opens a range of bytes from a file for reading.

        If start is negative, opens the last abs(start) bytes.
        Otherwise opens bytes from start to end (inclusive).
        """
        ...


class NetZipFile:
    """
    A zip file reader optimized for remote storage with range GET support.

    Parses the central directory on construction (1 read) and caches it.
    Each subsequent per-entry open() call costs 1 read (best case) or 2 reads (worst case).
    """

    def __init__(self, open_range: OpenRangeCallable) -> None:
        self._open_range = open_range
        self._entries = _read_central_directory(open_range)

    def size(self, entry_name: str) -> int:
        """
        Returns the uncompressed size of the named entry.

        Reads directly from the cached central directory: no I/O needed.

        Raises:
        * KeyError -- if entry_name is not found in the zip file.
        """
        entry = self._entries.get(entry_name)
        if entry is None:
            raise KeyError(entry_name)
        return entry.uncompressed_size

    def open(self, entry_name: str, mode: Literal['r'] = 'r') -> BinaryIO:
        """
        Opens the named entry for reading.

        Handles both stored (uncompressed) and compressed entries.

        Raises:
        * KeyError -- if entry_name is not found in the zip file.
        * ValueError -- if the entry uses an unsupported compression method.
        * RuntimeError -- if the entry uses a compression method whose
            supporting module is not available (e.g. zstandard on Python <3.14).
        """
        entry = self._entries.get(entry_name)
        if entry is None:
            raise KeyError(entry_name)
        return _open_entry_data(self._open_range, entry)


# === Central Directory Parsing ===

# Size of the initial tail read, chosen to comfortably fit the central
# directory of a Pack16 zip (max ~1,394 bytes) plus some headroom.
_TAIL_READ_SIZE = 2048

# ZIP signatures
_SIG_EOCD = b'PK\x05\x06'
_SIG_ZIP64_EOCD = b'PK\x06\x06'
_SIG_ZIP64_LOCATOR = b'PK\x06\x07'
_SIG_CENTRAL_DIR = b'PK\x01\x02'
_SIG_LOCAL_HEADER = b'PK\x03\x04'

# Sentinel value indicating ZIP64 extensions are in use
_ZIP64_SENTINEL_32 = 0xFFFFFFFF

# Struct formats
_FMT_EOCD = '<4sHHHHIIH'  # 22 bytes
_FMT_ZIP64_LOCATOR = '<4sIQI'  # 20 bytes
_FMT_ZIP64_EOCD = '<4sQHHIIQQQQ'  # 56 bytes
_FMT_CD_ENTRY = '<4sHHHHHHIIIHHHHHII'  # 46 bytes (fixed part)


class _CdEntry:
    """A parsed central directory entry."""
    __slots__ = (
        'local_offset', 'compressed_size', 'uncompressed_size',
        'compression_method', 'filename_length',
    )

    def __init__(
        self,
        local_offset: int,
        compressed_size: int,
        uncompressed_size: int,
        compression_method: int,
        filename_length: int,
    ) -> None:
        self.local_offset = local_offset
        self.compressed_size = compressed_size
        self.uncompressed_size = uncompressed_size
        self.compression_method = compression_method
        self.filename_length = filename_length


def _read_central_directory(
    open_range: OpenRangeCallable,
) -> dict[str, _CdEntry]:
    # Read 1: Grab the tail of the file
    tail = open_range(-_TAIL_READ_SIZE).read()

    # Find the EOCD record by scanning backwards for its signature
    eocd_pos = tail.rfind(_SIG_EOCD)
    if eocd_pos < 0:
        raise ValueError('Could not find End of Central Directory record')

    eocd = tail[eocd_pos:eocd_pos + 22]
    (_, _, _, _, _, cd_size, cd_offset, _) = struct.unpack(_FMT_EOCD, eocd)

    # Check for ZIP64 EOCD
    (cd_size, cd_offset) = _try_parse_zip64_eocd(
        tail, eocd_pos, cd_size, cd_offset
    )

    # Determine where the tail buffer starts in the file.
    # The tail was read as the last _TAIL_READ_SIZE bytes (or less if the
    # file is smaller). The EOCD is at the end, so:
    #   file_size = cd_offset + cd_size + (len(tail) - eocd_pos_from_start_of_cd)
    # But it's simpler to compute the tail's file offset from the CD offset:
    #   tail starts at file offset = file_size - len(tail)
    # We can derive file_size from cd_offset + cd_size + trailer_size,
    # where trailer_size = len(tail) - eocd_pos + trailing bytes after EOCD.
    # Instead, check whether the CD is fully contained in our tail buffer.
    # The CD should end right where the post-CD records begin.
    # In the tail buffer, the CD starts at some position and the EOCD
    # (possibly preceded by ZIP64 records) follows.
    #
    # We know the CD is cd_size bytes. We need to find where cd_offset
    # maps to in our tail buffer. The tail covers the last len(tail) bytes
    # of the file, so a file offset F maps to tail index F - (file_size - len(tail)).
    # We can compute file_size = cd_offset + cd_size + (len(tail) - cd_end_in_tail)
    # where cd_end_in_tail is where the CD ends in the tail.
    #
    # Simpler approach: the bytes between cd_offset and the EOCD (or ZIP64
    # records before it) should be exactly cd_size. Find where the CD would
    # start in the tail buffer by working backwards from the known structures.

    # Find the start of post-CD records (ZIP64 EOCD, ZIP64 locator, EOCD)
    # The CD ends right before these records begin.
    cd_end_in_tail = _find_cd_end_in_tail(tail, eocd_pos)

    cd_start_in_tail = cd_end_in_tail - cd_size
    if cd_start_in_tail >= 0:
        # The full CD is in our tail buffer
        cd_bytes = tail[cd_start_in_tail:cd_end_in_tail]
    else:
        # Read 1b (adversarial case): CD doesn't fit in tail, fetch it exactly
        cd_bytes = open_range(cd_offset, cd_offset + cd_size - 1).read()

    return _parse_cd_entries(cd_bytes)


def _try_parse_zip64_eocd(
    tail: bytes, eocd_pos: int, cd_size: int, cd_offset: int,
) -> tuple[int, int]:
    """Check for ZIP64 EOCD and return (cd_size, cd_offset), updated if ZIP64."""
    # The ZIP64 EOCD locator is 20 bytes immediately before the EOCD
    locator_pos = eocd_pos - 20
    if locator_pos < 0:
        return (cd_size, cd_offset)

    locator_data = tail[locator_pos:locator_pos + 20]
    if locator_data[:4] != _SIG_ZIP64_LOCATOR:
        return (cd_size, cd_offset)

    (_, _, _, _) = struct.unpack(_FMT_ZIP64_LOCATOR, locator_data)

    # The ZIP64 EOCD is 56 bytes immediately before the locator
    zip64_eocd_pos = locator_pos - 56
    if zip64_eocd_pos < 0:
        return (cd_size, cd_offset)

    zip64_eocd_data = tail[zip64_eocd_pos:zip64_eocd_pos + 56]
    if zip64_eocd_data[:4] != _SIG_ZIP64_EOCD:
        return (cd_size, cd_offset)

    (_, _, _, _, _, _, _, _, cd_size_64, cd_offset_64) = struct.unpack(
        _FMT_ZIP64_EOCD, zip64_eocd_data
    )

    # Use ZIP64 values if the regular EOCD had sentinel values
    if cd_size == _ZIP64_SENTINEL_32:
        cd_size = cd_size_64
    if cd_offset == _ZIP64_SENTINEL_32:
        cd_offset = cd_offset_64

    return (cd_size, cd_offset)


def _find_cd_end_in_tail(tail: bytes, eocd_pos: int) -> int:
    """
    Find where the central directory ends in the tail buffer.

    The CD is followed by optional ZIP64 records, then the EOCD.
    Returns the tail buffer index where the CD ends.
    """
    # Check for ZIP64 locator before EOCD
    locator_pos = eocd_pos - 20
    if locator_pos >= 0 and tail[locator_pos:locator_pos + 4] == _SIG_ZIP64_LOCATOR:
        # Check for ZIP64 EOCD before locator
        zip64_eocd_pos = locator_pos - 56
        if zip64_eocd_pos >= 0 and tail[zip64_eocd_pos:zip64_eocd_pos + 4] == _SIG_ZIP64_EOCD:
            return zip64_eocd_pos
        return locator_pos
    return eocd_pos


def _parse_cd_entries(cd_bytes: bytes) -> dict[str, _CdEntry]:
    """Parse all central directory entries into a dict keyed by filename."""
    entries: dict[str, _CdEntry] = {}
    offset = 0

    while offset < len(cd_bytes):
        if offset + 46 > len(cd_bytes):
            break

        (sig, _, _, _, compression_method, _, _,
         _, compressed_size, uncompressed_size,
         name_len, extra_len, comment_len, _, _,
         _, local_offset) = struct.unpack_from(_FMT_CD_ENTRY, cd_bytes, offset)

        if sig != _SIG_CENTRAL_DIR:
            raise ValueError(
                f'Bad central directory signature at offset {offset}: {sig!r}'
            )

        name_start = offset + 46
        name = cd_bytes[name_start:name_start + name_len].decode('ascii')

        # If the regular fields have ZIP64 sentinel values, read from the
        # ZIP64 extra field
        extra_start = name_start + name_len
        extra_data = cd_bytes[extra_start:extra_start + extra_len]
        (compressed_size, uncompressed_size, local_offset) = _apply_zip64_extras(
            extra_data, compressed_size, uncompressed_size, local_offset
        )

        entries[name] = _CdEntry(
            local_offset=local_offset,
            compressed_size=compressed_size,
            uncompressed_size=uncompressed_size,
            compression_method=compression_method,
            filename_length=name_len,
        )

        offset += 46 + name_len + extra_len + comment_len

    return entries


def _apply_zip64_extras(
    extra_data: bytes,
    compressed_size: int,
    uncompressed_size: int,
    local_offset: int,
) -> tuple[int, int, int]:
    """
    Parse ZIP64 extended information extra field if present,
    and override sentinel values with the real 64-bit values.

    The ZIP64 extra field (tag 0x0001) contains 8-byte values in order:
    original size, compressed size, local header offset, disk start number.
    Each field is present only if the corresponding regular field is set
    to its sentinel value (0xFFFFFFFF or 0xFFFF).
    """
    needs_zip64 = (
        uncompressed_size == _ZIP64_SENTINEL_32
        or compressed_size == _ZIP64_SENTINEL_32
        or local_offset == _ZIP64_SENTINEL_32
    )
    if not needs_zip64:
        return (compressed_size, uncompressed_size, local_offset)

    # Scan extra fields for the ZIP64 tag (0x0001)
    pos = 0
    while pos + 4 <= len(extra_data):
        (tag, size) = struct.unpack_from('<HH', extra_data, pos)
        if tag == 0x0001:
            # Found ZIP64 extra field
            field_pos = pos + 4
            if uncompressed_size == _ZIP64_SENTINEL_32:
                uncompressed_size = struct.unpack_from('<Q', extra_data, field_pos)[0]
                field_pos += 8
            if compressed_size == _ZIP64_SENTINEL_32:
                compressed_size = struct.unpack_from('<Q', extra_data, field_pos)[0]
                field_pos += 8
            if local_offset == _ZIP64_SENTINEL_32:
                local_offset = struct.unpack_from('<Q', extra_data, field_pos)[0]
            break
        pos += 4 + size

    return (compressed_size, uncompressed_size, local_offset)


# === Entry Data Reading ===

# Generous upper bound for the local file header's extra field.
# If exceeded (adversarial case), an additional read is issued.
_MAX_LOCAL_EXTRA = 64


def _open_entry_data(open_range: OpenRangeCallable, entry: _CdEntry) -> BinaryIO:
    """Open a single zip entry's data for streaming reads."""
    # Read 2: local file header + data in one request
    # Over-read by _MAX_LOCAL_EXTRA bytes to account for the unknown
    # local extra field length
    header_size = 30 + entry.filename_length + _MAX_LOCAL_EXTRA
    total_size = header_size + entry.compressed_size
    stream = open_range(entry.local_offset, entry.local_offset + total_size - 1)

    # Parse local file header to get actual extra field length
    lfh = stream.read(30)
    if len(lfh) < 30:
        raise ValueError('Read too few bytes for local file header')
    sig = lfh[:4]
    if sig != _SIG_LOCAL_HEADER:
        raise ValueError(f'Bad local file header signature: {sig!r}')
    (lfh_name_len, lfh_extra_len) = struct.unpack_from('<HH', lfh, 26)

    if lfh_extra_len > _MAX_LOCAL_EXTRA:
        # Read 2b (adversarial case): local extra field was larger than
        # _MAX_LOCAL_EXTRA, so the stream doesn't contain all the entry data.
        # Discard this stream and fetch exactly the data portion.
        stream.close()
        data_offset = entry.local_offset + 30 + lfh_name_len + lfh_extra_len
        stream = open_range(data_offset, data_offset + entry.compressed_size - 1)
    else:
        # Skip past filename and extra field to reach entry data
        stream.read(lfh_name_len + lfh_extra_len)

    if entry.compression_method == 0:
        return io.BufferedReader(
            _LimitedReader(stream, entry.compressed_size)
        )
    elif entry.compression_method == 8:
        return io.BufferedReader(
            _DeflateReader(
                _LimitedReader(stream, entry.compressed_size)  # type: ignore[arg-type]
            )
        )
    elif entry.compression_method == 12:
        return io.BufferedReader(
            _Bzip2Reader(
                _LimitedReader(stream, entry.compressed_size)  # type: ignore[arg-type]
            )
        )
    elif entry.compression_method == 14:
        return io.BufferedReader(
            _LzmaReader(
                _LimitedReader(stream, entry.compressed_size)  # type: ignore[arg-type]
            )
        )
    elif entry.compression_method == 93:
        if _zstd is None:
            raise RuntimeError(
                'Zstandard compression requires Python 3.14+ (compression.zstd module)'
            )
        return io.BufferedReader(
            _ZstdReader(
                _LimitedReader(stream, entry.compressed_size)  # type: ignore[arg-type]
            )
        )
    else:
        raise ValueError(
            f'Unsupported compression method: {entry.compression_method}'
        )


class _LimitedReader(io.RawIOBase):
    """Wraps a stream and limits the number of bytes that can be read."""

    def __init__(self, stream: BinaryIO, limit: int) -> None:
        self._stream = stream
        self._remaining = limit

    def readable(self) -> bool:
        return True

    def readinto(self, b: bytearray | memoryview) -> int:  # type: ignore[override]
        if self._remaining <= 0:
            return 0
        n = min(len(b), self._remaining)
        data = self._stream.read(n)
        if not data:
            return 0
        actual = len(data)
        b[:actual] = data
        self._remaining -= actual
        return actual


class _DeflateReader(io.RawIOBase):
    # Chunk size for reading compressed data from the underlying stream
    _READ_CHUNK = 65536

    def __init__(self, raw: BinaryIO) -> None:
        self._raw = raw
        # wbits=-15: raw deflate (no zlib header), as used in ZIP
        self._decompressor = zlib.decompressobj(-15)
        self._buf = bytearray()  # decompressed bytes not yet consumed by caller
        self._buf_pos = 0        # read cursor into _buf; advance instead of slicing
        self._done = False       # True once decompressor is exhausted

    def readable(self) -> bool:
        return True

    def readinto(self, b: bytearray | memoryview) -> int:  # type: ignore[override]
        # Trim bytes consumed by the previous call, keeping memory usage bounded.
        # del bytearray[:n] is O(remaining), not O(total).
        if self._buf_pos > 0:
            del self._buf[:self._buf_pos]
            self._buf_pos = 0

        # Fill the internal buffer until we have enough decompressed bytes or
        # reach the end of the compressed stream.
        want = len(b)  # cache
        while len(self._buf) < want and not self._done:
            chunk = self._raw.read(self._READ_CHUNK)
            if chunk:
                # bytearray.extend() is amortized O(1); avoids creating a new bytes object
                self._buf.extend(self._decompressor.decompress(chunk))
            else:
                # No more compressed data; flush any remaining decompressed bytes
                self._buf.extend(self._decompressor.flush())
                self._done = True

        # Copy min(want, len(self._buf)) bytes from the start of self._buf to b.
        # Return the number of bytes copied.
        if (len_buf := len(self._buf)) <= want:
            b[:len_buf] = self._buf
            self._buf_pos = len_buf
            return len_buf
        else:
            # NOTE: Use a memoryview to avoid creating a temporary slice
            b[:] = memoryview(self._buf)[:want]
            self._buf_pos = want
            return want


class _Bzip2Reader(io.RawIOBase):
    # Chunk size for reading compressed data from the underlying stream
    _READ_CHUNK = 65536

    def __init__(self, raw: BinaryIO) -> None:
        self._raw = raw
        self._decompressor = bz2.BZ2Decompressor()
        self._buf = bytearray()  # decompressed bytes not yet consumed by caller
        self._buf_pos = 0        # read cursor into _buf; advance instead of slicing
        self._done = False       # True once decompressor is exhausted

    def readable(self) -> bool:
        return True

    def readinto(self, b: bytearray | memoryview) -> int:  # type: ignore[override]
        # Trim bytes consumed by the previous call, keeping memory usage bounded.
        if self._buf_pos > 0:
            del self._buf[:self._buf_pos]
            self._buf_pos = 0

        # Fill the internal buffer until we have enough decompressed bytes or
        # reach the end of the compressed stream.
        want = len(b)  # cache
        while len(self._buf) < want and not self._done:
            chunk = self._raw.read(self._READ_CHUNK)
            if chunk:
                self._buf.extend(self._decompressor.decompress(chunk))
            else:
                self._done = True

        # Copy min(want, len(self._buf)) bytes from the start of self._buf to b.
        if (len_buf := len(self._buf)) <= want:
            b[:len_buf] = self._buf
            self._buf_pos = len_buf
            return len_buf
        else:
            b[:] = memoryview(self._buf)[:want]
            self._buf_pos = want
            return want


class _LzmaReader(io.RawIOBase):
    # Chunk size for reading compressed data from the underlying stream
    _READ_CHUNK = 65536

    def __init__(self, raw: BinaryIO) -> None:
        self._raw = raw
        self._decompressor = _LzmaZipDecompressor()
        self._buf = bytearray()  # decompressed bytes not yet consumed by caller
        self._buf_pos = 0        # read cursor into _buf; advance instead of slicing
        self._done = False       # True once decompressor is exhausted

    def readable(self) -> bool:
        return True

    def readinto(self, b: bytearray | memoryview) -> int:  # type: ignore[override]
        # Trim bytes consumed by the previous call, keeping memory usage bounded.
        if self._buf_pos > 0:
            del self._buf[:self._buf_pos]
            self._buf_pos = 0

        # Fill the internal buffer until we have enough decompressed bytes or
        # reach the end of the compressed stream.
        want = len(b)  # cache
        while len(self._buf) < want and not self._done:
            chunk = self._raw.read(self._READ_CHUNK)
            if chunk:
                self._buf.extend(self._decompressor.decompress(chunk))
            else:
                self._done = True

        # Copy min(want, len(self._buf)) bytes from the start of self._buf to b.
        if (len_buf := len(self._buf)) <= want:
            b[:len_buf] = self._buf
            self._buf_pos = len_buf
            return len_buf
        else:
            b[:] = memoryview(self._buf)[:want]
            self._buf_pos = want
            return want


class _LzmaZipDecompressor:
    """
    Handles the ZIP LZMA stream format, which prepends a 4-byte header
    (2 bytes version + 2 bytes properties size) and the LZMA properties
    before the raw LZMA compressed data.

    Mirrors the LZMADecompressor class used in Python's own zipfile module.
    """

    def __init__(self) -> None:
        self._decomp: lzma.LZMADecompressor | None = None
        self._unconsumed = b''

    def decompress(self, data: bytes) -> bytes:
        if self._decomp is None:
            self._unconsumed += data
            if len(self._unconsumed) <= 4:
                return b''
            (psize,) = struct.unpack('<H', self._unconsumed[2:4])
            if len(self._unconsumed) <= 4 + psize:
                return b''
            # NOTE: lzma._decode_filter_properties is a private CPython function
            # used here following the same pattern as Python's own zipfile module
            # (see Lib/zipfile/__init__.py LZMADecompressor class).
            self._decomp = lzma.LZMADecompressor(
                lzma.FORMAT_RAW,
                filters=[lzma._decode_filter_properties(  # type: ignore[attr-defined]
                    lzma.FILTER_LZMA1, self._unconsumed[4:4 + psize]
                )],
            )
            data = self._unconsumed[4 + psize:]
            self._unconsumed = b''  # release buffered header bytes
        return self._decomp.decompress(data)


class _ZstdReader(io.RawIOBase):
    # Chunk size for reading compressed data from the underlying stream
    _READ_CHUNK = 65536

    def __init__(self, raw: BinaryIO) -> None:
        self._raw = raw
        assert _zstd is not None
        self._decompressor = _zstd.ZstdDecompressor()
        self._buf = bytearray()  # decompressed bytes not yet consumed by caller
        self._buf_pos = 0        # read cursor into _buf; advance instead of slicing
        self._done = False       # True once decompressor is exhausted

    def readable(self) -> bool:
        return True

    def readinto(self, b: bytearray | memoryview) -> int:  # type: ignore[override]
        # Trim bytes consumed by the previous call, keeping memory usage bounded.
        if self._buf_pos > 0:
            del self._buf[:self._buf_pos]
            self._buf_pos = 0

        # Fill the internal buffer until we have enough decompressed bytes or
        # reach the end of the compressed stream.
        want = len(b)  # cache
        while len(self._buf) < want and not self._done:
            chunk = self._raw.read(self._READ_CHUNK)
            if chunk:
                self._buf.extend(self._decompressor.decompress(chunk))
            else:
                self._done = True

        # Copy min(want, len(self._buf)) bytes from the start of self._buf to b.
        if (len_buf := len(self._buf)) <= want:
            b[:len_buf] = self._buf
            self._buf_pos = len_buf
            return len_buf
        else:
            b[:] = memoryview(self._buf)[:want]
            self._buf_pos = want
            return want
