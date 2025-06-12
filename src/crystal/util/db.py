from __future__ import annotations

from collections.abc import Callable
import sqlite3
from typing import Self

# Whether to print each database query
VERBOSE_QUERIES = False


class DatabaseConnection:
    """Wraps a sqlite3.dbapi2.Connection, ensuring that it is used correctly."""
    
    def __init__(self,
            db: sqlite3.dbapi2.Connection,
            readonly_func: Callable[[], bool]) -> None:
        self._db = db
        self._readonly_func = readonly_func
    
    def cursor(self, *args, **kwargs) -> DatabaseCursor:
        c = self._db.cursor(*args, **kwargs)  # type: sqlite3.dbapi2.Cursor
        return DatabaseCursor(c, self._readonly_func())
    
    def __getattr__(self, attr_name: str):
        return getattr(self._db, attr_name)


class DatabaseCursor:
    """Wraps a sqlite3.dbapi2.Cursor, ensuring that it is used correctly."""
    
    def __init__(self, c: sqlite3.dbapi2.Cursor, readonly: bool) -> None:
        self._c = c
        self._readonly = readonly
    
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
    
    def __getattr__(self, attr_name: str):
        return getattr(self._c, attr_name)


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
