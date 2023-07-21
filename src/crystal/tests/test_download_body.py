"""Tests for DownloadResourceBodyTask"""

from contextlib import asynccontextmanager
from crystal.model import Project, Resource, ResourceRevision
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import served_project
from crystal.tests.util.wait import DEFAULT_WAIT_PERIOD
from crystal.tests.util.windows import OpenOrCreateDialog
from http.client import HTTPConnection, HTTPResponse
import os
import sqlite3
import tempfile
import time
from typing import AsyncIterator, Iterable, NoReturn
from unittest import skip
from unittest.mock import Mock, patch, PropertyMock


# ------------------------------------------------------------------------------
# Tests

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
    
    def mock_read_results() -> Iterable[bytes]:
        yield b'<html>'
        raise_connection_reset()
    
    mock_response = Mock(spec=HTTPResponse)
    mock_response.version = 10  # HTTP/1.0
    mock_response.status = 200
    mock_response.reason = 'OK'
    mock_response.getheaders = Mock(return_value=[
        ('Content-Type', 'text/html; charset=utf-8')
    ])
    mock_response.read = Mock(side_effect=mock_read_results())
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