#!/usr/bin/env python3
"""
Runs end-to-end tests in parallel across subprocesses.
"""

import argparse
from collections.abc import Sequence
from contextlib import closing
from crystal.tests.runner.shared import normalize_test_names
from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.pipes import create_selectable_pipe, Pipe, ReadablePipeEnd
from crystal.util.xfunctools import partial2
from crystal.util.xthreading import bg_affinity, bg_call_later, fg_affinity
from dataclasses import dataclass
import datetime
import faulthandler
import multiprocessing
import os
import queue
from queue import Queue
import selectors
import signal
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
    
    # Determine which tests should be run by each worker
    try:
        worker_task_assignments = _parse_worker_tasks_env(
            num_workers,
            num_tests=len(test_names_to_run),
        )
    except ValueError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return False
    deterministic_mode = worker_task_assignments is not None
    simulate_parent_interrupt = (
        worker_task_assignments is not None and
        worker_task_assignments.interrupt_positions is not None
    )
    
    if verbose:
        print(f'[Runner] Running {len(test_names_to_run)} tests in parallel across {num_workers} workers...', file=sys.stderr)
        if deterministic_mode:
            print(f'[Runner] Deterministic mode enabled via CRYSTAL_PARALLEL_WORKER_TASKS', file=sys.stderr)
        if simulate_parent_interrupt:
            print(f'[Runner] Parent interrupt simulation enabled via "!" in CRYSTAL_PARALLEL_WORKER_TASKS', file=sys.stderr)
    # Create log directory for worker output
    log_dir = _create_log_directory()
    if verbose:
        print(f'[Runner] Worker logs in: {log_dir}', file=sys.stderr)
    
    # Create work queues for each worker
    # NOTE: Work queue items are either:
    #   - A test name (str) to run
    #   - _INTERRUPT_MARKER to signal worker should wait for parent interrupt
    #   - None sentinel to signal end of work
    if worker_task_assignments is not None:
        # Create per-worker queues with assigned tests
        work_queues: list[Queue[Optional[str]]] = []
        for worker_id in range(num_workers):
            worker_queue: Queue[Optional[str]] = Queue()
            
            interrupt_pos = (
                worker_task_assignments.interrupt_positions[worker_id]
                if worker_task_assignments.interrupt_positions is not None
                else None
            )
            task_indexes = worker_task_assignments.task_indexes[worker_id]
            for (i, task_index) in enumerate(task_indexes):
                if interrupt_pos is not None and i == interrupt_pos:
                    worker_queue.put(_INTERRUPT_MARKER)
                worker_queue.put(test_names_to_run[task_index])
            if interrupt_pos is not None and interrupt_pos == len(task_indexes):
                worker_queue.put(_INTERRUPT_MARKER)
            
            worker_queue.put(None)  # sentinel
            
            work_queues.append(worker_queue)
    else:
        # Create shared work queue with all tests
        shared_work_queue: Queue[Optional[str]] = Queue()
        for test_name in test_names_to_run:
            shared_work_queue.put(test_name)
        # Add sentinel values to signal workers to stop
        for _ in range(num_workers):
            shared_work_queue.put(None)
        work_queues = [shared_work_queue] * num_workers  # all workers share the same queue
    
    # Initialize test progress counters
    with _output_lock:
        global _displayed_test_index, _num_tests_to_display
        _displayed_test_index = 0
        _num_tests_to_display = len(test_names_to_run)
    
    # Create shared state for interrupt handling
    interrupted_event = threading.Event()
    
    # Create coordination state for simulated parent interrupt
    # (used when '!' appears in CRYSTAL_PARALLEL_WORKER_TASKS)
    workers_at_interrupt_point: list[threading.Event] = [
        threading.Event() for _ in range(num_workers)
    ]
    
    # Run workers in parallel
    start_time = time.monotonic()  # capture
    worker_results: list[Optional[WorkerResult]] = [None] * num_workers
    worker_results_lock = threading.Lock()
    worker_interrupt_pipes: list[Pipe] = [
        create_selectable_pipe() for i in range(num_workers)
    ]
    if True:
        @capture_crashes_to_stderr
        def run_worker_thread(worker_id: int) -> None:
            result = _run_worker(
                worker_id, work_queues[worker_id], log_dir, verbose,
                interrupted_event,
                worker_interrupt_pipes[worker_id].readable_end,
                display_result_immediately=(not deterministic_mode),
                at_interrupt_point_event=(
                    workers_at_interrupt_point[worker_id]
                    if simulate_parent_interrupt else None
                ),
            )
            with worker_results_lock:
                worker_results[worker_id] = result
        
        # Start workers
        worker_threads = []
        for i in range(num_workers):
            worker_thread = bg_call_later(
                partial2(run_worker_thread, i),
                name=f'Worker-{i}'
            )
            worker_threads.append(worker_thread)
        
        # Wait for all workers to complete
        try:
            if simulate_parent_interrupt:
                # Wait for all workers to reach their '!' interrupt point
                for event in workers_at_interrupt_point:
                    event.wait()
                if verbose:
                    print('[Runner] All workers at interrupt point. Simulating Ctrl-C...', file=sys.stderr)
                # Simulate Ctrl-C by raising KeyboardInterrupt
                raise KeyboardInterrupt()
            else:
                for worker_thread in worker_threads:
                    worker_thread.join()
            all_workers_joined = True
        except KeyboardInterrupt:
            # Ctrl-C pressed
            if verbose:
                print('\n[Runner] Received Ctrl-C. Shutting down workers...', file=sys.stderr)
            
            _interrupt_workers(interrupted_event, worker_interrupt_pipes, verbose)
            
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
    for (worker_id, pipe) in enumerate(worker_interrupt_pipes):
        try:
            pipe.writable_end.close()
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
        
        # In deterministic mode, print results in worker order
        # (worker 0's tests first, then worker 1's, etc.)
        if deterministic_mode:
            for worker_id in range(num_workers):
                worker_result = worker_results[worker_id]
                if worker_result is not None:
                    for test_result in worker_result.test_results:
                        _display_test_result(test_result)
        
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


