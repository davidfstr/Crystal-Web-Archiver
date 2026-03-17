import apsw
from crystal.filesystem import S3Filesystem


class S3VFS(apsw.VFS):
    """Read-only SQLite VFS backed by S3 range requests."""
    NAME = 'crystal-s3'

    def __init__(self, fs: S3Filesystem, db_s3_path: str) -> None:
        self._fs = fs
        self._db_s3_path = db_s3_path
        super().__init__(name=self.NAME, base='')  # no base VFS

    def xOpen(self, name, flags):
        # flags[1] is output flags - set to SQLITE_OPEN_READONLY
        flags[1] = apsw.SQLITE_OPEN_READONLY
        # Ignore `name` (a placeholder URI); use the stored S3 path instead.
        # S3 URLs cannot be embedded in a file: URI, so we store the path on
        # the VFS and pass a placeholder URI with ?immutable=1 to the connection.
        return S3VFSFile(self._db_s3_path, self._fs)

    def xAccess(self, pathname, flags):
        return False  # journal/WAL files don't exist

    def xFullPathname(self, name):
        return name  # S3 URLs are already absolute


class S3VFSFile(apsw.VFSFile):
    """Serves SQLite page reads from S3 via HTTP range requests."""
    
    # Whether to print all I/O operations
    VERBOSE = False

    def __init__(self, path: str, fs: S3Filesystem) -> None:
        self._path = path  # not calling super().__init__ - no base file
        self._fs = fs
        # NOTE: xFileSize is always called once shortly after the database is
        #       opened, so it is efficent & simple to pre-cache it early
        self._size = fs.getsize(path)

    def xRead(self, amount: int, offset: int) -> bytes:
        if self.VERBOSE:
            print(f'S3VFSFile: xRead: {offset}-{offset + amount - 1}')
        
        with self._fs.open(
                self._path, 'rb', start=offset, end=offset + amount - 1) as f:
            data = f.read()
        if len(data) < amount:
            # SQLite requires exact amount; pad with zeros if short read
            data = data + b'\x00' * (amount - len(data))
        return data

    def xFileSize(self) -> int:
        if self.VERBOSE:
            print(f'S3VFSFile: xFileSize')
        
        return self._size

    def xClose(self) -> None:
        pass  # nothing to clean up

    def xLock(self, level: int) -> None:
        pass  # read-only, no locking needed

    def xUnlock(self, level: int) -> None:
        pass

    def xCheckReservedLock(self) -> bool:
        return False

    def xSectorSize(self) -> int:
        return 4096

    def xDeviceCharacteristics(self) -> int:
        return 0  # no special characteristics

    def xFileControl(self, op: int, ptr: int) -> bool:
        return False  # not handled
