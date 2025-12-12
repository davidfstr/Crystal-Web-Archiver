import argparse
from contextlib import ExitStack
from crystal.util import xtempfile
import os
import signal
import socket
import subprocess
import sys
import threading
from typing import Optional

_POLL_INTERVAL = 1  # seconds


def main(args: list[str]) -> None:
    # Recognize special "---" argument
    try:
        remainder_start = args.index('---')
    except ValueError:
        extra_remaining_args = []
    else:
        extra_remaining_args = args[remainder_start+1:]
        args[remainder_start:] = []
    
    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--stdouterrfile',
        help='Path to stdout and stderr file. Optional.',
        type=str,
        default=None,
    )
    # TODO: Eliminate non-interactive mode once interactive mode has been
    #       more-thoroughly tested and seemed fully stable.
    parser.add_argument(
        '--no-interactive',
        help='Do not forward stdin.',
        action='store_true',
    )
    parser.add_argument(
        'exefile',
        help='Path to .exe file to run.',
        type=str,
    )
    parser.add_argument('args', nargs='*', type=str)
    parsed_args = parser.parse_args(args)  # may raise SystemExit
    
    exe_filepath = parsed_args.exefile
    stdouterr_filepath = parsed_args.stdouterrfile
    interactive = not parsed_args.no_interactive
    remaining_args = parsed_args.args + extra_remaining_args

    if interactive:
        # Use socket-based communication for stdin/stdout/stderr
        _run_with_socket(exe_filepath, remaining_args)
    else:
        # Use file-based communication for stdout/stderr only
        _run_with_file(exe_filepath, remaining_args, stdouterr_filepath)


def _run_with_socket(exe_filepath: str, remaining_args: list[str]) -> None:
    """Run executable with socket-based stdin/stdout/stderr communication."""
    # Create a socket server on a random available port
    process = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(('127.0.0.1', 0))  # bind to any available port
            server_socket.listen(1)
            port = server_socket.getsockname()[1]
            
            # Communicate arguments and socket port to executable via environment variables
            env = os.environ.copy()
            env['CRYSTAL_ARGUMENTS'] = ' '.join(remaining_args)
            env['CRYSTAL_STDINOUT_PORT'] = str(port)
            
            # Start the subprocess
            process = subprocess.Popen([exe_filepath], env=env)
            
            # Wait for subprocess to connect (with timeout)
            server_socket.settimeout(5.0)  # seconds
            try:
                (client_socket, _) = server_socket.accept()
            except socket.timeout:
                print('Error: Subprocess did not connect to socket within timeout', file=sys.stderr)
                process.kill()
                sys.exit(1)
        
        # Set up bidirectional communication with client socket
        with client_socket:
            # Thread to forward stdin to socket
            stdin_thread_exception = None  # type: Optional[Exception]
            def forward_stdin():
                nonlocal stdin_thread_exception
                try:
                    while True:
                        data = sys.stdin.buffer.read(1024)
                        if not data:
                            break
                        client_socket.sendall(data)
                except Exception as e:
                    stdin_thread_exception = e
                finally:
                    # Signal EOF to subprocess by shutting down write side
                    try:
                        client_socket.shutdown(socket.SHUT_WR)
                    except Exception:
                        # Ignore errors on close
                        pass
            
            # NOTE: Don't use bg_call_later here to minimize dependency
            #       on the "crystal" package
            stdin_thread = threading.Thread(  # pylint: disable=no-direct-thread
                target=forward_stdin,
                daemon=True,
            )
            stdin_thread.start()
            
            # Forward socket to stdout/stderr (on main thread)
            try:
                while True:
                    data = client_socket.recv(1024)
                    if not data:
                        break
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
            except OSError as e:
                # [WinError 10054] An existing connection was forcibly closed by the remote host
                if e.errno == 10054:
                    # OK
                    pass
                else:
                    raise
    except KeyboardInterrupt:
        if process is not None:
            process.kill()
        if os.environ.get('CI') == 'true':
            print('*** CI environment is terminating this job with SIGINT.')
            print('*** Is timeout-minutes set too low in ci.yaml?')
            # Exit with code (128 + <signal number>) to align with shell conventions
            # https://unix.stackexchange.com/a/386856/380012
            sys.exit(128 + signal.SIGINT)
        else:
            raise
    
    # Wait for subprocess to complete
    process_returncode = process.wait()
    
    # Warn if stdin thread had an exception
    if stdin_thread_exception is not None:
        # Only report if it's not a harmless "broken pipe" error
        # (which happens when subprocess closes connection)
        if not isinstance(stdin_thread_exception, BrokenPipeError):
            print(f'Warning: Exception in stdin thread: {stdin_thread_exception}', file=sys.stderr)
    
    sys.exit(process_returncode)


def _run_with_file(exe_filepath: str, remaining_args: list[str], stdouterr_filepath: Optional[str]) -> None:
    """Run executable with file-based stdout/stderr communication (no stdin)."""
    with ExitStack() as stack:
        # Create temporary file if path not provided
        if stdouterr_filepath is None:
            stdouterr_file = stack.enter_context(xtempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                delete=True,
                delete_on_close=False,
                suffix='.log'))
            stdouterr_filepath = stdouterr_file.name
            stdouterr_file.close()
        
        # Create stdouterr log file if missing
        if not os.path.exists(stdouterr_filepath):
            os.makedirs(os.path.dirname(stdouterr_filepath), exist_ok=True)
            with open(stdouterr_filepath, 'wb') as f:
                pass
        
        # 1. Run executable until complete
        # 2. Tail the stdouterr log file
        with open(stdouterr_filepath, encoding='utf-8') as stdouterr_stream:
            # Communicate arguments and file path to executable via environment variables
            env = os.environ.copy()
            env['CRYSTAL_ARGUMENTS'] = ' '.join(remaining_args)
            env['CRYSTAL_STDOUTERR_FILE'] = stdouterr_filepath
            
            process_returncode = None  # type: Optional[int]
            def run_process():
                nonlocal process_returncode
                process = subprocess.run([exe_filepath], check=False, env=env)
                process_returncode = process.returncode
            process_thread = threading.Thread(  # pylint: disable=no-direct-thread
                target=run_process,
                daemon=False
            )
            process_thread.start()
            
            try:
                while True:
                    # TODO: Does this only print output after the subprocess exits,
                    #       or does it actually print incrementally?
                    print(stdouterr_stream.read(), end='', flush=True)
                    
                    if not process_thread.is_alive():
                        break
                    
                    process_thread.join(timeout=_POLL_INTERVAL)
            except KeyboardInterrupt:
                if os.environ.get('CI') == 'true':
                    print('*** CI environment is terminating this job with SIGINT.')
                    print('*** Is timeout-minutes set too low in ci.yaml?')
                    # Exit with code (128 + <signal number>) to align with shell conventions
                    # https://unix.stackexchange.com/a/386856/380012
                    sys.exit(128 + signal.SIGINT)
                else:
                    raise
    
    sys.exit(process_returncode if process_returncode is not None else 1)


if __name__ == '__main__':
    main(sys.argv[1:])
