from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
import sqlite3
import sqlite3.dbapi2
from typing import Any, cast, Self, TYPE_CHECKING
from warnings import deprecated

if TYPE_CHECKING:
    import apsw
    from crystal.model.s3vfs import S3VFS


# Whether to print each database query
VERBOSE_QUERIES = False


# ------------------------------------------------------------------------------
# Database Connection

class DatabaseConnection:
    """
    Wraps a sqlite3.dbapi2.Connection, ensuring that it is used correctly.
    
    In particular:
    - If project is opened as readonly then blocks writes to the project database.
    - When write to project database then mark project as dirty.
    
    Examples:
    - Read from database:
        with closing(project._db.cursor()) as c:
            rows = list(c.execute('select id from resource where url = ?', (url,)))
    
    - Write to database, in a new transaction:
        with project._db:
            with closing(project._db.cursor()) as c:
                c.execute('insert into resource (url) values (?)', (normalized_url,))
                id = c.lastrowid
    
    - Write to database, in an already-open transaction:
        with project._db(commit=False):
            with closing(project._db.cursor()) as c:
                c.execute('insert into resource (url) values (?)', (normalized_url,))
                id = c.lastrowid
    """
    
    def __init__(self,
            raw_db: sqlite3.dbapi2.Connection,
            readonly: bool,
            mark_dirty_func: Callable[[], None]) -> None:
        self._raw_db = raw_db
        self._readonly = readonly
        self._mark_dirty_func = mark_dirty_func
        self._outer_transaction = None  # type: DatabaseTransaction | None
    
    # === Transactions ===
    
    def __call__(self,
            *, commit: bool = True,
            commit_context: AbstractContextManager | None = None,
            ) -> DatabaseTransaction:
        transaction = DatabaseTransaction(
            self, commit=commit, commit_context=commit_context)
        if commit:
            if self._outer_transaction is not None:
                raise ValueError('Expected no outer database transaction to be in progress')
            self._outer_transaction = transaction
        else:
            if self._outer_transaction is None:
                raise ValueError('Expected outer database transaction to be in progress')
        return transaction
    
    def __enter__(self) -> DatabaseTransaction:
        outer_transaction = self(commit=True)
        assert self._outer_transaction == outer_transaction
        return outer_transaction
    
    def __exit__(self, *args) -> None:
        assert self._outer_transaction is not None
        self._outer_transaction.__exit__(*args)
        assert self._outer_transaction is None
    
    # === Operations ===
    
    def cursor(self, *args, **kwargs) -> DatabaseCursor:
        c = self._raw_db.cursor(*args, **kwargs)  # type: sqlite3.dbapi2.Cursor
        return DatabaseCursor(c, self._readonly)
    
    @deprecated('Use DatabaseTransaction instead of managing transactions manually')
    def commit(self) -> None:
        self._raw_db.commit()  # pylint: disable=no-direct-database-commit
        self._mark_dirty_func()
    
    @deprecated('Use DatabaseTransaction instead of managing transactions manually')
    def rollback(self) -> None:
        self._raw_db.rollback()  # pylint: disable=no-direct-database-rollback
    
    # === Misc ===
    
    def __getattr__(self, attr_name: str):
        return getattr(self._raw_db, attr_name)


class DatabaseTransaction:
    """
    Context which manages the current database transaction or the upcoming transaction
    that will be started when the next write query is executed.
    """
    def __init__(self,
            db: DatabaseConnection,
            *, commit: bool = True,
            commit_context: AbstractContextManager | None = None,
            ) -> None:
        self._db = db
        self._commit = commit
        self._commit_context = commit_context or nullcontext()
    
    def __enter__(self) -> Self:
        return self
    
    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._commit:
            with self._commit_context:
                if exc_value is None:
                    self._db.commit()  # pylint: disable=no-direct-database-commit
                else:
                    self._db.rollback()  # pylint: disable=no-direct-database-rollback
            self._db._outer_transaction = None


