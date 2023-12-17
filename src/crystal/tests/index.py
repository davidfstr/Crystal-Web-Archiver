from crystal.tests import (
    test_disk_io_errors,
    test_download,
    test_download_body,
    test_entitytree,
    test_file_extension_visibility,
    test_icons,
    test_install_to_desktop,
    test_load_urls,
    test_log_drawer,
    test_menus,
    test_open_project,
    test_parse_html,
    test_profile,
    test_project_migrate,
    test_readonly_mode,
    test_server,
    test_shell,
    test_ssd,
    test_tasks,
    test_tasktree,
    test_workflows,
    test_xthreading,
)
from crystal.tests.util.downloads import delay_between_downloads_minimized
from crystal.tests.util.runner import run_test
from crystal.util.xthreading import bg_affinity
from functools import wraps
import gc
import os
import sys
import time
import traceback
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple
from unittest import SkipTest


def _test_functions_in_module(mod) -> List[Callable]:
    return [f for f in mod.__dict__.values() if callable(f) and getattr(f, '__name__', '').startswith('test_')]

# TODO: Avoid the need to manually enumerate all test modules individually
_TEST_FUNCS = (
    _test_functions_in_module(test_disk_io_errors) +
    _test_functions_in_module(test_download) +
    _test_functions_in_module(test_download_body) +
    _test_functions_in_module(test_entitytree) +
    _test_functions_in_module(test_file_extension_visibility) +
    _test_functions_in_module(test_icons) +
    _test_functions_in_module(test_install_to_desktop) +
    _test_functions_in_module(test_load_urls) +
    _test_functions_in_module(test_log_drawer) +
    _test_functions_in_module(test_menus) +
    _test_functions_in_module(test_open_project) +
    _test_functions_in_module(test_parse_html) +
    _test_functions_in_module(test_profile) +
    _test_functions_in_module(test_project_migrate) +
    _test_functions_in_module(test_readonly_mode) +
    _test_functions_in_module(test_server) +
    _test_functions_in_module(test_shell) +
    _test_functions_in_module(test_ssd) +
    _test_functions_in_module(test_tasks) +
    _test_functions_in_module(test_tasktree) +
    _test_functions_in_module(test_workflows) +
    _test_functions_in_module(test_xthreading) +
    []
)


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
    with delay_between_downloads_minimized():
        return _run_tests(test_names)


def _run_tests(test_names: List[str]) -> bool:
    assert os.environ.get('CRYSTAL_RUNNING_TESTS') == 'True'
    
    result_for_test_func_id = {}  # type: Dict[_TestFuncId, Optional[Exception]]
    start_time = time.time()  # capture
    run_count = 0
    for test_func in _TEST_FUNCS:
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
            
            traceback.print_exc(file=sys.stdout)
            print('ERROR')
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
            print('s', end='')
        else:
            print('E', end='')
    print()
    
    print('-' * 70)
    print(f'Ran {run_count} tests in {"%.3f" % delta_time}s')
    print()
    print(f'{"OK" if is_ok else "FAILURE"}{suffix}')
    
    if len(failed_test_names) != 0:
        print()
        print('Rerun failed tests with:')
        print(f'$ crystal --test {" ".join(failed_test_names)}')
        print()
    
    return is_ok
