"""
Tests for Crystal's test runner functionality.

These tests verify that the test infrastructure itself works correctly,
including error recovery mechanisms, and test utilities.
"""

from contextlib import redirect_stderr
from crystal.browser import MainWindow as RealMainWindow
from crystal.model import Project
from crystal.tests.util.asserts import (
    assertEqual, assertIn, assertNotEqual, assertNotIn, assertRegex
)
from crystal.tests.util.cli import (
    crystal_running, read_until, run_crystal,
)
from crystal.tests.util.subtests import SubtestsContext, with_subtests
from crystal.tests.util.windows import MainWindow, OpenOrCreateDialog
from crystal.util.xtyping import not_none
import io
from io import TextIOBase
import os
import re


# === Testing Tests (test, --test): Serial ===

def test_can_run_tests_with_test_subcommand() -> None:
    """Test that 'crystal test <test1> <test2>' works."""
    result = run_crystal([
        'test',
        # NOTE: This is a simple, fast test
        'crystal.tests.test_main_window.test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors',
        # NOTE: This is a skipped test
        'crystal.tests.test_main_window.test_branding_area_looks_good_in_light_mode_and_dark_mode'
    ])
    assertEqual(0, result.returncode)
    assertIn('Ran 2 tests', result.stdout)


def test_can_run_tests_with_test_flag() -> None:
    """Test that 'crystal --test <test1> <test2>' works for backward compatibility."""
    result = run_crystal([
        '--test',
        # NOTE: This is a simple, fast test
        'crystal.tests.test_main_window.test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors',
        # NOTE: This is a skipped test
        'crystal.tests.test_main_window.test_branding_area_looks_good_in_light_mode_and_dark_mode'
    ])
    assertEqual(0, result.returncode)
    assertIn('Ran 2 tests', result.stdout)


# NOTE: More kinds of raw test names are tested in TestNormalizeTestNames
def test_can_run_tests_with_unqualified_function_or_module_name() -> None:
    result = run_crystal([
        '--test',
        # NOTE: This is a simple, fast test
        'test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors',
        # NOTE: This is a fast test module
        'test_profile',
    ])
    assertEqual(0, result.returncode)
    assertRegex(result.stdout, r'Ran \d+ tests')


def test_can_run_tests_in_interactive_mode() -> None:
    """Test that 'crystal test --interactive' works."""
    # Start Crystal in interactive test mode
    with crystal_running(args=['test', '--interactive'], kill=False) as crystal:
        assert crystal.stdin is not None
        assert isinstance(crystal.stdout, TextIOBase)
        
        # Read the first prompt
        (output, _) = read_until(crystal.stdout, 'test>\n', timeout=2.0)
        
        # Send a test name
        crystal.stdin.write('crystal.tests.test_main_window.test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors\n')
        crystal.stdin.flush()
        
        # Wait for the test to complete
        (output, _) = read_until(crystal.stdout, 'test>\n', timeout=30.0)
        
        # Verify the test ran
        assertIn('RUNNING: test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors', output)
        assertIn('OK', output)
        
        # NOTE: No percentage should be in the RUNNING line in interactive mode
        assertNotIn('[', output.split('\n')[0])  # First line shouldn't have [%]
        
        # Close stdin to signal end of interactive mode
        crystal.stdin.close()
        
        # Wait for summary
        (output, _) = read_until(crystal.stdout, '\x07', timeout=5.0)
        assertIn('SUMMARY', output)
        assertIn('OK', output)
    
    # Verify exit code
    assertEqual(0, crystal.returncode)


