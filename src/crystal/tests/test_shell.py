from ast import literal_eval
from contextlib import contextmanager
from crystal import __version__ as crystal_version
from crystal.tests.util.asserts import *
from crystal.tests.util.wait import DEFAULT_WAIT_PERIOD, DEFAULT_WAIT_TIMEOUT, WaitTimedOut
from crystal.tests.util.server import served_project
from crystal.tests.util.subtests import SubtestsContext, with_subtests
from crystal.tests.util.xos import skip_on_windows
from crystal.util.xos import is_windows
from crystal.util.xthreading import fg_call_and_wait
from functools import wraps
from io import StringIO, TextIOBase
import os
import platform
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import traceback
from typing import Callable, Iterator, List, Optional, Tuple, Union
from unittest import skip, SkipTest, TestCase
from unittest.mock import ANY


_EXPECTED_PROXY_PUBLIC_MEMBERS = []  # type: List[str]

_EXPECTED_PROJECT_PUBLIC_MEMBERS = [
    'FILE_EXTENSION',
    'OPENER_FILE_EXTENSION',
    'add_task',
    'close',
    'default_url_prefix',
    'get_display_url',
    'get_resource',
    'get_resource_group',
    'get_root_resource',
    'html_parser_type',
    'is_valid',
    'listeners',
    'load_urls',
    'major_version',
    'min_fetch_date',
    'path',
    'readonly',
    'request_cookie',
    'request_cookie_applies_to',
    'request_cookies_in_use',
    'resource_groups',
    'resources',
    'resources_matching_pattern',
    'root_resources',
    'root_task',
    'urls_matching_pattern',
]

_EXPECTED_WINDOW_PUBLIC_MEMBERS = [
    'close',
    'entity_tree',
    'project',
    'start_server',
    'task_tree'
]

# ------------------------------------------------------------------------------
# Tests

@skip_on_windows
@with_subtests
def test_can_launch_with_shell(subtests: SubtestsContext) -> None:
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
            assertEqual('<unset crystal.model.Project proxy>\n', _py_eval(crystal, 'project'))
            assertEqual('<unset crystal.browser.MainWindow proxy>\n', _py_eval(crystal, 'window'))
            
            assertIn('Help on _Proxy in module ', _py_eval(crystal, 'help(project)'))
            assertIn('Help on _Proxy in module ', _py_eval(crystal, 'help(window)'))
            
            # Ensure public members match expected set
            assertEqual(repr(_EXPECTED_PROXY_PUBLIC_MEMBERS) + '\n',
                _py_eval(crystal, "[x for x in dir(project) if not x.startswith('_')]"))
            assertEqual(repr(_EXPECTED_PROXY_PUBLIC_MEMBERS) + '\n',
                _py_eval(crystal, "[x for x in dir(window) if not x.startswith('_')]"))
        
        # Open MainWindow by creating new empty project
        _create_new_empty_project(crystal)
        
        with subtests.test(msg='and {project, window} can be used for real, after main window appears'):
            assert re.fullmatch(
                r'^<crystal\.model\.Project object at 0x[0-9a-f]+>\n$',
                _py_eval(crystal, 'project'))
            assert re.fullmatch(
                r'^<crystal\.browser\.MainWindow object at 0x[0-9a-f]+>\n$',
                _py_eval(crystal, 'window'))
        
        with subtests.test(msg='and {project, window} can be used with help()'):
            assertIn('Help on Project in module crystal.model object:', _py_eval(crystal, 'help(project)'))
            assertIn('Help on MainWindow in module crystal.browser object:', _py_eval(crystal, 'help(window)'))


@skip_on_windows
def test_can_use_pythonstartup_file() -> None:
    with tempfile.NamedTemporaryFile(suffix='.py') as startup_file:
        startup_file.write(textwrap.dedent('''\
            EXCLUDED_URLS = ['a', 'b', 'c']
            '''
        ).encode('utf-8'))
        startup_file.flush()
        
        with crystal_shell(env_extra={'PYTHONSTARTUP': startup_file.name}) as (crystal, _):
            assertEqual(
                ['a', 'b', 'c'],
                literal_eval(_py_eval(crystal, 'EXCLUDED_URLS')),
                'Expected variables written at top-level by '
                    '$PYTHONSTARTUP file to be accessible from shell'
            )


