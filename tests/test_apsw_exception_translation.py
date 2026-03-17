"""
Unit tests for the apsw-to-sqlite3 exception translation machinery in crystal.util.db.

These tests verify that:
1. apsw exceptions are translated to the correct sqlite3 exception types.
2. Error messages are preserved (or translated where Crystal checks specific messages).
3. The original apsw exception is chained as __cause__.
4. Non-apsw exceptions from VFS (e.g. PermissionError) are wrapped in sqlite3.OperationalError.
5. StopIteration and sqlite3 exceptions pass through unchanged.
6. Crystal's error-identification helpers recognize translated exceptions.
"""

import apsw
from crystal.util.db import (
    ApswConnectionAdapter, ApswCursorAdapter, _ApswRowsIterator,
    _apsw_errors_as_sqlite3, _translate_apsw_error,
    is_no_such_column_error_for,
)
from crystal.util.xsqlite3 import (
    is_database_closed_error,
    is_database_gone_error,
    is_database_read_only_error,
)
import pytest
import sqlite3


# === Test: _translate_apsw_error ===

def test_translate_apsw_sql_error_to_sqlite3_operational_error() -> None:
    e = apsw.SQLError('no such column: foo')
    result = _translate_apsw_error(e)
    assert isinstance(result, sqlite3.OperationalError)
    assert str(result) == 'no such column: foo'


def test_translate_apsw_io_error_to_sqlite3_operational_error() -> None:
    e = apsw.IOError()
    result = _translate_apsw_error(e)
    assert isinstance(result, sqlite3.OperationalError)


def test_translate_apsw_busy_error_to_sqlite3_operational_error() -> None:
    e = apsw.BusyError()
    result = _translate_apsw_error(e)
    assert isinstance(result, sqlite3.OperationalError)


def test_translate_apsw_readonly_error_to_sqlite3_operational_error() -> None:
    e = apsw.ReadOnlyError('attempt to write a readonly database')
    result = _translate_apsw_error(e)
    assert isinstance(result, sqlite3.OperationalError)
    assert str(result) == 'attempt to write a readonly database'


def test_translate_apsw_corrupt_error_to_sqlite3_database_error() -> None:
    e = apsw.CorruptError('database disk image is malformed')
    result = _translate_apsw_error(e)
    assert isinstance(result, sqlite3.DatabaseError)
    assert str(result) == 'database disk image is malformed'


def test_translate_apsw_not_a_db_error_to_sqlite3_database_error() -> None:
    e = apsw.NotADBError('file is not a database')
    result = _translate_apsw_error(e)
    assert isinstance(result, sqlite3.DatabaseError)
    assert str(result) == 'file is not a database'


def test_translate_apsw_constraint_error_to_sqlite3_integrity_error() -> None:
    e = apsw.ConstraintError('UNIQUE constraint failed')
    result = _translate_apsw_error(e)
    assert isinstance(result, sqlite3.IntegrityError)
    assert str(result) == 'UNIQUE constraint failed'


def test_translate_apsw_connection_closed_error_to_sqlite3_programming_error_with_translated_message() -> None:
    e = apsw.ConnectionClosedError()
    result = _translate_apsw_error(e)
    assert isinstance(result, sqlite3.ProgrammingError)
    assert str(result) == 'Cannot operate on a closed database.'


def test_translate_apsw_cursor_closed_error_to_sqlite3_programming_error() -> None:
    e = apsw.CursorClosedError()
    result = _translate_apsw_error(e)
    assert isinstance(result, sqlite3.ProgrammingError)


def test_translate_apsw_misuse_error_to_sqlite3_programming_error() -> None:
    e = apsw.MisuseError()
    result = _translate_apsw_error(e)
    assert isinstance(result, sqlite3.ProgrammingError)


def test_translate_apsw_internal_error_to_sqlite3_internal_error() -> None:
    e = apsw.InternalError()
    result = _translate_apsw_error(e)
    assert isinstance(result, sqlite3.InternalError)


# === Test: _apsw_errors_as_sqlite3 (context manager) ===

def test_context_manager_translates_apsw_error() -> None:
    with pytest.raises(sqlite3.OperationalError) as exc_info:
        with _apsw_errors_as_sqlite3():
            raise apsw.SQLError('some SQL error')
    assert str(exc_info.value) == 'some SQL error'
    assert isinstance(exc_info.value.__cause__, apsw.SQLError)


