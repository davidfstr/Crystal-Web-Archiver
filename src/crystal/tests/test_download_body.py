"""Tests for DownloadResourceBodyTask"""

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from crystal import resources
from crystal.model import (
    Project, ProjectHasTooManyRevisionsError, Resource, ResourceRevision,
)
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import served_project
from crystal.tests.util.wait import DEFAULT_WAIT_PERIOD
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.db import DatabaseCursor
import errno
from http.client import HTTPConnection, HTTPResponse
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import sqlite3
import tempfile
import threading
from typing import BinaryIO, cast, NoReturn, Self
from unittest import skip
from unittest.mock import ANY, Mock, patch

# ------------------------------------------------------------------------------
# Tests: Success Cases

async def test_download_does_save_resource_metadata_and_content_accurately() -> None:
    HEADERS = [
        ['Content-Type', 'application/zip'],
        ['Server', 'TestServer/1.0'],
        ['Date', 'Wed, 16 Aug 2023 00:00:00 GMT'],  # arbitrary
    ]
    
    with resources.open_binary('testdata_xkcd.crystalproj.zip') as content_file:
        content_bytes = content_file.read()
    assert len(content_bytes) > 1000  # ensure is a reasonably sized file
    
    with _file_served(HEADERS, content_bytes) as server_port:
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, f'http://localhost:{server_port}/')
            revision_future = r.download_body()
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            downloaded_revision = revision_future.result()  # type: ResourceRevision
            loaded_revision = r.default_revision()
            assert loaded_revision is not None
            
            for revision in [downloaded_revision, loaded_revision]:
                # Ensure no error is reported
                assert None == revision.error
                
                # Ensure metadata is correct
                EXPECTED_METADATA = {
                    'http_version': 10,  # HTTP/1.0
                    'status_code': 200,
                    'reason_phrase': 'OK',
                    'headers': HEADERS,
                }
                assert EXPECTED_METADATA == revision.metadata
                
                # Ensure content is correct
                with revision.open() as saved_content:
                    saved_content_bytes = saved_content.read()
                assert content_bytes == saved_content_bytes


async def test_download_does_autopopulate_date_header_if_not_received_from_origin() -> None:
    HEADERS = [
        ['Content-Type', 'application/zip'],
        ['Server', 'TestServer/1.0'],
        # (No 'Date' header)
    ]
    EXPECTED_HEADERS_SAVED = [
        ['Content-Type', 'application/zip'],
        ['Server', 'TestServer/1.0'],
        ['Date', ANY],
    ]
    
    with resources.open_binary('testdata_xkcd.crystalproj.zip') as content_file:
        content_bytes = content_file.read()
    
    with _file_served(HEADERS, content_bytes) as server_port:
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, f'http://localhost:{server_port}/')
            revision_future = r.download_body()
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            downloaded_revision = revision_future.result()  # type: ResourceRevision
            loaded_revision = r.default_revision()
            assert loaded_revision is not None
            
            for revision in [downloaded_revision, loaded_revision]:
                EXPECTED_METADATA = {
                    'http_version': 10,  # HTTP/1.0
                    'status_code': 200,
                    'reason_phrase': 'OK',
                    'headers': EXPECTED_HEADERS_SAVED,
                }
                assert EXPECTED_METADATA == revision.metadata
                
                assert None != revision.date, \
                    'Date header has invalid value'


@contextmanager
def _file_served(headers: list[list[str]], content_bytes: bytes) -> Iterator[int]:
    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # override
            self.send_response_only(200)
            for (k, v) in headers:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(content_bytes)
    
    # Start an HTTP server that serves a test file for any GET request
    with HTTPServer(('', 0), RequestHandler) as server:
        (_, server_port) = server.server_address
        
        def do_serve_forever() -> None:
            try:
                server.serve_forever()
            except OSError as e:
                # [WinError 10038] An operation was attempted on something that is not a socket
                if getattr(e, 'winerror', None) == 10038:
                    # Already called server_close(). Ignore error.
                    pass
                else:
                    raise
        server_thread = threading.Thread(target=do_serve_forever, daemon=True)
        server_thread.start()
        try:
            yield server_port
        finally:
            server.server_close()


# ------------------------------------------------------------------------------
# Tests: Error Cases

async def test_when_no_errors_then_database_row_and_body_file_is_created_and_returns_normal_revision() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            r = Resource(project, home_url)
            revision_future = r.download_body()
            while not revision_future.done():
                await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            # Ensure no error is reported
            revision = revision_future.result()  # type: ResourceRevision
            assert None == revision.error
            
            # Ensure database and filesystem is in expected state
            assert 1 == project._revision_count()
            assert True == os.path.exists(os.path.join(
                project.path, Project._REVISIONS_DIRNAME,
                '000', '000', '000', '000', f'{revision._id:03x}'))
            assert [] == os.listdir(os.path.join(
                project.path, Project._TEMPORARY_DIRNAME))


