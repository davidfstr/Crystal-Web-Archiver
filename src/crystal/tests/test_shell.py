from contextlib import contextmanager
from crystal import __version__ as crystal_version
from crystal.tests.util.wait import DEFAULT_WAIT_PERIOD, DEFAULT_WAIT_TIMEOUT, WaitTimedOut
from functools import wraps
from io import StringIO, TextIOBase
import os
import platform
import re
import subprocess
import sys
import textwrap
import time
import traceback
from typing import Callable, Iterator, List, Optional, Tuple, Union
from unittest import skip, SkipTest, TestCase


_EXPECTED_PROXY_PUBLIC_MEMBERS = []  # type: List[str]

_EXPECTED_PROJECT_PUBLIC_MEMBERS = [
    'FILE_EXTENSION',
    'add_task',
    'close',
    'default_url_prefix',
    'get_display_url',
    'get_resource',
    'get_resource_group',
    'get_root_resource',
    'is_valid',
    'listeners',
    'min_fetch_date',
    'path',
    'readonly',
    'request_cookie',
    'request_cookie_applies_to',
    'request_cookies_in_use',
    'resource_groups',
    'resources',
    'root_resources',
    'root_task',
    'server_running',
    'start_server',
    'title'
]

_EXPECTED_WINDOW_PUBLIC_MEMBERS = [
    'entity_tree',
    'frame',
    'project',
    'task_tree'
]

# ------------------------------------------------------------------------------
# Utility: Assertions

# All of these assert methods provide a better error message upon failure
# than a bare assert statement
assertEqual = TestCase().assertEqual
assertIn = TestCase().assertIn

# Not a true assertion, but similar
skipTest = TestCase().skipTest


# ------------------------------------------------------------------------------
# Utility: Subtests

