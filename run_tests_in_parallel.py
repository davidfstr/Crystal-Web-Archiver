#!/usr/bin/env python3
"""
Runs Crystal end-to-end tests in parallel across 2 subprocesses.

Usage:
    python run_tests_in_parallel.py [test_name1 test_name2 ...]

If no test names are provided, runs all tests.

This script splits the tests into 2 groups and runs them in parallel,
streaming output as tests complete.
"""

import argparse
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
import datetime
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from typing import IO, Optional


# === Main ===

def main(args: Sequence[str]) -> int:
    """
    Main entry point.
    
    Args:
        args: Command line arguments (test names)
    
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    parser = argparse.ArgumentParser(
        description='Run Crystal tests in parallel across 2 subprocesses.'
    )
    parser.add_argument(
        'test_names',
        nargs='*',
        help='Optional test names to run. If not provided, runs all tests.'
    )
    parsed_args = parser.parse_args(args)
    
    # Get test names to run
    if parsed_args.test_names:
        test_names = parsed_args.test_names
    else:
        # Get all available tests
        test_names = get_all_test_names()
    
    print(f'[Runner] Running {len(test_names)} tests in parallel across 2 workers...', file=sys.stderr)
    
    # Create log directory for worker output
    log_dir = create_log_directory()
    print(f'[Runner] Worker logs in: {log_dir}', file=sys.stderr)
    
    # Split tests into 2 groups
    NUM_WORKERS = 2
    test_groups = split_tests(test_names, NUM_WORKERS)
    
    for i, group in enumerate(test_groups):
        print(f'[Runner] Worker {i}: {len(group)} tests', file=sys.stderr)
    
    # Run workers in parallel using threads
    # (threads are sufficient since each worker runs a subprocess)
    worker_results: list[Optional[WorkerResult]] = [None] * NUM_WORKERS
    total_duration: float
    if True:
        def run_worker_thread(worker_id: int, test_group: list[str]) -> None:
            worker_results[worker_id] = \
                run_worker(worker_id, test_group, log_dir)
        
        start_time = time.monotonic()
        
        threads = []
        for (i, test_group) in enumerate(test_groups):
            # NOTE: Don't use bg_call_later() here, which is part of "crystal"
            #       infrastructure, so that this module stays self-contained
            thread = threading.Thread(  # pylint: disable=no-direct-thread
                target=run_worker_thread,
                args=(i, test_group),
                name=f'Worker-{i}'
            )
            thread.start()
            threads.append(thread)
        
        # Wait for all workers to complete
        for thread in threads:
            thread.join()
        
        total_duration = time.monotonic() - start_time
    
    # Ensure all workers completed
    assert all(result is not None for result in worker_results)
    
    # Gather all test results
    all_test_results: list[TestResult] = []
    for worker_result in worker_results:
        assert worker_result is not None
        all_test_results.extend(worker_result.test_results)
    
    # Format and print summary (individual tests already printed during streaming)
    (summary, is_ok) = format_summary(all_test_results, total_duration)
    print(summary)
    
    # Play bell sound in terminal (like crystal --test does)
    print('\a', end='', flush=True)
    
    return 0 if is_ok else 1


def get_all_test_names() -> list[str]:
    """
    Get all available test names by importing Crystal's test index.
    
    Returns:
        List of fully qualified test names (e.g., 'crystal.tests.test_workflows.test_function')
    """
    # Add src directory to path so we can import crystal modules
    src_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'src')
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    
    from crystal.tests.index import _TEST_FUNCS
    
    test_names = []
    for test_func in _TEST_FUNCS:
        module_name = test_func.__module__
        func_name = test_func.__name__
        test_names.append(f'{module_name}.{func_name}')
    
    return test_names


def create_log_directory() -> str:
    """
    Create a timestamped directory for worker log files.
    
    Returns:
        Path to the created directory
    """
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d-%H%M')
    log_dir = os.path.join(tempfile.gettempdir(), f'{timestamp}-crystal-tests')
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def split_tests(test_names: list[str], num_workers: int) -> list[list[str]]:
    """
    Split test names into groups for parallel execution.
    
    For now, this uses simple round-robin distribution.
    In the future, this could be made smarter by considering test duration history.
    
    Args:
        test_names: List of test names to split
        num_workers: Number of worker processes
    
    Returns:
        List of test name groups, one per worker
    """
    groups: list[list[str]] = [[] for _ in range(num_workers)]
    
    for i, test_name in enumerate(test_names):
        groups[i % num_workers].append(test_name)
    
    return groups


def format_summary(all_tests: 'list[TestResult]', total_duration: float) -> tuple[str, bool]:
    """
    Format the summary section in the same format as `crystal --test`.
    
    Individual test results have already been printed during streaming.
    
    Args:
        all_tests: All completed test results
        total_duration: Total time taken
    
    Returns:
        Tuple of (formatted summary string, is_ok boolean)
    """
    output_lines = []
    
    # Print summary header
    output_lines.append('=' * 70)
    output_lines.append('SUMMARY')
    output_lines.append('-' * 70)
    
    # Create summary character string (like "c......c")
    summary_chars = []
    for test in all_tests:
        if test.status == 'OK':
            summary_chars.append('.')
        elif test.status == 'SKIP':
            # Tests skipped because they're covered by other tests use 'c'
            if test.skip_reason and test.skip_reason.startswith('covered by:'):
                summary_chars.append('c')
            else:
                summary_chars.append('s')
        elif test.status == 'FAILURE':
            summary_chars.append('F')
        elif test.status == 'ERROR':
            summary_chars.append('E')
        else:
            summary_chars.append('?')
    
    output_lines.append(''.join(summary_chars))
    output_lines.append('-' * 70)
    output_lines.append(f'Ran {len(all_tests)} tests in {total_duration:.3f}s')
    output_lines.append('')
    
    # Count different statuses
    num_ok = sum(1 for t in all_tests if t.status == 'OK')
    num_skip = sum(1 for t in all_tests if t.status == 'SKIP')
    num_failure = sum(1 for t in all_tests if t.status == 'FAILURE')
    num_error = sum(1 for t in all_tests if t.status == 'ERROR')
    
    is_ok = (num_failure == 0 and num_error == 0)
    
    if is_ok:
        if num_skip > 0:
            output_lines.append(f'OK (skipped={num_skip})')
        else:
            output_lines.append('OK')
    else:
        status_parts = []
        if num_failure > 0:
            status_parts.append(f'failures={num_failure}')
        if num_error > 0:
            status_parts.append(f'errors={num_error}')
        if num_skip > 0:
            status_parts.append(f'skipped={num_skip}')
        output_lines.append(f'FAILED ({", ".join(status_parts)})')
    
    # Print command to rerun failed tests
    if not is_ok:
        failed_tests = [t.name for t in all_tests if t.status in ('FAILURE', 'ERROR')]
        if failed_tests:
            output_lines.append('')
            output_lines.append('Rerun failed tests with:')
            output_lines.append(f'$ crystal --test {" ".join(failed_tests)}')
            output_lines.append('')
    
    return '\n'.join(output_lines), is_ok


# === Worker ===

@dataclass(frozen=True)
class WorkerResult:
    """Result of a worker subprocess."""
    test_results: 'list[TestResult]'
    duration: float
    returncode: int


@dataclass(frozen=True)
class TestResult:
    """Result of running a single test."""
    name: str
    status: str  # 'OK', 'SKIP', 'FAILURE', 'ERROR'
    output: str
    skip_reason: Optional[str] = None


@dataclass(frozen=True)
class PartialTestResult:
    """Partial result of a test that is currently being parsed."""
    short_name: str
    name: str
    percentage: str
    output: list[str]


# Global lock for serializing output from multiple workers
output_lock = threading.Lock()


def run_worker(worker_id: int, test_names: list[str], log_dir: str) -> WorkerResult:
    """
    Run a worker subprocess with the given test names, streaming output in real-time.
    
    Args:
        worker_id: ID of this worker (for logging)
        test_names: List of test names to run
        log_dir: Directory to write log files to
    
    Returns:
        WorkerResult containing test results and metadata
    """
    if not test_names:
        return WorkerResult(test_results=[], duration=0.0, returncode=0)
    
    print(f'[Worker {worker_id}] Starting with {len(test_names)} tests', file=sys.stderr)
    
    start_time = time.monotonic()
    
    # Start subprocess with streaming output
    process = subprocess.Popen(
        ['crystal', '--test'] + test_names,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # Merge stderr into stdout
        text=True,
        bufsize=1,  # Line buffered
    )
    assert process.stdout is not None
    
    # Create log file for this worker
    log_file_path = os.path.join(log_dir, f'worker{worker_id}-pid{process.pid}.log')
    print(f'[Worker {worker_id}] Logging to: {log_file_path}', file=sys.stderr)
    
    # Wrap stdout with TeeReader to copy output to log file
    tee_reader = TeeReader(process.stdout, log_file_path)
    with closing(tee_reader):
        
        # - Read test results from subprocess stdout.
        # - Print test results to this process's stdout.
        worker_results = \
            stream_and_parse_test_output(worker_id, tee_reader)
        
        # Wait for process to complete
        returncode = process.wait()
        duration = time.monotonic() - start_time
        
        print(f'[Worker {worker_id}] Completed in {duration:.1f}s with exit code {returncode}', file=sys.stderr)
        
        return WorkerResult(
            test_results=worker_results,
            duration=duration,
            returncode=returncode
        )


def stream_and_parse_test_output(
        worker_id: int,
        stdout: 'IO[str] | TeeReader',
    ) -> list[TestResult]:
    """
    Stream output from a worker subprocess, parsing and displaying test results in real-time.
    
    Expected format:
        ======================================================================
        RUNNING: test_name (crystal.tests.test_module.test_name) [50%]
        ----------------------------------------------------------------------
        ... test output ...
        OK
    
    Args:
        worker_id: ID of the worker (for debugging)
        stdout: stdout stream from the subprocess
    """
    results: list[TestResult] = []
    
    current_test: Optional[PartialTestResult] = None
    seen_separator = False
    
    def complete_current_test() -> None:
        """Complete the current test by parsing its output and displaying it."""
        assert current_test is not None
        
        # Find the last status line in the collected output
        last_status = None
        last_skip_reason = None
        last_status_idx = -1
        for i in range(len(current_test.output) - 1, -1, -1):
            output_line = current_test.output[i].strip()
            if output_line == 'OK':
                last_status = 'OK'
                last_status_idx = i
                break
            elif output_line.startswith('SKIP ('):
                last_status = 'SKIP'
                last_skip_reason = output_line[5:].strip('()')
                last_status_idx = i
                break
            elif output_line == 'SKIP':
                last_status = 'SKIP'
                last_status_idx = i
                break
            elif output_line == 'FAILURE':
                last_status = 'FAILURE'
                last_status_idx = i
                break
            elif output_line.startswith('ERROR ('):
                last_status = 'ERROR'
                last_status_idx = i
                break
        if not last_status:
            raise ValueError(
                f'Unable to locate status line in test output: '
                f'{current_test.output!r}')
        
        # Remove the status line and any separator lines from output
        test_output = current_test.output[:last_status_idx]
        
        # Test complete - display it immediately
        test_result = TestResult(
            name=current_test.name,
            status=last_status,
            output='\n'.join(test_output),
            skip_reason=last_skip_reason
        )
        results.append(test_result)
        
        # Display the test result immediately
        with output_lock:
            print('=' * 70)
            print(f'RUNNING: {current_test.short_name} ({current_test.name}) {current_test.percentage}')
            print('-' * 70)
            for output_line in test_output:
                print(output_line)
            if last_status == 'SKIP' and last_skip_reason:
                print(f'SKIP ({last_skip_reason})')
            else:
                print(last_status)
            print()
            sys.stdout.flush()
    
    for line in stdout:
        line = line.rstrip('\n')
        
        # Check for test start marker
        if line.startswith('RUNNING: '):
            # If we were in a previous test, complete it first
            if current_test is not None and seen_separator:
                complete_current_test()
            
            # Extract test name for the new test
            # Format: "RUNNING: test_name (crystal.tests.test_module.test_name) [50%]"
            match = re.match(r'RUNNING: (.+) \((.+)\)\s*(.*)', line)
            assert match, f'Unable to parse RUNNING line: {line!r}'
            
            current_test = PartialTestResult(
                short_name=match.group(1),
                name=match.group(2),
                percentage=match.group(3).strip(),
                output=[]
            )
            seen_separator = False
        
        # Check for separator line after test name
        elif current_test is not None and not seen_separator and line.startswith('---'):
            seen_separator = True
        
        # Check for summary section starting
        elif line == 'SUMMARY':
            # Summary section starting - process any pending test first
            if current_test is not None and seen_separator:
                complete_current_test()
            
            # Stop processing - we've reached the summary
            break
        
        # Collect output lines while in a test
        elif current_test is not None and seen_separator:
            current_test.output.append(line)
    
    # Skip remainder of summary section
    for line in stdout:
        pass
    
    return results


# === Utility: TeeReader ===

class TeeReader:
    """
    A wrapper around a text stream that copies everything read to a log file.
    Similar to the Unix 'tee' command.
    """
    def __init__(self, source: IO[str], log_file_path: str):
        self.source = source
        self.log_file = open(log_file_path, 'w', encoding='utf-8')
    
    def __iter__(self):
        return self
    
    def __next__(self) -> str:
        line = next(self.source)
        self.log_file.write(line)
        self.log_file.flush()
        return line
    
    def close(self) -> None:
        self.log_file.close()


# ------------------------------------------------------------------------------

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