async def test_when_network_io_error_then_tries_to_delete_partial_body_file_but_leave_database_row_and_returns_error_revision() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with _downloads_mocked_to_raise_network_io_error() as is_connection_reset:
                r = Resource(project, home_url)
                revision_future = r.download_body()
                while not revision_future.done():
                    await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            # Ensure an I/O error is reported as an error revision
            revision = revision_future.result()  # type: ResourceRevision
            assert None != revision.error
            assert is_connection_reset(revision.error)
            
            # Ensure database and filesystem is in expected state
            assert 1 == project._revision_count()
            assert False == os.path.exists(revision._body_filepath)
            assert [] == os.listdir(os.path.join(
                project.path, Project._TEMPORARY_DIRNAME))


async def test_when_database_error_then_tries_to_delete_partial_body_file_and_raises_database_error() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with _database_cursor_mocked_to_raise_database_io_error_on_write(project) as is_database_error:
                r = Resource(project, home_url)
                revision_future = r.download_body()
                while not revision_future.done():
                    await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            # Ensure a database error is reported as a raised exception
            try:
                revision = revision_future.result()  # type: ResourceRevision
            except Exception as e:
                assert is_database_error(e)
            else:
                assert False, 'Expected database error'
            
            # Ensure database and filesystem is in expected state
            assert 0 == project._revision_count()
            assert [] == os.listdir(os.path.join(
                project.path, Project._REVISIONS_DIRNAME))
            assert [] == os.listdir(os.path.join(
                project.path, Project._TEMPORARY_DIRNAME))


async def test_when_network_io_error_and_database_error_then_tries_to_delete_partial_body_file_and_raises_database_error() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with _downloads_mocked_to_raise_network_io_error() as is_connection_reset:
                with _database_cursor_mocked_to_raise_database_io_error_on_write(project) as is_database_error:
                    r = Resource(project, home_url)
                    revision_future = r.download_body()
                    while not revision_future.done():
                        await bg_sleep(DEFAULT_WAIT_PERIOD)
                
            # Ensure a database error is reported as a raised exception
            # (rather than reporting the I/O error as an error revision)
            try:
                revision = revision_future.result()  # type: ResourceRevision
            except Exception as e:
                assert is_database_error(e)
            else:
                assert False, 'Expected database error'
            
            # Ensure database and filesystem is in expected state
            assert 0 == project._revision_count()
            assert [] == os.listdir(os.path.join(
                project.path, Project._REVISIONS_DIRNAME))
            assert [] == os.listdir(os.path.join(
                project.path, Project._TEMPORARY_DIRNAME))


async def test_when_open_project_given_partial_body_files_exist_then_deletes_all_partial_body_files() -> None:
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        # Create empty project
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
            pass
        assert [] == os.listdir(os.path.join(
            project_dirpath, Project._TEMPORARY_DIRNAME))
        
        # Insert a partial body file manually
        with open(os.path.join(project_dirpath, Project._TEMPORARY_DIRNAME, '1.body'), 'wb') as f:
            pass
        assert [] != os.listdir(os.path.join(
            project_dirpath, Project._TEMPORARY_DIRNAME))
        
        # Reopen project
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            # Ensure partial body file is deleted
            assert [] == os.listdir(os.path.join(
                project_dirpath, Project._TEMPORARY_DIRNAME))


# ------------------------------------------------------------------------------
# Tests: Specific Error Cases

@skip('covered by: test_when_network_io_error_then_tries_to_delete_partial_body_file_but_leave_database_row_and_returns_error_revision')
async def test_given_downloading_revision_when_reading_from_network_raises_io_error_then_returns_error_revision() -> None:
    pass


async def test_given_downloading_revision_when_writing_to_disk_raises_io_error_then_returns_error_revision() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with _downloads_mocked_to_raise_disk_io_error() as is_io_error:
                r = Resource(project, home_url)
                revision_future = r.download_body()
                while not revision_future.done():
                    await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            # Ensure an I/O error is reported as an error revision
            revision = revision_future.result()  # type: ResourceRevision
            assert None != revision.error
            assert is_io_error(revision.error)
            
            # Ensure database and filesystem is in expected state
            assert 1 == project._revision_count()
            assert False == os.path.exists(revision._body_filepath)
            assert [] == os.listdir(os.path.join(
                project.path, Project._TEMPORARY_DIRNAME))


async def test_given_downloading_revision_when_writing_to_disk_raises_io_error_and_writing_to_database_raises_io_error_then_raises_database_error() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with _downloads_mocked_to_raise_disk_io_error() as is_io_error:
                with _database_cursor_mocked_to_raise_database_io_error_on_write(project) as is_database_error:
                    r = Resource(project, home_url)
                    revision_future = r.download_body()
                    while not revision_future.done():
                        await bg_sleep(DEFAULT_WAIT_PERIOD)
            
            # Ensure a database error is reported as a raised exception
            try:
                revision = revision_future.result()  # type: ResourceRevision
            except Exception as e:
                assert is_database_error(e)
            else:
                assert False, 'Expected database error'
            
            # Ensure database and filesystem is in expected state
            assert 0 == project._revision_count()
            assert [] == os.listdir(os.path.join(
                project.path, Project._REVISIONS_DIRNAME))
            assert [] == os.listdir(os.path.join(
                project.path, Project._TEMPORARY_DIRNAME))


