import socket

_LOCALHOST = '127.0.0.1'


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
    if isinstance(e, OSError) and 'Address already in use' in str(e):
        return True
    return False
