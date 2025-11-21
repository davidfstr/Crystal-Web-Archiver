#!/usr/bin/env python3
"""
Runs end-to-end tests in parallel across subprocesses.
"""

import argparse
from collections.abc import Sequence
from contextlib import closing
from crystal.tests.runner.shared import normalize_test_names
from crystal.util.xthreading import fg_affinity
from dataclasses import dataclass
import datetime
import faulthandler
import multiprocessing
import os
from queue import Queue
import select
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from typing import IO, Literal, Optional, assert_never


# === Main ===

def main(args: Sequence[str]) -> int:
    """
    Main entry point.
    
    Arguments:
    * args -- Command line arguments (test names).
    
    Returns:
    * Exit code (0 for success, 1 for failure).
    """
    parser = argparse.ArgumentParser(
        description='Run Crystal tests in parallel across multiple subprocesses.'
    )
    parser.add_argument(
        '-j', '--jobs',
        type=int,
        default=None,
        help='Number of workers to use. Defaults to the number of detected CPU cores.'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Whether to print additional diagnostic information.'
    )
    
    parser.add_argument(
        'test_names',
        nargs='*',
        help='Optional test names to run. If not provided, runs all tests.'
    )
    parsed_args = parser.parse_args(args)
    
    is_ok = run_tests(
        raw_test_names=parsed_args.test_names,
        jobs=parsed_args.jobs,
        verbose=parsed_args.verbose,
    )
    
    return 0 if is_ok else 1


# === Run Tests ===

