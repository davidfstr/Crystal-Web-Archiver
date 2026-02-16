import os


DEFAULT_SERVER_HOST = '127.0.0.1'


def DEFAULT_SERVER_PORT() -> int:
    """Returns the default server port, allowing override via environment variable for testing."""
    env_port = os.environ.get('CRYSTAL_DEFAULT_SERVER_PORT')
    if env_port is not None:
        return int(env_port)
    return 2797  # CRYS on telephone keypad
