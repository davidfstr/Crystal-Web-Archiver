from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from crystal.app_preferences import app_prefs
from crystal.tests import (
    test_about_box,
    test_bulkheads, test_callout, test_cli, test_disk_io_errors, test_do_not_download_groups,
    test_download, test_download_body, test_edit_group, test_edit_root_url,
    test_entitytree, test_file_extension_visibility, test_hibernate,
    test_icons, test_install_to_desktop, test_load_urls, test_log_drawer,
    test_main_window,
    test_menus, test_new_group, test_new_root_url, test_open_project,
    test_parse_html, test_preferences,
    test_profile, test_project_migrate, test_readonly_mode,
    test_runner, test_server, test_shell, test_ssd, test_tasks, test_tasktree,
    test_untitled_projects,
    test_window_modal_titles, test_workflows, test_xthreading,
)
from crystal.tests.util.downloads import delay_between_downloads_minimized
from crystal.tests.util.runner import run_test
from crystal.tests.util.subtests import SubtestFailed
from crystal.util.test_mode import tests_are_running
from crystal.util.xcollections.dedup import dedup_list
from crystal.util import xcoverage
from crystal.util.xos import is_coverage, is_windows
from crystal.util.xthreading import NoForegroundThreadError, bg_affinity, fg_call_and_wait, has_foreground_thread, is_foreground_thread
from crystal.util.xtime import sleep_profiled
from crystal.util.xtraceback import _CRYSTAL_PACKAGE_PARENT_DIRPATH
import gc
import os
import sys
import time
import traceback
from typing import Dict, Optional
from unittest import SkipTest
import warnings


class _TestInterrupted(Exception):
    """Marker exception to indicate a test was interrupted by Ctrl-C."""
    pass


def _test_functions_in_module(mod) -> list[Callable]:
    return [
        f for f in mod.__dict__.values() 
        if (
            callable(f) and 
            getattr(f, '__name__', '').startswith('test_') and
            # NOTE: Need to check stringness explicitly to exclude "call" from 
            #       "from unittest.mock import call"
            isinstance(getattr(f, '__name__', ''), str)
        )
    ]

# TODO: Avoid the need to manually enumerate all test modules individually
_TEST_FUNCS = (
    _test_functions_in_module(test_about_box) +
    _test_functions_in_module(test_bulkheads) +
    _test_functions_in_module(test_callout) +
    _test_functions_in_module(test_cli) +
    _test_functions_in_module(test_disk_io_errors) +
    _test_functions_in_module(test_do_not_download_groups) +
    _test_functions_in_module(test_download) +
    _test_functions_in_module(test_download_body) +
    _test_functions_in_module(test_edit_group) +
    _test_functions_in_module(test_edit_root_url) +
    _test_functions_in_module(test_entitytree) +
    _test_functions_in_module(test_file_extension_visibility) +
    _test_functions_in_module(test_hibernate) +
    _test_functions_in_module(test_icons) +
    _test_functions_in_module(test_install_to_desktop) +
    _test_functions_in_module(test_load_urls) +
    _test_functions_in_module(test_log_drawer) +
    _test_functions_in_module(test_main_window) +
    _test_functions_in_module(test_menus) +
    _test_functions_in_module(test_new_group) +
    _test_functions_in_module(test_new_root_url) +
    _test_functions_in_module(test_open_project) +
    _test_functions_in_module(test_parse_html) +
    _test_functions_in_module(test_preferences) +
    _test_functions_in_module(test_profile) +
    _test_functions_in_module(test_project_migrate) +
    _test_functions_in_module(test_readonly_mode) +
    _test_functions_in_module(test_runner) +
    _test_functions_in_module(test_server) +
    _test_functions_in_module(test_shell) +
    _test_functions_in_module(test_ssd) +
    _test_functions_in_module(test_tasks) +
    _test_functions_in_module(test_tasktree) +
    _test_functions_in_module(test_untitled_projects) +
    _test_functions_in_module(test_window_modal_titles) +
    _test_functions_in_module(test_workflows) +
    _test_functions_in_module(test_xthreading) +
    []
)


_TestFuncId = tuple[str, str]  # (module, func_name)