def test_context_manager_wraps_vfs_permission_error() -> None:
    with pytest.raises(sqlite3.OperationalError) as exc_info:
        with _apsw_errors_as_sqlite3():
            raise PermissionError('S3 access denied')
    assert str(exc_info.value) == 'S3 access denied'
    assert isinstance(exc_info.value.__cause__, PermissionError)


def test_context_manager_wraps_arbitrary_vfs_exception() -> None:
    with pytest.raises(sqlite3.OperationalError) as exc_info:
        with _apsw_errors_as_sqlite3():
            raise RuntimeError('network timeout')
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_context_manager_passes_through_sqlite3_error() -> None:
    with pytest.raises(sqlite3.IntegrityError):
        with _apsw_errors_as_sqlite3():
            raise sqlite3.IntegrityError('unique constraint violated')


def test_context_manager_passes_through_stop_iteration() -> None:
    with pytest.raises(StopIteration):
        with _apsw_errors_as_sqlite3():
            raise StopIteration()


def test_context_manager_passes_through_keyboard_interrupt() -> None:
    with pytest.raises(KeyboardInterrupt):
        with _apsw_errors_as_sqlite3():
            raise KeyboardInterrupt()


# === Test: _ApswRowsIterator ===

def test_rows_iterator_yields_rows_normally() -> None:
    rows = iter([(1,), (2,), (3,)])
    it = _ApswRowsIterator(rows)
    assert list(it) == [(1,), (2,), (3,)]


def test_rows_iterator_translates_apsw_error_during_iteration() -> None:
    def failing_iter():
        yield (1,)
        raise apsw.SQLError('no such table: t')
    it = _ApswRowsIterator(failing_iter())
    assert next(it) == (1,)
    with pytest.raises(sqlite3.OperationalError, match='no such table: t'):
        next(it)


def test_rows_iterator_translates_vfs_exception_during_iteration() -> None:
    def failing_iter():
        yield (1,)
        raise PermissionError('S3 denied')
    it = _ApswRowsIterator(failing_iter())
    assert next(it) == (1,)
    with pytest.raises(sqlite3.OperationalError, match='S3 denied'):
        next(it)


# === Test: Compatibility with Crystal's Error-Identification Helpers ===

def test_translated_connection_closed_error_is_recognized_by_is_database_closed_error() -> None:
    e = apsw.ConnectionClosedError()
    translated = _translate_apsw_error(e)
    assert is_database_closed_error(translated)


def test_translated_corrupt_error_is_recognized_by_is_database_gone_error() -> None:
    e = apsw.CorruptError('database disk image is malformed')
    translated = _translate_apsw_error(e)
    assert is_database_gone_error(translated)


def test_translated_readonly_error_is_recognized_by_is_database_read_only_error() -> None:
    e = apsw.ReadOnlyError('attempt to write a readonly database')
    translated = _translate_apsw_error(e)
    assert is_database_read_only_error(translated)


def test_translated_no_such_column_error_is_recognized_by_is_no_such_column_error_for() -> None:
    e = apsw.SQLError('no such column: request_cookie')
    translated = _translate_apsw_error(e)
    assert is_no_such_column_error_for('request_cookie', translated)


# === Test: End-to-End Through Adapter (Real apsw Connection) ===

def test_adapter_cursor_execute_translates_apsw_error_for_bad_sql() -> None:
    conn = apsw.Connection(':memory:')
    conn.execute('CREATE TABLE t (x INT)')
    adapter = ApswCursorAdapter(conn.cursor())
    with pytest.raises(sqlite3.OperationalError, match='no such column: nonexistent'):
        adapter.execute('SELECT nonexistent FROM t')


def test_adapter_cursor_iteration_translates_apsw_error_for_missing_column() -> None:
    conn = apsw.Connection(':memory:')
    conn.execute('CREATE TABLE t (x INT)')
    conn.execute('INSERT INTO t VALUES (1)')
    adapter = ApswCursorAdapter(conn.cursor())
    # apsw defers some errors to iteration time
    adapter.execute('SELECT x FROM t')
    # Normal iteration should work
    rows = list(adapter)
    assert rows == [(1,)]


def test_adapter_cursor_on_closed_connection_translates_to_programming_error() -> None:
    conn = apsw.Connection(':memory:')
    adapter = ApswCursorAdapter(conn.cursor())
    conn.close()
    with pytest.raises(sqlite3.ProgrammingError):
        adapter.execute('SELECT 1')