def _parse_worker_tasks_env(num_workers: int, num_tests: int) -> 'Optional[WorkerTaskAssignments]':
    """
    Parse the CRYSTAL_PARALLEL_WORKER_TASKS environment variable.
    
    Format: '0,2;1' means worker 0 gets test indexes 0,2 and worker 1 gets test index 1.
    
    If a '!' appears in the value, it indicates where the parent process should be
    interrupted (simulating Ctrl-C). For example '0,!;!,1' means:
    - Worker 0 runs test 0, then pauses at the '!' point
    - Worker 1 pauses at the '!' point, then would run test 1
    - When all workers reach their '!' point, a KeyboardInterrupt is raised in the parent
    
    Returns:
    * WorkerTaskAssignments containing task indexes and interrupt info, or None if env var is not set.
    
    Raises:
    * ValueError -- if the format is invalid.
    """
    env_value = os.environ.get('CRYSTAL_PARALLEL_WORKER_TASKS')
    if not env_value:
        return None
    
    has_interrupt_marker = '!' in env_value
    
    worker_task_indexes: list[list[int]] = []
    worker_interrupt_positions: list[int | None] = []  # position of '!' in each worker's task list
    
    for worker_spec in env_value.split(';'):
        if not worker_spec:
            worker_task_indexes.append([])
            worker_interrupt_positions.append(None)
        else:
            task_indexes: list[int] = []
            interrupt_position: int | None = None
            position = 0
            for item in worker_spec.split(','):
                item = item.strip()
                if item == '!':
                    if interrupt_position is not None:
                        raise ValueError(
                            f'CRYSTAL_PARALLEL_WORKER_TASKS has multiple "!" in one worker spec: {env_value!r}'
                        )
                    interrupt_position = position
                    # (Don't increment position. '!' is not a real task.)
                else:
                    try:
                        task_indexes.append(int(item))
                    except ValueError:
                        raise ValueError(
                            f'Invalid CRYSTAL_PARALLEL_WORKER_TASKS format: {env_value!r}'
                        )
                    position += 1
            worker_task_indexes.append(task_indexes)
            worker_interrupt_positions.append(interrupt_position)
    
    # Validate worker count matches
    if len(worker_task_indexes) != num_workers:
        raise ValueError(
            f'CRYSTAL_PARALLEL_WORKER_TASKS specifies {len(worker_task_indexes)} workers, '
            f'but -j/--jobs specifies {num_workers} workers.'
        )
    
    # Validate interrupt markers: if any worker has '!', all workers must have exactly one '!'
    if has_interrupt_marker:
        for (worker_id, interrupt_pos) in enumerate(worker_interrupt_positions):
            if interrupt_pos is None:
                raise ValueError(
                    f'CRYSTAL_PARALLEL_WORKER_TASKS has "!" but worker {worker_id} is missing "!". '
                    f'When using "!", every worker must have exactly one "!".'
                )
    
    # Validate all test indexes are valid and exactly cover all tests
    all_assigned_indexes = set()
    for task_indexes in worker_task_indexes:
        for task_index in task_indexes:
            if task_index < 0 or task_index >= num_tests:
                raise ValueError(
                    f'CRYSTAL_PARALLEL_WORKER_TASKS contains invalid test index {task_index}. '
                    f'Valid range is 0-{num_tests-1}.'
                )
            if task_index in all_assigned_indexes:
                raise ValueError(
                    f'CRYSTAL_PARALLEL_WORKER_TASKS assigns test index {task_index} to multiple workers.'
                )
            all_assigned_indexes.add(task_index)
    
    if all_assigned_indexes != set(range(num_tests)):
        missing = set(range(num_tests)) - all_assigned_indexes
        raise ValueError(
            f'CRYSTAL_PARALLEL_WORKER_TASKS does not assign all tests. '
            f'Missing test indexes: {sorted(missing)}'
        )
    
    return WorkerTaskAssignments(
        task_indexes=worker_task_indexes,
        interrupt_positions=worker_interrupt_positions if has_interrupt_marker else None,
    )