# TODO: Rename "test_names" to something more appropriate,
#       now that items can also refer to test modules (and not just test functions)
@bg_affinity
def run_tests(test_names: list[str], *, interactive: bool = False) -> bool:
    """
    Runs automated UI tests, printing a summary report,
    and returning whether the run was OK.
    
    If interactive is True, test names are read from stdin one at a time
    instead of using the test_names parameter.
    
    The format of the summary report is designed to be similar
    to that used by Python's unittest module.
    """
    with delay_between_downloads_minimized(), sleep_profiled(), \
            _future_result_deadlock_detection(), _tqdm_locks_disabled():
        if not interactive:
            # 1. Normalize test names to handle various input formats
            # 2. Error if a test name cannot be resolved to a valid module or function
            try:
                normalized_test_names = _normalize_test_names(test_names)
            except ValueError as e:
                print(f'ERROR: {e}', file=sys.stderr)
                return False
        else:
            normalized_test_names = []  # ignored
        
        return _run_tests(normalized_test_names, interactive=interactive)


def _normalize_test_names(raw_test_names: list[str]) -> list[str]:
    """
    Normalize test names from various formats into the canonical format.
    
    Handles these input formats:
    - crystal.tests.test_workflows (module)
    - crystal.tests.test_workflows.test_function (function)
    - crystal.tests.test_workflows::test_function (pytest-style function)
    - src/crystal/tests/test_workflows.py (file path)
    - test_workflows (unqualified module)
    - test_function (unqualified function)
    
    Raises:
    * ValueError -- if a test name cannot be resolved to a valid module or function.
    """
    if not raw_test_names:
        return []
    
    # Build sets of available modules and functions
    available_modules = set()
    available_functions = set()
    for test_func in _TEST_FUNCS:
        module_name = test_func.__module__
        func_name = test_func.__name__
        available_modules.add(module_name)
        available_functions.add(f'{module_name}.{func_name}')
    
    normalized = []
    for raw_name in raw_test_names:
        candidates = []
        
        # Handle pytest-style function notation (::)
        if '::' in raw_name:
            parts = raw_name.split('::', 1)
            if len(parts) == 2:
                (module_part, func_part) = parts
                
                # Convert module part if it's a file path
                if module_part.endswith('.py'):
                    module_part = module_part.replace('/', '.').replace('\\', '.')
                    if module_part.startswith('src.'):
                        module_part = module_part[len('src.'):]
                    if module_part.endswith('.py'):
                        module_part = module_part[:-len('.py')]
                
                candidates.append(f'{module_part}.{func_part}')
        
        # Handle file path notation
        elif raw_name.endswith('.py'):
            file_path = raw_name.replace('/', '.').replace('\\', '.')
            if file_path.startswith('src.'):
                file_path = file_path[len('src.'):]
            if file_path.endswith('.py'):
                file_path = file_path[:-len('.py')]
            candidates.append(file_path)
        
        # Handle unqualified names (try to match against available modules/functions)
        elif '.' not in raw_name:
            # Try to match as unqualified module
            for module in available_modules:
                if module.endswith(f'.{raw_name}'):
                    candidates.append(module)
            
            # Try to match as unqualified function
            for func in available_functions:
                if func.endswith(f'.{raw_name}'):
                    candidates.append(func)
        
        # Handle already qualified names
        else:
            candidates.append(raw_name)
        
        # Gather valid candidates
        valid_candidates = []
        for candidate in candidates:
            if candidate in available_modules or candidate in available_functions:
                valid_candidates.append(candidate)
        
        # Any valid candidate? Use them.
        if valid_candidates:
            normalized.extend(valid_candidates)
            continue
        
        # No valid candidates found
        closest_matches = []
        for candidate in candidates:
            # Find close matches in available modules/functions
            for available in sorted(available_modules | available_functions):
                if candidate.lower() in available.lower() or available.lower() in candidate.lower():
                    closest_matches.append(available)
        
        error_msg = f'Test not found: {raw_name}'
        if closest_matches:
            error_msg += f'\n\nDid you mean one of: {", ".join(sorted(set(closest_matches)))}'
        else:
            error_msg += f'\n\nAvailable test modules: {_available_modules_str(available_modules)}'
        raise ValueError(error_msg)
    
    return normalized


