"""
Unit tests for crystal.util.pipes module.
"""

from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.pipes import create_selectable_pipe, Pipe, SelectableReader
from crystal.util.xthreading import bg_call_later
from io import StringIO
import selectors
import time


class TestCreateSelectablePipe:
    """Tests for the create_selectable_pipe() function."""
    
    def test_returns_pipe_with_readable_and_writable_ends(self) -> None:
        """Test that create_selectable_pipe returns a Pipe with readable and writable ends."""
        pipe = create_selectable_pipe()
        try:
            assert isinstance(pipe, Pipe)
            # Check that fileno() returns valid file descriptors
            assert isinstance(pipe.readable_end.fileno(), int)
            assert isinstance(pipe.writable_end.fileno(), int)
            assert pipe.readable_end.fileno() >= 0
            assert pipe.writable_end.fileno() >= 0
            assert pipe.readable_end.fileno() != pipe.writable_end.fileno()
        finally:
            pipe.readable_end.close()
            pipe.writable_end.close()
    
    def test_can_write_and_read_data(self) -> None:
        """Test that data written to writable end can be read from readable end."""
        pipe = create_selectable_pipe()
        try:
            test_data = b'hello world'
            pipe.writable_end.write(test_data)
            received_data = pipe.readable_end.read(len(test_data))
            assert received_data == test_data
        finally:
            pipe.readable_end.close()
            pipe.writable_end.close()
    
    def test_can_write_single_byte(self) -> None:
        """Test that a single byte can be written and read (common for interrupt signals)."""
        pipe = create_selectable_pipe()
        try:
            pipe.writable_end.write(b'\x00')
            received_data = pipe.readable_end.read(1)
            assert received_data == b'\x00'
        finally:
            pipe.readable_end.close()
            pipe.writable_end.close()
    
    def test_works_with_selectors_module(self) -> None:
        """Test that the pipe file descriptors work with the selectors module."""
        pipe = create_selectable_pipe()
        try:
            sel = selectors.DefaultSelector()
            try:
                # Register the read end for read events
                sel.register(pipe.readable_end.fileno(), selectors.EVENT_READ)
                
                # Initially, nothing is readable (no data written yet)
                events = sel.select(timeout=0.01)
                assert len(events) == 0
                
                # Write some data
                pipe.writable_end.write(b'x')
                
                # Now the read end should be readable
                events = sel.select(timeout=1.0)
                assert len(events) == 1
                assert events[0][0].fd == pipe.readable_end.fileno()
            finally:
                sel.close()
        finally:
            pipe.readable_end.close()
            pipe.writable_end.close()
    
    def test_select_blocks_until_data_available(self) -> None:
        """Test that select blocks until data is written to the pipe."""
        pipe = create_selectable_pipe()
        try:
            sel = selectors.DefaultSelector()
            try:
                sel.register(pipe.readable_end.fileno(), selectors.EVENT_READ)
                
                # Track when we received data
                received_time = [None]
                
                @capture_crashes_to_stderr
                def write_after_delay() -> None:
                    time.sleep(0.1)
                    pipe.writable_end.write(b'x')
                
                # Start a thread that will write data after a delay
                start_time = time.monotonic()
                writer_thread = bg_call_later(
                    write_after_delay,
                    name='test_pipes.write_after_delay',
                )
                
                # select should block until data is available
                events = sel.select(timeout=2.0)
                elapsed_time = time.monotonic() - start_time
                
                writer_thread.join()
                
                # Should have received data
                assert len(events) == 1
                # Should have blocked for approximately 0.1 seconds (but less than timeout)
                assert elapsed_time >= 0.05  # allow some slack
                assert elapsed_time < 1.0
            finally:
                sel.close()
        finally:
            pipe.readable_end.close()
            pipe.writable_end.close()
    
    def test_multiple_writes_and_reads(self) -> None:
        """Test that multiple writes and reads work correctly."""
        pipe = create_selectable_pipe()
        try:
            # Write multiple chunks
            pipe.writable_end.write(b'first')
            pipe.writable_end.write(b'second')
            pipe.writable_end.write(b'third')
            
            # Read all data
            data = pipe.readable_end.read(1024)
            assert data == b'firstsecondthird'
        finally:
            pipe.readable_end.close()
            pipe.writable_end.close()
    
    def test_closing_write_end_signals_eof(self) -> None:
        """Test that closing the write end allows the read end to detect EOF."""
        pipe = create_selectable_pipe()
        write_end_closed = False
        try:
            # Write some data, then close write end
            pipe.writable_end.write(b'data')
            pipe.writable_end.close()
            write_end_closed = True
            
            # Read the data
            data = pipe.readable_end.read(1024)
            assert data == b'data'
            
            # Next read should return empty (EOF)
            data = pipe.readable_end.read(1024)
            assert data == b''
        finally:
            pipe.readable_end.close()
            if not write_end_closed:
                pipe.writable_end.close()
    
    def test_can_create_multiple_pipes(self) -> None:
        """Test that multiple independent pipes can be created."""
        pipe1 = create_selectable_pipe()
        pipe2 = create_selectable_pipe()
        try:
            # All file descriptors should be unique
            fds = {
                pipe1.readable_end.fileno(), pipe1.writable_end.fileno(),
                pipe2.readable_end.fileno(), pipe2.writable_end.fileno()
            }
            assert len(fds) == 4
            
            # Write different data to each pipe
            pipe1.writable_end.write(b'pipe1')
            pipe2.writable_end.write(b'pipe2')
            
            # Read from each pipe and verify data isolation
            data1 = pipe1.readable_end.read(1024)
            data2 = pipe2.readable_end.read(1024)
            assert data1 == b'pipe1'
            assert data2 == b'pipe2'
        finally:
            pipe1.readable_end.close()
            pipe1.writable_end.close()
            pipe2.readable_end.close()
            pipe2.writable_end.close()
    
    def test_select_with_multiple_pipes(self) -> None:
        """Test that selectors can monitor multiple pipes simultaneously."""
        pipe1 = create_selectable_pipe()
        pipe2 = create_selectable_pipe()
        try:
            sel = selectors.DefaultSelector()
            try:
                sel.register(pipe1.readable_end.fileno(), selectors.EVENT_READ, data='pipe1')
                sel.register(pipe2.readable_end.fileno(), selectors.EVENT_READ, data='pipe2')
                
                # Nothing readable initially
                events = sel.select(timeout=0.01)
                assert len(events) == 0
                
                # Write to pipe2 only
                pipe2.writable_end.write(b'x')
                
                # Only pipe2 should be readable
                events = sel.select(timeout=1.0)
                assert len(events) == 1
                assert events[0][0].data == 'pipe2'
                
                # Read the data
                pipe2.readable_end.read(1)
                
                # Now write to pipe1
                pipe1.writable_end.write(b'y')
                
                # Only pipe1 should be readable
                events = sel.select(timeout=1.0)
                assert len(events) == 1
                assert events[0][0].data == 'pipe1'
            finally:
                sel.close()
        finally:
            pipe1.readable_end.close()
            pipe1.writable_end.close()
            pipe2.readable_end.close()
            pipe2.writable_end.close()


