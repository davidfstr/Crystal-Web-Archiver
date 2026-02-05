from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from crystal.model import Project
import errno
from http.client import HTTPConnection, HTTPResponse
import sqlite3
import tempfile
from typing import BinaryIO, cast, NoReturn
from unittest.mock import Mock, patch


@contextmanager
def downloads_mocked_to_raise_network_io_error() -> Iterator:
    def raise_connection_reset() -> NoReturn:
        raise OSError('Connection reset')
    def is_connection_reset(e: object) -> bool:
        return (
            isinstance(e, IOError) and
            str(e) == 'Connection reset'
        )
    
    DATA_BEFORE_EOF = b'<html>'
    
    def mock_read() -> Iterable[bytes]:
        yield DATA_BEFORE_EOF
        raise_connection_reset()
    def mock_readinto() -> Iterable[int]:
        yield len(DATA_BEFORE_EOF)
        raise_connection_reset()
    
    mock_response = Mock(spec=HTTPResponse)
    mock_response.version = 10  # HTTP/1.0
    mock_response.status = 200
    mock_response.reason = 'OK'
    mock_response.getheaders = Mock(return_value=[
        ('Content-Type', 'text/html; charset=utf-8')
    ])
    mock_response.read = Mock(side_effect=mock_read())
    mock_response.readinto = Mock(side_effect=mock_readinto())
    mock_response.fileno = Mock(side_effect=OSError)  # no file descriptor
    
    mock_connection = Mock(spec_set=HTTPConnection)
    mock_connection.getresponse = Mock(return_value=mock_response)
    mock_connection.close = Mock(return_value=None)
    with patch(
            # HTTPConnection used by HttpResourceRequest.__call__()
            'crystal.download.HTTPConnection',
            return_value=mock_connection):
        
        # Shrink the copy buffer size in the "length" parameter,
        # because Python 3.12+ assumes that a read that doesn't fill the
        # copy buffer is an EOF, without checking. We want to ensure that
        # at least 2 calls to read() or readinto() are made.
        from crystal.util import xshutil
        super_copyfileobj_readinto = xshutil.copyfileobj_readinto
        def copyfileobj_readinto(src, dst, length=len(DATA_BEFORE_EOF)):
            return super_copyfileobj_readinto(src, dst, length=length)
        with patch(
                # xshutil.copyfileobj_readinto used by ResourceRevision._create_from_stream()
                'crystal.util.xshutil.copyfileobj_readinto',
                copyfileobj_readinto):
            yield is_connection_reset


@contextmanager
def downloads_mocked_to_raise_disk_io_error(
        *, will_raise: Callable[[], None] | None = None,
        ) -> Iterator[Callable[[object], bool]]:
    if will_raise is None:
        will_raise = lambda: None
    
    def raise_io_error() -> NoReturn:
        # Simulate faulty disk
        # NOTE: This is the specific error that macOS raises if you try to flush
        #       to a file on a locally-attached disk that is physically disconnected.
        raise OSError(errno.EIO, 'Input/output error')
    def is_io_error(e: object) -> bool:
        return (
            isinstance(e, OSError) and
            e.errno == errno.EIO
        )
    
    real_NamedTemporaryFile = tempfile.NamedTemporaryFile  # capture
    def FakeNamedTemporaryFile(*args, **kwargs) -> BinaryIO:
        f = real_NamedTemporaryFile(*args, **kwargs)
        if kwargs.get('suffix', '').endswith('.body'):
            def fake_write(b: bytes) -> int:
                will_raise()
                raise_io_error()
            f.write = fake_write  # type: ignore[assignment]
        return cast(BinaryIO, f)
    
    with patch('crystal.model.NamedTemporaryFile', FakeNamedTemporaryFile):
        yield is_io_error


@contextmanager
def database_cursor_mocked_to_raise_database_io_error_on_write(
        project: Project,
        *, should_raise: Callable[[str], bool] | None = None
        ) -> Iterator[Callable[[object], bool]]:
    """
    Mocks database cursor to raise I/O error on write operations.
    
    Arguments:
    * should_raise -- A callable(command: str) -> bool that determines whether to raise an error.
        - If None, errors are raised for all write operations (default).
        - If provided, errors are raised when it returns True for the given SQL command.
    """
    if should_raise is None:
        should_raise = lambda cmd: True
    
    def raise_database_error() -> NoReturn:
        # NOTE: This is the specific error that SQLite raises if you try to query
        #       a database file on a locally-attached disk that is physically disconnected.
        raise sqlite3.OperationalError('disk I/O error')  # SQLITE_IOERR
    def is_database_error(e: object) -> bool:
        return (
            isinstance(e, sqlite3.OperationalError) and
            str(e) == 'disk I/O error'
        )
    
    real_cursor_func = project._db.cursor  # capture
    def mock_cursor():
        real_cursor = real_cursor_func()
        
        def mock_execute(command: str, *args, **kwargs):
            is_write = (
                command.startswith('insert ') or 
                command.startswith('update ') or 
                command.startswith('delete ')
            )
            if is_write and should_raise(command):
                raise_database_error()
            
            return real_cursor.execute(command, *args, **kwargs)
        
        mock_cursor = Mock(wraps=real_cursor)
        mock_cursor.execute = mock_execute
        type(mock_cursor).lastrowid = property(lambda self: real_cursor.lastrowid)
        return mock_cursor
    
    with patch.object(project._db, 'cursor', mock_cursor):
        yield is_database_error
