"""
Unit tests for the Crystal test runner functionality in:
- crystal.tests.runner
- crystal.tests.util.runner
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager, redirect_stdout
from crystal.tests.runner.parallel import (
    TestResult, WorkerResult, _display_test_result,
    _interrupt_workers, _parse_test_result, _read_until_prompt, _run_worker,
)
from crystal.tests.runner.shared import normalize_test_names
from crystal.util.pipes import create_selectable_pipe, Pipe
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import os
import pytest
import queue
import signal
import sys
import tempfile
import threading
from typing import Any
from unittest import skip
from unittest.mock import patch


# ------------------------------------------------------------------------------
# TestNormalizeTestNames

class TestNormalizeTestNames:
    """Test the normalize_test_names() function with various input formats."""
    
    def test_qualified_module_name(self) -> None:
        """Test that qualified module names work correctly."""
        result = normalize_test_names(['crystal.tests.test_workflows'])
        assert result == ['crystal.tests.test_workflows']
    
    def test_qualified_function_name(self) -> None:
        """Test that qualified function names work correctly."""
        result = normalize_test_names(['crystal.tests.test_workflows.test_can_download_and_serve_a_static_site_using_main_window_ui'])
        assert result == ['crystal.tests.test_workflows.test_can_download_and_serve_a_static_site_using_main_window_ui']
    
    def test_unqualified_module_name(self) -> None:
        """Test that unqualified module names are resolved correctly."""
        result = normalize_test_names(['test_workflows'])
        assert result == ['crystal.tests.test_workflows']
    
    def test_file_path_notation(self) -> None:
        """Test that file path notation is converted correctly."""
        result = normalize_test_names(['src/crystal/tests/test_workflows.py'])
        assert result == ['crystal.tests.test_workflows']
    
    def test_pytest_style_function_notation(self) -> None:
        """Test that pytest-style function notation (::) is converted correctly."""
        result = normalize_test_names(['crystal.tests.test_workflows::test_can_download_and_serve_a_static_site_using_main_window_ui'])
        assert result == ['crystal.tests.test_workflows.test_can_download_and_serve_a_static_site_using_main_window_ui']
    
    def test_unqualified_function_name(self) -> None:
        """Test that unqualified function names are resolved correctly."""
        result = normalize_test_names(['test_can_download_and_serve_a_static_site_using_main_window_ui'])
        assert result == ['crystal.tests.test_workflows.test_can_download_and_serve_a_static_site_using_main_window_ui']
    
    def test_multiple_test_names(self) -> None:
        """Test that multiple test names are all normalized correctly."""
        result = normalize_test_names([
            'test_workflows',
            'crystal.tests.test_bulkheads::test_capture_crashes_to_self_decorator_works',
            'src/crystal/tests/test_xthreading.py'
        ])
        expected = [
            'crystal.tests.test_workflows',
            'crystal.tests.test_bulkheads.test_capture_crashes_to_self_decorator_works',
            'crystal.tests.test_xthreading'
        ]
        assert result == expected
    
    def test_empty_list(self) -> None:
        """Test that an empty list returns an empty list."""
        result = normalize_test_names([])
        assert result == []
    
    def test_nonexistent_module_raises_error(self) -> None:
        """Test that non-existent modules raise a descriptive error."""
        with pytest.raises(ValueError) as exc_info:
            normalize_test_names(['crystal.tests.test_no_such_suite'])
        
        error_msg = str(exc_info.value)
        assert 'Test not found: crystal.tests.test_no_such_suite' in error_msg
        assert 'Available test modules:' in error_msg
    
    def test_nonexistent_unqualified_function_raises_error(self) -> None:
        """Test that non-existent unqualified functions raise a descriptive error."""
        with pytest.raises(ValueError) as exc_info:
            normalize_test_names(['test_no_such_function'])
        
        error_msg = str(exc_info.value)
        assert 'Test not found: test_no_such_function' in error_msg
    
    def test_invalid_pytest_style_format(self) -> None:
        """Test that invalid pytest-style formats raise errors."""
        with pytest.raises(ValueError) as exc_info:
            normalize_test_names(['invalid::format::too::many::colons'])
        
        error_msg = str(exc_info.value)
        assert 'Test not found: invalid::format::too::many::colons' in error_msg
    
    def test_file_path_without_src_prefix(self) -> None:
        """Test that file paths without 'src/' prefix work correctly."""
        result = normalize_test_names(['crystal/tests/test_workflows.py'])
        assert result == ['crystal.tests.test_workflows']
    
    def test_windows_style_file_path(self) -> None:
        """Test that Windows-style file paths work correctly."""
        result = normalize_test_names(['src\\crystal\\tests\\test_workflows.py'])
        assert result == ['crystal.tests.test_workflows']
    
    def test_partial_module_match(self) -> None:
        """Test that partial module names are resolved correctly."""
        # This should match any module ending with test_workflows
        result = normalize_test_names(['test_workflows'])
        assert 'crystal.tests.test_workflows' in result
    
    def test_case_sensitivity(self) -> None:
        """Test that function names are case-sensitive."""
        with pytest.raises(ValueError):
            normalize_test_names(['test_CAN_DOWNLOAD_AND_SERVE_A_STATIC_SITE'])  # Wrong case
    
    def test_function_in_nonexistent_module(self) -> None:
        """Test that functions in non-existent modules raise errors."""
        with pytest.raises(ValueError) as exc_info:
            normalize_test_names(['crystal.tests.test_nonexistent::test_some_function'])
        
        error_msg = str(exc_info.value)
        assert 'Test not found' in error_msg


# ------------------------------------------------------------------------------
# TestInterruptRunParallelTestWorker

# NOTE: `test --parallel` is tested in multiple locations:
# - "# === Testing Tests (test): Parallel ==="
# - TestInterruptRunParallelTestWorker
# - TestParseAndDisplayOutputOfInterruptedParallelTestWorkerProcess

class TestInterruptRunParallelTestWorker:
    """
    Ensures that _run_worker() crystal.tests.runner.parallel will terminate
    gracefully when it is interrupted, at any point while executing.
    """
    _EXAMPLE_TEST_NAME = 'test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors'
    
    def test_when_interrupt_before_subprocess_started_then_exits_gracefully(self) -> None:
        # Strategy:
        # - Wait until the subprocess.Popen() call is in progress,
        #   then trigger the interrupt directly before that call happens.
        #     - Case: Parent process interupted.
        #       Child process never receives interrupt signal.
        #     - Interrupt should be observed on the initial call to _read_until_prompt()
        # 
        # Also:
        # - Ensure that child process eventually terminates
        #   (because parent process terminates it while shutting down)
        
        with self._worker_context() as (run_worker, interrupt_parent_process):
            
            # Mock the subprocess.Popen to return a process that outputs the initial prompt
            child_process = _MockProcess(
                stdout_lines=[
                    # (Interrupt here)
                    #'test>',
                ],
                returncode=None
            )
            
            def mock_popen(*args: Any, **kwargs: Any) -> _MockProcess:
                # Trigger interrupt immediately before subprocess is created
                interrupt_parent_process()
                return child_process
            
            with patch('subprocess.Popen', side_effect=mock_popen):
                result = run_worker()
            
            # Verify the result
            assert [] == result.test_results
            assert -signal.SIGTERM == result.returncode
            
            # Ensure subprocess terminated because parent process terminated it
            # during its own cleanup
            child_process._ensure_terminated_and_no_warnings()
    
    def test_when_interrupt_directly_after_subprocess_started_then_exits_gracefully(self, subtests: pytest.Subtests) -> None:
        # Strategy:
        # - Wait until the subprocess.Popen() call is in progress,
        #   then trigger the interrupt shortly afterward.
        #     - Case 1: Child process interupted before parent process interrupted
        #     - Case 2: Parent process interupted before child process interrupted
        #     - Interrupt should be observed on the initial call to _read_until_prompt()
        
        with subtests.test(target_process='child'):
            with self._worker_context() as (run_worker, interrupt_parent_process):
            
                # Mock the subprocess.Popen to return a process that outputs the initial prompt
                child_process = _MockProcess(
                    stdout_lines=[
                        # (Interrupt here)
                        #'test>',
                    ],
                    returncode=None,
                )
                
                def mock_popen(*args: Any, **kwargs: Any) -> _MockProcess:
                    # Trigger interrupt immediately after subprocess is created
                    child_process.send_signal(signal.SIGINT)
                    return child_process
                
                with patch('subprocess.Popen', side_effect=mock_popen):
                    result = run_worker()
                
                # Verify the result
                assert [] == result.test_results
                assert -signal.SIGINT == result.returncode
                
                # Verify the process was properly terminated
                child_process._ensure_terminated_and_no_warnings()
        
        with subtests.test(target_process='parent'):
            with self._worker_context() as (run_worker, interrupt_parent_process):
                
                # Mock the subprocess.Popen to return a process that outputs the initial prompt
                child_process = _MockProcess(
                    stdout_lines=[
                        # (Interrupt here)
                        #'test>',
                    ],
                    returncode=None,
                )
                    
                def mock_popen(*args: Any, **kwargs: Any) -> _MockProcess:
                    # Trigger interrupt immediately after subprocess is created
                    interrupt_parent_process()
                    return child_process
                
                with patch('subprocess.Popen', side_effect=mock_popen):
                    result = run_worker()
                
                # Verify the result
                assert [] == result.test_results
                assert -signal.SIGTERM == result.returncode
                
                # Verify the process was properly terminated
                child_process._ensure_terminated_and_no_warnings()
    
    def test_when_interrupt_directly_before_reading_initial_prompt_then_exits_gracefully(self, subtests: pytest.Subtests) -> None:
        # Strategy:
        # - Wait until just before_read_until_prompt(),
        #   then trigger the interrupt.
        #     - Case 1: Child process interupted before parent process interrupted
        #     - Case 2: Parent process interupted before child process interrupted
        #     - Interrupt should be observed on the initial call to _read_until_prompt()
        
        with subtests.test(target_process='child'):
            with self._worker_context() as (run_worker, interrupt_parent_process):
                
                # Mock the subprocess.Popen to return a process that will block while reading initial prompt
                child_process = _MockProcess(
                    stdout_lines=[
                        # (Interrupt here)
                        #'test>',
                    ],
                    returncode=None
                )
                
                # Patch _read_until_prompt to trigger interrupt on first call
                call_count = 0
                original_read_until_prompt = _read_until_prompt
                def mock_read_until_prompt(*args: Any, **kwargs: Any) -> Any:
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        # On first call (reading initial prompt), interrupt the child process
                        child_process.send_signal(signal.SIGINT)
                    return original_read_until_prompt(*args, **kwargs)
                
                with patch('subprocess.Popen', return_value=child_process):
                    with patch('crystal.tests.runner.parallel._read_until_prompt', side_effect=mock_read_until_prompt):
                        result = run_worker()
                
                # Verify the result
                assert [] == result.test_results
                assert -signal.SIGINT == result.returncode
                
                # Verify the process was properly terminated
                child_process._ensure_terminated_and_no_warnings()
        
        with subtests.test(target_process='parent'):
            with self._worker_context() as (run_worker, interrupt_parent_process):
                
                # Mock the subprocess.Popen to return a process that will block while reading initial prompt
                child_process = _MockProcess(
                    stdout_lines=[
                        # (Interrupt here)
                        #'test>',
                    ],
                    returncode=None
                )
                
                # Patch _read_until_prompt to trigger interrupt on first call
                call_count = 0
                original_read_until_prompt = _read_until_prompt
                def mock_read_until_prompt(*args: Any, **kwargs: Any) -> Any:
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        # On first call (reading initial prompt), interrupt the parent process
                        interrupt_parent_process()
                    return original_read_until_prompt(*args, **kwargs)
                
                with patch('subprocess.Popen', return_value=child_process):
                    with patch('crystal.tests.runner.parallel._read_until_prompt', side_effect=mock_read_until_prompt):
                        result = run_worker()
                
                # Verify the result
                assert [] == result.test_results
                assert -signal.SIGTERM == result.returncode
                
                # Verify the process was properly terminated
                child_process._ensure_terminated_and_no_warnings()
    
    def test_when_interrupt_while_waiting_for_item_from_work_queue_then_exits_gracefully(self, subtests: pytest.Subtests) -> None:
        # Strategy:
        # - Use an empty work queue
        # - Spy on call to work_queue.get(). When it is called, trigger the interrupt.
        #     - work_queue.get() should return an queue.Empty exception.
        #     - Case 1: Child process interupted before parent process interrupted
        #         - Interrupt should be observed on the next call to process.stdin.write()
        #     - Case 2: Parent process interupted before child process interrupted
        #         - Interrupt should be observed on next cycle of polling loop
        #           that starts with `if interrupted_event is not None and interrupted_event.is_set():`
        
        with subtests.test(target_process='child'):
            work_queue_child: queue.Queue[str | None] = queue.Queue()
            with self._worker_context(work_queue=work_queue_child) as (run_worker, interrupt_parent_process):
                
                # Mock the subprocess.Popen to return a process that outputs the initial prompt
                child_process = _MockProcess(
                    stdout_lines=[
                        'test>',
                        # (Interrupt here)
                    ],
                    returncode=None
                )
                
                # Track calls to work_queue_child.get() and trigger interrupt on first call
                call_count = 0
                original_get = work_queue_child.get
                def mock_queue_get(*args: Any, **kwargs: Any) -> Any:
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        # On first call to get(), interrupt the child process
                        child_process.send_signal(signal.SIGINT)
                    elif call_count == 2:
                        # NOTE: This is a simple, fast test
                        work_queue_child.put(self._EXAMPLE_TEST_NAME)
                    # Call original get() which will:
                    # - Call 1: Raise queue.Empty due to timeout
                    # - Call 2: Return test added to queue
                    return original_get(*args, **kwargs)
                
                with patch('subprocess.Popen', return_value=child_process):
                    with patch.object(work_queue_child, 'get', side_effect=mock_queue_get):
                        result = run_worker()
                
                # Verify the result
                assert [] == result.test_results
                assert -signal.SIGINT == result.returncode
                
                # Verify the process was properly terminated
                child_process._ensure_terminated_and_no_warnings()
        
        with subtests.test(target_process='parent'):
            work_queue_parent: queue.Queue[str | None] = queue.Queue()
            with self._worker_context(work_queue=work_queue_parent) as (run_worker, interrupt_parent_process):
                
                # Mock the subprocess.Popen to return a process that outputs the initial prompt
                child_process = _MockProcess(
                    stdout_lines=[
                        'test>',
                        # (Interrupt here)
                    ],
                    returncode=0  # after process.stdin.close()
                )
                
                # Track calls to work_queue_parent.get() and trigger interrupt on first call
                call_count = 0
                original_get = work_queue_parent.get
                def mock_queue_get(*args: Any, **kwargs: Any) -> Any:
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        # On first call to get(), interrupt the parent process
                        interrupt_parent_process()
                    # Call original get() which will:
                    # - Raise queue.Empty due to timeout
                    return original_get(*args, **kwargs)
                
                with patch('subprocess.Popen', return_value=child_process):
                    with patch.object(work_queue_parent, 'get', side_effect=mock_queue_get):
                        result = run_worker()
                
                # Verify the result
                assert [] == result.test_results
                assert 0 == result.returncode
                
                # Verify the process was properly terminated
                child_process._ensure_terminated_and_no_warnings()
    
    def test_when_interrupt_directly_before_test_requested_to_be_run_then_exits_gracefully(self, subtests: pytest.Subtests) -> None:
        # Strategy:
        # - Wait until the process.stdin.write() call near `# Send test name to subprocess`,
        #   then trigger the interrupt directly before that call happens.
        #     - Case 1: Child process interupted before parent process interrupted
        #         - Interrupt should be observed on the next call to process.stdin.write()
        #     - Case 2: Parent process interupted before child process interrupted
        #         - Interrupt should be observed on the initial call to _read_until_prompt()
        
        with subtests.test(target_process='child'):
            work_queue_child: queue.Queue[str | None] = queue.Queue()
            with self._worker_context(work_queue=work_queue_child) as (run_worker, interrupt_parent_process):
                # Add a test to the queue so worker will proceed to stdin.write() call
                work_queue_child.put(self._EXAMPLE_TEST_NAME)
                work_queue_child.put(None)  # Sentinel to stop after one test
                
                # Mock the subprocess.Popen to return a process that outputs the initial prompt
                child_process = _MockProcess(
                    stdout_lines=[
                        'test>',
                        # (Interrupt here)
                    ],
                    returncode=None
                )
                
                # Track calls to stdin.write() and trigger interrupt on first call
                call_count = 0
                original_write = child_process.stdin.write
                def mock_write(s: str) -> int:
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        # On first call to write(), interrupt the child process
                        child_process.send_signal(signal.SIGINT)
                    # Try to call original write - may fail if process was terminated
                    return original_write(s)
                
                with patch('subprocess.Popen', return_value=child_process):
                    with patch.object(child_process.stdin, 'write', side_effect=mock_write):
                        result = run_worker()
                
                # Verify the result
                assert [] == result.test_results
                assert -signal.SIGINT == result.returncode
                
                # Verify the process was properly terminated
                child_process._ensure_terminated_and_no_warnings()
        
        with subtests.test(target_process='parent'):
            work_queue_parent: queue.Queue[str | None] = queue.Queue()
            with self._worker_context(work_queue=work_queue_parent) as (run_worker, interrupt_parent_process):
                # Add a test to the queue so worker will proceed to stdin.write() call
                work_queue_parent.put(self._EXAMPLE_TEST_NAME)
                
                # Mock the subprocess.Popen to return a process that outputs the initial prompt
                child_process = _MockProcess(
                    stdout_lines=[
                        'test>',
                        # (Interrupt here)
                    ],
                    returncode=0  # after process.stdin.close()
                )
                
                # Track calls to stdin.write() and trigger interrupt on first call
                call_count = 0
                original_write = child_process.stdin.write
                def mock_write(s: str) -> int:
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        # On first call to write(), interrupt the parent process
                        interrupt_parent_process()
                    # Call original write
                    return original_write(s)
                
                with patch('subprocess.Popen', return_value=child_process):
                    with patch.object(child_process.stdin, 'write', side_effect=mock_write):
                        result = run_worker()
                
                # Verify the result
                assert [
                    TestResult(
                        name=self._EXAMPLE_TEST_NAME,
                        status='INTERRUPTED',
                        skip_reason=None,
                        output_lines=[]
                    )
                ] == result.test_results
                assert 0 == result.returncode
                
                # Verify the process was properly terminated
                child_process._ensure_terminated_and_no_warnings()
    
    # NOTE: This is expected to be the MOST COMMON location where interrupts will occur
    def test_when_interrupt_while_subprocess_is_running_test_then_exits_gracefully(self, subtests: pytest.Subtests) -> None:
        # Strategy:
        # - Wait until a few calls to stdout.readline() are made,
        #   then trigger the interrupt shortly afterward.
        #     - Case 1: Child process interupted before parent process interrupted
        #     - Case 2: Parent process interupted before child process interrupted
        #     - Interrupt should be observed on the next call to _read_until_prompt()
        
        with subtests.test(target_process='child'):
            work_queue_child: queue.Queue[str | None] = queue.Queue()
            with self._worker_context(work_queue=work_queue_child) as (run_worker, interrupt_parent_process):
                # Add a test to the queue so worker will proceed to stdin.write() call
                work_queue_child.put(self._EXAMPLE_TEST_NAME)
                work_queue_child.put(None)  # Sentinel to stop after one test
                
                # Mock the subprocess.Popen to return a process that outputs the initial prompt
                child_process = _MockProcess(
                    stdout_lines=[
                        'test>',
                        '======================================================================',
                        f'RUNNING: {self._EXAMPLE_TEST_NAME}',
                        '----------------------------------------------------------------------',
                        'foo',
                        'bar',
                        # (Interrupt here)
                        #'OK',
                        #'',
                    ],
                    returncode=None
                )
                
                # Track calls to stdout.readline() and trigger interrupt on Nth call
                readline_call_count = 0
                original_readline = child_process.stdout.readline
                def mock_readline() -> str:
                    nonlocal readline_call_count
                    readline_call_count += 1
                    if readline_call_count == 7:
                        child_process.send_signal(signal.SIGINT)
                    return original_readline()
                
                with patch('subprocess.Popen', return_value=child_process):
                    with patch.object(child_process.stdout, 'readline', side_effect=mock_readline):
                        result = run_worker()
                
                # Verify the result
                assert [
                    TestResult(
                        name=self._EXAMPLE_TEST_NAME,
                        status='INTERRUPTED',
                        skip_reason=None,
                        output_lines=['foo', 'bar']
                    )
                ] == result.test_results
                assert -signal.SIGINT == result.returncode
                
                # Verify the process was properly terminated
                child_process._ensure_terminated_and_no_warnings()
        
        with subtests.test(target_process='parent'):
            work_queue_parent: queue.Queue[str | None] = queue.Queue()
            with self._worker_context(work_queue=work_queue_parent) as (run_worker, interrupt_parent_process):
                # Add a test to the queue so worker will proceed to stdin.write() call
                work_queue_parent.put(self._EXAMPLE_TEST_NAME)
                
                # Mock the subprocess.Popen to return a process that outputs the initial prompt
                child_process = _MockProcess(
                    stdout_lines=[
                        'test>',
                        '======================================================================',
                        f'RUNNING: {self._EXAMPLE_TEST_NAME}',
                        '----------------------------------------------------------------------',
                        'foo',
                        # (Interrupt signaled here)
                        'bar',
                        # (Interrupt detected here)
                        #'OK',
                        #'',
                    ],
                    returncode=0
                )
                
                # Track calls to stdout.readline() and trigger interrupt on Nth call
                readline_call_count = 0
                original_readline = child_process.stdout.readline
                def mock_readline() -> str:
                    nonlocal readline_call_count
                    readline_call_count += 1
                    if readline_call_count == 6:
                        interrupt_parent_process()
                    return original_readline()
                
                with patch('subprocess.Popen', return_value=child_process):
                    with patch.object(child_process.stdout, 'readline', side_effect=mock_readline):
                        result = run_worker()
                
                # Verify the result
                assert [
                    TestResult(
                        name=self._EXAMPLE_TEST_NAME,
                        status='INTERRUPTED',
                        skip_reason=None,
                        output_lines=['foo', 'bar']
                    )
                ] == result.test_results
                assert 0 == result.returncode
                
                # Verify the process was properly terminated
                child_process._ensure_terminated_and_no_warnings()
    
    def test_when_interrupt_directly_before_stdin_closed_then_exits_gracefully(self, subtests: pytest.Subtests) -> None:
        # Strategy:
        # - Wait until the process.stdin.close() call near `# Close stdin to signal end of interactive mode`,
        #   then trigger the interrupt directly before that call happens.
        #     - Case 1: Child process interupted before parent process interrupted
        #         - Interrupt should be observed on the next call to process.stdin.close()
        #     - Case 2: Parent process interupted before child process interrupted
        #         - Interrupt should be observed on the next call to reader.readline()
        
        with subtests.test(target_process='child'):
            work_queue_child: queue.Queue[str | None] = queue.Queue()
            with self._worker_context(work_queue=work_queue_child) as (run_worker, interrupt_parent_process):
                # Add a test to the queue and then sentinel to indicate no more tests
                work_queue_child.put(self._EXAMPLE_TEST_NAME)
                work_queue_child.put(None)
                
                # Mock the subprocess.Popen to return a process that outputs the initial prompt and test output
                child_process = _MockProcess(
                    stdout_lines=[
                        'test>',
                        '======================================================================',
                        f'RUNNING: {self._EXAMPLE_TEST_NAME}',
                        '----------------------------------------------------------------------',
                        'OK',
                        '',
                        'test>',
                        # (Interrupt here)
                    ],
                    returncode=None
                )
                
                # Track calls to stdin.close() and trigger interrupt on first call
                close_call_count = 0
                original_close = child_process.stdin.close
                def mock_close() -> None:
                    nonlocal close_call_count
                    close_call_count += 1
                    if close_call_count == 1:
                        # On first call to close(), interrupt the child process
                        child_process.send_signal(signal.SIGINT)
                    # Try to call original close - may fail if process was terminated
                    try:
                        return original_close()
                    except Exception:
                        pass
                
                with patch('subprocess.Popen', return_value=child_process):
                    with patch.object(child_process.stdin, 'close', side_effect=mock_close):
                        result = run_worker()
                
                # Verify the result
                assert [
                    TestResult(
                        name=self._EXAMPLE_TEST_NAME,
                        status='OK',
                        skip_reason=None,
                        output_lines=[
                            'OK',
                            '',
                        ]
                    )
                ] == result.test_results
                assert -signal.SIGINT == result.returncode
                
                # Verify the process was properly terminated
                child_process._ensure_terminated_and_no_warnings()
        
        with subtests.test(target_process='parent'):
            work_queue_parent: queue.Queue[str | None] = queue.Queue()
            with self._worker_context(work_queue=work_queue_parent) as (run_worker, interrupt_parent_process):
                # Add a test to the queue and then sentinel to indicate no more tests
                work_queue_parent.put(self._EXAMPLE_TEST_NAME)
                work_queue_parent.put(None)
                
                # Mock the subprocess.Popen to return a process that outputs the initial prompt and test output
                child_process = _MockProcess(
                    stdout_lines=[
                        'test>',
                        '======================================================================',
                        f'RUNNING: {self._EXAMPLE_TEST_NAME}',
                        '----------------------------------------------------------------------',
                        'OK',
                        '',
                        'test>',
                        # (Interrupt here)
                    ],
                    returncode=0
                )
                
                # Track calls to stdin.close() and trigger interrupt on first call
                close_call_count = 0
                original_close = child_process.stdin.close
                def mock_close() -> None:
                    nonlocal close_call_count
                    close_call_count += 1
                    if close_call_count == 1:
                        # On first call to close(), interrupt the parent process
                        interrupt_parent_process()
                    # Call original close
                    return original_close()
                
                with patch('subprocess.Popen', return_value=child_process):
                    with patch.object(child_process.stdin, 'close', side_effect=mock_close):
                        result = run_worker()
                
                # Verify the result
                assert [
                    TestResult(
                        name=self._EXAMPLE_TEST_NAME,
                        status='OK',
                        skip_reason=None,
                        output_lines=[
                            'OK',
                            '',
                        ]
                    )
                ] == result.test_results
                assert 0 == result.returncode
                
                # Verify the process was properly terminated
                child_process._ensure_terminated_and_no_warnings()
    
    def test_when_interrupt_while_subprocess_printing_summary_then_exits_gracefully(self, subtests: pytest.Subtests) -> None:
        # Strategy:
        # - Wait until after process.stdin.close() call near `# Close stdin to signal end of interactive mode`,
        #   then trigger the interrupt during the summary output reading phase.
        #     - Case 1: Child process interrupted before parent process interrupted
        #         - Interrupt should be observed on a reader.readline() call in the summary reading loop
        #     - Case 2: Parent process interrupted before child process interrupted
        #         - Interrupt should be observed on a reader.readline() call in the summary reading loop
        
        with subtests.test(target_process='child'):
            work_queue_child: queue.Queue[str | None] = queue.Queue()
            with self._worker_context(work_queue=work_queue_child) as (run_worker, interrupt_parent_process):
                # Add a test to the queue and then sentinel to indicate no more tests
                work_queue_child.put(self._EXAMPLE_TEST_NAME)
                work_queue_child.put(None)
                
                # Mock the subprocess.Popen to return a process that outputs a test result and a partial summary
                child_process = _MockProcess(
                    stdout_lines=[
                        'test>',
                        '======================================================================',
                        f'RUNNING: {self._EXAMPLE_TEST_NAME}',
                        '----------------------------------------------------------------------',
                        'OK',
                        '',
                        'test>',
                        '======================================================================',
                        'SUMMARY',
                        '----------------------------------------------------------------------',
                        # (Interrupt here)
                        #'.',
                        #'----------------------------------------------------------------------',
                        #'Ran 1 tests in 0.429s',
                        #'',
                        #'OK',
                    ],
                    returncode=None
                )
                
                # Track calls to reader.readline() and trigger interrupt on first call after stdin closed
                # We'll use a flag to track when stdin has been closed
                readline_call_count = 0
                original_readline = child_process.stdout.readline
                def mock_readline() -> str:
                    nonlocal readline_call_count
                    readline_call_count += 1
                    if readline_call_count == 11:
                        child_process.send_signal(signal.SIGINT)
                    return original_readline()
                
                with patch('subprocess.Popen', return_value=child_process):
                    with patch.object(child_process.stdout, 'readline', side_effect=mock_readline):
                        result = run_worker()
                
                # Verify the result
                assert [
                    TestResult(
                        name=self._EXAMPLE_TEST_NAME,
                        status='OK',
                        skip_reason=None,
                        output_lines=[
                            'OK',
                            '',
                        ]
                    )
                ] == result.test_results
                assert -signal.SIGINT == result.returncode
                
                # Verify the process was properly terminated
                child_process._ensure_terminated_and_no_warnings()
        
        with subtests.test(target_process='parent'):
            work_queue_parent: queue.Queue[str | None] = queue.Queue()
            with self._worker_context(work_queue=work_queue_parent) as (run_worker, interrupt_parent_process):
                # Add a test to the queue and then sentinel to indicate no more tests
                work_queue_parent.put(self._EXAMPLE_TEST_NAME)
                work_queue_parent.put(None)
                
                # Mock the subprocess.Popen to return a process that outputs a test result and a partial summary
                child_process = _MockProcess(
                    stdout_lines=[
                        'test>',
                        '======================================================================',
                        f'RUNNING: {self._EXAMPLE_TEST_NAME}',
                        '----------------------------------------------------------------------',
                        'OK',
                        '',
                        'test>',
                        '======================================================================',
                        'SUMMARY',
                        # (Interrupt signaled here)
                        '----------------------------------------------------------------------',
                        # (Interrupt detected here)
                        #'.',
                        #'----------------------------------------------------------------------',
                        #'Ran 1 tests in 0.429s',
                        #'',
                        #'OK',
                    ],
                    returncode=0
                )
                
                # Track calls to reader.readline() and trigger interrupt on first call after stdin closed
                readline_call_count = 0
                original_readline = child_process.stdout.readline
                def mock_readline() -> str:
                    nonlocal readline_call_count
                    readline_call_count += 1
                    if readline_call_count == 10:
                        interrupt_parent_process()
                    return original_readline()
                
                with patch('subprocess.Popen', return_value=child_process):
                    with patch.object(child_process.stdout, 'readline', side_effect=mock_readline):
                        result = run_worker()
                
                # Verify the result
                assert [
                    TestResult(
                        name=self._EXAMPLE_TEST_NAME,
                        status='OK',
                        skip_reason=None,
                        output_lines=[
                            'OK', 
                            '',
                        ]
                    )
                ] == result.test_results
                assert 0 == result.returncode
                
                # Verify the process was properly terminated
                child_process._ensure_terminated_and_no_warnings()
    
    # === Utility ===
    
    @staticmethod
    @contextmanager
    def _worker_context(
        *, work_queue: queue.Queue[str | None] | None = None,
    ) -> Iterator[tuple[Callable[[], WorkerResult], Callable[[], None]]]:
        """
        Context in which a single worker thread and process can run.
        
        Returns tuple of (run_worker, interrupt_parent_process):
        - def run_worker() -> WorkerResult: ...
        - def interrupt_parent_process() -> None: ...
        """
        # Create empty work queue, so that the worker will block waiting for an item
        if work_queue is None:
            work_queue = queue.Queue()
        
        # Create temporary directory for logs
        with tempfile.TemporaryDirectory() as log_dir:
            # Create interrupt event and pipes
            interrupted_event = threading.Event()
            interrupt_pipe = create_selectable_pipe()
            worker_interrupt_pipes = [interrupt_pipe]
            
            try:
                def run_worker() -> WorkerResult:
                    # Run worker in a background thread (for realism)
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(
                            _run_worker,
                            worker_id=0,
                            work_queue=work_queue,
                            log_dir=log_dir,
                            verbose=False,
                            interrupted_event=interrupted_event,
                            interrupt_read_pipe=interrupt_pipe.readable_end,
                        )
                        
                        # Wait for worker to complete and get result
                        result = future.result(timeout=2.0)
                    
                    return result
                
                def interrupt_parent_process() -> None:
                    _interrupt_workers(interrupted_event, worker_interrupt_pipes, verbose=False)
                
                yield (run_worker, interrupt_parent_process)
                    
            finally:
                # Clean up pipes (write pipe is closed by _interrupt_workers)
                try:
                    interrupt_pipe.readable_end.close()
                except OSError:
                    pass


class _MockProcess:
    """
    Mock subprocess.Popen object for testing _run_worker().
    
    Simulates a subprocess with realistic stdin/stdout streams and process lifecycle methods.
    The mock process will appear to terminate after any one of these situations:
    - all stdout_lines are read from process.stdin
    - process.send_signal() is called
    - process.terminate() is called
    """
    
    def __init__(self, stdout_lines: list[str], returncode: int | None = None):
        """
        Arguments:
        * stdout_lines -- Lines to return when reading from stdout (without newlines).
        * returncode -- Return code to simulate after all lines read from stdout.
        """
        self.stdin = _MockWritableFile()
        self.stdout = _MockReadableFile(stdout_lines)
        self._returncode_after_stdout = returncode
        self.returncode = None  # type: int | None
        self.pid = 12345
        self._terminated = False
        self._warnings = []  # type: list[str]
    
    # === Popen API ===
    
    def send_signal(self, signum: int) -> None:
        if self._returncode_after_stdout is not None:
            self._warn(
                f'*** MockProcess: Process expected to terminate normally '
                f'because initialized with returncode=<int> but process.send_signal() was called. '
                f'Check that the returncode=<int> given to MockProcess is correct.')
        if not self.stdout._at_eof():
            line = self.stdout.readline()
            self._warn(
                f'*** MockProcess: Expected no more stdout_lines '
                f'to be defined at time of process.send_signal() call but got: {line!r}. '
                f'Check that the stdout_lines given to MockProcess is correct.')
        # TODO: Investigate whether Windows has a different returncode behavior
        #       here when compared with macOS and Linux.
        self.terminate(_returncode=-signum)
    
    def wait(self, timeout: float | None = None) -> int:
        """Wait for process to terminate and return returncode."""
        if not self.stdout._at_eof():
            line = self.stdout.readline()
            self._warn(
                f'*** MockProcess.wait(): Expected no more stdout_lines '
                f'to be defined at time of process.wait() call but got: {line!r}. '
                f'Check that the stdout_lines given to MockProcess is correct.')
        if self.returncode is None:
            if self._returncode_after_stdout is None:
                self._warn(
                    f'*** MockProcess.wait(): Process expected to terminate non-normally '
                    f'because initialized with returncode=None but process.wait() was called. '
                    f'Check that the returncode=<int> given to MockProcess is correct.')
                self._returncode_after_stdout = -999  # internal error
            
            self.returncode = self._returncode_after_stdout
            self._terminated = True
        return self.returncode
    
    def poll(self) -> int | None:
        """Return the returncode if process has terminated, None otherwise."""
        if self.returncode is not None:
            return self.returncode
        if self.stdout._at_eof():
            if self._returncode_after_stdout is None:
                return None
            else:
                return self.wait()
        else:
            return None
    
    def terminate(self, *, _returncode: int = -signal.SIGTERM) -> None:
        """Terminate the process."""
        if self.returncode is not None:
            # No process running to send SIGTERM to
            return
        
        self.returncode = _returncode
        self._terminated = True
        
        self.stdin.close()
        try:
            # NOTE: May raise `OSError: [Errno 9] Bad file descriptor` if
            #       log_file has never been read from.
            self.stdout._pipe.writable_end.close()
        except Exception:
            pass
    
    # === Popen API Extensions ===
    
    def _ensure_terminated_and_no_warnings(self) -> None:
        """
        Raises:
        * AssertionError
        """
        assert self._terminated
        assert [] == self._warnings
    
    # === Utility ===
    
    def _warn(self, message: str) -> None:
        print(message, file=sys.stderr)
        self._warnings.append(message)


class _MockReadableFile:
    """
    Mock file object that simulates a subprocess stdout stream.
    
    Supports both text-mode reading (readline()) and file descriptor operations (fileno()).
    This class uses a real pipe internally to provide a legitimate file descriptor
    that can be used with select.select().
    """
    
    def __init__(self, lines: list[str]):
        """
        Arguments:
        * lines -- Lines to return when reading. Each line should NOT include newline.
        """
        self._lines = lines
        self._line_index = 0
        self._closed = False
        # Create a real pipe to provide a real file descriptor
        self._pipe = create_selectable_pipe()
        if self._line_index < len(self._lines):
            # Send "input available" signal byte
            self._pipe.writable_end.write(b'\x00')
    
    def fileno(self) -> int:
        """Return the file descriptor for this file."""
        return self._pipe.readable_end.fileno()
    
    def readline(self) -> str:
        """Read and return the next line."""
        if self._closed or self._at_eof():
            return ''
        line = self._lines[self._line_index]
        self._line_index += 1
        if not self._at_eof():
            # Send "input available" signal byte
            self._pipe.writable_end.write(b'\x00')
        return line + '\n'
    
    def close(self) -> None:
        """Close the file."""
        self._closed = True
        try:
            self._pipe.readable_end.close()
        except OSError:
            pass
        try:
            self._pipe.writable_end.close()
        except OSError:
            pass
    
    def _at_eof(self) -> bool:
        return self._line_index >= len(self._lines)


class _MockWritableFile:
    """Mock file object for subprocess stdin."""
    
    def __init__(self):
        self._buffer = StringIO()
        self._closed = False
    
    def write(self, s: str) -> int:
        """Write string to buffer."""
        if self._closed:
            raise BrokenPipeError()
        return self._buffer.write(s)
    
    def flush(self) -> None:
        """Flush the buffer."""
        if self._closed:
            raise BrokenPipeError()
        pass
    
    def close(self) -> None:
        """Close the file."""
        self._closed = True
    
    def getvalue(self) -> str:
        """Get all written content."""
        return self._buffer.getvalue()


# ------------------------------------------------------------------------------
# TestParseAndDisplayOutputOfInterruptedParallelTestWorkerProcess

# NOTE: `test --parallel` is tested in multiple locations:
# - "# === Testing Tests (test): Parallel ==="
# - TestInterruptRunParallelTestWorker
# - TestParseAndDisplayOutputOfInterruptedParallelTestWorkerProcess

class TestParseAndDisplayOutputOfInterruptedParallelTestWorkerProcess:
    """
    Tests that _parse_test_result() + _display_test_result() give reasonable
    output when given input from parallel test worker processes that were
    interrupted at different points while running.
    
    Input/output space tested:
        Inputs to _parse_test_result() of note:
        * test_output_lines: list[str]
        * interrupted: bool -- whether the parent process detected it was interrupted
        
        Outputs from _parse_test_result() of note:
        * TestResult
            * output_lines: list[str]
        
        Outputs from _display_test_result():
        * printed_lines: list[str] -- print() calls to sys.stdout
    """
    _EXAMPLE_TEST_NAME = 'crystal.tests.test_example.test_something'
    _EXAMPLE_TEST_SHORT_NAME = 'test_something'
    
    def test_interrupted_child_process_printed_zero_lines(self, subtests: pytest.Subtests) -> None:
        for interrupted in [True, False]:
            truncated_error_lines = [
                'ERROR (Incomplete test prefix lines. Did the test segfault?)',
                '',
            ] if not interrupted else []
            
            with subtests.test(interrupted=interrupted):
                expected_status = 'INTERRUPTED' if interrupted else 'ERROR'
                
                self._check(
                    process_output_lines=[
                        # (Interrupted)
                        #'======================================================================',
                        #f'RUNNING: {self._EXAMPLE_TEST_SHORT_NAME} ({self._EXAMPLE_TEST_NAME})',
                        #'----------------------------------------------------------------------',
                    ],
                    interrupted=interrupted,
                    expected_test_result=TestResult(
                        name=self._EXAMPLE_TEST_NAME,
                        status=expected_status,
                        skip_reason=None,
                        output_lines=(truncated_error_lines),
                    ),
                    expected_printed_lines=(
                        []
                        if (expected_status == 'INTERRUPTED')
                        else [
                            '======================================================================',
                            f'RUNNING: {self._EXAMPLE_TEST_SHORT_NAME} ({self._EXAMPLE_TEST_NAME})',
                            '----------------------------------------------------------------------',
                        ] + truncated_error_lines
                    ),
                )
    
    # NOTE: It should be impossible for an interrupted child process to PRINT
    #       only 1 or 2 lines because that would imply only a partial set of 
    #       the 3 prefix lines was printed. But the current implementation in 
    #       _run_single_test() uses an atomic print() which outputs all 
    #       3 lines in an all-or-nothing fashion.
    #       
    #       However the parent process may be interrupted while READING
    #       individual prefix lines from the child process.
    
    def test_interrupted_child_process_printed_one_line(self, subtests: pytest.Subtests) -> None:
        for interrupted in [True, False]:
            truncated_error_lines = [
                'ERROR (Incomplete test prefix lines. Did the test segfault?)',
                '',
            ] if not interrupted else []
            
            with subtests.test(interrupted=interrupted):
                expected_status = 'INTERRUPTED' if interrupted else 'ERROR'
                
                self._check(
                    process_output_lines=[
                        '======================================================================',
                        # (Interrupted)
                        #f'RUNNING: {self._EXAMPLE_TEST_SHORT_NAME} ({self._EXAMPLE_TEST_NAME})',
                        #'----------------------------------------------------------------------',
                    ],
                    interrupted=interrupted,
                    expected_test_result=TestResult(
                        name=self._EXAMPLE_TEST_NAME,
                        status=expected_status,
                        skip_reason=None,
                        output_lines=(truncated_error_lines),
                    ),
                    expected_printed_lines=(
                        []
                        if (expected_status == 'INTERRUPTED')
                        else [
                            '======================================================================',
                            f'RUNNING: {self._EXAMPLE_TEST_SHORT_NAME} ({self._EXAMPLE_TEST_NAME})',
                            '----------------------------------------------------------------------',
                        ] + truncated_error_lines
                    ),
                )
    
    def test_interrupted_child_process_printed_two_lines(self, subtests: pytest.Subtests) -> None:
        for interrupted in [True, False]:
            truncated_error_lines = [
                'ERROR (Incomplete test prefix lines. Did the test segfault?)',
                '',
            ] if not interrupted else []
            
            with subtests.test(interrupted=interrupted):
                expected_status = 'INTERRUPTED' if interrupted else 'ERROR'
                
                self._check(
                    process_output_lines=[
                        '======================================================================',
                        f'RUNNING: {self._EXAMPLE_TEST_SHORT_NAME} ({self._EXAMPLE_TEST_NAME})',
                        # (Interrupted)
                        #'----------------------------------------------------------------------',
                    ],
                    interrupted=interrupted,
                    expected_test_result=TestResult(
                        name=self._EXAMPLE_TEST_NAME,
                        status=expected_status,
                        skip_reason=None,
                        output_lines=(truncated_error_lines),
                    ),
                    expected_printed_lines=(
                        []
                        if (expected_status == 'INTERRUPTED')
                        else [
                            '======================================================================',
                            f'RUNNING: {self._EXAMPLE_TEST_SHORT_NAME} ({self._EXAMPLE_TEST_NAME})',
                            '----------------------------------------------------------------------',
                        ] + truncated_error_lines
                    ),
                )
    
    def test_interrupted_child_process_printed_three_lines(self, subtests: pytest.Subtests) -> None:
        for interrupted in [True, False]:
            truncated_error_lines = [
                'ERROR (No test status line. Did the test segfault?)',
                '',
            ] if not interrupted else []
            
            with subtests.test(interrupted=interrupted):
                expected_status = 'INTERRUPTED' if interrupted else 'ERROR'
                
                self._check(
                    process_output_lines=(prefix_lines := [
                        '======================================================================',
                        f'RUNNING: {self._EXAMPLE_TEST_SHORT_NAME} ({self._EXAMPLE_TEST_NAME})',
                        '----------------------------------------------------------------------',
                    ]) + ([
                        # (Interrupted)
                    ]),
                    interrupted=interrupted,
                    expected_test_result=TestResult(
                        name=self._EXAMPLE_TEST_NAME,
                        status=expected_status,
                        skip_reason=None,
                        output_lines=(truncated_error_lines),
                    ),
                    expected_printed_lines=(
                        []
                        if (expected_status == 'INTERRUPTED')
                        else (prefix_lines + truncated_error_lines)
                    ),
                )
    
    # NOTE: This is expected to be the MOST COMMON type of partial output that
    #       will need to be parsed.
    # TODO: Consider altering subtests to print status lines like
    #       "SUBSKIP", "SUBERROR", etc so that they are easy to distinguish
    #       from the test-level status lines like "SKIP", "ERROR", etc.
    def test_interrupted_child_process_printed_at_least_four_lines_excluding_final_status_line(self, subtests: pytest.Subtests) -> None:
        # Extra Dimension:
        # * includes_intermediate_status_line: bool -- whether a subtest has printed a status line
        
        for interrupted in [True, False]:
            truncated_error_lines = [
                'ERROR (No test status line. Did the test segfault?)',
                '',
            ] if not interrupted else []
            NO_truncated_error_lines = []  # type: list[str]
            
            with subtests.test(interrupted=interrupted, includes_intermediate_status_line=False):
                self._check(
                    process_output_lines=(prefix_lines := [
                        '======================================================================',
                        f'RUNNING: {self._EXAMPLE_TEST_SHORT_NAME} ({self._EXAMPLE_TEST_NAME})',
                        '----------------------------------------------------------------------',
                    ]) + (suffix_lines := [
                        'Some test output line 1',
                        'Some test output line 2',
                        'Some test output line 3',
                        # (Interrupted)
                    ]),
                    interrupted=interrupted,
                    expected_test_result=TestResult(
                        name=self._EXAMPLE_TEST_NAME,
                        status='INTERRUPTED' if interrupted else 'ERROR',
                        skip_reason=None,
                        output_lines=(suffix_lines + truncated_error_lines),
                    ),
                    expected_printed_lines=(prefix_lines + suffix_lines + truncated_error_lines),
                )
            
            with subtests.test(interrupted=interrupted, includes_intermediate_status_line=True):
                self._check(
                    process_output_lines=(prefix_lines := [
                        '======================================================================',
                        f'RUNNING: {self._EXAMPLE_TEST_SHORT_NAME} ({self._EXAMPLE_TEST_NAME})',
                        '----------------------------------------------------------------------',
                    ]) + (suffix_lines := [
                        'subtest 1 output',
                        'subtest 2 output',
                        'subtest 3 output',
                        'subtest 4 output',
                        '- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - ',
                        f'SUBTEST: {self._EXAMPLE_TEST_NAME} (case=1)',
                        '. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ',
                        'Traceback (most recent call last):',
                        '  ...',
                        'ValueError: boom',
                        'ERROR',
                        '- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - ',
                        f'SUBTEST: {self._EXAMPLE_TEST_NAME} (case=2)',
                        '. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ',
                        'SKIP',
                        '- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - ',
                        f'SUBTEST: {self._EXAMPLE_TEST_NAME} (case=3)',
                        # (Interrupted)
                    ]),
                    interrupted=interrupted,
                    expected_test_result=TestResult(
                        name=self._EXAMPLE_TEST_NAME,
                        # NOTE: If interrupted=False, can misidentify test status as last line that
                        #       looks like a status line.
                        status='INTERRUPTED' if interrupted else 'SKIP',
                        skip_reason=None,
                        # NOTE: No truncated_error_lines even if interrupted=False
                        output_lines=(suffix_lines + NO_truncated_error_lines),
                    ),
                    # NOTE: No truncated_error_lines even if interrupted=False
                    expected_printed_lines=(prefix_lines + suffix_lines + NO_truncated_error_lines),
                )
    
    def test_interrupted_child_process_printed_at_least_four_lines_including_final_status_line(self, subtests: pytest.Subtests) -> None:
        # Extra Dimension:
        # * includes_intermediate_status_line: bool -- whether a subtest has printed a status line
        
        for interrupted in [True, False]:
            with subtests.test(interrupted=interrupted, includes_intermediate_status_line=False):
                self._check(
                    process_output_lines=(prefix_lines := [
                        '======================================================================',
                        f'RUNNING: {self._EXAMPLE_TEST_SHORT_NAME} ({self._EXAMPLE_TEST_NAME})',
                        '----------------------------------------------------------------------',
                    ]) + (suffix_lines := [
                        'Some test output line 1',
                        'Some test output line 2',
                        'Some test output line 3',
                        'OK',
                        ''
                        # (Interrupted)
                    ]),
                    interrupted=interrupted,
                    expected_test_result=TestResult(
                        name=self._EXAMPLE_TEST_NAME,
                        status='INTERRUPTED' if interrupted else 'OK',
                        skip_reason=None,
                        output_lines=(suffix_lines),
                    ),
                    expected_printed_lines=(prefix_lines + suffix_lines),
                )
            
            with subtests.test(interrupted=interrupted, includes_intermediate_status_line=True):
                self._check(
                    process_output_lines=(prefix_lines := [
                        '======================================================================',
                        f'RUNNING: {self._EXAMPLE_TEST_SHORT_NAME} ({self._EXAMPLE_TEST_NAME})',
                        '----------------------------------------------------------------------',
                    ]) + (suffix_lines := [
                        'subtest 1 output',
                        'subtest 2 output',
                        'subtest 3 output',
                        'subtest 4 output',
                        '- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - ',
                        f'SUBTEST: {self._EXAMPLE_TEST_NAME} (case=1)',
                        '. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ',
                        'Traceback (most recent call last):',
                        '  ...',
                        'ValueError: boom',
                        'ERROR',
                        '- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - ',
                        f'SUBTEST: {self._EXAMPLE_TEST_NAME} (case=2)',
                        '. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ',
                        'SKIP',
                        '- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - ',
                        f'SUBTEST: {self._EXAMPLE_TEST_NAME} (case=3)',
                        '. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ',
                        'Traceback (most recent call last):',
                        '  ...',
                        'AssertionError: 1 + 1 == 3',
                        'FAILURE',
                        '----------------------------------------------------------------------',
                        'ERROR (SubtestFailed)',
                        '',
                        # (Interrupted)
                    ]),
                    interrupted=interrupted,
                    expected_test_result=TestResult(
                        name=self._EXAMPLE_TEST_NAME,
                        status='INTERRUPTED' if interrupted else 'ERROR',
                        skip_reason=None,
                        output_lines=(suffix_lines),
                    ),
                    expected_printed_lines=(prefix_lines + suffix_lines),
                )
    
    # === Utility ===
    
    def _check(self,
            process_output_lines: list[str],
            interrupted: bool,
            expected_test_result: TestResult,
            expected_printed_lines: list[str],
            ) -> None:
        
        # Exercise: Parse the test result
        test_result = _parse_test_result(
            test_name=self._EXAMPLE_TEST_NAME,
            output_lines=process_output_lines,
            interrupted=interrupted,
        )
        
        # Verify
        assert expected_test_result == test_result
        
        # Exercise: Display the test result and capture output
        with redirect_stdout(StringIO()) as captured_stdout:
            _display_test_result(test_result)
        printed_lines_str = captured_stdout.getvalue()
        printed_lines = (
            printed_lines_str.removesuffix('\n').split('\n')
            if printed_lines_str != ''
            else []
        )
        
        # Verify
        assert expected_printed_lines == printed_lines


# ------------------------------------------------------------------------------