# NOTE: This test code was split out of the test_can_launch_with_shell() test above
#       because it is particularly easy to break and having a separate test function
#       makes the break type quicker to identify.
@skip_on_windows
@with_subtests
def test_builtin_globals_have_stable_public_api(subtests: SubtestsContext) -> None:
    with crystal_shell() as (crystal, banner):
        # Open MainWindow by creating new empty project
        _create_new_empty_project(crystal)
        
        with subtests.test(global_name='project'):
            assertEqual(_EXPECTED_PROJECT_PUBLIC_MEMBERS,
                literal_eval(_py_eval(crystal, "[x for x in dir(project) if not x.startswith('_')]")),
                'Public API of Project class has changed')
        
        with subtests.test(global_name='window'):
            assertEqual(_EXPECTED_WINDOW_PUBLIC_MEMBERS,
                literal_eval(_py_eval(crystal, "[x for x in dir(window) if not x.startswith('_')]")),
                'Public API of MainWindow class has changed')


@skip_on_windows
@with_subtests
def test_shell_exits_with_expected_message(subtests: SubtestsContext) -> None:
    with subtests.test(case='test when first open/create dialog is closed given shell is running then shell remains running'):
        with crystal_shell() as (crystal, _):
            _close_open_or_create_dialog(crystal)
            
            assert '4\n' == _py_eval(crystal, '2 + 2')
    
    with subtests.test(case='test when main window or non-first open/create dialog is closed given shell is running then shell remains running'):
        with crystal_shell() as (crystal, _):
            _create_new_empty_project(crystal)
            _close_main_window(crystal)
            
            _close_open_or_create_dialog(crystal)
            
            assert '4\n' == _py_eval(crystal, '2 + 2')
    
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


@skip_on_windows
@with_subtests
def test_can_read_project_with_shell(subtests: SubtestsContext) -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = 'https://xkcd.com/'
        
        project_path = sp.project.path  # capture
        fg_call_and_wait(lambda: sp.project.close())
        
        with crystal_shell() as (crystal, _):
            with subtests.test(case='test can open project', return_if_failure=True):
                # Test can import Project
                assertEqual('', _py_eval(crystal, 'from crystal.model import Project'))
                # Test can open project
                assertEqual('', _py_eval(crystal, f'p = Project({sp.project.path!r})'))
            
            with subtests.test(case='test can list project entities'):
                assertEqual(
                    "[RootResource('Home','https://xkcd.com/')]\n",
                    _py_eval(crystal, 'list(p.root_resources)[:1]'))
                assertEqual(
                    "[ResourceGroup('Comics','https://xkcd.com/#/')]\n",
                    _py_eval(crystal, 'list(p.resource_groups)'))
                assertEqual(
                    '71\n',
                    _py_eval(crystal, 'len(p.resources)'))
                assertEqual(
                    "Resource('https://xkcd.com/')\n",
                    _py_eval(crystal, 'list(p.resources)[0]'))
            
            with subtests.test(case='test can get project entities', return_if_failure=True):
                assertEqual(
                    "Resource('https://xkcd.com/')\n",
                    _py_eval(crystal, f'r = p.get_resource({home_url!r}); r'))
                
                assertEqual(
                    "[<ResourceRevision 1 for 'https://xkcd.com/'>]\n",
                    _py_eval(crystal, f'list(r.revisions())'))
                assertEqual(
                    "<ResourceRevision 1 for 'https://xkcd.com/'>\n",
                    _py_eval(crystal, f'rr = r.default_revision(); rr'))
                
                assertEqual(
                    "RootResource('Home','https://xkcd.com/')\n",
                    _py_eval(crystal, f'root_r = p.get_root_resource(r); root_r'))
                
                assertEqual(
                    "ResourceGroup('Comics','https://xkcd.com/#/')\n",
                    _py_eval(crystal, f'rg = p.get_resource_group("Comics"); rg'))
                assertEqual(
                    '14\n',
                    _py_eval(crystal, f'len(rg.members)'))
                assertEqual(
                    "Resource('https://xkcd.com/1/')\n",
                    _py_eval(crystal, f'list(rg.members)[0]'))
            
            with subtests.test(case='test can read content of resource revision'):
                assertEqual(
                    {
                        'http_version': 11,
                        'status_code': 200,
                        'reason_phrase': 'OK',
                        'headers': ANY
                    },
                    literal_eval(_py_eval(crystal, f'rr.metadata')))
                _py_eval(crystal, f'with rr.open() as f:\n    body = f.read()\n')
                assertEqual(
                    r"""b'<!DOCTYPE html>\n<html>\n<head>\n<link rel="stylesheet" type="text/css" href="/s/7d94e0.css" title="Default"/>\n<title>xkcd: Air Gap</title>\n'""" + '\n',
                    _py_eval(crystal, f'body[:137]'))