class SubtestsContext:
    def __init__(self, test_name: str) -> None:
        self._test_name = test_name
        self._report = StringIO()
    
    @contextmanager
    def test(self, msg: Optional[str]=None, **kwargs: object) -> Iterator[None]:
        if msg is None and len(kwargs) == 0:
            raise ValueError()
        
        try:
            yield
        except Exception as e:
            if isinstance(e, AssertionError):
                exc_category = 'FAILURE'
                exc_traceback_useful = True
            elif isinstance(e, SkipTest):
                exc_category = 'SKIP'
                exc_traceback_useful = False
            else:
                exc_category = 'ERROR'
                exc_traceback_useful = True
            
            subtest_name_parts = [f'[{msg}] '] if msg is not None else []
            for (k, v) in kwargs.items():
                subtest_name_parts.append(f'({k}={v!r}) ')
            subtest_name = ''.join(subtest_name_parts).rstrip()
            
            print('- ' * (70 // 2), file=self._report)
            print(f'SUBTEST: {self._test_name} {subtest_name}', file=self._report)
            print('. ' * (70 // 2), file=self._report)
            if exc_traceback_useful:
                traceback.print_exc(file=self._report)
            print(exc_category, file=self._report)
        else:
            # Passed. No output.
            pass
            

def with_subtests(test_func: Callable[[SubtestsContext], None]) -> Callable[[], None]:
    test_func_id = (test_func.__module__, test_func.__name__)
    test_name = f'{test_func_id[0]}.{test_func_id[1]}'
    
    subtests = SubtestsContext(test_name)
    
    @wraps(test_func)
    def wrapper():
        raised_exc = True
        try:
            test_func(subtests)
            raised_exc = False
        finally:
            subtest_report = subtests._report.getvalue()
            if len(subtest_report) != 0:
                print(subtest_report, end='')
                print('-' * 70)
                if not raised_exc:
                    raise Exception('Subtests did fail')
    return wrapper


# ------------------------------------------------------------------------------
# Tests

@with_subtests
def test_can_launch_with_shell(subtests: SubtestsContext) -> None:
    if platform.system() == 'Windows':
        skipTest('--shell is not supported on Windows')
    
    with crystal_shell() as (crystal, banner):
        with subtests.test(msg='with informative banner'):
            # ...containing Crystal's version
            assertIn(f'Crystal {crystal_version}', banner)
            # ...containing the Python version
            python_version = '.'.join([str(x) for x in sys.version_info[:3]])
            assertIn(f'Python {python_version}', banner)
            # ...mentioning the "help" command
            assertIn('"help"', banner)
            # ...mentioning the "project" and "window" variables
            assertIn('"project"', banner)
            assertIn('"window"', banner)
            # ...mentioning how to exit (with both "exit" and Ctrl-D (or Ctrl-Z plus Return))
            assert (
                'Use exit() or Ctrl-D (i.e. EOF) to exit.' in banner or
                'Use exit() or Ctrl-Z plus Return to exit.' in banner
            ), banner
        
        with subtests.test(msg='and {project, window} can be used as placeholders, before main window appears'):
            assertEqual('<unset crystal.model.Project proxy>', _py_eval(crystal, 'project'))
            assertEqual('<unset crystal.browser.MainWindow proxy>', _py_eval(crystal, 'window'))
            
            assertIn('Help on _Proxy in module ', _py_eval(crystal, 'help(project)'))
            assertIn('Help on _Proxy in module ', _py_eval(crystal, 'help(window)'))
            
            # Ensure public members match expected set
            assertEqual(repr(_EXPECTED_PROXY_PUBLIC_MEMBERS),
                _py_eval(crystal, "[x for x in dir(project) if not x.startswith('_')]"))
            assertEqual(repr(_EXPECTED_PROXY_PUBLIC_MEMBERS),
                _py_eval(crystal, "[x for x in dir(window) if not x.startswith('_')]"))
        
        # Open MainWindow by creating new empty project
        _create_new_empty_project(crystal)
        
        with subtests.test(msg='and {project, window} can be used for real, after main window appears'):
            assert re.fullmatch(
                r'^<crystal\.model\.Project object at 0x[0-9a-f]+>$',
                _py_eval(crystal, 'project'))
            assert re.fullmatch(
                r'^<crystal\.browser\.MainWindow object at 0x[0-9a-f]+>$',
                _py_eval(crystal, 'window'))
            
            assertIn('Help on Project in module crystal.model object:', _py_eval(crystal, 'help(project)'))
            assertIn('Help on MainWindow in module crystal.browser object:', _py_eval(crystal, 'help(window)'))
            
            # Ensure public members match expected set
            assertEqual(repr(_EXPECTED_PROJECT_PUBLIC_MEMBERS),
                _py_eval(crystal, "[x for x in dir(project) if not x.startswith('_')]"))
            assertEqual(repr(_EXPECTED_WINDOW_PUBLIC_MEMBERS),
                _py_eval(crystal, "[x for x in dir(window) if not x.startswith('_')]"))


@with_subtests
def test_shell_exits_with_expected_message(subtests: SubtestsContext) -> None:
    if platform.system() == 'Windows':
        skipTest('--shell is not supported on Windows')
    
    with subtests.test(case='test when first open/create dialog is closed given shell is running then shell remains running'):
        with crystal_shell() as (crystal, _):
            _close_open_or_create_dialog(crystal)
            
            assert '4' == _py_eval(crystal, '2 + 2')
    
    with subtests.test(case='test when main window or non-first open/create dialog is closed given shell is running then shell remains running'):
        with crystal_shell() as (crystal, _):
            _create_new_empty_project(crystal)
            _close_main_window(crystal)
            
            _close_open_or_create_dialog(crystal)
            
            assert '4' == _py_eval(crystal, '2 + 2')
    
    for exit_method in ('exit()', 'Ctrl-D'):
        with subtests.test(case=f'test when {exit_method} given first open/create dialog is already closed then exits'):
            with crystal_shell() as (crystal, _):
                assert isinstance(crystal.stdin, TextIOBase)
                
                _close_open_or_create_dialog(crystal)
                
                if exit_method == 'exit()':
                    _py_eval(crystal, 'exit()', stop_suffix='')
                elif exit_method == 'Ctrl-D':
                    crystal.stdin.close()  # Ctrl-D
                else:
                    raise AssertionError()
                
                try:
                    crystal.wait(timeout=DEFAULT_WAIT_TIMEOUT)
                except subprocess.TimeoutExpired:
                    raise AssertionError('Timed out waiting for Crystal to exit')
        
        with subtests.test(case=f'test when {exit_method} given non-first open/create dialog is already closed then exits'):
            with crystal_shell() as (crystal, _):
                assert isinstance(crystal.stdin, TextIOBase)
                
                _create_new_empty_project(crystal)
                _close_main_window(crystal)
                
                _close_open_or_create_dialog(crystal)
                
                if exit_method == 'exit()':
                    _py_eval(crystal, 'exit()', stop_suffix='')
                elif exit_method == 'Ctrl-D':
                    crystal.stdin.close()  # Ctrl-D
                else:
                    raise AssertionError()
                
                try:
                    crystal.wait(timeout=DEFAULT_WAIT_TIMEOUT)
                except subprocess.TimeoutExpired:
                    raise AssertionError('Timed out waiting for Crystal to exit')
    
    for exit_method in ('exit()', 'Ctrl-D'):
        with subtests.test(case=f'test when {exit_method} given first open/create dialog still open then prints waiting message and does not exit'):
            with crystal_shell() as (crystal, _):
                assert isinstance(crystal.stdin, TextIOBase)
                
                _close_open_or_create_dialog(crystal, after_delay=.5)
                
                if exit_method == 'exit()':
                    _py_eval(crystal, 'exit()', stop_suffix='now waiting for all windows to close...\n')
                elif exit_method == 'Ctrl-D':
                    crystal.stdin.close()  # Ctrl-D
                    _read_until(crystal.stdout, 'now waiting for all windows to close...\n')
                else:
                    raise AssertionError()
                
                try:
                    crystal.wait(timeout=.5 + DEFAULT_WAIT_TIMEOUT)
                except subprocess.TimeoutExpired:
                    raise AssertionError('Timed out waiting for Crystal to exit')
        
        with subtests.test(case=f'test when {exit_method} given main window still open then prints waiting message and does not exit'):
            with crystal_shell() as (crystal, _):
                assert isinstance(crystal.stdin, TextIOBase)
                
                _create_new_empty_project(crystal)
                
                _close_main_window(crystal, after_delay=.5)
                _close_open_or_create_dialog(crystal, after_delay=.5*2)
                
                if exit_method == 'exit()':
                    _py_eval(crystal, 'exit()', stop_suffix='now waiting for all windows to close...\n')
                elif exit_method == 'Ctrl-D':
                    crystal.stdin.close()  # Ctrl-D
                    _read_until(crystal.stdout, 'now waiting for all windows to close...\n')
                else:
                    raise AssertionError()
                
                try:
                    crystal.wait(timeout=.5*2 + DEFAULT_WAIT_TIMEOUT)
                except subprocess.TimeoutExpired:
                    raise AssertionError('Timed out waiting for Crystal to exit')
        
        with subtests.test(case=f'test when {exit_method} given non-first open/create dialog still open then prints waiting message and does not exit'):
            with crystal_shell() as (crystal, _):
                assert isinstance(crystal.stdin, TextIOBase)
                
                _create_new_empty_project(crystal)
                _close_main_window(crystal)
                
                _close_open_or_create_dialog(crystal, after_delay=.5)
                
                if exit_method == 'exit()':
                    _py_eval(crystal, 'exit()', stop_suffix='now waiting for all windows to close...\n')
                elif exit_method == 'Ctrl-D':
                    crystal.stdin.close()  # Ctrl-D
                    _read_until(crystal.stdout, 'now waiting for all windows to close...\n')
                else:
                    raise AssertionError()
                
                try:
                    crystal.wait(timeout=.5 + DEFAULT_WAIT_TIMEOUT)
                except subprocess.TimeoutExpired:
                    raise AssertionError('Timed out waiting for Crystal to exit')


# ------------------------------------------------------------------------------
# Utility: Windows

_OK_THREAD_STOP_SUFFIX = (
    # If thread finishes after the "t.start()" fully completes and writes the next '>>> ' prompt
    'OK\n',
    # If thread finishes before the "t.start()" fully completes and writes the next '>>> ' prompt
    'OK\n>>> ',
    # TODO: Determine how this empiricially observed situation is possible
    'OK\n>>> >>> ',
)

def _create_new_empty_project(crystal: subprocess.Popen) -> None:
    # NOTE: Uses private API, including the entire crystal.tests package
    _py_eval(crystal, textwrap.dedent('''\
        from crystal.tests.util.runner import run_test
        from crystal.tests.util.windows import OpenOrCreateDialog
        import os
        import tempfile
        from threading import Thread

        async def create_new_project():
            # Create named temporary directory that won't be deleted automatically
            with tempfile.NamedTemporaryFile(suffix='.crystalproj', delete=False) as project_td:
                pass
            os.remove(project_td.name)
            os.mkdir(project_td.name)
            project_dirpath = project_td.name
            #
            ocd = await OpenOrCreateDialog.wait_for()
            mw = await ocd.create_and_leave_open(project_dirpath)
            #
            print('OK')
            return mw

        result_cell = [Ellipsis]
        def get_result(result_cell):
            result_cell[0] = run_test(lambda: create_new_project())

        t = Thread(target=lambda: get_result(result_cell))
        t.start()
        '''), stop_suffix=_OK_THREAD_STOP_SUFFIX)
    assert "<class 'crystal.tests.util.windows.MainWindow'>" == \
        _py_eval(crystal, 'type(result_cell[0])')


def _close_open_or_create_dialog(crystal: subprocess.Popen, *, after_delay: Optional[float]=None) -> None:
    # NOTE: Uses private API, including the entire crystal.tests package
    _py_eval(crystal, textwrap.dedent(f'''\
        from crystal.tests.util.runner import bg_sleep, run_test
        from crystal.tests.util.windows import OpenOrCreateDialog
        from threading import Thread

        async def close_ocd():
            ocd = await OpenOrCreateDialog.wait_for()
            if {after_delay} != None:
                await bg_sleep({after_delay})
            ocd.open_or_create_project_dialog.Close()
            #
            print('OK')

        t = Thread(target=lambda: run_test(close_ocd))
        t.start()
        '''), stop_suffix=_OK_THREAD_STOP_SUFFIX if after_delay is None else '')


def _close_main_window(crystal: subprocess.Popen, *, after_delay: Optional[float]=None) -> None:
    # NOTE: Uses private API, including the entire crystal.tests package
    _py_eval(crystal, textwrap.dedent(f'''\
        from crystal.tests.util.runner import bg_sleep, run_test
        from crystal.tests.util.windows import MainWindow
        from threading import Thread

        async def close_main_window():
            mw = await MainWindow.wait_for()
            if {after_delay} != None:
                await bg_sleep({after_delay})
            await mw.close()
            #
            print('OK')

        t = Thread(target=lambda: run_test(close_main_window))
        t.start()
        '''), stop_suffix=_OK_THREAD_STOP_SUFFIX if after_delay is None else '')


# ------------------------------------------------------------------------------
# Utility: Shell

@contextmanager
def crystal_shell() -> Iterator[Tuple[subprocess.Popen, str]]:
    """
    Context which starts "crystal --shell" upon enter
    and cleans up the associated process upon exit.
    """
    python = sys.executable
    crystal = subprocess.Popen(
        [python, '-m', 'crystal', '--shell'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding='utf-8')
    try:
        assert isinstance(crystal.stdout, TextIOBase)
        os.set_blocking(crystal.stdout.fileno(), False)
        
        (banner, _) = _read_until(crystal.stdout, '\n>>> ')
        yield (crystal, banner)
    finally:
        crystal.kill()


def _py_eval(python: subprocess.Popen, py_code: str, stop_suffix: Optional[Union[str, Tuple[str, ...]]]=None) -> str:
    if stop_suffix is None:
        stop_suffix = '\n>>> '
    
    assert isinstance(python.stdin, TextIOBase)
    assert isinstance(python.stdout, TextIOBase)
    python.stdin.write(f'{py_code}\n'); python.stdin.flush()
    (result, found_stop_suffix) = _read_until(python.stdout, stop_suffix)
    return result[:-len(found_stop_suffix)]


def _read_until(
        stream: TextIOBase,
        stop_suffix: Union[str, Tuple[str, ...]],
        timeout: Optional[float]=None,
        *, period: Optional[float]=None,
        ) -> Tuple[str, str]:
    """
    Reads from the specified stream until the provided `stop_suffix`
    is read at the end of the stream or the timeout expires.
    
    Raises:
    * WaitTimedOut -- if the timeout expires before `stop_suffix` is read
    """
    if isinstance(stop_suffix, str):
        stop_suffix = (stop_suffix,)
    if timeout is None:
        timeout = DEFAULT_WAIT_TIMEOUT
    if period is None:
        period = DEFAULT_WAIT_PERIOD
    
    if os.get_blocking(stream.fileno()) != False:
        raise ValueError('Expected stream to be opened in non-blocking mode')
    
    stop_suffix_bytes_choices = [s.encode(stream.encoding) for s in stop_suffix]
    
    read_buffer = b''
    found_stop_suffix = None  # type: Optional[str]
    start_time = time.time()
    while True:
        last_read_bytes = stream.buffer.read()  # type: ignore[attr-defined]
        if last_read_bytes is not None:
            # NOTE: Quadratic performance.
            #       Not using for large amounts of text so I don't care.
            read_buffer += last_read_bytes
        for (i, s_bytes) in enumerate(stop_suffix_bytes_choices):
            if read_buffer.endswith(s_bytes):
                found_stop_suffix = stop_suffix[i]
                break
        if found_stop_suffix is not None:
            break
        delta_time = time.time() - start_time
        if delta_time > timeout:
            raise WaitTimedOut(
                f'Timed out after {timeout:.1f}s while '
                f'reading until {stop_suffix!r}. '
                f'Read so far: {read_buffer.decode(stream.encoding)!r}')
        time.sleep(period)
    return (read_buffer.decode(stream.encoding), found_stop_suffix)


# ------------------------------------------------------------------------------