def _run_tests(test_names: list[str], *, interactive: bool = False) -> bool:
    # Ensure ancestor caller did already call set_tests_are_running()
    assert tests_are_running()
    
    # Disable autoflush during tests for better performance
    app_prefs.autoflush = False
    
    is_coverage_now = is_coverage()  # cache
    
    if interactive:
        # Build map of available test functions
        test_func_by_name = {}  # type: dict[str, Callable]
        for test_func in _TEST_FUNCS:
            if not callable(test_func):
                raise ValueError(f'Test function is not callable: {test_func}')
            test_name = f'{test_func.__module__}.{test_func.__name__}'
            test_func_by_name[test_name] = test_func
    else:
        test_func_by_name = {}  # unused
    
    # Run selected tests
    result_for_test_func_id = {}  # type: Dict[_TestFuncId, Optional[Exception]]
    start_time = time.monotonic()  # capture
    run_count = 0
    with warnings.catch_warnings(record=True) as warning_list, _warnings_sent_to_ci():
        assert warning_list is not None
        
        if interactive:
            # Interactive mode: read test names from stdin one at a time
            while True:
                # Print prompt
                print('test>', flush=True)
                
                # Read test name from stdin
                try:
                    line = sys.stdin.readline()
                except KeyboardInterrupt:
                    # Ctrl-C pressed at the prompt - exit normally
                    print()  # new line after ^C
                    break
                
                # Check for EOF
                if not line:
                    break
                
                test_name = line.strip()
                
                # Skip empty lines
                if not test_name:
                    continue
                
                # Check if test exists
                if test_name not in test_func_by_name:
                    # Try to normalize the test name
                    try:
                        normalized_names = _normalize_test_names([test_name])
                        if normalized_names and normalized_names[0] in test_func_by_name:
                            test_name = normalized_names[0]  # reinterpret
                        else:
                            print(f'test: Test not found: {test_name}')
                            continue
                    except ValueError as e:
                        # Normalization failed
                        print(f'test: Test not found: {test_name}')
                        continue
                
                # Get test function
                test_func = test_func_by_name[test_name]
                test_func_id = (test_func.__module__, test_func.__name__)  # type: _TestFuncId
                
                # Run the single test
                try:
                    _run_single_test(
                        test_func=test_func,
                        test_func_id=test_func_id,
                        test_func_index=run_count,
                        num_test_funcs_to_run=None,
                        result_for_test_func_id=result_for_test_func_id,
                        is_coverage_now=is_coverage_now
                    )
                    run_count += 1
                except KeyboardInterrupt:
                    # Ctrl-C pressed while running test - mark as interrupted
                    print()  # new line after ^C
                    result_for_test_func_id[test_func_id] = _TestInterrupted()
                    run_count += 1
                    # In interactive mode, only mark this single test as interrupted
                    break
                except NoForegroundThreadError:
                    # Fatal error; abort
                    break
        else:
            # Batch mode: run all requested tests
            test_funcs_to_run = []
            for test_func in _TEST_FUNCS:
                if not callable(test_func):
                    raise ValueError(f'Test function is not callable: {test_func}')
                test_name = f'{test_func.__module__}.{test_func.__name__}'
                
                # Only run test if it was requested (or if all tests are to be run)
                if len(test_names) > 0:
                    if test_name not in test_names and test_func.__module__ not in test_names:
                        continue
                test_funcs_to_run.append(test_func)
                
            num_test_funcs_to_run = len(test_funcs_to_run)  # cache
            
            for (test_func_index, test_func) in enumerate(test_funcs_to_run):
                test_func_id = (test_func.__module__, test_func.__name__)
                
                # Run the single test
                try:
                    _run_single_test(
                        test_func=test_func,
                        test_func_id=test_func_id,
                        test_func_index=test_func_index,
                        num_test_funcs_to_run=num_test_funcs_to_run,
                        result_for_test_func_id=result_for_test_func_id,
                        is_coverage_now=is_coverage_now
                    )
                    run_count += 1
                except KeyboardInterrupt:
                    # Ctrl-C pressed while running test
                    print()  # new line after ^C
                    result_for_test_func_id[test_func_id] = _TestInterrupted()
                    run_count += 1
                    # Mark all remaining tests as interrupted
                    for remaining_test_func in test_funcs_to_run[test_func_index + 1:]:
                        remaining_test_func_id = (remaining_test_func.__module__, remaining_test_func.__name__)
                        result_for_test_func_id[remaining_test_func_id] = _TestInterrupted()
                    break
                except NoForegroundThreadError:
                    # Fatal error; abort
                    break
    if is_coverage_now:
        # Tell code coverage that no test is now running
        xcoverage.switch_context()
    end_time = time.monotonic()  # capture
    delta_time = end_time - start_time
    
    # Calculate summary of test run
    failure_count = 0
    error_count = 0
    skip_count = 0
    interrupted_count = 0
    failed_test_names = []
    interrupted_test_names = []
    for (test_func_id, result) in result_for_test_func_id.items():
        if result is None:
            pass
        elif isinstance(result, _TestInterrupted):
            interrupted_count += 1
            test_name = f'{test_func_id[0]}.{test_func_id[1]}'
            interrupted_test_names.append(test_name)
        elif isinstance(result, SkipTest):
            skip_count += 1
        else:
            if isinstance(result, AssertionError):
                failure_count += 1
            else:
                error_count += 1
            
            test_name = f'{test_func_id[0]}.{test_func_id[1]}'
            failed_test_names.append(test_name)
    
    # Print summary of test run
    if True:
        is_ok = (failure_count + error_count + interrupted_count) == 0
        
        suffix_parts = []
        if failure_count != 0:
            suffix_parts.append(f'failures={failure_count}')
        if error_count != 0:
            suffix_parts.append(f'errors={error_count}')
        if interrupted_count != 0:
            suffix_parts.append(f'interrupted={interrupted_count}')
        if skip_count != 0:
            suffix_parts.append(f'skipped={skip_count}')
        suffix = (
            f' ({", ".join(suffix_parts)})'
            if len(suffix_parts) != 0
            else ''
        )
        
        print('=' * 70)
        print('SUMMARY')
        print('-' * 70)
        for result in result_for_test_func_id.values():
            if result is None:
                print('.', end='')
            elif isinstance(result, _TestInterrupted):
                print('-', end='')
            elif isinstance(result, AssertionError):
                print('F', end='')
            elif isinstance(result, SkipTest):
                if str(result).startswith('covered by:'):
                    print('c', end='')
                else:
                    print('s', end='')
            else:
                print('E', end='')
        print()
        
        print('-' * 70)
        print(f'Ran {run_count} tests in {"%.3f" % delta_time}s')
        print()
        
        # Handle case where no tests were run
        if run_count == 0 and len(test_names) > 0:
            print('FAILURE: No tests were found matching the specified names')
            available_modules = set(test_func.__module__ for test_func in _TEST_FUNCS)
            print(f'Available test modules: {_available_modules_str(available_modules)}')
            print()
            return False
        
        print(f'{"OK" if is_ok else "FAILURE"}{suffix}')
    
    # Print warnings, if any
    if len(warning_list) >= 1:
        print()
        print('Warnings:')
        warning_strs = []
        for w in warning_list:
            if w.filename.startswith(_CRYSTAL_PACKAGE_PARENT_DIRPATH):
                short_filepath = os.path.relpath(w.filename, start=_CRYSTAL_PACKAGE_PARENT_DIRPATH)
            else:
                short_filepath = w.filename
            w_str = warnings.formatwarning(w.message, w.category, short_filepath, w.lineno, w.line)
            warning_strs.append(w_str)
        for w_str in sorted(dedup_list(warning_strs)):
            print('- ' + w_str, end='')
    
    # Print command to rerun failed tests
    if len(failed_test_names) != 0:
        print()
        print('Rerun failed tests with:')
        print(f'$ crystal --test {" ".join(failed_test_names)}')
        print()
    
    # Print command to rerun interrupted tests
    if len(interrupted_test_names) != 0:
        print()
        print('Rerun interrupted tests with:')
        print(f'$ crystal --test {" ".join(interrupted_test_names)}')
        print()
    
    # Play bell sound in terminal
    print('\a', end='', flush=True)
    
    return is_ok