@skip_on_windows
@with_subtests
def test_can_write_project_with_shell(subtests: SubtestsContext) -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        if True:
            home_url = sp.get_request_url('https://xkcd.com/')
            
            comic1_url = sp.get_request_url('https://xkcd.com/1/')
            comic2_url = sp.get_request_url('https://xkcd.com/2/')
            comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        # Create named temporary directory that won't be deleted automatically
        with tempfile.NamedTemporaryFile(suffix='.crystalproj', delete=False) as project_td:
            pass
        os.remove(project_td.name)
        project_dirpath = project_td.name
        
        with crystal_shell() as (crystal, _):
            with subtests.test(case='test can create project', return_if_failure=True):
                # Test can import Project
                assertEqual('', _py_eval(crystal, 'from crystal.model import Project'))
                # Test can create project
                assertEqual('', _py_eval(crystal, f'p = Project({project_dirpath!r})'))
            
            with subtests.test(case='test can create project entities', return_if_failure=True):
                # Test can import Resource
                assertEqual('', _py_eval(crystal, 'from crystal.model import Resource'))
                # Test can create Resource
                assertEqual(
                    "Resource('http://localhost:2798/_/https/xkcd.com/')\n",
                    _py_eval(crystal, f'r = Resource(p, {home_url!r}); r'))
                
                # Test can import RootResource
                assertEqual('', _py_eval(crystal, 'from crystal.model import RootResource'))
                # Test can create RootResource
                assertEqual(
                    "RootResource('Home','http://localhost:2798/_/https/xkcd.com/')\n",
                    _py_eval(crystal, f'root_r = RootResource(p, "Home", r); root_r'))
                
                # Test can download ResourceRevision
                with _delay_between_downloads_minimized(crystal):
                    assertEqual('', _py_eval(crystal, 'rr_future = r.download()'))
                    while True:
                        is_done = (literal_eval(_py_eval(crystal, 'rr_future.done()')) == True)
                        if is_done:
                            break
                        time.sleep(.2)
                    assertIn('<ResourceRevision ', _py_eval(crystal, 'rr = rr_future.result(); rr'))
                
                # Test can import ResourceGroup
                assertEqual('', _py_eval(crystal, 'from crystal.model import ResourceGroup'))
                # Test can create ResourceGroup
                assertEqual(
                    "ResourceGroup('Comic','http://localhost:2798/_/https/xkcd.com/#/')\n",
                    _py_eval(crystal, f'rg = ResourceGroup(p, "Comic", {comic_pattern!r}); rg'))
                # Ensure ResourceGroup includes some members discovered by downloading resource Home
                assertEqual(
                    '9\n',
                    _py_eval(crystal, f'len(rg.members)'))
            
            with subtests.test(case='test can delete project entities', return_if_failure=True):
                # Test can delete ResourceGroup
                assertEqual('', _py_eval(crystal, f'rg_m = list(rg.members)[0]'))
                assertEqual('', _py_eval(crystal, f'rg.delete()'))
                # Ensure ResourceGroup itself is deleted
                assertEqual('', _py_eval(crystal, f'p.get_resource_group(rg.name)'))
                # Ensure former members of ResourceGroup still exist
                assertEqual('True\n', _py_eval(crystal, f'p.get_resource(rg_m.url) == rg_m'))
                
                # Test can delete RootResource
                assertEqual('', _py_eval(crystal, f'root_r_r = root_r.resource'))
                assertEqual('', _py_eval(crystal, f'root_r.delete()'))
                # Ensure RootResource itself is deleted
                assertEqual('', _py_eval(crystal, f'p.get_root_resource(root_r_r)'))
                # Ensure former target of RootResource still exists
                assertEqual('True\n', _py_eval(crystal, f'p.get_resource(root_r_r.url) == root_r_r'))
                
                # Test can delete ResourceRevision
                assertEqual('', _py_eval(crystal, f'rr_r = rr.resource'))
                assertEqual('1\n', _py_eval(crystal, f'len(list(rr_r.revisions()))'))
                assertEqual('', _py_eval(crystal, f'rr.delete()'))
                # Ensure ResourceRevision itself is deleted
                assertEqual('0\n', _py_eval(crystal, f'len(list(rr_r.revisions()))'))
                
                # Test can delete Resource
                assertEqual('', _py_eval(crystal, f'r.delete()'))
                # Ensure Resource itself is deleted
                assertEqual('', _py_eval(crystal, f'p.get_resource(r.url)'))


