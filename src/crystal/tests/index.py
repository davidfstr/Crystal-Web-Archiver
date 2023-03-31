from crystal.tests import (
    test_shell,
    test_workflows,
)
from crystal.tests.util.downloads import delay_between_downloads_minimized
from crystal.tests.util.runner import run_test
from functools import wraps
import os
import sys
import time
import traceback
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple
from unittest import SkipTest


# TODO: Avoid the need to manually enumerate all test functions individually
_TEST_FUNCS = [
    # test_shell
    test_shell.test_can_launch_with_shell,
    test_shell.test_shell_exits_with_expected_message,
    test_shell.test_can_read_project_with_shell,
    test_shell.test_can_write_project_with_shell,
    
    # test_workflows
    test_workflows.test_can_download_and_serve_a_static_site,
    test_workflows.test_can_download_and_serve_a_site_requiring_dynamic_url_discovery,
    test_workflows.test_can_download_and_serve_a_site_requiring_dynamic_link_rewriting,
    test_workflows.test_cannot_download_anything_given_project_is_opened_as_readonly,
    test_workflows.test_can_update_downloaded_site_with_newer_page_revisions,
    test_workflows.test_can_download_and_serve_a_site_requiring_cookie_authentication,
]


_TestFuncId = Tuple[str, str]  # (module, func_name)


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
    os.environ['CRYSTAL_RUNNING_TESTS'] = 'True'
    
    result_for_test_func_id = {}  # type: Dict[_TestFuncId, Optional[Exception]]
    start_time = time.time()  # capture
    run_count = 0
    for test_func in _TEST_FUNCS:
        test_func_id = (test_func.__module__, test_func.__name__)  # type: _TestFuncId
        test_name = f'{test_func_id[0]}.{test_func_id[1]}'
        
        # Only run test if it was requested (or if all tests are to be run)
        if len(test_names) > 0:
            if test_name not in test_names:
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
            
            print('SKIP')
        except Exception as e:
            result_for_test_func_id[test_func_id] = e
            
            traceback.print_exc(file=sys.stdout)
            print('ERROR')
        else:
            result_for_test_func_id[test_func_id] = None
            
            print('OK')
        print()
    end_time = time.time()  # capture
    delta_time = end_time - start_time
    
    failure_count = 0
    error_count = 0
    skip_count = 0
    for result in result_for_test_func_id.values():
        if result is None:
            pass
        elif isinstance(result, AssertionError):
            failure_count += 1
        elif isinstance(result, SkipTest):
            skip_count += 1
        else:
            error_count += 1
    
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
    
    return is_ok


