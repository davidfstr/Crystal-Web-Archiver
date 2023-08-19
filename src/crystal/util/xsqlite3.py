import sqlite3


def is_database_closed_error(e: object) -> bool:
    return (
        isinstance(e, sqlite3.ProgrammingError) and 
        str(e) == 'Cannot operate on a closed database.'
    )


# HACK: Some Windows runners in GitHub Actions don't have a version of SQLite
#       compiled with JSON for some reason. So some behavior must be altered
#       in that case.
def sqlite_has_json_support() -> bool:
    with sqlite3.connect(':memory:') as db:
        c = db.cursor()
        try:
            return list(c.execute('select json(1)')) == [('1',)]
        except sqlite3.OperationalError as e:
            if str(e) == 'no such function: json':
                return False
            else:
                raise