@dataclass(frozen=True)
class WorkerTaskAssignments:
    """Parsed result of CRYSTAL_PARALLEL_WORKER_TASKS environment variable."""
    task_indexes: list[list[int]]  # test indexes for each worker
    interrupt_positions: list[int | None] | None  # position of '!' in each worker's task list, or None if no interrupts


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


def _interrupt_workers(
        interrupted_event: threading.Event,
        worker_interrupt_pipes: list[Pipe],
        verbose: bool,
        ) -> None:
    # Signal workers to stop
    interrupted_event.set()
    
    # Signal workers via interrupt pipes to unblock any stuck reads
    for (worker_id, pipe) in enumerate(worker_interrupt_pipes):
        try:
            # Send interrupt signal byte
            pipe.writable_end.write(b'\x00')
        except Exception as e:
            if verbose:
                print(f'[Runner] Failed to signal worker {worker_id} via pipe: {e}', file=sys.stderr)


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

# Special marker in work queue that signals worker should wait for parent interrupt
_INTERRUPT_MARKER = '!'


@dataclass(frozen=True)
class WorkerResult:
    """Result of a worker subprocess."""
    test_results: 'list[TestResult]'
    duration: float
    returncode: int | Literal[-1]  # -1 if process did not terminate


@dataclass(frozen=True)
class TestResult:
    """Result of running a single test."""
    name: str
    status: str  # 'OK', 'SKIP', 'FAILURE', 'ERROR', 'INTERRUPTED'
    skip_reason: Optional[str]
    output_lines: list[str]
    
    # Tell pytest this class is not a test suite, despite being named "Test*"
    __test__ = False


# Global lock for serializing output from multiple workers
_output_lock = threading.Lock()

# Counters for tracking test progress (protected by _output_lock)
_displayed_test_index = 0
_num_tests_to_display: int | None = None


