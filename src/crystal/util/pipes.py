from crystal.util.xos import is_linux, is_mac_os, is_windows
import os
import socket
from typing import Optional


def create_selectable_pipe() -> 'Pipe':
    """
    Similar to os.pipe(), but returns a Pipe that works with selectors
    like select.select() on all platforms.
    
    - On Unix-like systems, returns a pipe backed by os.pipe().
    - On Windows, returns a pipe backed by connected sockets.
    
    Returns:
    * Pipe object with readable_end and writable_end.
    """
    if is_mac_os() or is_linux():
        # On Unix-like systems, use regular pipes which work fine with selectors
        (read_fd, write_fd) = os.pipe()
        return Pipe(
            readable_end=ReadablePipeEnd(read_fd, None),
            writable_end=WritablePipeEnd(write_fd, None),
        )
    elif is_windows():
        # On Windows, use socket-based pipes since select() doesn't work with os.pipe()
        
        # Create a server socket
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(('127.0.0.1', 0))
        server_socket.listen(1)
        server_addr = server_socket.getsockname()
        
        # Create client socket and connect to server
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect(server_addr)
        
        # Accept the connection on the server side
        (connected_socket, _) = server_socket.accept()
        server_socket.close()
        
        # The 'read' end is the connected_socket (server-side after accept).
        # The 'write' end is the client_socket.
        # Keep socket objects alive in the pipe ends to prevent garbage collection
        # from closing the underlying file descriptors.
        return Pipe(
            readable_end=ReadablePipeEnd(connected_socket.fileno(), connected_socket),
            writable_end=WritablePipeEnd(client_socket.fileno(), client_socket),
        )
    else:
        raise NotImplementedError('Unrecognized operating system')


class Pipe:
    """
    A pipe with readable and writable ends that work with selectors
    like select.select() on all platforms.
    
    On Windows, this wraps socket objects internally to ensure the file
    descriptors remain valid for the lifetime of the Pipe object.
    """
    
    def __init__(self,
            readable_end: 'ReadablePipeEnd',
            writable_end: 'WritablePipeEnd',
            ) -> None:
        """
        Internal constructor. Use create_selectable_pipe() to create pipes.
        """
        self._readable_end = readable_end
        self._writable_end = writable_end
    
    @property
    def readable_end(self) -> 'ReadablePipeEnd':
        """The readable end of the pipe."""
        return self._readable_end
    
    @property
    def writable_end(self) -> 'WritablePipeEnd':
        """The writable end of the pipe."""
        return self._writable_end


class ReadablePipeEnd:
    """
    The readable end of a pipe.
    
    This abstraction handles platform differences between Unix and Windows
    for reading from pipes.
    """
    
    def __init__(self, fd: int, sock: Optional[socket.socket]) -> None:
        """
        Internal constructor. Use create_selectable_pipe() to create pipes.
        
        Arguments:
        * fd -- File descriptor for reading.
        * sock -- Socket object (on Windows) or None (on Unix).
        """
        self._fd = fd
        self._socket = sock
    
    def fileno(self) -> int:
        """Return the file descriptor for use with selectors."""
        return self._fd
    
    def read(self, size: int) -> bytes:
        """Read up to size bytes from the pipe."""
        if self._socket is not None:
            return self._socket.recv(size)
        else:
            return os.read(self._fd, size)
    
    def close(self) -> None:
        """Close the readable end of the pipe."""
        if self._socket is not None:
            self._socket.close()
        else:
            os.close(self._fd)


class WritablePipeEnd:
    """
    The writable end of a pipe.
    
    This abstraction handles platform differences between Unix and Windows
    for writing to pipes.
    """
    
    def __init__(self, fd: int, sock: Optional[socket.socket]) -> None:
        """
        Internal constructor. Use create_selectable_pipe() to create pipes.
        
        Arguments:
        * fd -- File descriptor for writing.
        * sock -- Socket object (on Windows) or None (on Unix).
        """
        self._fd = fd
        self._socket = sock
    
    def fileno(self) -> int:
        """Return the file descriptor for use with selectors."""
        return self._fd
    
    def write(self, data: bytes) -> int:
        """Write data to the pipe. Returns number of bytes written."""
        if self._socket is not None:
            return self._socket.send(data)
        else:
            return os.write(self._fd, data)
    
    def close(self) -> None:
        """Close the writable end of the pipe."""
        if self._socket is not None:
            self._socket.close()
        else:
            os.close(self._fd)