class DatabaseCursor:
    """
    Wraps a sqlite3.dbapi2.Cursor, ensuring that it is used correctly.
    
    See docstring for DatabaseConnection for details RE what correct usage
    looks like.
    """
    
    def __init__(self, c: sqlite3.dbapi2.Cursor, readonly: bool) -> None:
        self._c = c
        self._readonly = readonly
    
    # === Operations ===
    
    def execute(self, command: str, *args, **kwargs) -> Self:
        ignore_readonly = bool(kwargs.pop('ignore_readonly', False))
        
        # Ensure that caller does disallow commands that write to the database
        # if the project is readonly
        if self._readonly and not ignore_readonly:
            command_lower = command.lower()  # cache
            command_is_read = (
                command_lower.startswith('select ') or
                command_lower.startswith('pragma table_info(') or
                command_lower.startswith('explain ')
            )
            command_is_write = not command_is_read  # conservative
            if command_is_write:
                raise AssertionError(
                    'Attempted to write to database when (Project.readonly == True). '
                    'Caller should have checked this case and thrown ProjectReadOnlyError.'
                )
        
        if VERBOSE_QUERIES:
            print(f'QUERY: {command!r}, {args=}')
        result = self._c.execute(command, *args, **kwargs)
        assert result is self._c
        return self
    
    # Define specially to help mypy know that this attribute exists
    def __iter__(self, *args, **kwargs):
        return self._c.__iter__(*args, **kwargs)
    
    # === Misc ===
    
    def __getattr__(self, attr_name: str):
        return getattr(self._c, attr_name)


# ------------------------------------------------------------------------------
# Apsw Database Connection
#
# The adapter classes below bridge apsw's API to look like sqlite3's API,
# so that Crystal's existing code (which catches sqlite3 exception types
# and uses sqlite3 cursor/connection semantics) works unchanged.
#
# Exception translation is critical: apsw raises its own exception hierarchy
# (apsw.Error and subclasses) which is completely separate from sqlite3's.
# Additionally, S3 I/O errors (PermissionError, botocore exceptions, etc.)
# can escape through apsw's VFS layer. Both must be translated to sqlite3
# equivalents so that Crystal's error-handling code works correctly.

class ApswConnectionAdapter:
    """Makes an apsw.Connection look like sqlite3.dbapi2.Connection."""

    def __init__(self, conn: 'apsw.Connection', s3_vfs: 'S3VFS') -> None:
        self._conn = conn
        # Hold reference to prevent garbage collection
        self._s3_vfs = s3_vfs

    def cursor(self) -> sqlite3.dbapi2.Cursor:
        with _apsw_errors_as_sqlite3():
            return cast(
                sqlite3.dbapi2.Cursor,
                ApswCursorAdapter(self._conn.cursor())
            )

    def create_function(self, name: str, num_params: int, func) -> None:
        with _apsw_errors_as_sqlite3():
            self._conn.create_scalar_function(name, func, num_params)

    def close(self) -> None:
        with _apsw_errors_as_sqlite3():
            self._conn.close()

    def commit(self) -> None:
        pass  # read-only, no-op

    def rollback(self) -> None:
        pass  # read-only, no-op

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


class ApswCursorAdapter:
    """Makes an apsw.Cursor look like sqlite3.dbapi2.Cursor."""

    def __init__(self, cursor) -> None:
        self._cursor = cursor
        self._rows = None  # type: _ApswRowsIterator | None

    def execute(self, sql: str, *args, **kwargs):
        with _apsw_errors_as_sqlite3():
            raw_rows = self._cursor.execute(sql, *args, **kwargs)
        self._rows = _ApswRowsIterator(raw_rows)
        return self  # match sqlite3 behavior

    def fetchone(self):
        if self._rows is None:
            return None
        try:
            return next(self._rows)
        except StopIteration:
            return None

    def fetchall(self) -> list:
        if self._rows is None:
            return []
        return list(self._rows)

    def close(self) -> None:
        with _apsw_errors_as_sqlite3():
            self._cursor.close()

    @property
    def description(self):
        return self._cursor.description

    @property
    def lastrowid(self):
        return None  # read-only, never used

    def __iter__(self):
        return self._rows if self._rows is not None else iter([])

    def __next__(self):
        if self._rows is None:
            raise StopIteration
        return next(self._rows)

    def __getattr__(self, name: str):
        return getattr(self._cursor, name)