# NOTE: More kinds of raw test names are tested in TestNormalizeTestNames
def test_given_interactive_mode_can_run_tests_with_unqualified_function_or_module_name() -> None:
    with crystal_running(args=['test', '--interactive'], kill=False) as crystal:
        assert crystal.stdin is not None
        assert isinstance(crystal.stdout, TextIOBase)
        
        # Read the first prompt
        (output, _) = read_until(crystal.stdout, 'test>\n', timeout=2.0)
        
        # Send test name #1
        # NOTE: This is a simple, fast test
        crystal.stdin.write('test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors\n')
        crystal.stdin.flush()
        
        # Verify OK was printed
        (output, _) = read_until(crystal.stdout, 'test>\n', timeout=5.0)
        assertIn('OK\n', output)
        
        # Send test name #2
        # NOTE: This is a fast test module
        crystal.stdin.write('test_profile\n')
        crystal.stdin.flush()
        
        # Verify multiple tests finished
        (output, _) = read_until(crystal.stdout, 'test>\n', timeout=5.0)
        
        # Close stdin
        crystal.stdin.close()
        
        # Wait for summary
        (output, _) = read_until(crystal.stdout, '\x07', timeout=5.0)
        assertIn('SUMMARY', output)
        assertIn('OK', output)
        assertRegex(output, r'Ran \d+ tests')
    
    # Exit code should be 0
    assertEqual(0, crystal.returncode)


def test_given_interactive_mode_when_test_not_found_then_prints_error() -> None:
    """Test that 'crystal test --interactive' handles non-existent tests gracefully."""
    with crystal_running(args=['test', '--interactive'], kill=False) as crystal:
        assert crystal.stdin is not None
        assert isinstance(crystal.stdout, TextIOBase)
        
        # Read the first prompt
        (output, _) = read_until(crystal.stdout, 'test>\n', timeout=2.0)
        
        # Send a non-existent test name
        crystal.stdin.write('crystal.tests.test_no_such_module.test_no_such_function\n')
        crystal.stdin.flush()
        
        # Wait for error message and next prompt
        (output, _) = read_until(crystal.stdout, 'test>\n', timeout=5.0)
        
        # Verify error was printed
        assertIn('test: Test not found:', output)
        
        # Close stdin
        crystal.stdin.close()
        
        # Wait for summary
        (output, _) = read_until(crystal.stdout, '\x07', timeout=5.0)
        assertIn('SUMMARY', output)
        assertIn('OK', output)
        assertIn('Ran 0 tests', output)
    
    # Exit code should still be 0 since no tests failed (just none were run)
    assertEqual(0, crystal.returncode)


def test_given_interactive_mode_when_test_names_provided_then_prints_error() -> None:
    """Test that 'crystal test --interactive <test_name>' is rejected."""
    result = run_crystal([
        'test',
        '--interactive',
        'crystal.tests.test_main_window.test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors'
    ])
    assert result.returncode != 0
    assertIn('error: test names cannot be specified with --interactive', result.stderr)


def test_when_ctrl_c_pressed_while_test_running_noninteractively_then_marks_that_test_and_all_following_tests_as_interrupted() -> None:
    with crystal_running(
        args=[
            'test',
            # Test 0: Fast test that should pass
            'crystal.tests.test_runner.test_special_a_causing_pass',
            # Test 1: Special test that simulates Ctrl-C
            'crystal.tests.test_runner.test_special_b_causing_ctrl_c',
            # Test 2: Fast test that should pass, if it wasn't interrupted
            'crystal.tests.test_runner.test_special_c_causing_pass',
        ],
        # Enable Ctrl-C simulation in test_special_b_causing_ctrl_c
        env_extra={'CRYSTAL_SIMULATE_CTRL_C_DURING_TEST': '1'},
    ) as crystal:
        (stdout_str, _) = crystal.communicate()
        returncode = crystal.returncode
    
    # Verify "INTERRUPTED" status line was printed for the test that received Ctrl-C
    assertIn('INTERRUPTED', stdout_str)
    
    # Verify SUMMARY section is still printed
    assertIn('SUMMARY', stdout_str)
    assertIn('-' * 70, stdout_str)
    
    # Verify the test that received Ctrl-C and all following tests are marked with '-'
    # Expected pattern: '.s---' (pass, interrupted, interrupted)
    assertIn('\n.--\n', stdout_str)
    
    # Verify summary status line mentions interrupted tests
    assertIn('interrupted=2', stdout_str)
    assertIn('FAILURE', stdout_str)
    
    # Verify 'Rerun interrupted tests with:' section exists
    assertIn('Rerun interrupted tests with:', stdout_str)
    assertIn(
        'crystal --test '
        'crystal.tests.test_runner.test_special_b_causing_ctrl_c '
        'crystal.tests.test_runner.test_special_c_causing_pass', stdout_str)
    
    # Verify exit code indicates failure
    assertNotEqual(0, returncode, f'Expected non-zero exit code, got {returncode}')


