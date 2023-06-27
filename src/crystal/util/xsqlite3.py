import sqlite3


def is_database_closed_error(e: object) -> bool:
    return (
        isinstance(e, sqlite3.ProgrammingError) and 
        str(e) == 'Cannot operate on a closed database.'
    )