@skip_on_windows
def test_can_import_guppy_in_shell() -> None:
    with crystal_shell() as (crystal, _):
        # Ensure can import guppy
        import_result = literal_eval(_py_eval(crystal, 'import guppy; guppy.__version__'))
        assert isinstance(import_result, str)
        
        # Ensure can create hpy instance
        assertEqual('', _py_eval(crystal, 'from guppy import hpy; h = hpy()'))
        
        # Ensure can take memory sample
        result = _py_eval(crystal, 'import gc; gc.collect(); heap = h.heap(); heap; _.more')
        assertNotIn('Traceback', result)
        
        # Ensure can create checkpoint
        assertEqual('', _py_eval(crystal, 'h.setref()'))
        
        # Ensure can take memory sample since checkpoint
        result = _py_eval(crystal, 'import gc; gc.collect(); heap = h.heap(); heap; _.more')
        assertNotIn('Traceback', result)


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
        '''),
        stop_suffix=_OK_THREAD_STOP_SUFFIX,
        # NOTE: 6.0 was observed to sometimes not be long enough on macOS
        timeout=8.0
    )
    assert "<class 'crystal.tests.util.windows.MainWindow'>\n" == \
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


@contextmanager
def _delay_between_downloads_minimized(crystal: subprocess.Popen) -> Iterator[None]:
    # NOTE: Uses private API, including the entire crystal.tests package
    _py_eval(crystal, textwrap.dedent(f'''\
        from crystal.tests.util.downloads import delay_between_downloads_minimized as D
        download_ctx = D()
        download_ctx.__enter__()
        '''))
    try:
        yield
    finally:
        _py_eval(crystal, 'download_ctx.__exit__(None, None, None)')


# ------------------------------------------------------------------------------
# Utility: Shell

@contextmanager
def crystal_shell(*, env_extra={}) -> Iterator[Tuple[subprocess.Popen, str]]:
    """
    Context which starts "crystal --shell" upon enter
    and cleans up the associated process upon exit.
    """
    if platform.system() == 'Windows':
        # Windows doesn't provide stdout for graphical processes,
        # which is needed by the current implementation
        raise AssertionError('not supported on Windows')
    
    # Determine how to run Crystal on command line
    crystal_command: List[str]
    python = sys.executable
    if getattr(sys, 'frozen', None) == 'macosx_app':
        python_neighbors = os.listdir(os.path.dirname(python))
        (crystal_binary_name,) = [n for n in python_neighbors if 'crystal' in n.lower()]
        crystal_binary = os.path.join(os.path.dirname(python), crystal_binary_name)
        crystal_command = [crystal_binary]
    else:
        crystal_command = [python, '-m', 'crystal']
    
    crystal = subprocess.Popen(
        [*crystal_command, '--shell'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding='utf-8',
        env={
            **os.environ,
            **{
                'CRYSTAL_FAULTHANDLER': 'True',
                
                # Prevent profiling warnings from being mixed into output
                # TODO: Recommend renaming to avoid (double-)negatives
                'CRYSTAL_NO_PROFILE_FG_TASKS': 'True',
                'CRYSTAL_NO_PROFILE_GC': 'True',
                'CRYSTAL_NO_PROFILE_RECORD_LINKS': 'True',
            },
            **env_extra
        })
    try:
        assert isinstance(crystal.stdout, TextIOBase)
        os.set_blocking(crystal.stdout.fileno(), False)
        
        (banner, _) = _read_until(
            crystal.stdout, '\n>>> ',
            timeout=4.0  # 2.0s isn't long enough for macOS test runners on GitHub Actions
        )
        yield (crystal, banner)
    finally:
        crystal.kill()        


def _py_eval(
        python: subprocess.Popen,
        py_code: str,
        stop_suffix: Optional[Union[str, Tuple[str, ...]]]=None,
        *, timeout: Optional[float]=None) -> str:
    if stop_suffix is None:
        stop_suffix = '>>> '
    
    assert isinstance(python.stdin, TextIOBase)
    assert isinstance(python.stdout, TextIOBase)
    python.stdin.write(f'{py_code}\n'); python.stdin.flush()
    (result, found_stop_suffix) = _read_until(python.stdout, stop_suffix, timeout=timeout)
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
    
    assert not is_windows()
    if os.get_blocking(stream.fileno()) != False:  # type: ignore[attr-defined]  # available in non-Windows
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