def test_when_ctrl_c_pressed_while_test_running_interactively_then_marks_that_test_as_interrupted_and_ignores_further_tests_on_stdin() -> None:
    with crystal_running(
        args=['test', '--interactive'],
        # Enable Ctrl-C simulation in test_special_b_causing_ctrl_c
        env_extra={'CRYSTAL_SIMULATE_CTRL_C_DURING_TEST': '1'},
    ) as crystal:
        assert crystal.stdin is not None
        assert isinstance(crystal.stdout, TextIOBase)
        
        # Read the first prompt
        (_, _) = read_until(crystal.stdout, 'test>\n', timeout=2.0)
        
        # Send test 1 (should pass)
        crystal.stdin.write('crystal.tests.test_runner.test_special_a_causing_pass\n')
        crystal.stdin.flush()
        (early_stdout_str, _) = read_until(crystal.stdout, 'test>\n', timeout=30.0)
        assertIn('OK', early_stdout_str)
        
        # Send test 2 (will trigger Ctrl-C simulation)
        crystal.stdin.write('crystal.tests.test_runner.test_special_b_causing_ctrl_c\n')
        crystal.stdin.flush()
        
        # Try to send test 3 (should be ignored after Ctrl-C)
        # Note: We send this immediately, but after Ctrl-C it should be ignored
        crystal.stdin.write('crystal.tests.test_runner.test_special_c_causing_pass\n')
        crystal.stdin.flush()
        
        # Wait for process to exit
        (late_stdout_str, _) = crystal.communicate(input='')
        returncode = crystal.returncode
    
    # Verify "INTERRUPTED" status line was printed for the test that received Ctrl-C
    assertIn('INTERRUPTED', late_stdout_str)
    
    # Verify SUMMARY section is still printed
    assertIn('SUMMARY', late_stdout_str)
    assertIn('-' * 70, late_stdout_str)
    
    # Verify only test_special_b_causing_ctrl_c is marked as interrupted (not test_special_c_causing_pass)
    # Expected pattern: '.-' (pass, interrupted)
    # test_special_c_causing_pass should not appear in the summary since it was ignored
    assertIn('\n.-\n', late_stdout_str)
    
    # Verify summary status line mentions interrupted tests
    assertIn('interrupted=1', late_stdout_str)
    assertIn('FAILURE', late_stdout_str)
    
    # Verify 'Rerun interrupted tests with:' section exists
    assertIn('Rerun interrupted tests with:', late_stdout_str)
    assertIn('crystal --test crystal.tests.test_runner.test_special_b_causing_ctrl_c', late_stdout_str)
    
    # Verify test_special_c_causing_pass was NOT run (it was on stdin but ignored after Ctrl-C)
    assertNotIn('test_special_c_causing_pass', late_stdout_str)
    
    # Verify exit code indicates failure
    assertNotEqual(0, returncode, f'Expected non-zero exit code, got {returncode}')


# NOTE: This is not a real test. It is used by:
#       - test_when_ctrl_c_pressed_while_tests_running_then_marks_that_test_and_all_following_tests_as_interrupted
#       - test_when_ctrl_c_pressed_while_test_running_interactively_then_marks_that_test_as_interrupted_and_ignores_further_tests_on_stdin
def test_special_a_causing_pass() -> None:
    pass


