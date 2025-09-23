from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from crystal.tests import (
    test_bulkheads, test_callout, test_cli, test_disk_io_errors, test_do_not_download_groups,
    test_download, test_download_body, test_edit_group, test_edit_root_url,
    test_entitytree, test_file_extension_visibility, test_hibernate,
    test_icons, test_install_to_desktop, test_load_urls, test_log_drawer,
    test_main_window,
    test_menus, test_new_group, test_new_root_url, test_open_project,
    test_parse_html, test_profile, test_project_migrate, test_readonly_mode,
    test_runner, test_server, test_shell, test_ssd, test_tasks, test_tasktree,
    test_untitled_projects,
    test_window_modal_titles, test_workflows, test_xthreading,
)
from crystal.tests.util.downloads import delay_between_downloads_minimized
from crystal.tests.util.runner import run_test
from crystal.tests.util.subtests import SubtestFailed
from crystal.util.test_mode import tests_are_running
from crystal.util.xcollections.dedup import dedup_list
from crystal.util.xos import is_windows
from crystal.util.xthreading import bg_affinity, fg_call_and_wait, has_foreground_thread, is_foreground_thread
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
def run_tests(test_names: list[str]) -> bool:
    """
    Runs automated UI tests, printing a summary report,
    and returning whether the run was OK.
    
    The format of the summary report is designed to be similar
    to that used by Python's unittest module.
    """
    # Disable auto-reopening of untitled projects during tests by default.
    # This prevents tests from unexpectedly auto-opening unsaved untitled projects
    # that were created outside of the test environment.
    os.environ.setdefault('CRYSTAL_NO_REOPEN_PROJECTS', 'True')
    
    with delay_between_downloads_minimized(), sleep_profiled(), \
            _future_result_deadlock_detection(), _tqdm_locks_disabled():
        # 1. Normalize test names to handle various input formats
        # 2. Error if a test name cannot be resolved to a valid module or function
        try:
            normalized_test_names = _normalize_test_names(test_names)
        except ValueError as e:
            print(f'ERROR: {e}', file=sys.stderr)
            return False
        
        return _run_tests(normalized_test_names)


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
            error_msg += f'\n\nAvailable test modules: {", ".join(sorted(available_modules))}'
        raise ValueError(error_msg)
    
    return normalized


def _run_tests(test_names: list[str]) -> bool:
    # Ensure ancestor caller did already call set_tests_are_running()
    assert tests_are_running()
    
    result_for_test_func_id = {}  # type: Dict[_TestFuncId, Optional[Exception]]
    start_time = time.time()  # capture
    run_count = 0
    with warnings.catch_warnings(record=True) as warning_list, _warnings_sent_to_ci():
        assert warning_list is not None
        
        test_funcs_to_run = []
        for test_func in _TEST_FUNCS:
            if not callable(test_func):
                raise ValueError(f'Test function is not callable: {test_func}')
            test_func_id = (test_func.__module__, test_func.__name__)  # type: _TestFuncId
            test_name = f'{test_func_id[0]}.{test_func_id[1]}'
            
            # Only run test if it was requested (or if all tests are to be run)
            if len(test_names) > 0:
                if test_name not in test_names and test_func.__module__ not in test_names:
                    continue
            test_funcs_to_run.append(test_func)
            
        num_test_funcs_to_run = len(test_funcs_to_run)  # cache
        for (test_func_index, test_func) in enumerate(test_funcs_to_run):
            test_func_id = (test_func.__module__, test_func.__name__)
            test_name = f'{test_func_id[0]}.{test_func_id[1]}'
            
            run_count += 1
            
            os.environ['CRYSTAL_SCREENSHOT_ID'] = test_name
            
            print('=' * 70)
            (numer, denom) = (test_func_index+1, num_test_funcs_to_run)
            print(f'RUNNING: {test_func_id[1]} ({test_func_id[0]}.{test_func_id[1]}) [{int(numer*100/denom)}%]')
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
                break

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
    
    end_time = time.time()  # capture
    delta_time = end_time - start_time
    
    failure_count = 0
    error_count = 0
    skip_count = 0
    failed_test_names = []
    for (test_func_id, result) in result_for_test_func_id.items():
        if result is None:
            pass
        elif isinstance(result, SkipTest):
            skip_count += 1
        else:
            if isinstance(result, AssertionError):
                failure_count += 1
            else:
                error_count += 1
            
            test_name = f'{test_func_id[0]}.{test_func_id[1]}'
            failed_test_names.append(test_name)
    
    is_ok = (failure_count + error_count) == 0
    
    suffix_parts = []
    if failure_count != 0:
        suffix_parts.append(f'failures={failure_count}')
    if error_count != 0:
        suffix_parts.append(f'errors={error_count}')
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
        print(f'Available test modules: {", ".join(sorted(available_modules))}')
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
    
    # Play bell sound in terminal
    print('\a', end='', flush=True)
    
    return is_ok

# === Utility ===

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