def _run_single_test(
    test_func: Callable,
    test_func_id: _TestFuncId,
    test_func_index: int,
    num_test_funcs_to_run: Optional[int],
    result_for_test_func_id: Dict[_TestFuncId, Optional[Exception]],
    is_coverage_now: bool
) -> None:
    """
    Run a single test function and record its result.
    
    Arguments:
    * test_func -- The test function to run
    * test_func_id -- Tuple of (module, func_name)
    * test_func_index -- Index of this test in the sequence
    * num_test_funcs_to_run -- Total number of tests to run (None for interactive mode)
    * result_for_test_func_id -- Dict to record test results in
    * is_coverage_now -- Whether coverage is enabled
    
    Raises:
    * NoForegroundThreadError
    """
    test_name = f'{test_func_id[0]}.{test_func_id[1]}'
    
    if is_coverage_now:
        # Tell code coverage that new test is starting
        xcoverage.switch_context(test_name)
    
    os.environ['CRYSTAL_SCREENSHOT_ID'] = test_name
    
    app_prefs.reset()
    
    print('=' * 70)
    if num_test_funcs_to_run is not None:
        (numer, denom) = (test_func_index+1, num_test_funcs_to_run)
        suffix = f' [{int(numer*100/denom)}%]'
    else:
        suffix = ''
    print(f'RUNNING: {test_func_id[1]} ({test_func_id[0]}.{test_func_id[1]}){suffix}')
    print('-' * 70)
    try:
        try:
            run_test(test_func)
        finally:
            # Flush any stderr output immediately,
            # to keep aligned with stdout output from the test
            sys.stderr.flush()
    except AssertionError as e:
        result_for_test_func_id[test_func_id] = e
        
        traceback.print_exc(file=sys.stdout)
        print('FAILURE')
    except SkipTest as e:
        result_for_test_func_id[test_func_id] = e
        
        print(f'SKIP ({str(e)})')
    except Exception as e:
        result_for_test_func_id[test_func_id] = e
        
        if not isinstance(e, SubtestFailed):
            traceback.print_exc(file=sys.stdout)
        print(f'ERROR ({e.__class__.__name__})')
    else:
        result_for_test_func_id[test_func_id] = None
        
        print('OK')
    print()
    
    if not has_foreground_thread():
        print('FATAL ERROR: Foreground thread is not running')
        print()
        raise NoForegroundThreadError()
    
    # Garbage collect, running any finalizers in __del__() early,
    # such as the warnings printed by ListenableMixin
    # 
    # However skip forced garbage collection on Windows,
    # because it is suspected to be related to hang of the test
    # test_when_save_as_menu_item_selected_for_titled_or_untitled_project_then_shows_save_as_dialog.
    # 
    # If garbage collection is really needed on Windows,
    # then it should probably be run on the foreground thread
    # with fg_call_and_wait(), since wxPython Windows seems to
    # implicitly assume that it will be.
    if not is_windows():
        gc.collect()