# NOTE: This is not a real test. It is used by:
#       - test_when_ctrl_c_pressed_while_tests_running_then_marks_that_test_and_all_following_tests_as_interrupted
#       - test_when_ctrl_c_pressed_while_test_running_interactively_then_marks_that_test_as_interrupted_and_ignores_further_tests_on_stdin
def test_special_b_causing_ctrl_c() -> None:
    # Simulate pressing Ctrl-C if a special environment variable is set.
    if os.environ.get('CRYSTAL_SIMULATE_CTRL_C_DURING_TEST') == '1':
        raise KeyboardInterrupt


# NOTE: This is not a real test. It is used by:
#       - test_when_ctrl_c_pressed_while_tests_running_then_marks_that_test_and_all_following_tests_as_interrupted
#       - test_when_ctrl_c_pressed_while_test_running_interactively_then_marks_that_test_as_interrupted_and_ignores_further_tests_on_stdin
def test_special_c_causing_pass() -> None:
    pass


# === Testing Tests (test): Parallel ===

# NOTE: `test --parallel` is tested in multiple locations:
# - "# === Testing Tests (test): Parallel ==="
# - TestInterruptRunParallelTestWorker
# - TestParseAndDisplayOutputOfInterruptedParallelTestWorkerProcess

def test_can_run_tests_in_parallel() -> None:
    """Test that 'crystal test --parallel <test_name>' works."""
    result = run_crystal([
        'test',
        '--parallel',
        # NOTE: This is a simple, fast test
        'crystal.tests.test_main_window.test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors'
    ])
    assertEqual(0, result.returncode)
    assertIn('OK', result.stdout)
    assertIn('Ran 1 tests', result.stdout)


def test_can_run_tests_in_parallel_with_explicit_job_count() -> None:
    """Test that 'crystal test --parallel -j 2 <test_name>' works."""
    result = run_crystal([
        'test',
        '--parallel', '-j', '2',
        # NOTE: This is a simple, fast test
        'crystal.tests.test_main_window.test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors'
    ])
    assertEqual(0, result.returncode)
    assertIn('OK', result.stdout)
    assertIn('Ran 1 tests', result.stdout)


def test_when_interactive_flag_used_with_parallel_then_prints_error() -> None:
    """Test that 'crystal test --parallel --interactive' is rejected."""
    result = run_crystal([
        'test',
        '--parallel',
        '--interactive',
    ])
    assert result.returncode != 0
    assertIn('error: --interactive cannot be used with -p/--parallel', result.stderr)


def test_when_jobs_flag_used_without_parallel_then_prints_error() -> None:
    """Test that 'crystal test -j 2 <test_name>' without --parallel is rejected."""
    result = run_crystal([
        'test',
        '-j', '2',
        'crystal.tests.test_main_window.test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors'
    ])
    assert result.returncode != 0
    assertIn('error: -j/--jobs can only be used with -p/--parallel', result.stderr)


def test_can_run_tests_in_parallel_with_verbose_flag() -> None:
    """Test that 'crystal test --parallel -v <test_name>' works and prints verbose output."""
    result = run_crystal([
        'test',
        '--parallel', '-v',
        # NOTE: This is a simple, fast test
        'crystal.tests.test_main_window.test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors'
    ])
    assertEqual(0, result.returncode)
    assertIn('OK', result.stdout)
    assertIn('Ran 1 tests', result.stdout)
    # Verbose mode should print additional diagnostic information to stderr
    assertIn('[Runner]', result.stderr)


# NOTE: More kinds of raw test names are tested in TestNormalizeTestNames
def test_can_run_tests_in_parallel_with_unqualified_function_or_module_name() -> None:
    result = run_crystal([
        'test',
        '--parallel',
        # NOTE: This is a simple, fast test
        'test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors',
        # NOTE: This is a fast test module
        'test_profile',
    ])
    assertEqual(0, result.returncode)
    assertRegex(result.stdout, r'Ran \d+ tests')


