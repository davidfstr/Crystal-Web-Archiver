from collections.abc import Iterator
from contextlib import closing, contextmanager
import socket


_ANY_PORT = 0
_LOCALHOST = '127.0.0.1'


@contextmanager
def port_in_use(port: int=_ANY_PORT, hostname: str=_LOCALHOST) -> Iterator[int]:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as conflicting_server:
        # Set SO_REUSEADDR to allow immediate reuse of the port,
        # matching the behavior of ProjectServer's HTTPServer
        conflicting_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        conflicting_server.bind((hostname, port))  # bind to default port
        conflicting_server.listen(1)
        
        chosen_port = conflicting_server.getsockname()[1]
        
        yield chosen_port


def is_port_in_use(port: int, hostname: str=_LOCALHOST) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        try:
            result = s.connect_ex((hostname, port))
        except:
            raise ValueError(f'socket.connect_ex({(hostname, port)}) failed')
        if result == 0:
            return True
        else:
            return False
    finally:
        s.close()


def is_port_in_use_error(e: Exception) -> bool:
    # macOS: [Errno 48] Address already in use
    # Linux: [Errno 98] Address already in use
    # TODO: Look for errno.EADDRINUSE instead of substring
    if isinstance(e, OSError) and 'Address already in use' in str(e):
        return True
    return False