# === Utility ===

def _available_modules_str(available_modules: set[str]) -> str:
    return ", ".join(sorted(available_modules)).replace("crystal.tests.", "")


@contextmanager
def _future_result_deadlock_detection():
    """
    Patch Future.result() to raise a RuntimeError if called from the foreground thread during tests.
    
    This helps catch deadlocks caused by waiting on a Future synchronously in the foreground thread.
    """
    original_result = Future.result
    def patched_result(self, timeout=None):
        if is_foreground_thread():
            # HACK: Permit timeout=None when self.done() to accomodate existing
            #       code that unsafely calls Future.result(timeout=None)
            #       in a context it believes the Future will always be done.
            if timeout is None and not self.done() and not getattr(self, '_cr_declare_no_deadlocks', False):
                raise RuntimeError(
                    "Calling Future.result() from the foreground thread will cause a deadlock. "
                    "Use 'await wait_for_future(future)' instead."
                )
        return original_result(self, timeout)

    Future.result = patched_result
    try:
        yield
    finally:
        Future.result = original_result


@contextmanager
def _tqdm_locks_disabled() -> Iterator[None]:
    """
    Context manager to ensure TqdmDefaultWriteLock.mp_lock (an RLock) is never created.
    
    This is useful to avoid warnings like:
        multiprocessing/resource_tracker.py:254: UserWarning: resource_tracker: There appear to be 1 leaked semaphore objects to clean up at shutdown
    """
    from tqdm.std import TqdmDefaultWriteLock  # type: ignore[attr-defined]
    from unittest.mock import patch
    
    @classmethod  # type: ignore[misc]
    def create_mp_lock_disabled(cls):
        if not hasattr(cls, 'mp_lock'):
            cls.mp_lock = None
    
    with patch.object(TqdmDefaultWriteLock, 'create_mp_lock', create_mp_lock_disabled):
        yield


@contextmanager
def _warnings_sent_to_ci() -> Iterator[None]:
    if not _running_in_ci():
        yield
        return
    
    super_showwarning = warnings.showwarning  # capture
    
    def showwarning(message, category, filename, lineno, file=None, line=None):
        # Try to reformat `filename` to use the Linux format so that warning
        # annotations are associated with the correct file
        # 
        # Depending on OS, `filename` initially looks like:
        #     - macOS: setup/dist/Crystal.app/Contents/Resources/lib/python38.zip/crystal/tests/index.py
        #     - Linux: src/crystal/tests/index.py
        #     - Windows: crystal\tests\index.pyc
        filename_parts = filename.split(os.path.sep)
        if 'crystal' in filename_parts:
            filename_parts = ['src'] + filename_parts[filename_parts.index('crystal'):]
            if filename_parts[-1].endswith('.pyc'):
                filename_parts[-1] = filename_parts[-1][:-1]  # convert .pyc ending to .py
            filename = '/'.join(filename_parts)  # reinterpret
        
        # Create warning annotation in GitHub Action's [Summary > Annotations] section
        # 
        # Syntax: https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions#example-setting-a-warning-message
        print(f'::warning file={filename},line={lineno}::{message}')
        
        return super_showwarning(message, category, filename, lineno, file, line)
    
    warnings.showwarning = showwarning
    try:
        yield
    finally:
        warnings.showwarning = super_showwarning


def _running_in_ci() -> bool:
    return os.environ.get('GITHUB_ACTIONS') == 'true'
