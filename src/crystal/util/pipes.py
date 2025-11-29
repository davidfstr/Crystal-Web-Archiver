from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.xos import is_linux, is_mac_os, is_windows
from crystal.util.xthreading import bg_call_later
import os
import socket
from typing import IO, Optional


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


class SelectableReader:
    """
    Wraps a readable text stream (like process.stdout) to make it usable
    with select() on Windows.
    
    On Windows, select() only works with sockets, not with regular file
    descriptors or pipes. This class works around that limitation by using
    a background thread to forward data from the source stream to a socket
    pair, allowing the socket to be used with select().
    
    On Unix-like systems, this class is not needed since select() works
    directly with pipes.
    """
    
    def __init__(self, source: IO[str]) -> None:
        """
        Create a SelectableReader wrapping the given text stream.
        
        Arguments:
        * source -- A readable text stream (e.g., process.stdout).
        """
        self._source = source
        self._closed = False
        
        # Create a socket pair for forwarding data
        # Server socket listens for a connection
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(('127.0.0.1', 0))
        server_socket.listen(1)
        server_addr = server_socket.getsockname()
        
        # Client socket connects to server
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect(server_addr)
        
        # Accept the connection
        (connected_socket, _) = server_socket.accept()
        server_socket.close()
        
        # The reader reads from connected_socket (server-side)
        # The forwarder thread writes to client_socket
        self._read_socket = connected_socket
        self._write_socket = client_socket
        
        # Buffer for incomplete lines
        self._buffer = ''
        
        # Start background thread to forward data from source to socket
        self._forwarder_thread = bg_call_later(
            target=self._forward_data,
            daemon=True,
            name='SelectableReader.forward_data'
        )
    
    @capture_crashes_to_stderr
    def _forward_data(self) -> None:
        """Background thread that forwards data from source to write socket."""
        try:
            while True:
                # Read from source (blocking)
                data = self._source.readline()
                if not data:
                    # EOF reached
                    break
                # Forward to socket (encode text to bytes)
                self._write_socket.sendall(data.encode('utf-8'))
        except Exception:
            # Source was closed or error occurred
            pass
        finally:
            # Close write socket to signal EOF to reader
            try:
                self._write_socket.close()
            except Exception:
                pass
    
    def fileno(self) -> int:
        """Return the file descriptor for use with selectors."""
        return self._read_socket.fileno()
    
    def readline(self) -> str:
        """
        Read a line from the stream.
        
        Returns an empty string on EOF.
        """
        # Check if we have a complete line in the buffer
        newline_pos = self._buffer.find('\n')
        if newline_pos != -1:
            line = self._buffer[:newline_pos + 1]
            self._buffer = self._buffer[newline_pos + 1:]
            return line
        
        # Read more data from socket
        while True:
            try:
                data = self._read_socket.recv(4096)
            except Exception:
                # Socket closed or error
                data = b''
            
            if not data:
                # EOF - return any remaining buffer content
                if self._buffer:
                    result = self._buffer
                    self._buffer = ''
                    return result
                return ''
            
            # Decode and add to buffer
            self._buffer += data.decode('utf-8')
            
            # Check for complete line
            newline_pos = self._buffer.find('\n')
            if newline_pos != -1:
                line = self._buffer[:newline_pos + 1]
                self._buffer = self._buffer[newline_pos + 1:]
                return line
    
    def close(self) -> None:
        """Close the reader and clean up resources."""
        if self._closed:
            return
        self._closed = True
        
        try:
            self._source.close()
        except Exception:
            pass
        
        try:
            self._read_socket.close()
        except Exception:
            pass
        
        try:
            self._write_socket.close()
        except Exception:
            pass