@bg_affinity
def _run_worker(
        worker_id: int,
        work_queue: Queue[Optional[str]],
        log_dir: str,
        verbose: bool,
        interrupted_event: threading.Event,
        interrupt_read_pipe: 'ReadablePipeEnd',
        display_result_immediately: bool = True,
        at_interrupt_point_event: threading.Event | None = None,
        ) -> WorkerResult:
    """
    Run a worker subprocess in interactive mode, pulling tests from work_queue on-demand.
    
    Implementation notes:
    - Runs in the parent process that is controlling worker subprocesses,
      on a background thread.
    - Is prepared to be interrupted at any time by its caller,
      through interrupted_event and interrupt_read_pipe.
        - Is NOT prepared to handle KeyboardInterrupt exceptions itself,
          because it always runs in a background thread, and background threads
          never receive KeyboardInterrupt exceptions directly.
    - Is prepared for its worker subprocess to unexpectedly terminate, for several reasons:
        - A Ctrl-C signal may interrupt the worker subprocess.
        - A segfault while running tests may terminate the worker subprocess.
    
    Arguments:
    * worker_id -- ID of this worker (for logging).
    * work_queue -- Queue of test names to run. None sentinel indicates no more work.
        May contain _INTERRUPT_MARKER to signal worker should pause at that point.
    * log_dir -- Directory to write log files to.
    * verbose -- Whether to print verbose diagnostic information.
    * interrupted_event -- Event that is set when Ctrl-C is pressed.
    * interrupt_read_pipe -- File descriptor for interrupt signaling.
    * display_result_immediately -- Whether to print test results as they complete.
        If False, results are only returned in the WorkerResult.
    * at_interrupt_point_event -- Event to set when worker reaches _INTERRUPT_MARKER.
        The worker will then wait for interrupted_event to be set before continuing.
    
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
            print(f'[Worker {worker_id}] Starting with pid {process.pid}', file=sys.stderr)
        
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
                    except queue.Empty:
                        # Timeout. Check for interrupts and try again.
                        continue
                    
                    # Check for sentinel value, indicating no more work
                    if test_name is None:
                        if verbose:
                            print(f'[Worker {worker_id}] No more work, shutting down', file=sys.stderr)
                        break
                    
                    # Check for interrupt marker,
                    # indicating should pause and wait for parent to interrupt
                    if test_name == _INTERRUPT_MARKER:
                        if verbose:
                            print(f'[Worker {worker_id}] Reached interrupt point, waiting...', file=sys.stderr)
                        if at_interrupt_point_event is not None:
                            at_interrupt_point_event.set()
                        # Wait for the parent to signal interruption
                        interrupted_event.wait()
                        if verbose:
                            print(f'[Worker {worker_id}] Received interrupt signal', file=sys.stderr)
                        break
                    
                    if verbose:
                        print(f'[Worker {worker_id}] Running test: {test_name}', file=sys.stderr)
                    
                    # Send test name to subprocess
                    process.stdin.write(test_name + '\n')
                    process.stdin.flush()
                    
                    # Read test output until we see the next prompt
                    (test_output_lines, status) = _read_until_prompt(reader)
                    process_is_interrupted = (
                        status == 'interrupted' or
                        (status == 'eof' and process.poll() == -signal.SIGINT)
                    )
                    
                    # Parse the test result
                    test_result = _parse_test_result(
                        test_name,
                        test_output_lines,
                        interrupted=process_is_interrupted,
                    )
                    test_results.append(test_result)
                    tests_run += 1
                    
                    # Display the test result immediately (unless deferred)
                    if display_result_immediately:
                        _display_test_result(test_result)
                    
                    if process_is_interrupted:
                        break
                
                # Close stdin to signal end of interactive mode
                process.stdin.close()
                
                # Read any remaining output (summary section)
                try:
                    while (line := reader.readline()):
                        pass
                except InterruptedError:
                    pass
                
                # Wait for process to complete
                returncode = process.wait()
            else:
                assert_never(status)
    except Exception as e:
        if isinstance(e, BrokenPipeError):
            if verbose:
                print(f'[Worker {worker_id}] Interrupted. Shutting down.', file=sys.stderr)
        else:
            print(f'[Worker {worker_id}] Unexpected exception. Shutting down.', file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        # (keep going)
    finally:
        assert process.stdin is not None
        assert process.stdout is not None
        
        # Close subprocess streams to avoid BrokenPipeError in __del__
        # when the subprocess has already terminated
        try:
            process.stdin.close()
        except Exception:
            pass  # Already closed
        try:
            process.stdout.close()
        except Exception:
            pass  # Already closed
        
        # Ensure process is terminated
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                print(
                    f'[Runner] Warning: Timed out waiting for worker {worker_id} process to terminate.',
                    file=sys.stderr)
        
        # Close interrupt pipe read-end.
        # (The write-end will be closed by the main thread.)
        try:
            interrupt_read_pipe.close()
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
        if line == 'SUMMARY':
            if len(lines) >= 1 and lines[-1] == _DOUBLE_SEPARATOR_LINE:
                del lines[-1]
            return (lines, 'interrupted')
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
    * interrupted -- Whether the test run in this process was interrupted.
    
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
            output_lines=['ERROR (Incomplete test prefix lines. Did the test segfault?)', ''],
        )
    output_lines = output_lines[3:]  # reinterpret
    
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
                output_lines=output_lines + ['ERROR (No test status line. Did the test segfault?)', ''],
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
    global _displayed_test_index
    
    with _output_lock:
        # Don't display INTERRUPTED tests that were never started
        if test_result.status == 'INTERRUPTED' and not test_result.output_lines:
            return
        
        # Calculate percentage suffix
        _displayed_test_index += 1
        if _num_tests_to_display is not None:
            (numer, denom) = (_displayed_test_index, _num_tests_to_display)
            percent_suffix = f' [{int(numer*100/denom)}%]'
        else:
            percent_suffix = ''
        
        print(_DOUBLE_SEPARATOR_LINE)
        short_name = test_result.name.split('.')[-1] if '.' in test_result.name else test_result.name
        print(f'RUNNING: {short_name} ({test_result.name}){percent_suffix}')
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
            interrupt_read_pipe: 'ReadablePipeEnd',
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
        
        line = self.source.readline()
        
        if line:
            self.log_file.write(line)
            self.log_file.flush()
        
        return line
    
    def close(self) -> None:
        self.source.close()
        try:
            # NOTE: May raise `OSError: [Errno 9] Bad file descriptor` if
            #       log_file has never been read from.
            self.log_file.close()
        except Exception:
            pass


# ------------------------------------------------------------------------------

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