class TestSelectableReader:
    """Tests for the SelectableReader class."""
    
    def test_can_read_single_line(self) -> None:
        """Test that a single line can be read from the wrapped stream."""
        source = StringIO('hello world\n')
        reader = SelectableReader(source)
        try:
            line = reader.readline()
            assert line == 'hello world\n'
        finally:
            reader.close()
    
    def test_can_read_multiple_lines(self) -> None:
        """Test that multiple lines can be read sequentially."""
        source = StringIO('line1\nline2\nline3\n')
        reader = SelectableReader(source)
        try:
            assert reader.readline() == 'line1\n'
            assert reader.readline() == 'line2\n'
            assert reader.readline() == 'line3\n'
        finally:
            reader.close()
    
    def test_returns_empty_string_on_eof(self) -> None:
        """Test that readline returns empty string when EOF is reached."""
        source = StringIO('only line\n')
        reader = SelectableReader(source)
        try:
            assert reader.readline() == 'only line\n'
            # Give the forwarder thread time to detect EOF
            time.sleep(0.1)
            assert reader.readline() == ''
        finally:
            reader.close()
    
    def test_handles_line_without_trailing_newline(self) -> None:
        """Test that a line without a trailing newline is returned on EOF."""
        source = StringIO('no newline at end')
        reader = SelectableReader(source)
        try:
            # Give the forwarder thread time to process
            time.sleep(0.1)
            line = reader.readline()
            assert line == 'no newline at end'
        finally:
            reader.close()
    
    def test_fileno_returns_valid_descriptor(self) -> None:
        """Test that fileno() returns a valid file descriptor."""
        source = StringIO('test\n')
        reader = SelectableReader(source)
        try:
            fd = reader.fileno()
            assert isinstance(fd, int)
            assert fd >= 0
        finally:
            reader.close()
    
    def test_works_with_selectors_module(self) -> None:
        """Test that the reader's file descriptor works with selectors."""
        source = StringIO('test line\n')
        reader = SelectableReader(source)
        try:
            sel = selectors.DefaultSelector()
            try:
                sel.register(reader.fileno(), selectors.EVENT_READ)
                
                # Data should become available after forwarder processes it
                events = sel.select(timeout=1.0)
                assert len(events) == 1
                assert events[0][0].fd == reader.fileno()
            finally:
                sel.close()
        finally:
            reader.close()
    
    def test_can_select_alongside_pipe(self) -> None:
        """Test that SelectableReader can be used with select alongside a Pipe."""
        source = StringIO('')  # Empty source, won't produce data
        reader = SelectableReader(source)
        pipe = create_selectable_pipe()
        try:
            sel = selectors.DefaultSelector()
            try:
                sel.register(reader.fileno(), selectors.EVENT_READ, data='reader')
                sel.register(pipe.readable_end.fileno(), selectors.EVENT_READ, data='pipe')
                
                # Write to pipe
                pipe.writable_end.write(b'x')
                
                # Wait for events - pipe should be ready
                events = sel.select(timeout=1.0)
                
                # At least the pipe should be readable
                pipe_events = [e for e in events if e[0].data == 'pipe']
                assert len(pipe_events) == 1
            finally:
                sel.close()
        finally:
            reader.close()
            pipe.readable_end.close()
            pipe.writable_end.close()
    
    def test_handles_unicode_content(self) -> None:
        """Test that unicode content is handled correctly."""
        source = StringIO('héllo wörld 日本語\n')
        reader = SelectableReader(source)
        try:
            line = reader.readline()
            assert line == 'héllo wörld 日本語\n'
        finally:
            reader.close()
    
    def test_handles_empty_lines(self) -> None:
        """Test that empty lines are handled correctly."""
        source = StringIO('\n\ntext\n\n')
        reader = SelectableReader(source)
        try:
            assert reader.readline() == '\n'
            assert reader.readline() == '\n'
            assert reader.readline() == 'text\n'
            assert reader.readline() == '\n'
        finally:
            reader.close()
    
    def test_handles_long_lines(self) -> None:
        """Test that lines longer than the buffer size are handled correctly."""
        # Create a line longer than the 4096 byte buffer
        long_content = 'x' * 10000
        source = StringIO(long_content + '\n')
        reader = SelectableReader(source)
        try:
            line = reader.readline()
            assert line == long_content + '\n'
        finally:
            reader.close()
    
    def test_close_is_idempotent(self) -> None:
        """Test that calling close multiple times is safe."""
        source = StringIO('test\n')
        reader = SelectableReader(source)
        reader.close()
        reader.close()  # Should not raise
        reader.close()  # Should not raise
