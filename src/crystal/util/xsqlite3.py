from contextlib import closing
import random
import sqlite3
from typing import LiteralString


def is_database_closed_error(e: object) -> bool:
    return (
        isinstance(e, sqlite3.ProgrammingError) and 
        str(e) == 'Cannot operate on a closed database.'
    )


# Empirically, this error was observed to occur on macOS 15.3 when the disk
# containing the database was unmounted forcefully while the database was open.
def is_database_gone_error(e: object) -> bool:
    return (
        isinstance(e, sqlite3.DatabaseError) and
        str(e) == 'database disk image is malformed'
    )


# Empirically, this error was observed to occur on Linux when attempting to
# write to a project database created on a remote filesystem mounted via GVFS/SFTP.
def is_database_read_only_error(e: object) -> bool:
    return (
        isinstance(e, sqlite3.OperationalError) and
        str(e) == 'attempt to write a readonly database'
    )


# HACK: Some Windows runners in GitHub Actions don't have a version of SQLite
#       compiled with JSON for some reason. So some behavior must be altered
#       in that case.
def sqlite_has_json_support() -> bool:
    with sqlite3.connect(':memory:') as db:
        with closing(db.cursor()) as c:
            try:
                return list(c.execute('select json(1)')) == [('1',)]
            except sqlite3.OperationalError as e:
                if str(e) == 'no such function: json':
                    return False
                else:
                    raise


def random_choices_from_table_ids(
    k: int,
    table_name: LiteralString,
    c: sqlite3.Cursor
) -> list[int]:
    """
    Return k random IDs from `table_name`, allowing duplicates,
    without reading all IDs into memory.

    Runs in time O(k/density * log(N)), where N is the number of rows in the table,
    and density is the ratio of the number of rows to the range of IDs.
    
    Uses O(k) memory to store the random IDs.

    Raises:
    * IndexError -- if the table is empty
    """
    [(min_id,)] = c.execute(f'select min(id) from {table_name}')
    [(max_id,)] = c.execute(f'select max(id) from {table_name}')
    if min_id is None or max_id is None:
        raise IndexError(f'Table {table_name!r} is empty')
    
    random_ids: list[int] = []
    while len(random_ids) < k:
        # Pick a candidate id in the full integer range
        id_candidate = random.randint(min_id, max_id)

        # log(N) lookup in PK index
        c.execute(f'select id from {table_name} where id = ?', (id_candidate,))
        hits = c.fetchall()
        if len(hits) > 0:
            random_ids.append(id_candidate)
    return random_ids