@with_subtests
def test_when_ctrl_c_pressed_while_test_running_in_parallel_then_marks_that_test_and_all_following_tests_as_interrupted(subtests: SubtestsContext) -> None:
    def run_tests_and_interrupt_child_process(worker_task_indexes: str) -> tuple[str, int]:
        # NOTE: Print something regularly so that watchdog doesn't timeout
        #       the test on slow CI runners like macOS
        print(f'interrupt child: {worker_task_indexes=!r}')
        
        with crystal_running(
            args=[
                'test',
                '--parallel',
                '-j', '2',
                # Test 0: Fast test that should pass
                'crystal.tests.test_runner.test_special_a_causing_pass',
                # Test 1: Special test that simulates Ctrl-C
                'crystal.tests.test_runner.test_special_b_causing_ctrl_c',
                # Test 2: Fast test that should pass, if it is not interrupted
                'crystal.tests.test_runner.test_special_c_causing_pass',
            ],
            env_extra={
                # Assign tests to workers deterministically
                'CRYSTAL_PARALLEL_WORKER_TASKS': worker_task_indexes,
                # Enable Ctrl-C simulation in test_special_b_causing_ctrl_c
                'CRYSTAL_SIMULATE_CTRL_C_DURING_TEST': '1',
            },
        ) as crystal:
            (stdout_str, _) = crystal.communicate()
            returncode = crystal.returncode
        return (stdout_str, returncode)
    
    def run_tests_and_interrupt_parent_process(worker_task_indexes: str) -> tuple[str, int]:
        # NOTE: Print something regularly so that watchdog doesn't timeout
        #       the test on slow CI runners like macOS
        print(f'interrupt parent: {worker_task_indexes=!r}')
        
        with crystal_running(
            args=[
                'test',
                '--parallel',
                '-j', '2',
                # Test 0: Fast test that should pass, if it is not interrupted
                'crystal.tests.test_runner.test_special_a_causing_pass',
                # Test 1: Fast test that should pass, if it is not interrupted
                'crystal.tests.test_runner.test_special_c_causing_pass',
            ],
            env_extra={
                # Assign tests to workers deterministically
                'CRYSTAL_PARALLEL_WORKER_TASKS': worker_task_indexes,
            },
        ) as crystal:
            (stdout_str, _) = crystal.communicate()
            returncode = crystal.returncode
        return (stdout_str, returncode)
    
    # target_process='child'
    if True:
        with subtests.test(target_process='child', allocation='all_together'):
            # - Worker 0: Tests 0, 1, 2 (all tests)
            # - Worker 1: nothing
            (stdout_str, returncode) = run_tests_and_interrupt_child_process(
                '0,1,2;')
            
            summary_line = not_none(re.search(r'\n([-.E]{3})\n', stdout_str)).group(1)
            assertEqual('.--', summary_line)
            assertEqual(1, returncode)
        
        with subtests.test(target_process='child', allocation='ctrl_c_alone'):
            # - Worker 0: Tests 0, 2 (fast pass tests)
            # - Worker 1: Test 1 (Ctrl-C test)
            (stdout_str, returncode) = run_tests_and_interrupt_child_process(
                '0,2;1')
            
            summary_line = not_none(re.search(r'\n([-.E]{3})\n', stdout_str)).group(1)
            assertEqual('.-.', summary_line)
            assertEqual(1, returncode)
        
        with subtests.test(target_process='child', allocation='ctrl_c_plus_another'):
            # - Worker 0: Tests 0
            # - Worker 1: Test 1 (Ctrl-C test), 2
            (stdout_str, returncode) = run_tests_and_interrupt_child_process(
                '0;1,2')
            
            summary_line = not_none(re.search(r'\n([-.E]{3})\n', stdout_str)).group(1)
            assertEqual('.--', summary_line)
            assertEqual(1, returncode)
    
    # target_process='parent'
    if True:
        with subtests.test(target_process='parent', num_interrupted=2, allocation='all_together'):
            (stdout_str, returncode) = run_tests_and_interrupt_parent_process(
                '!,0,1;!')
            
            summary_line = not_none(re.search(r'\n([-.E]{2})\n', stdout_str)).group(1)
            assertEqual('--', summary_line)
            assertEqual(1, returncode)
        
        with subtests.test(target_process='parent', num_interrupted=2, allocation='all_separate'):
            (stdout_str, returncode) = run_tests_and_interrupt_parent_process(
                '!,0;!,1')
            
            summary_line = not_none(re.search(r'\n([-.E]{2})\n', stdout_str)).group(1)
            assertEqual('--', summary_line)
            assertEqual(1, returncode)
        
        with subtests.test(target_process='parent', num_interrupted=1, allocation='all_together'):
            (stdout_str, returncode) = run_tests_and_interrupt_parent_process(
                '0,!,1;!')
            
            summary_line = not_none(re.search(r'\n([-.E]{2})\n', stdout_str)).group(1)
            assertEqual('.-', summary_line)
            assertEqual(1, returncode)
        
        with subtests.test(target_process='parent', num_interrupted=1, allocation='all_separate'):
            (stdout_str, returncode) = run_tests_and_interrupt_parent_process(
                '0,!;!,1')
            
            summary_line = not_none(re.search(r'\n([-.E]{2})\n', stdout_str)).group(1)
            assertEqual('.-', summary_line)
            assertEqual(1, returncode)
        
        with subtests.test(target_process='parent', num_interrupted=0, allocation='all_together'):
            (stdout_str, returncode) = run_tests_and_interrupt_parent_process(
                '0,1,!;!')
            
            summary_line = not_none(re.search(r'\n([-.E]{2})\n', stdout_str)).group(1)
            assertEqual('..', summary_line)
            assertEqual(0, returncode)
        
        with subtests.test(target_process='parent', num_interrupted=0, allocation='all_separate'):
            (stdout_str, returncode) = run_tests_and_interrupt_parent_process(
                '0,!;1,!')
            
            summary_line = not_none(re.search(r'\n([-.E]{2})\n', stdout_str)).group(1)
            assertEqual('..', summary_line)
            assertEqual(0, returncode)


