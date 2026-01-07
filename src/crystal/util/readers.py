from crystal.util.pipes import ReadablePipeEnd
import selectors
from typing import IO, Protocol


class ReadableStream(Protocol):
    """Protocol for a readable text stream with fileno() support."""
    def readline(self) -> str: ...
    def fileno(self) -> int: ...
    def close(self) -> None: ...


class InterruptableReader:  # implements ReadableStream
    """
    A wrapper around a text stream which enforces that every I/O operation 
    is performed in an interruptable manner.
    
    This reader monitors an interrupt pipe and raises InterruptedError when
    the interrupt signal is received.
    """
    def __init__(self,
            source: ReadableStream,
            interrupt_read_pipe: 'ReadablePipeEnd',
            ) -> None:
        self.source = source
        self.interrupt_read_pipe = interrupt_read_pipe
        self._interrupted = False
    
    def readline(self) -> str:
        """
        Reads a line from the underlying text stream.
        
        Raises:
        * InterruptedError -- if the read was interrupted.
        """
        if self._interrupted:
            raise InterruptedError()
        
        # Wait for either the source or interrupt pipe to become readable
        with selectors.DefaultSelector() as fileobjs:
            fileobjs.register(self.source.fileno(), selectors.EVENT_READ)
            fileobjs.register(self.interrupt_read_pipe.fileno(), selectors.EVENT_READ)
            events = fileobjs.select(timeout=None)
            
            for (key, _) in events:
                if key.fd == self.interrupt_read_pipe.fileno():
                    self._interrupted = True
                    raise InterruptedError()
            else:
                # self.source.fileno() must be in events
                pass
        
        return self.source.readline()
    
    def fileno(self) -> int:
        """Return the file descriptor of the underlying source stream."""
        return self.source.fileno()
    
    def close(self) -> None:
        self.source.close()


class TeeReader:  # implements ReadableStream
    """
    A wrapper around a text stream that copies everything read to a log file.
    Similar to the Unix 'tee' command.
    """
    def __init__(self,
            source: IO[str],
            log_file_path: str,
            ) -> None:
        log_file = open(log_file_path, 'w', encoding='utf-8')
        
        self.source = source
        self.log_file = log_file
    
    def readline(self) -> str:
        """
        Reads a line from the underlying text stream and copies it to the log file.
        """
        line = self.source.readline()
        
        if line:
            self.log_file.write(line)
            self.log_file.flush()
        
        return line
    
    def fileno(self) -> int:
        """Return the file descriptor of the underlying source stream."""
        return self.source.fileno()
    
    def close(self) -> None:
        self.source.close()
        try:
            # NOTE: May raise `OSError: [Errno 9] Bad file descriptor` if
            #       log_file has never been read from.
            self.log_file.close()
        except Exception:
            pass