# NOTE: This error scenario is expected to never happen in practice,
#       so there's limited value in optimizing handling for it.
# TODO: Consider alter behavior to still return an error revision,
#       but NOT persist the error revision to disk.
# TODO: Also report the I/O error to the UI in some fashion rather
#       than silently dropping it.
async def test_given_project_has_revision_with_maximum_id_when_download_revision_then_raises_error_and_error_revision_not_created() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
    
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            old_revision_count = project._revision_count()  # capture
            
            resource = Resource(project, home_url)
            
            with _database_cursor_mocked_to_create_revision_with_id(Project._MAX_REVISION_ID + 1, project):
                download_result = resource.download_body()
                while not download_result.done():
                    await bg_sleep(DEFAULT_WAIT_PERIOD)
                try:
                    download_result.result()
                except ProjectHasTooManyRevisionsError:
                    pass
                else:
                    raise AssertionError(
                        'Expected ProjectHasTooManyRevisionsError to be raised')
            
            new_revision_count = project._revision_count()
            assert old_revision_count == new_revision_count


# ------------------------------------------------------------------------------
# Utility

@contextmanager
def _downloads_mocked_to_raise_network_io_error() -> Iterator:
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
def _downloads_mocked_to_raise_disk_io_error() -> Iterator[Callable[[object], bool]]:
    def fake_write(b: bytes) -> None:
        # Simulate faulty disk
        raise OSError(errno.EIO, 'Input/output error')
    def is_io_error(e: object) -> bool:
        return (
            isinstance(e, OSError) and
            e.errno == errno.EIO
        )
    
    def FakeNamedTemporaryFile(*args, **kwargs) -> BinaryIO:
        f = tempfile.NamedTemporaryFile(*args, **kwargs)
        if kwargs.get('suffix', '').endswith('.body'):
            f.write = fake_write  # type: ignore[assignment]
        return cast(BinaryIO, f)
    
    with patch('crystal.model.NamedTemporaryFile', FakeNamedTemporaryFile):
        yield is_io_error


@contextmanager
def _database_cursor_mocked_to_raise_database_io_error_on_write(
        project: Project
        ) -> Iterator[Callable[[object], bool]]:
    def raise_database_error() -> NoReturn:
        raise sqlite3.OperationalError('database is locked')
    def is_database_error(e: object) -> bool:
        return (
            isinstance(e, sqlite3.OperationalError) and
            str(e) == 'database is locked'
        )
    
    real_cursor_func = project._db.cursor  # capture
    def mock_cursor():
        real_cursor = real_cursor_func()
        
        def mock_execute(command: str, *args, **kwargs):
            if command.startswith('insert into resource_revision '):
                raise_database_error()
            else:
                return real_cursor.execute(command, *args, **kwargs)
        
        mock_cursor = Mock(wraps=real_cursor)
        mock_cursor.execute = mock_execute
        type(mock_cursor).lastrowid = property(lambda self: real_cursor.lastrowid)
        return mock_cursor
    
    with patch.object(project._db, 'cursor', mock_cursor):
        yield is_database_error


@contextmanager
def _database_cursor_mocked_to_create_revision_with_id(new_row_id: int, project: Project) -> Iterator[None]:
    """
    Forces any created ResourceRevision row to use the specified ID.
    """
    # Where c = project._db.cursor(),
    # mock c.execute() so that if query starts with
    # 'insert into resource_revision ' then
    # 1. followup query is made to alter the created row's
    #    ID to match a desired value
    # 2. the next call to c.lastrowid returns that new ID
    
    class FakeDatabaseCursor:  # logically extends DatabaseCursor
        def __init__(self, base) -> None:
            self._base = base
        
        def execute(self, command: str, *args, **kwargs) -> Self:
            self._base.execute(command, *args, **kwargs)
            
            did_create_revision = command.startswith(
                'insert into resource_revision ')
            if did_create_revision:
                old_row_id = self._base.lastrowid
                
                self._base.execute(
                    'update resource_revision set id = ? where id = ?',
                    (new_row_id, old_row_id))
                self._base.lastrowid = new_row_id
            
            return self
        
        def __getattr__(self, attr_name: str) -> object:
            return getattr(self._base, attr_name)
    
    real_cursor = project._db.cursor  # capture
    def fake_cursor(*args, **kwargs) -> DatabaseCursor:
        return cast(DatabaseCursor, FakeDatabaseCursor(
            real_cursor(*args, **kwargs)))
    
    with patch.object(project._db, 'cursor', fake_cursor):
        yield


# ------------------------------------------------------------------------------