# NOTE: Must run on the main thread so that it can handle KeyboardInterrupts
@fg_affinity
def run_tests(
        raw_test_names: list[str],
        *, jobs: int | None,
        verbose: bool,
        ) -> bool:
    from crystal.tests.index import TEST_FUNCS
    
    # Get test names to run
    if raw_test_names:
        # Normalize test names to handle various input formats
        try:
            test_names = normalize_test_names(raw_test_names)
        except ValueError as e:
            print(f'ERROR: {e}', file=sys.stderr)
            return False
        
        test_names_to_run = []
        for test_func in TEST_FUNCS:
            test_name = f'{test_func.__module__}.{test_func.__name__}'
            
            # Only run test if it was requested (or if all tests are to be run)
            if len(test_names) > 0:
                if test_name not in test_names and test_func.__module__ not in test_names:
                    continue
            test_names_to_run.append(test_name)
    else:
        # Get all available tests
        test_names_to_run = []
        for test_func in TEST_FUNCS:
            test_name = f'{test_func.__module__}.{test_func.__name__}'
            test_names_to_run.append(test_name)
    
    # Determine number of workers
    num_workers = jobs if jobs is not None else multiprocessing.cpu_count()
    
    if verbose:
        print(f'[Runner] Running {len(test_names_to_run)} tests in parallel across {num_workers} workers...', file=sys.stderr)
    # Create log directory for worker output
    log_dir = _create_log_directory()
    if verbose:
        print(f'[Runner] Worker logs in: {log_dir}', file=sys.stderr)
    
    # Create work queue with all tests
    work_queue: Queue[Optional[str]] = Queue()
    for test_name in test_names_to_run:
        work_queue.put(test_name)
    # Add sentinel values to signal workers to stop
    for _ in range(num_workers):
        work_queue.put(None)
    
    # Create shared state for interrupt handling
    interrupted_event = threading.Event()
    
    # Run workers in parallel
    start_time = time.monotonic()  # capture
    worker_results: list[Optional[WorkerResult]] = [None] * num_workers
    worker_results_lock = threading.Lock()
    worker_interrupt_pipes: list[tuple[int, int]] = [
        os.pipe() for i in range(num_workers)
    ]  # tuples of (interrupt_read_pipe, interrupt_write_pipe)
    if True:
        def run_worker_thread(worker_id: int) -> None:
            result = _run_worker(
                worker_id, work_queue, log_dir, verbose,
                interrupted_event, worker_interrupt_pipes[worker_id][0],
            )
            with worker_results_lock:
                worker_results[worker_id] = result
        
        # Start workers
        worker_threads = []
        for i in range(num_workers):
            # NOTE: Don't use bg_call_later() here, which is part of "crystal"
            #       infrastructure, so that this module stays self-contained
            worker_thread = threading.Thread(  # pylint: disable=no-direct-thread
                target=run_worker_thread,
                args=(i,),
                name=f'Worker-{i}'
            )
            worker_thread.start()
            worker_threads.append(worker_thread)
        
        # Wait for all workers to complete
        try:
            for worker_thread in worker_threads:
                worker_thread.join()
            all_workers_joined = True
        except KeyboardInterrupt:
            # Ctrl-C pressed
            if verbose:
                print('\n[Runner] Received Ctrl-C, shutting down workers...', file=sys.stderr)
            
            # Signal workers to stop
            interrupted_event.set()
            
            # Signal workers via interrupt pipes to unblock any stuck reads
            with worker_results_lock:
                for (worker_id, (_, interrupt_write_pipe)) in enumerate(worker_interrupt_pipes):
                    try:
                        # Send interrupt signal byte
                        os.write(interrupt_write_pipe, b'\x00')
                    except Exception as e:
                        if verbose:
                            print(f'[Runner] Failed to signal worker {worker_id} via pipe: {e}', file=sys.stderr)
            
            # Wait for workers to finish gracefully
            all_workers_joined = True  # may be overridden
            for (worker_id, worker_thread) in enumerate(worker_threads):
                worker_thread.join(timeout=2.0)
                if worker_thread.is_alive():  # timed out
                    print(
                        f'[Runner] *** Timed out waiting for worker {worker_id} to terminate. '
                        f'Summary below may be missing data from this worker. '
                        f'Tracebacks of all threads:\n', file=sys.stderr)
                    faulthandler.dump_traceback(file=sys.stderr)
                    print('', file=sys.stderr)
                    all_workers_joined = False
        
        end_time = time.monotonic()  # capture
    
    # Clean up interrupt pipes
    for (worker_id, (_, interrupt_write_pipe)) in enumerate(worker_interrupt_pipes):
        try:
            os.close(interrupt_write_pipe)
        except Exception:
            pass  # Already closed or error
    
    with worker_results_lock:
        if all_workers_joined:
            # Ensure all workers completed (they should have all set their results)
            missing_results = False
            for (worker_id, worker_result) in enumerate(worker_results):
                if worker_result is None:
                    print(f'[Runner] *** Missing results from worker {worker_id} unexpectedly', file=sys.stderr)
                    missing_results = True
            if missing_results:
                return False
        
        # Gather all test results
        completed_test_results: dict[str, TestResult] = {}
        for worker_result in worker_results:
            if worker_result is None:
                # Missing data from a worker.
                # Affected tests will be marked as interrupted.
                continue
            for test_result in worker_result.test_results:
                completed_test_results[test_result.name] = test_result
        
        del worker_results  # prevent further accidental use
    
    # - Build ordered list of results, preserving the original test order.
    # - Mark tests that were never started as interrupted.
    all_test_results: list[TestResult] = []
    for test_name in test_names_to_run:
        if test_name in completed_test_results:
            all_test_results.append(completed_test_results[test_name])
        else:
            # Test was never started (still in queue when interrupted)
            all_test_results.append(TestResult(
                name=test_name,
                status='INTERRUPTED',
                skip_reason=None,
                output_lines=[],  # don't print this test at all
            ))
    
    # Format and print summary (individual tests already printed during streaming)
    (summary, is_ok) = _format_summary(all_test_results, end_time - start_time)
    print(summary)
    
    # Play bell sound in terminal (like crystal --test does)
    print('\a', end='', flush=True)
    
    return is_ok


def _get_all_test_names() -> list[str]:
    """
    Gets all available test names.
    
    Returns:
    * List of fully qualified test names (e.g., 'crystal.tests.test_workflows.test_function').
    """
    from crystal.tests.index import TEST_FUNCS
    
    test_names = []
    for test_func in TEST_FUNCS:
        module_name = test_func.__module__
        func_name = test_func.__name__
        test_names.append(f'{module_name}.{func_name}')
    
    return test_names


