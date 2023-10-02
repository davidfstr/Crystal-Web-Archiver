from crystal.util.xos import is_linux
import subprocess


def set(itempath: str, attr_name: str, attr_value: str) -> None:
    """
    Raises:
    * GioNotAvailable
    * UnrecognizedGioAttributeError
    """
    assert is_linux()
    try:
        subprocess.run(
            ['gio', 'set', itempath, attr_name, attr_value],
            check=True,
            capture_output=True,
        )
    except FileNotFoundError:
        raise GioNotAvailable()
    except subprocess.CalledProcessError as e:
        if (e.stderr.startswith(b'gio: Setting attribute ') and
                e.stderr.endswith(b'not supported\n')):
            raise UnrecognizedGioAttributeError()
        else:
            raise


class GioNotAvailable(Exception):
    pass


class UnrecognizedGioAttributeError(Exception):
    pass
