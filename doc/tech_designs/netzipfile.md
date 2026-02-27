# netzipfile — Design Document

## What It Does

`netzipfile` is a read-only zip file library optimized for remote storage where each read is expensive — specifically, storage accessed via HTTP range GETs (e.g. Amazon S3, CloudFront, or any HTTP server supporting `Range` headers).

Standard zip libraries like Python's `zipfile` assume cheap, random-access I/O. They issue many small reads (8+ HTTP requests to open a zip and read one entry — see analysis below). `netzipfile` minimizes read count by batching reads and using speculative over-reads, achieving **2 reads** in the common case to open a zip and extract a single entry.

The module was originally built to serve [Crystal](https://github.com/davidfstr/crystal-web-archiver) Pack16 `.zip` files from AWS Lambda + S3, but the design is not inherently tied to S3 or Lambda.

## How It Works

### Architecture

```
┌───────────────┐      ReadRangeCallable      ┌───────────────────┐
│  NetZipFile   │ ──────────────────────────▶ │  Storage backend  │
│               │    (start, end) → bytes     │  (S3, HTTP, file, │
│  • CD cache   │                             │   memory, ...)    │
│  • read_entry │ ◀────────────────────────── │                   │
└───────────────┘         bytes               └───────────────────┘
```

`NetZipFile` is initialized with a `ReadRangeCallable` — any callable that can fetch a byte range from the zip file. This abstraction decouples zip parsing from the transport layer. A `ReadRangeCallable` for S3 translates to `GetObject` with a `Range` header; for a local file it translates to `seek` + `read`; for an in-memory buffer it's just slicing.

### Opening: Central Directory Parsing (1 read)

On construction, `NetZipFile` reads and caches the **central directory** (CD), which is the zip file's table of contents stored at the end of the file.

**Read 1:** Fetch the last 2,048 bytes of the file in a single range GET.

The tail of a zip file contains, in order:
1. **Central directory entries** — one per file, with metadata (name, sizes, compression method, local header offset)
2. **ZIP64 End of Central Directory record** (56 bytes) — present only in ZIP64 zips
3. **ZIP64 End of Central Directory Locator** (20 bytes) — present only in ZIP64 zips
4. **End of Central Directory record** (22 bytes) — always present

The parser works backwards from the end of the buffer:
1. Scan backwards for the EOCD signature (`PK\x05\x06`)
2. Parse the EOCD to get the CD's offset and size
3. Check for ZIP64 records immediately before the EOCD; if present, use the 64-bit CD offset and size instead
4. Verify the full CD is contained within the 2,048-byte buffer (it almost always is)
5. Parse all CD entries into an in-memory dict keyed by filename

If the CD doesn't fit in the initial buffer (see "Adversarial Fallback" below), a second read fetches the exact CD byte range. This is Read 1b.

### Reading an Entry (1 read)

Each `read_entry()` call looks up the entry in the cached CD, then fetches the entry's data.

**Read 2:** Fetch `[local_header_offset, local_header_offset + 30 + filename_length + 64 + compressed_size)` — the local file header and entry data in a single range GET.

The **64 extra bytes** are a speculative over-read to cover the local file header's extra field, whose length is not known until the local header is parsed. The local header is parsed from the beginning of the returned buffer to find the actual extra field length, and the entry data is sliced from the correct offset.

If the extra field exceeds 64 bytes (see "Adversarial Fallback" below), a follow-up read fetches the missing tail. This is Read 2b.

For compressed entries, the raw data is decompressed before returning.

### Adversarial Fallback

The 2-read design makes assumptions that hold for typical zip files. When these assumptions are violated — by zip files manipulated with arbitrary tools — the parser degrades gracefully:

| Assumption | Violation | Cost |
|---|---|---|
| CD + trailer records fit in 2,048 bytes | Large EOCD comment (> ~2 KB) or large extra fields on CD entries | +1 read (exact CD fetch) |
| Local header extra field ≤ 64 bytes | Tool adds large extra fields (Unicode paths, timestamps, etc.) | +1 read (missing data tail) |

**Worst case: 4 reads** (Read 1 + Read 1b + Read 2 + Read 2b). Both fallbacks are independent, so both can occur in the same request.

### Read Count Summary

| Operation | Best/average | Worst |
|---|---|---|
| Open zip (parse CD) | 1 | 2 |
| Read one entry | 1 | 2 |
| Open + first entry | 2 | 4 |
| Each subsequent entry | 1 | 2 |
| Open + all 16 Pack16 entries | 17 | 34 |

## Relationship to Python's `zipfile`

The implementation is inspired by CPython's `zipfile` module, and `netzipfile` follows several of its conventions:

- **`KeyError` for missing entries.** Both `zipfile.ZipFile.getinfo()` and `NetZipFile.read_entry()` raise `KeyError` when an entry name is not found. This makes `NetZipFile` a familiar interface for Python developers.
- **Central directory structure parsing.** The EOCD, ZIP64 EOCD, and CD entry struct formats follow the same ZIP specification that `zipfile` implements.
- **ZIP64 extra field parsing.** The logic for detecting sentinel values (`0xFFFFFFFF`) in regular fields and reading real values from the ZIP64 extra field (tag `0x0001`) follows the same field ordering as `zipfile`.

The key difference is the I/O strategy. `zipfile` issues many small, sequential reads through a seekable file object (8+ reads to open and extract one entry). `netzipfile` batches these into 1-2 large reads per operation by reading the entire CD and entire entry in single requests.

## Pack16-Specific Assumptions

The current implementation was built for Crystal's Pack16 format. These assumptions affect default buffer sizes but **do not affect correctness** — the parser falls back gracefully when they don't hold:

- **≤ 16 entries per zip file.** The 2,048-byte tail read size (`_TAIL_READ_SIZE`) is based on a worst-case calculation: 16 entries × 81 bytes/entry (46-byte CD header + 3-byte filename + 32-byte ZIP64 extra) + 98 bytes of trailer records = 1,394 bytes, rounded up. Zips with more entries or longer filenames may exceed this buffer.
- **3-character ASCII filenames** (`000`–`fff`). Filenames are decoded as ASCII. Non-ASCII filenames are not handled.
- **ZIP64 extensions at the file and entry level.** Crystal writes Pack16 zips with `force_zip64=True`, so the parser is designed to handle ZIP64 as the common case, not a rare edge case.
- **Uncompressed (STORED) entries.** Pack16 entries are stored without compression. Deflate is supported for robustness (in case a tool recompresses entries), but this is not the expected path.
- **Local header extra field ≤ 64 bytes.** The over-read margin (`_MAX_LOCAL_EXTRA = 64`) is generous for typical ZIP64 local headers (~20 bytes). Larger extra fields trigger a fallback read.

## Known Limitations

### Compression formats

Only two compression methods are supported:
- **Method 0 (STORED)** — uncompressed, returned as-is
- **Method 8 (DEFLATE)** — decompressed via `zlib.decompress(data, -15)`

Other compression methods defined by the ZIP specification — including bzip2 (method 12), LZMA (method 14), and zstd (method 93) — are **not** supported. Attempting to read an entry with an unsupported compression method raises `ValueError`.

### Write support

`netzipfile` is read-only. It cannot create or modify zip files. Use Python's `zipfile` module for writing.

### Multi-disk archives

Only single-disk (single-file) zip archives are supported. The multi-disk fields in the EOCD and ZIP64 EOCD are parsed but ignored.

### Filename encoding

Filenames are decoded as ASCII. Zip files with UTF-8 filenames (indicated by the general purpose bit flag, bit 11) are not handled — the UTF-8 flag is not checked, and non-ASCII bytes will raise `UnicodeDecodeError`.

### EOCD comment scanning

The EOCD record is located by scanning backwards for its signature (`PK\x05\x06`). In theory, this signature could appear in file data or an EOCD comment, producing a false match. Python's `zipfile` has the same limitation and notes that it is "unrecoverable" for certain pathological archives. In practice, this is not an issue for Pack16 files.

### No entry metadata API

There is no way to list entries, inspect compression methods, or access other metadata without reading entry data. If needed, the internal `_entries` dict could be exposed through a public API in a future version.

### _TAIL_READ_SIZE is not adaptive

The initial tail read is always 2,048 bytes. For zip files with many entries, long filenames, or large extra fields, this may not capture the full CD, triggering a fallback read. A future version could accept a configurable tail size hint, or use the file size (from an initial HEAD request or similar) to choose a better default.

## Future Directions

If extracted to a standalone PyPI package, consider:

- **Configurable tail read size** — allow callers to tune `_TAIL_READ_SIZE` based on their knowledge of the zip file structure
- **UTF-8 filename support** — check the general purpose bit flag and decode accordingly
- **Entry listing API** — expose `entries()` or `namelist()` for discovering available entries
- **Additional compression methods** — bzip2, LZMA, zstd as optional dependencies
- **Built-in `ReadRangeCallable` implementations** — for common backends (local file, `io.BytesIO`, `httpx`, `boto3` S3) so users don't have to write their own
- **Async support** — an async variant of `ReadRangeCallable` for use with `aiohttp` or `aioboto3`
