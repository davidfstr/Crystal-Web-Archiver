import argparse
import os
import signal
import subprocess
import sys
import threading

_POLL_INTERVAL = 1  # seconds


def main(args: list[str]) -> None:
    # Recognize special "--" argument
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
        '--argsfile',
        help='Path to arguments file.',
        type=str,
    )
    parser.add_argument(
        '--stdouterrfile',
        help='Path to stdout and stderr file.',
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
    stdouterr_filepath = parsed_args.stdouterrfile
    remaining_args = parsed_args.args + extra_remaining_args
    
    # Write arguments file
    with open(args_filepath, 'w', encoding='utf-8') as args_stream:
        args_stream.write(' '.join(remaining_args))
    
    # Create stdouterr log file if missing
    if not os.path.exists(stdouterr_filepath):
        os.makedirs(os.path.dirname(stdouterr_filepath), exist_ok=True)
        with open(stdouterr_filepath, 'wb') as f:
            pass
    
    # 1. Run executable until complete
    # 2. Tail the stdouterr log file
    with open(stdouterr_filepath, encoding='utf-8') as stdouterr_stream:
        process_returncode = None  # type: Optional[int]
        def run_process():
            nonlocal process_returncode
            process = subprocess.run([exe_filepath], check=False)
            process_returncode = process.returncode
        process_thread = threading.Thread(target=run_process, daemon=False)
        process_thread.start()
        
        try:
            while True:
                print(stdouterr_stream.read(), end='')
                sys.stdout.flush()
                
                if not process_thread.is_alive():
                    break
                
                process_thread.join(timeout=_POLL_INTERVAL)
        except KeyboardInterrupt:
            if os.environ.get('CI') == 'true':
                print('*** CI environment is terminating this job with SIGINT.')
                print('*** Is timeout-minutes set too low in push-github-action.yml?')
                # Exit with code (128 + <signal number>) to align with shell conventions
                # https://unix.stackexchange.com/a/386856/380012
                sys.exit(128 + signal.SIGINT)
            else:
                raise
        
        sys.exit(process_returncode if process_returncode is not None else 1)


if __name__ == '__main__':
    main(sys.argv[1:])