@with_subtests
def test_output_format_of_running_tests_in_parallel_and_in_serial_are_identical(subtests: SubtestsContext) -> None:
    _3_PASSING_TESTS = [
        # Test 0: Fast test that should pass
        'crystal.tests.test_runner.test_special_a_causing_pass',
        # Test 1: Fast test that should pass
        'crystal.tests.test_runner.test_special_b_causing_ctrl_c',
        # Test 2: Fast test that should pass
        'crystal.tests.test_runner.test_special_c_causing_pass',
    ]
    
    TEST_0_LINES = [
        '======================================================================',
        'RUNNING: test_special_a_causing_pass (crystal.tests.test_runner.test_special_a_causing_pass) [$%]',
        '----------------------------------------------------------------------',
        'OK',
        '',
    ]
    TEST_1_LINES = [
        '======================================================================',
        'RUNNING: test_special_b_causing_ctrl_c (crystal.tests.test_runner.test_special_b_causing_ctrl_c) [$%]',
        '----------------------------------------------------------------------',
        'OK',
        '',
    ]
    TEST_2_LINES = [
        '======================================================================',
        'RUNNING: test_special_c_causing_pass (crystal.tests.test_runner.test_special_c_causing_pass) [$%]',
        '----------------------------------------------------------------------',
        'OK',
        '',
    ]
    SUMMARY_LINES = lambda num_tests: [
        '======================================================================',
        'SUMMARY',
        '----------------------------------------------------------------------',
        '.' * num_tests,
        '----------------------------------------------------------------------',
        'Ran $ tests in $.$s',
        '',
        'OK',
    ]
    
    TEST_X_LINES = {
        0: TEST_0_LINES,
        1: TEST_1_LINES,
        2: TEST_2_LINES,
    }
    
    def run_tests_in_serial(num_tests: int) -> str:
        with crystal_running(
            args=[
                'test',
                *_3_PASSING_TESTS[:num_tests],
            ],
            env_extra={
                # DISABLE Ctrl-C simulation in test_special_b_causing_ctrl_c
                'CRYSTAL_SIMULATE_CTRL_C_DURING_TEST': '0',
            },
        ) as crystal:
            (stdout_str, _) = crystal.communicate()
        return stdout_str
    
    def run_tests_in_parallel(num_tests: int, worker_task_indexes: str) -> str:
        with crystal_running(
            args=[
                'test',
                '--parallel',
                '-j', '2',
                *_3_PASSING_TESTS[:num_tests],
            ],
            env_extra={
                # Assign tests to workers deterministically
                'CRYSTAL_PARALLEL_WORKER_TASKS': worker_task_indexes,
                # DISABLE Ctrl-C simulation in test_special_b_causing_ctrl_c
                'CRYSTAL_SIMULATE_CTRL_C_DURING_TEST': '0',
            },
        ) as crystal:
            (stdout_str, _) = crystal.communicate()
        return stdout_str
    
    def output_to_lines(stdout_str: str) -> list[str]:
        # Replace runs of digits with '$', to normalize the following kind of lines:
        # - 'Ran 3 tests in 1.234s' -> 'Ran $ tests in $.$s'
        # - 'RUNNING: X (Y) [50%]'  -> 'RUNNING: X (Y) [$%]'
        normalized_str = re.sub(r'\d+', '$', stdout_str)
        # Split lines
        lines = normalized_str.rstrip('\n').split('\n')
        # Remove trailing BEL character
        if len(lines) > 0 and lines[-1] == '\x07':
            del lines[-1]
        return lines
    
    def tests_mentioned_in_output(lines: list[str]) -> list[int]:
        test_indexes = []
        for line in lines:
            if not line.startswith('RUNNING:'):
                continue
            # Extract the test function name from the RUNNING line
            # Format: "RUNNING: test_name (crystal.tests.test_cli.test_name) [$%]"
            match = re.search(r'RUNNING: (\S+) \(', line)
            if not match:
                continue
            short_test_name = match.group(1)
            for (i, full_test_name) in enumerate(_3_PASSING_TESTS):
                if full_test_name.endswith(short_test_name):
                    test_indexes.append(i)
                    break
            else:
                raise AssertionError(
                    f'RUNNING line does not match any of the expected tests. '
                    f'{line=!r}, tests={_3_PASSING_TESTS!r}')
        return test_indexes
    
    with subtests.test('serial format matches expected', return_if_failure=True):
        # Ensure serial test output looks the way we expect
        actual_serial_lines = output_to_lines(run_tests_in_serial(num_tests=3))
        expected_serial_lines = (
            TEST_0_LINES +
            TEST_1_LINES +
            TEST_2_LINES +
            SUMMARY_LINES(3)
        )
        assertEqual(
            expected_serial_lines, actual_serial_lines,
            'Output of "crystal test <test_names>" has changed format!')
    
    with subtests.test('parallel format matches serial', num_tests=1, return_if_failure=True):
        actual_parallel_lines = output_to_lines(run_tests_in_parallel(
            num_tests=1,
            worker_task_indexes='0;'))
        expected_parallel_lines = (
            TEST_0_LINES +
            SUMMARY_LINES(1)
        )
        assertEqual(
            expected_parallel_lines, actual_parallel_lines,
            'Output of "crystal test --parallel <test_names>" with 1 test '
            'does not match output of "crystal test <test_names>"')
    
    for worker_task_indexes in ['0,1;', '0;1', ';0,1']:
        with subtests.test('parallel format matches serial', num_tests=2, worker_task_indexes=worker_task_indexes):
            actual_parallel_lines = output_to_lines(run_tests_in_parallel(
                num_tests=2,
                worker_task_indexes=worker_task_indexes))
            test_indexes = tests_mentioned_in_output(actual_parallel_lines)
            assertEqual(2, len(test_indexes))
            expected_parallel_lines = (
                TEST_X_LINES[test_indexes[0]] +
                TEST_X_LINES[test_indexes[1]] +
                SUMMARY_LINES(2)
            )
            assertEqual(
                expected_parallel_lines, actual_parallel_lines,
                'Output of "crystal test --parallel <test_names>" with 2 tests '
                'does not match output of "crystal test <test_names>"')
    
    for worker_task_indexes in ['0,1,2;', '0,1;2', '0,2;1', '0;1,2', '1;0,2', ';0,1,2']:
        with subtests.test('parallel format matches serial', num_tests=3, worker_task_indexes=worker_task_indexes):
            actual_parallel_lines = output_to_lines(run_tests_in_parallel(
                num_tests=3,
                worker_task_indexes=worker_task_indexes))
            test_indexes = tests_mentioned_in_output(actual_parallel_lines)
            assertEqual(3, len(test_indexes))
            expected_parallel_lines = (
                TEST_X_LINES[test_indexes[0]] +
                TEST_X_LINES[test_indexes[1]] +
                TEST_X_LINES[test_indexes[2]] +
                SUMMARY_LINES(3)
            )
            assertEqual(
                expected_parallel_lines, actual_parallel_lines,
                'Output of "crystal test --parallel <test_names>" with 3 tests '
                'does not match output of "crystal test <test_names>"')


