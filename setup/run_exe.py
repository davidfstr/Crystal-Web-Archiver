import argparse
import os
import subprocess
import sys
import threading
import time
from typing import List, Optional


_POLL_INTERVAL = 1  # seconds


def main(args: List[str]) -> None:
    # Recognize special "--" argument
    try:
        remainder_start = args.index('--')
    except ValueError:
        extra_remaining_args = []
    else:
        extra_remaining_args = args[remainder_start+1:]
        args[remainder_start:] = []
    
    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--argsfile',
        help='Path to arguments file.',
        type=str,
    )
    parser.add_argument(
        '--stdoutfile',
        help='Path to stdout file.',
        type=str,
    )
    parser.add_argument(
        '--stderrfile',
        help='Path to stderr file.',
        type=str,
    )
    parser.add_argument(
        'exefile',
        help='Path to .exe file to run.',
        type=str,
    )
    parser.add_argument('args', nargs='*', type=str)
    parsed_args = parser.parse_args(args)  # may raise SystemExit
    
    exe_filepath = parsed_args.exefile
    args_filepath = parsed_args.argsfile
    stdout_filepath = parsed_args.stdoutfile
    stderr_filepath = parsed_args.stderrfile
    remaining_args = parsed_args.args + extra_remaining_args
    
    # Write arguments file
    with open(args_filepath, 'w', encoding='utf-8') as args_stream:
        args_stream.write(' '.join(remaining_args))
    
    # Create stdout log file if missing
    if not os.path.exists(stdout_filepath):
        os.makedirs(os.path.dirname(stdout_filepath), exist_ok=True)
        with open(stdout_filepath, 'wb') as f:
            pass
    
    # Create stderr log file if missing
    if not os.path.exists(stderr_filepath):
        os.makedirs(os.path.dirname(stderr_filepath), exist_ok=True)
        with open(stderr_filepath, 'wb') as f:
            pass
    
    # 1. Run executable until complete
    # 2. Tail the stdout and stderr log files
    with open(stdout_filepath, 'r', encoding='utf-8') as stdout_stream:
        with open(stderr_filepath, 'r', encoding='utf-8') as stderr_stream:
            process_returncode = None  # type: Optional[int]
            def run_process():
                nonlocal process_returncode
                process = subprocess.run([exe_filepath], check=False)
                process_returncode = process.returncode
            process_thread = threading.Thread(target=run_process, daemon=False)
            process_thread.start()
            
            while True:
                print(stdout_stream.read(), end='')
                print(stderr_stream.read(), end='')
                sys.stdout.flush()
                
                if not process_thread.is_alive():
                    break
                
                process_thread.join(timeout=_POLL_INTERVAL)
            
            sys.exit(process_returncode if process_returncode is not None else 1)


if __name__ == '__main__':
    main(sys.argv[1:])
