"""Tests for DownloadResourceBodyTask"""

from contextlib import asynccontextmanager, contextmanager
from crystal.model import Project, Resource, ResourceRevision
from crystal.tests import test_data
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import served_project
from crystal.tests.util.wait import DEFAULT_WAIT_PERIOD
from crystal.tests.util.windows import OpenOrCreateDialog
from http.client import HTTPConnection, HTTPResponse
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import sqlite3
import tempfile
import threading
import time
from typing import AsyncIterator, Iterable, Iterator, List, NoReturn
from unittest import skip
from unittest.mock import ANY, Mock, patch, PropertyMock


# ------------------------------------------------------------------------------
# Tests: Success Cases

async def test_download_does_save_resource_metadata_and_content_accurately() -> None:
    HEADERS = [
        ['Content-Type', 'application/zip'],
        ['Server', 'TestServer/1.0'],
        ['Date', 'Wed, 16 Aug 2023 00:00:00 GMT'],  # arbitrary
    ]
    
    with test_data.open_binary('testdata_xkcd.crystalproj.zip') as content_file:
        content_bytes = content_file.read()
    assert len(content_bytes) > 1000  # ensure is a reasonably sized file
    
    with _file_served(HEADERS, content_bytes) as server_port:
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                project = Project._last_opened_project
                assert project is not None
                
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
    
    with test_data.open_binary('testdata_xkcd.crystalproj.zip') as content_file:
        content_bytes = content_file.read()
    
    with _file_served(HEADERS, content_bytes) as server_port:
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                project = Project._last_opened_project
                assert project is not None
                
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
def _file_served(headers: List[List[str]], content_bytes: bytes) -> Iterator[int]:
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

async def test_when_no_errors_then_database_row_and_body_file_is_created() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
        
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                project = Project._last_opened_project
                assert project is not None
                
                r = Resource(project, home_url)
                revision_future = r.download_body()
                while not revision_future.done():
                    await bg_sleep(DEFAULT_WAIT_PERIOD)
                
                # Ensure no error is reported
                revision = revision_future.result()  # type: ResourceRevision
                assert None == revision.error
                
                # Ensure database and filesystem is in expected state
                c = project._db.cursor()
                ((count,),) = c.execute('select count(1) from resource_revision where id=?', (revision._id,))
                assert 1 == count
                assert True == os.path.exists(os.path.join(
                    project.path, Project._RESOURCE_REVISION_DIRNAME, str(revision._id)))
                assert [] == os.listdir(os.path.join(
                    project.path, Project._TEMPORARY_DIRNAME))


async def test_when_io_error_then_tries_to_delete_partial_body_file_and_but_leave_database_row() -> None:
    async with _downloads_mocked_to_raise_io_error() as is_connection_reset:
        with served_project('testdata_xkcd.crystalproj.zip') as sp:
            home_url = sp.get_request_url('https://xkcd.com/')
            
            with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
                async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                    project = Project._last_opened_project
                    assert project is not None
                    
                    r = Resource(project, home_url)
                    revision_future = r.download_body()
                    while not revision_future.done():
                        await bg_sleep(DEFAULT_WAIT_PERIOD)
                    
                    # Ensure an I/O error is reported
                    revision = revision_future.result()  # type: ResourceRevision
                    assert None != revision.error
                    assert is_connection_reset(revision.error)
                    
                    # Ensure database and filesystem is in expected state
                    c = project._db.cursor()
                    ((count,),) = c.execute('select count(1) from resource_revision where id=?', (revision._id,))
                    assert 1 == count
                    assert False == os.path.exists(os.path.join(
                        project.path, Project._RESOURCE_REVISION_DIRNAME, str(revision._id)))
                    assert [] == os.listdir(os.path.join(
                        project.path, Project._TEMPORARY_DIRNAME))


async def test_when_database_error_then_tries_to_delete_partial_body_file() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
        
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                project = Project._last_opened_project
                assert project is not None
                
                async with _downloads_mocked_to_raise_database_error(project) as is_database_error:
                    r = Resource(project, home_url)
                    revision_future = r.download_body()
                    while not revision_future.done():
                        await bg_sleep(DEFAULT_WAIT_PERIOD)
                    
                    # Ensure a database error is reported
                    try:
                        revision = revision_future.result()  # type: ResourceRevision
                    except Exception as e:
                        assert is_database_error(e)
                    else:
                        assert False, 'Expected database error'
                    
                    # Ensure database and filesystem is in expected state
                    c = project._db.cursor()
                    ((count,),) = c.execute('select count(1) from resource_revision')
                    assert 0 == count
                    assert [] == os.listdir(os.path.join(
                        project.path, Project._RESOURCE_REVISION_DIRNAME))
                    assert [] == os.listdir(os.path.join(
                        project.path, Project._TEMPORARY_DIRNAME))


async def test_when_io_error_and_database_error_then_tries_to_delete_partial_body_file() -> None:
    async with _downloads_mocked_to_raise_io_error() as is_connection_reset:
        with served_project('testdata_xkcd.crystalproj.zip') as sp:
            home_url = sp.get_request_url('https://xkcd.com/')
            
            with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
                async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                    project = Project._last_opened_project
                    assert project is not None
                    
                    async with _downloads_mocked_to_raise_database_error(project) as is_database_error:
                        r = Resource(project, home_url)
                        revision_future = r.download_body()
                        while not revision_future.done():
                            await bg_sleep(DEFAULT_WAIT_PERIOD)
                        
                        # Ensure a database error is reported (and not the I/O error)
                        try:
                            revision = revision_future.result()  # type: ResourceRevision
                        except Exception as e:
                            assert is_database_error(e)
                        else:
                            assert False, 'Expected database error'
                        
                        # Ensure database and filesystem is in expected state
                        c = project._db.cursor()
                        ((count,),) = c.execute('select count(1) from resource_revision')
                        assert 0 == count
                        assert [] == os.listdir(os.path.join(
                            project.path, Project._RESOURCE_REVISION_DIRNAME))
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
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
            # Ensure partial body file is deleted
            assert [] == os.listdir(os.path.join(
                project_dirpath, Project._TEMPORARY_DIRNAME))


# ------------------------------------------------------------------------------
# Utility

@asynccontextmanager
async def _downloads_mocked_to_raise_io_error() -> AsyncIterator:
    def raise_connection_reset() -> NoReturn:
        raise IOError('Connection reset')
    def is_connection_reset(e: object) -> bool:
        return (
            isinstance(e, IOError) and
            str(e) == 'Connection reset'
        )
    
    def mock_read() -> Iterable[bytes]:
         yield b'<html>'
         raise_connection_reset()
    def mock_readinto() -> Iterable[int]:
        yield len(b'<html>')
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
        yield is_connection_reset


@asynccontextmanager
async def _downloads_mocked_to_raise_database_error(project: Project) -> AsyncIterator:
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


# ------------------------------------------------------------------------------