# === Testing Tests (test): Help ===

def test_tests_are_not_mentioned_in_crystal_help() -> None:
    result = run_crystal(['--help'])
    assertEqual(0, result.returncode)
    assertNotIn('test', result.stdout)
    assertNotIn('--test', result.stdout)


def test_can_run_tests_subcommand_with_help_flag() -> None:
    result = run_crystal(['test', '--help'])
    assertEqual(0, result.returncode)
    # TODO: Investigate why this isn't appearing in the help
    #assertIn('Run automated tests.', result.stdout)
    assertIn('--interactive', result.stdout)
    assertIn('--parallel', result.stdout)
    assertIn('-j', result.stdout)
    assertIn('--jobs', result.stdout)
    assertIn('-v', result.stdout)
    assertIn('--verbose', result.stdout)


# === Page Objects: OpenOrCreateDialog Tests ===

async def test_when_main_window_left_open_then_ocd_wait_for_does_recover_gracefully() -> None:
    # Intentionally leave a MainWindow open, simulating a test failure
    ocd1 = await OpenOrCreateDialog.wait_for()
    main_window = await ocd1.create_and_leave_open()
    
    # Wait for an OpenOrCreateDialog to appear, simulating a newly started test.
    # But it won't appear because the MainWindow is still open.
    # OpenOrCreateDialog should detect this and attempt to recover automatically.
    # 
    # The recovery mechanism should:
    # 1. Detect that a MainWindow is open
    # 2. Print a warning message
    # 3. Close the MainWindow (handling any "Do you want to save?" dialog)
    # 4. Wait for the OpenOrCreateDialog to appear
    with redirect_stderr(io.StringIO()) as captured_stderr:
        ocd2 = await OpenOrCreateDialog.wait_for(timeout=1.0)
    assertIn(
        'WARNING: OpenOrCreateDialog.wait_for() noticed that a MainWindow was left open',
        captured_stderr.getvalue()
    )


# === Page Objects: MainWindow Tests ===

async def test_when_main_window_left_open_then_mw_connect_does_recover_gracefully() -> None:
    # Intentionally leave a MainWindow open, simulating a test failure
    ocd = await OpenOrCreateDialog.wait_for()
    main_window = await ocd.create_and_leave_open()
    try:
        # Wait for an OpenOrCreateDialog to appear, simulating a newly started test.
        # But it won't appear because the MainWindow is still open.
        # OpenOrCreateDialog should detect this and attempt to recover automatically.
        # 
        # The recovery mechanism should:
        # 1. Detect that a MainWindow is open
        # 2. Print a warning message
        with redirect_stderr(io.StringIO()) as captured_stderr:
            with Project() as project, \
                    RealMainWindow(project) as rmw:
                # NOTE: Calls MainWindow._connect() internally
                mw = await MainWindow.wait_for(timeout=1)
                
                ...  # remainder of simulated test
        assertIn(
                'WARNING: MainWindow._connect() noticed that a MainWindow was left open',
                captured_stderr.getvalue()
            )
    finally:
        await main_window.close()