def _create_log_directory() -> str:
    """
    Create a timestamped directory for worker log files.
    
    Returns:
    * Path to the created directory.
    """
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d-%H%M')
    log_dir = os.path.join(tempfile.gettempdir(), f'{timestamp}-crystal-tests')
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def _format_summary(all_tests: 'list[TestResult]', total_duration: float) -> tuple[str, bool]:
    """
    Format the summary section in the same format as `crystal --test`.
    
    Individual test results have already been printed during streaming.
    
    Arguments:
    * all_tests -- All completed test results.
    * total_duration -- Total time taken.
    
    Returns:
    * Tuple of (formatted summary string, is_ok boolean).
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
        elif test.status == 'INTERRUPTED':
            summary_chars.append('-')
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
    num_interrupted = sum(1 for t in all_tests if t.status == 'INTERRUPTED')
    
    is_ok = (num_failure == 0 and num_error == 0 and num_interrupted == 0)
    
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
        if num_interrupted > 0:
            status_parts.append(f'interrupted={num_interrupted}')
        if num_skip > 0:
            status_parts.append(f'skipped={num_skip}')
        output_lines.append(f'FAILED ({", ".join(status_parts)})')
    
    # Print command to rerun failed tests
    if not is_ok:
        failed_tests = [t.name for t in all_tests if t.status in ('FAILURE', 'ERROR')]
        interrupted_tests = [t.name for t in all_tests if t.status == 'INTERRUPTED']
        
        if failed_tests:
            output_lines.append('')
            output_lines.append('Rerun failed tests with:')
            output_lines.append(f'$ crystal --test {" ".join(failed_tests)}')
        
        if interrupted_tests:
            output_lines.append('')
            output_lines.append('Rerun interrupted tests with:')
            output_lines.append(f'$ crystal --test {" ".join(interrupted_tests)}')
    
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
    status: str  # 'OK', 'SKIP', 'FAILURE', 'ERROR', 'INTERRUPTED'
    skip_reason: Optional[str]
    output_lines: list[str]


# Global lock for serializing output from multiple workers
_output_lock = threading.Lock()


def _run_worker(
        worker_id: int,
        work_queue: Queue[Optional[str]],
        log_dir: str,
        verbose: bool,
        interrupted_event: threading.Event,
        interrupt_read_pipe: int,
        ) -> WorkerResult:
    """
    Run a worker subprocess in interactive mode, pulling tests from work_queue on-demand.
    
    Arguments:
    * worker_id -- ID of this worker (for logging).
    * work_queue -- Queue of test names to run. None sentinel indicates no more work.
    * log_dir -- Directory to write log files to.
    * verbose -- Whether to print verbose diagnostic information.
    * interrupted_event -- Event that is set when Ctrl-C is pressed.
    * interrupt_read_pipe -- File descriptor for interrupt signaling.
    
    Returns:
    * WorkerResult containing test results and metadata.
    """
    start_time = time.monotonic()
    test_results: list[TestResult] = []
    tests_run = 0
    
    try:
        # Start subprocess in interactive test mode
        process = subprocess.Popen(
            ['crystal', 'test', '--interactive'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout
            text=True,
            bufsize=1,  # Line buffered
        )
        assert process.stdin is not None
        assert process.stdout is not None
        
        # Create log file for this worker
        log_file_path = os.path.join(log_dir, f'worker{worker_id}-pid{process.pid}.log')
        if verbose:
            print(f'[Worker {worker_id}] Starting', file=sys.stderr)
        
        # Wrap stdout to copy output to log file and to provide interruptability
        reader = InterruptableTeeReader(
            process.stdout, interrupt_read_pipe, log_file_path
        )
        with closing(reader):
            
            # Read and discard the initial prompt
            (_, status) = _read_until_prompt(reader)
            if status == 'interrupted' or status == 'eof':
                # Interrupted (or crashed) before initial prompt read
                pass
            elif status == 'found':
                # Feed tests to the subprocess one at a time
                while True:
                    # Check if we've been interrupted
                    if interrupted_event is not None and interrupted_event.is_set():
                        if verbose:
                            print(f'[Worker {worker_id}] Interrupted, shutting down', file=sys.stderr)
                        break
                    
                    # Get next test from queue (blocking with timeout to check for interrupts)
                    try:
                        test_name = work_queue.get(timeout=0.1)
                    except:
                        # Timeout. Check for interrupts and try again.
                        continue
                    
                    # Check for sentinel value indicating no more work
                    if test_name is None:
                        if verbose:
                            print(f'[Worker {worker_id}] No more work, shutting down', file=sys.stderr)
                        break
                    
                    if verbose:
                        print(f'[Worker {worker_id}] Running test: {test_name}', file=sys.stderr)
                    
                    # Send test name to subprocess
                    process.stdin.write(test_name + '\n')
                    process.stdin.flush()
                    
                    # Read test output until we see the next prompt
                    (test_output_lines, status) = _read_until_prompt(reader)
                    
                    # Parse the test result
                    test_result = _parse_test_result(
                        test_name,
                        test_output_lines,
                        interrupted=(status == 'interrupted'),
                    )
                    test_results.append(test_result)
                    tests_run += 1
                    
                    # Display the test result immediately
                    _display_test_result(test_result)
                
                # Close stdin to signal end of interactive mode
                process.stdin.close()
                
                # Read any remaining output (summary section)
                try:
                    while (line := reader.readline()):
                        pass
                except InterruptedError:
                    pass
            else:
                assert_never(status)
            
            # Wait for process to complete
            returncode = process.wait()
    except Exception as e:
        if isinstance(e, BrokenPipeError):
            if verbose:
                print(f'[Worker {worker_id}] Interrupted. Shutting down.', file=sys.stderr)
        else:
            print(f'[Worker {worker_id}] Unexpected exception. Shutting down.', file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        # (keep going)
    finally:
        # Ensure process is terminated
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5.0)
        
        # Close interrupt pipe read-end (write-end will be closed by main thread)
        try:
            os.close(interrupt_read_pipe)
        except Exception:
            pass  # Already closed
    
    duration = time.monotonic() - start_time
    
    maybe_returncode = process.poll()
    returncode = maybe_returncode if maybe_returncode is not None else -1
    
    if verbose:
        print(f'[Worker {worker_id}] Completed {tests_run} tests in {duration:.1f}s with exit code {returncode}', file=sys.stderr)
    
    return WorkerResult(
        test_results=test_results,
        duration=duration,
        returncode=returncode,
    )


def _read_until_prompt(
        reader: 'InterruptableTeeReader'
        ) -> tuple[list[str], Literal['found', 'interrupted', 'eof']]:
    """
    Read lines from reader until we see the 'test>' prompt.
    
    Arguments:
    * reader -- TeeReader to read from.
    
    Returns:
    * Tuple of (list of lines read (excluding the prompt line), status).
    """
    lines = []  # type: list[str]
    while True:
        try:
            line = reader.readline()
        except InterruptedError:
            # Interrupted
            return (lines, 'interrupted')
        if not line:
            # EOF
            return (lines, 'eof')
        
        line = line.rstrip('\n')
        if line == 'test>':
            return (lines, 'found')
        lines.append(line)


_DOUBLE_SEPARATOR_LINE = '=' * 70
_SINGLE_SEPARATOR_LINE = '-' * 70

def _parse_test_result(test_name: str, output_lines: list[str], interrupted: bool) -> TestResult:
    """
    Parse test output to extract the result status.
    
    Expected format:
        ======================================================================
        RUNNING: test_short_name (test_name)
        ----------------------------------------------------------------------
        ... test output ...
        OK|SKIP|FAILURE|ERROR|INTERRUPTED
    
    Arguments:
    * test_name -- Name of the test.
    * output_lines -- Output lines from the test run.
    * interrupted -- Whether the test run was interrupted.
    
    Returns:
    * TestResult containing the parsed test result.
    """
    # Validate and remove prefix lines
    prefix_lines = output_lines[:3]
    prefix_ok = (
        (len(prefix_lines) >= 1 and prefix_lines[0] == _DOUBLE_SEPARATOR_LINE) and
        (len(prefix_lines) >= 2 and prefix_lines[1].startswith('RUNNING: ')) and
        (len(prefix_lines) >= 3 and prefix_lines[2] == _SINGLE_SEPARATOR_LINE)
    )
    if not prefix_ok and not interrupted:
        # Malformed output
        return TestResult(
            name=test_name,
            status='ERROR',
            skip_reason=None,
            output_lines=['ERROR (Invalid prefix lines in test output)', ''],
        )
    del output_lines[:3]
    
    if not interrupted:
        # Find the last status line
        last_status = None
        last_skip_reason = None
        for i in range(len(output_lines) - 1, -1, -1):
            output_line = output_lines[i].strip()
            if output_line == 'OK':
                last_status = 'OK'
                break
            elif output_line.startswith('SKIP ('):
                last_status = 'SKIP'
                last_skip_reason = output_line[5:].strip('()')
                break
            elif output_line == 'SKIP':
                last_status = 'SKIP'
                break
            elif output_line == 'FAILURE':
                last_status = 'FAILURE'
                break
            elif output_line.startswith('ERROR ('):
                last_status = 'ERROR'
                break
            elif output_line == 'INTERRUPTED':
                last_status = 'INTERRUPTED'
                break
        
        if last_status is None:
            # Could not find status
            return TestResult(
                name=test_name,
                status='ERROR',
                skip_reason=None,
                output_lines=output_lines + ['ERROR (Test status line not found)', ''],
            )
    else:
        last_status = 'INTERRUPTED'
        last_skip_reason = None
    
    return TestResult(
        name=test_name,
        status=last_status,
        skip_reason=last_skip_reason,
        output_lines=output_lines,
    )


def _display_test_result(test_result: TestResult) -> None:
    """
    Display a test result to stdout in the same format as `crystal --test`.
    """
    with _output_lock:
        # Don't display INTERRUPTED tests that were never started
        if test_result.status == 'INTERRUPTED' and not test_result.output_lines:
            return
        
        print(_DOUBLE_SEPARATOR_LINE)
        short_name = test_result.name.split('.')[-1] if '.' in test_result.name else test_result.name
        print(f'RUNNING: {short_name} ({test_result.name})')
        print(_SINGLE_SEPARATOR_LINE)
        for line in test_result.output_lines:
            print(line)
        sys.stdout.flush()


# === Utility: TeeReader ===

class InterruptableTeeReader:
    """
    - InterruptableReader: A wrapper around a text stream which enforces that
      every I/O operation performed in an interruptable manner.
    - TeeReader: A wrapper around a text stream that copies everything read 
      to a log file. Similar to the Unix 'tee' command.
    """
    def __init__(self,
            source: IO[str],
            interrupt_read_pipe: int,
            log_file_path: str,
            ) -> None:
        log_file = open(log_file_path, 'w', encoding='utf-8')
        
        self.source = source
        self.interrupt_read_pipe = interrupt_read_pipe
        self.log_file = log_file
        self._interrupted = False
    
    def readline(self) -> str:
        """
        Reads a line from the underlying text stream.
        
        Raises:
        * InterruptedError -- if the read was interrupted.
        """
        if self._interrupted:
            raise InterruptedError()
        
        (readable, _, _) = select.select([
            self.source.fileno(),
            self.interrupt_read_pipe
        ], [], [])
        if self.interrupt_read_pipe in readable:
            self._interrupted = True
            raise InterruptedError()
        line = self.source.readline()
        
        if line:
            self.log_file.write(line)
            self.log_file.flush()
        
        return line
    
    def close(self) -> None:
        self.source.close()
        self.log_file.close()


# ------------------------------------------------------------------------------

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
