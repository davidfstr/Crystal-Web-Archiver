from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
import sqlite3
from typing import Self
from typing_extensions import deprecated

# Whether to print each database query
VERBOSE_QUERIES = False


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
        in c.execute('PRAGMA table_info({})'.format(table_name))
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
