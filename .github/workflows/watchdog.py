#!/usr/bin/env python3
"""
Watchdog script that runs a subprocess while monitoring its output.

If the subprocess fails to print anything on stdout/stderr for more than
the specified timeout period, it aborts the subprocess with SIGABRT.
If the subprocess still fails to terminate after 5 seconds, Popen.terminate()
is used to stop the process.

This is useful for CI jobs where test runners might hang indefinitely.

Example usage:
    python3 watchdog.py --timeout=120 -- crystal --test
"""

import argparse
from io import TextIOBase
import os
import signal
import subprocess
import sys
from textwrap import dedent
import threading
import time
from typing import BinaryIO, Optional


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a subprocess with output timeout monitoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent(
            """
            Example:
              python3 watchdog.py --timeout=120 -- crystal --test
              python3 watchdog.py --timeout=300 -- python -m pytest tests/
            """
        )
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Timeout in seconds for subprocess output (default: 120)"
    )
    parser.add_argument(
        "command",
        nargs="+",
        help="Command and arguments to execute"
    )
    
    # Parse arguments, handling -- separator
    if "--" in sys.argv:
        separator_index = sys.argv.index("--")
        watchdog_args = sys.argv[1:separator_index]
        command_args = sys.argv[separator_index + 1:]
        
        args = parser.parse_args(watchdog_args + ['__cmd__'])
        args.command = command_args
    else:
        args = parser.parse_args()
    if not args.command:
        parser.error("No command specified")
    
    # Run the watchdog
    watchdog = SubprocessWatchdog(args.timeout)
    exit_code = watchdog.run(args.command)
    sys.exit(exit_code)


class SubprocessWatchdog:
    _UNINIT_OUTPUT_TIME = -1.0
    
    def __init__(self, timeout_seconds: float) -> None:
        self._timeout_seconds = timeout_seconds
        self._process: Optional[subprocess.Popen] = None
        
        self._lock = threading.Lock()
        self._last_output_time = self._UNINIT_OUTPUT_TIME  # protected by self._lock
        self._aborted = False  # protected by self._lock
    
    def run(self, command: list[str]) -> int:
        """Run the command with watchdog monitoring."""
        with self._lock:
            if self._last_output_time != self._UNINIT_OUTPUT_TIME:
                raise ValueError('Watchdog already running or finished')
            self._last_output_time = time.monotonic()
        
        try:
            # Start the subprocess
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0  # Unbuffered for real-time output
            )
            
            # Start monitoring thread
            monitor_thread = threading.Thread(  # pylint: disable=no-direct-thread
                target=self._monitor_timeout,
                daemon=True
            )
            monitor_thread.start()
            
            # Start output streaming threads
            stdout_thread = threading.Thread(  # pylint: disable=no-direct-thread
                target=self._stream_output, 
                args=(self._process.stdout, sys.stdout),
                daemon=True
            )
            stderr_thread = threading.Thread(  # pylint: disable=no-direct-thread
                target=self._stream_output, 
                args=(self._process.stderr, sys.stderr),
                daemon=True
            )
            stdout_thread.start()
            stderr_thread.start()
            
            # Wait for process to complete, forever
            return_code = self._process.wait()
            
            # Wait for output threads to finish, on a base-effort basis
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            
            with self._lock:
                if self._aborted:
                    # Return a specific exit code to indicate watchdog abortion
                    return 124  # Same as timeout command
            
            return return_code
            
        except KeyboardInterrupt:
            # Handle Ctrl+C gracefully
            if self._process and self._process.poll() is None:
                # Send SIGINT (Ctrl+C) to interrupt process nicely
                os.kill(self._process.pid, signal.SIGINT)
                try:
                    self._process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            return 130  # Standard exit code for SIGINT
        
        except Exception as e:
            print(f"Error running subprocess: {e}", file=sys.stderr)
            return 1
    
    # === Stream Thread ===
    
    def _stream_output(self, stream: BinaryIO, output_file: TextIOBase) -> None:
        """Read from stream and write to output_file while updating last output time."""
        try:
            for line_bytes in iter(stream.readline, b''):
                if line_bytes:
                    self._update_last_output_time()
                    output_file.buffer.write(line_bytes)  # type: ignore[attr-defined]
                    output_file.flush()
        except Exception:
            # Stream closed or other error
            pass
    
    def _update_last_output_time(self) -> None:
        """Update the timestamp of the last output from subprocess."""
        with self._lock:
            self._last_output_time = time.monotonic()
    
    # === Monitor Thread ===
    
    def _monitor_timeout(self) -> None:
        """Monitor thread that checks for timeout and aborts subprocess if needed."""
        while True:
            # Check every second
            time.sleep(1)
            
            with self._lock:
                if self._process is None or self._process.poll() is not None:
                    # Process has finished
                    break
                
                time_since_output = time.monotonic() - self._last_output_time
                if time_since_output <= self._timeout_seconds:
                    continue
                assert not self._aborted
                self._aborted = True
            
            # Send SIGINT (Ctrl+C) to interrupt process nicely
            print(
                f"\n[Watchdog] Sending SIGINT (Ctrl+C) because no output for {self._timeout_seconds} seconds", 
                file=sys.stderr,
                flush=True,
            )
            try:
                os.kill(self._process.pid, signal.SIGINT)
            except (OSError, ProcessLookupError):
                # Process might have already terminated
                pass
            try:
                # Wait for graceful termination
                self._process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                
                # Send SIGABRT to trigger faulthandler if enabled
                print(
                    f"\n[Watchdog] Sending SIGABRT because no response to SIGINT in {5.0} seconds",
                    file=sys.stderr,
                    flush=True,
                )
                try:
                    os.kill(self._process.pid, signal.SIGABRT)
                except (OSError, ProcessLookupError):
                    # Process might have already terminated
                    pass
                try:
                    # Wait for graceful termination
                    self._process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    
                    # Last resort: kill the process
                    print(
                        f"\n[Watchdog] Sending SIGKILL because no response to SIGABRT in {5.0} seconds", 
                        file=sys.stderr,
                        flush=True,
                    )
                    try:
                        self._process.kill()
                    except (OSError, ProcessLookupError):
                        pass
            break


if __name__ == "__main__":
    main()
