from contextlib import contextmanager
from crystal.tests.util.downloads import delay_between_downloads_minimized
from crystal.tests.util.runner import run_test
from crystal.tests.util.subtests import SubtestFailed
from crystal.util.xthreading import bg_affinity
from crystal.util.xtime import sleep_profiled
from functools import wraps
import gc
from importlib import import_module
import os
import sys
import time
import traceback
from typing import Any, Callable, Coroutine, Dict, List, Iterator, Optional, Tuple
from unittest import SkipTest
import warnings


# Path to parent directory of the "crystal" package
_SOURCE_DIRPATH = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


_TestFuncId = Tuple[str, str]  # (module, func_name)


# TODO: Rename "test_names" to something more appropriate,
#       now that items can also refer to test modules (and not just test functions)
@bg_affinity
def run_tests(test_names: List[str]) -> bool:
    """
    Runs automated UI tests, printing a summary report,
    and returning whether the run was OK.
    
    The format of the summary report is designed to be similar
    to that used by Python's unittest module.
    """
    with delay_between_downloads_minimized(), sleep_profiled():
        return _run_tests(test_names)


def _run_tests(test_names: List[str]) -> bool:
    assert os.environ.get('CRYSTAL_RUNNING_TESTS') == 'True'
    
    result_for_test_func_id = {}  # type: Dict[_TestFuncId, Optional[Exception]]
    start_time = time.time()  # capture
    run_count = 0
    with warnings.catch_warnings(record=True) as warning_list, _warnings_sent_to_ci():
        assert warning_list is not None
        
        # Discover all test functions,
        # possibly raising ImportError if a test module cannot be imported
        test_funcs = list(_discover_test_functions(_SOURCE_DIRPATH))
        
        # Run each test function
        for test_func in test_funcs:
            if not callable(test_func):
                raise ValueError(f'Test function is not callable: {test_func}')
            test_func_id = (test_func.__module__, test_func.__name__)  # type: _TestFuncId
            test_name = f'{test_func_id[0]}.{test_func_id[1]}'
            
            # Only run test if it was requested (or if all tests are to be run)
            if len(test_names) > 0:
                if test_name not in test_names and test_func.__module__ not in test_names:
                    continue
            run_count += 1
            
            os.environ['CRYSTAL_SCREENSHOT_ID'] = test_name
            
            print('=' * 70)
            print(f'RUNNING: {test_func_id[1]} ({test_func_id[0]})')
            print('-' * 70)
            try:
                run_test(test_func)
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
            
            # Garbage collect, running any finalizers in __del__() early,
            # such as the warnings printed by ListenableMixin
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
    print(f'{"OK" if is_ok else "FAILURE"}{suffix}')
    
    # Print warnings, if any
    if len(warning_list) >= 1:
        print()
        print('Warnings:')
        for w in warning_list:
            if w.filename.startswith(_SOURCE_DIRPATH):
                short_filepath = os.path.relpath(w.filename, start=_SOURCE_DIRPATH)
            else:
                short_filepath = w.filename
            w_str = warnings.formatwarning(w.message, w.category, short_filepath, w.lineno, w.line)
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


def _discover_test_functions(tests_dirpath: str) -> Iterator[Callable]:
    """
    Discovers a list of test functions found within the specified dirpath.
    
    Test functions will be returned ordered such that:
    - test modules are sorted by fully qualified name
    - test functions appear in the order they are defined in the test module
    
    Raises:
    * ImportError -- 
        if a test module failed to import,
        perhaps due to a syntax error or a runtime error 
        in code executed at the top-level
    """
    for (parent_dirpath, dirnames, filenames) in os.walk(tests_dirpath):
        # Visit files in sorted order
        for fn in sorted(filenames):
            if fn.startswith('test_') and fn.endswith('.py'):
                module_relpath = os.path.relpath(
                    os.path.join(parent_dirpath, fn),
                    start=tests_dirpath)
                module_importpath = '.'.join(
                    module_relpath[:-len('.py')].split(os.path.sep)
                )
                try:
                    module = import_module(module_importpath)
                except Exception:
                    raise ImportError(f'Error while importing test module {module_importpath!r}')
                yield from _test_functions_in_module(module)
        
        # Visit subdirectories in sorted order
        dirnames[:] = sorted(dirnames)


def _test_functions_in_module(mod) -> List[Callable]:
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
        #     - macOS: setup/dist/Crystal Web Archiver.app/Contents/Resources/lib/python38.zip/crystal/tests/index.py
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