class _ApswRowsIterator:
    """
    Wraps an apsw rows iterator, translating exceptions raised during
    iteration into sqlite3 equivalents.

    Without this wrapper, iterating raw apsw rows (e.g. in a for loop
    over cursor.execute(...)) would raise apsw exceptions that Crystal's
    error handlers don't recognize.
    """

    def __init__(self, rows) -> None:
        self._rows = rows

    def __iter__(self) -> _ApswRowsIterator:
        return self

    def __next__(self):
        with _apsw_errors_as_sqlite3():
            return next(self._rows)


@contextmanager
def _apsw_errors_as_sqlite3() -> Iterator[None]:
    """
    Context manager that translates apsw exceptions and VFS-propagated
    exceptions into their sqlite3 equivalents.
    """
    import apsw as _apsw
    try:
        yield
    except _apsw.Error as e:
        raise _translate_apsw_error(e) from e
    except (sqlite3.Error, StopIteration, GeneratorExit, KeyboardInterrupt):
        raise  # pass through unchanged
    except Exception as e:
        # Non-apsw, non-sqlite3 exception escaped from VFS
        # (e.g. PermissionError, botocore.exceptions.ClientError)
        raise sqlite3.OperationalError(str(e)) from e


def _translate_apsw_error(e: Exception) -> sqlite3.Error:
    """Map an apsw exception to the equivalent sqlite3 exception type."""
    import apsw as _apsw
    msg = str(e)
    if isinstance(e, (_apsw.CorruptError, _apsw.NotADBError)):
        return sqlite3.DatabaseError(msg)
    elif isinstance(e, _apsw.ConstraintError):
        return sqlite3.IntegrityError(msg)
    elif isinstance(e, (_apsw.ConnectionClosedError, _apsw.CursorClosedError, _apsw.MisuseError)):
        if isinstance(e, _apsw.ConnectionClosedError):
            # Translate message to match what sqlite3 uses,
            # so that is_database_closed_error() recognizes it
            msg = 'Cannot operate on a closed database.'
        return sqlite3.ProgrammingError(msg)
    elif isinstance(e, _apsw.InternalError):
        return sqlite3.InternalError(msg)
    else:
        # Default: sqlite3.OperationalError
        # (covers SQLError, IOError, BusyError, ReadOnlyError, etc.)
        return sqlite3.OperationalError(msg)


# ------------------------------------------------------------------------------
# Schema Introspection

def get_table_names(c: DatabaseCursor) -> list[str]:
    return [
        table_name
        for (table_name,) in
        c.execute('SELECT name FROM sqlite_master WHERE type = "table"')
    ]


def get_column_names_of_table(c: DatabaseCursor, table_name: str) -> list[str]:
    return [
        column_name
        for (_, column_name, column_type, _, _, _)
        # NOTE: Cannot use regular '?' placeholder in this PRAGMA
        in c.execute(f'PRAGMA table_info({table_name})')
    ]


def is_no_such_column_error_for(column_name: str, e: Exception) -> bool:
    return (
        isinstance(e, sqlite3.OperationalError) and
        str(e) == f'no such column: {column_name}'
    )


def get_index_names(c: DatabaseCursor) -> list[str]:
    return [
        index_name
        for (index_name,) in 
        c.execute('SELECT name FROM sqlite_master WHERE type = "index"')
    ]


# ------------------------------------------------------------------------------
