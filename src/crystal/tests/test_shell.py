from typing import List
from crystal import __version__ as crystal_version
from crystal.tests.util.asserts import assertEqual, assertIn, assertNotIn
from crystal.tests.util.cli import (
    _OK_THREAD_STOP_SUFFIX, PROJECT_PROXY_REPR_STR, WINDOW_PROXY_REPR_STR, 
    close_main_window, close_open_or_create_dialog, create_new_empty_project, 
    delay_between_downloads_minimized, drain, py_eval, py_eval_await, 
    py_eval_literal, py_exec, read_until, wait_for_crystal_to_exit, 
    crystal_shell, crystal_running
)
from crystal.tests.util.server import served_project
from crystal.tests.util.skip import skipTest
from crystal.tests.util.subtests import SubtestsContext, with_subtests
from crystal.tests.util.wait import (
    DEFAULT_WAIT_TIMEOUT, WaitTimedOut, wait_for_sync,
)
from crystal.util.xos import is_linux
from crystal.util.xthreading import fg_call_and_wait
from io import TextIOBase
import os
import re
import signal
import sys
import tempfile
import textwrap
import time
from unittest import skip
from unittest.mock import ANY
import urllib


_EXPECTED_PROXY_PUBLIC_MEMBERS = []  # type: List[str]

_EXPECTED_PROJECT_PUBLIC_MEMBERS = [
    'FILE_EXTENSION',
    'OPENER_FILE_EXTENSION',
    'PARTIAL_FILE_EXTENSION',
    'add_task',
    'close',
    'default_url_prefix',
    'entity_title_format',
    'get_display_url',
    'get_resource',
    'get_resource_group',
    'get_root_resource',
    'hibernate_tasks',
    'html_parser_type',
    'is_dirty',
    'is_untitled',
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
    'save_as',
    'unhibernate_tasks',
    'urls_matching_pattern',
]

_EXPECTED_WINDOW_PUBLIC_MEMBERS = [
    'close',
    'entity_tree',
    'project',
    'start_server',
    'task_tree',
    'try_close',
    'view_url',
]

# ------------------------------------------------------------------------------
# Tests: Launch Shell

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
            assertEqual(PROJECT_PROXY_REPR_STR, py_eval(crystal, 'project'))
            assertEqual(WINDOW_PROXY_REPR_STR, py_eval(crystal, 'window'))
            
            assertIn('Help on _Proxy in module ', py_eval(crystal, 'help(project)'))
            assertIn('Help on _Proxy in module ', py_eval(crystal, 'help(window)'))
            
            # Ensure public members match expected set
            assertEqual(repr(_EXPECTED_PROXY_PUBLIC_MEMBERS) + '\n',
                py_eval(crystal, "[x for x in dir(project) if not x.startswith('_')]"))
            assertEqual(repr(_EXPECTED_PROXY_PUBLIC_MEMBERS) + '\n',
                py_eval(crystal, "[x for x in dir(window) if not x.startswith('_')]"))
        
        # Open MainWindow by creating new empty project
        create_new_empty_project(crystal)
        
        with subtests.test(msg='and {project, window} can be used for real, after main window appears'):
            assert re.fullmatch(
                r'^<crystal\.model\.Project object at 0x[0-9a-f]+>\n$',
                py_eval(crystal, 'project'))
            assert re.fullmatch(
                r'^<crystal\.browser\.MainWindow object at 0x[0-9a-f]+>\n$',
                py_eval(crystal, 'window'))
        
        with subtests.test(msg='and {project, window} can be used with help()'):
            assertIn('Help on Project in module crystal.model object:', py_eval(crystal, 'help(project)'))
            assertIn('Help on MainWindow in module crystal.browser object:', py_eval(crystal, 'help(window)'))


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
                py_eval_literal(crystal, 'EXCLUDED_URLS'),
                'Expected variables written at top-level by '
                    '$PYTHONSTARTUP file to be accessible from shell'
            )


# ------------------------------------------------------------------------------
# Tests: Shell API Stability

# NOTE: This test code was split out of the test_can_launch_with_shell() test above
#       because it is particularly easy to break and having a separate test function
#       makes the break type quicker to identify.
@with_subtests
def test_builtin_globals_have_stable_public_api(subtests: SubtestsContext) -> None:
    with crystal_shell() as (crystal, _):
        # Open MainWindow by creating new empty project
        create_new_empty_project(crystal)
        
        with subtests.test(global_name='project'):
            assertEqual(_EXPECTED_PROJECT_PUBLIC_MEMBERS,
                py_eval_literal(crystal, "[x for x in dir(project) if not x.startswith('_')]"),
                'Public API of Project class has changed')
        
        with subtests.test(global_name='window'):
            assertEqual(_EXPECTED_WINDOW_PUBLIC_MEMBERS,
                py_eval_literal(crystal, "[x for x in dir(window) if not x.startswith('_')]"),
                'Public API of MainWindow class has changed')


# ------------------------------------------------------------------------------
# Tests: Shell Messages

@with_subtests
def test_shell_exits_with_expected_message(subtests: SubtestsContext) -> None:
    for exit_method in ('exit()', 'Ctrl-D'):
        with subtests.test(case=f'test when {exit_method} given first open/create dialog still open then prints waiting message and does not exit'):
            with crystal_shell() as (crystal, _):
                assert isinstance(crystal.stdin, TextIOBase)
                
                close_open_or_create_dialog(crystal, after_delay=.5)
                
                if exit_method == 'exit()':
                    py_eval(crystal, 'exit()', stop_suffix='now waiting for all windows to close...\n')
                elif exit_method == 'Ctrl-D':
                    crystal.stdin.close()  # Ctrl-D
                    read_until(crystal.stdout, 'now waiting for all windows to close...\n')
                else:
                    raise AssertionError()
                
                wait_for_crystal_to_exit(
                    crystal,
                    timeout=.5 + DEFAULT_WAIT_TIMEOUT)
        
        with subtests.test(case=f'test when {exit_method} given main window still open then prints waiting message and does not exit'):
            with crystal_shell() as (crystal, _):
                assert isinstance(crystal.stdin, TextIOBase)
                
                create_new_empty_project(crystal)
                
                close_main_window(crystal, after_delay=.5)
                close_open_or_create_dialog(crystal, after_delay=.5*2)
                
                if exit_method == 'exit()':
                    py_eval(crystal, 'exit()', stop_suffix='now waiting for all windows to close...\n')
                elif exit_method == 'Ctrl-D':
                    crystal.stdin.close()  # Ctrl-D
                    read_until(crystal.stdout, 'now waiting for all windows to close...\n')
                else:
                    raise AssertionError()
                
                wait_for_crystal_to_exit(
                    crystal,
                    timeout=.5*2 + DEFAULT_WAIT_TIMEOUT)
        
        with subtests.test(case=f'test when {exit_method} given non-first open/create dialog still open then prints waiting message and does not exit'):
            with crystal_shell() as (crystal, _):
                assert isinstance(crystal.stdin, TextIOBase)
                
                create_new_empty_project(crystal)
                close_main_window(crystal)
                
                close_open_or_create_dialog(crystal, after_delay=.5)
                
                if exit_method == 'exit()':
                    py_eval(crystal, 'exit()', stop_suffix='now waiting for all windows to close...\n')
                elif exit_method == 'Ctrl-D':
                    crystal.stdin.close()  # Ctrl-D
                    read_until(crystal.stdout, 'now waiting for all windows to close...\n')
                else:
                    raise AssertionError()
                
                wait_for_crystal_to_exit(
                    crystal,
                    timeout=.5 + DEFAULT_WAIT_TIMEOUT)


def test_when_typed_code_raises_exception_then_print_traceback() -> None:
    with crystal_shell() as (crystal, _):
        expected_traceback = (
            'Traceback (most recent call last):\n'
            '  File "<console>", line 1, in <module>\n'
            'NameError: name \'Resource\' is not defined\n'
        )
        assertEqual(expected_traceback, py_eval(crystal, 'Resource'))


# ------------------------------------------------------------------------------
# Tests: Shell Capabilities

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
                py_exec(crystal, 'from crystal.model import Project')
                # Test can open project
                py_exec(crystal, f'p = Project({sp.project.path!r})')
            
            with subtests.test(case='test can list project entities'):
                assertEqual(
                    "[RootResource('Home','https://xkcd.com/')]\n",
                    py_eval(crystal, 'list(p.root_resources)[:1]'))
                assertEqual(
                    "[ResourceGroup('Comics','https://xkcd.com/#/')]\n",
                    py_eval(crystal, 'list(p.resource_groups)'))
                assertEqual(
                    '71\n',
                    py_eval(crystal, 'len(p.resources)'))
                assertEqual(
                    "Resource('https://xkcd.com/')\n",
                    py_eval(crystal, 'list(p.resources)[0]'))
            
            with subtests.test(case='test can get project entities', return_if_failure=True):
                assertEqual(
                    "Resource('https://xkcd.com/')\n",
                    py_eval(crystal, f'r = p.get_resource({home_url!r}); r'))
                
                assertEqual(
                    "[<ResourceRevision 1 for 'https://xkcd.com/'>]\n",
                    py_eval(crystal, f'list(r.revisions())'))
                assertEqual(
                    "<ResourceRevision 1 for 'https://xkcd.com/'>\n",
                    py_eval(crystal, f'rr = r.default_revision(); rr'))
                
                assertEqual(
                    "RootResource('Home','https://xkcd.com/')\n",
                    py_eval(crystal, f'root_r = p.get_root_resource(r); root_r'))
                
                assertEqual(
                    "ResourceGroup('Comics','https://xkcd.com/#/')\n",
                    py_eval(crystal, f'rg = p.get_resource_group("Comics"); rg'))
                assertEqual(
                    '14\n',
                    py_eval(crystal, f'len(rg.members)'))
                assertEqual(
                    "Resource('https://xkcd.com/1/')\n",
                    py_eval(crystal, f'list(rg.members)[0]'))
            
            with subtests.test(case='test can read content of resource revision'):
                assertEqual(
                    {
                        'http_version': 11,
                        'status_code': 200,
                        'reason_phrase': 'OK',
                        'headers': ANY
                    },
                    py_eval_literal(crystal, f'rr.metadata'))
                py_exec(crystal, f'with rr.open() as f:\n    body = f.read()\n', stop_suffix='>>> ')
                assertEqual(
                    r"""b'<!DOCTYPE html>\n<html>\n<head>\n<link rel="stylesheet" type="text/css" href="/s/7d94e0.css" title="Default"/>\n<title>xkcd: Air Gap</title>\n'""" + '\n',
                    py_eval(crystal, f'body[:137]'))
            
            with subtests.test(case='test can serve resource revision'):
                # Test can import ProjectServer
                py_exec(crystal, 'from crystal.server import ProjectServer')
                py_exec(crystal, 'from io import StringIO')
                # Test can start ProjectServer
                py_exec(
                    crystal, f'server = ProjectServer(p, stdout=StringIO())',
                    timeout=8.0  # 2.0s and 4.0s isn't long enough for macOS test runners on GitHub Actions
                )
                port = py_eval_literal(crystal, f'server.port')
                request_url = py_eval_literal(crystal, f'server.get_request_url({home_url!r})')
                
                # Test ProjectServer serves resource revision
                assertIn(str(port), request_url)
                with urllib.request.urlopen(request_url) as response:
                    response_bytes = response.read()
                assertIn(b'<title>xkcd: Air Gap</title>', response_bytes)


@with_subtests
def test_can_write_project_with_shell(subtests: SubtestsContext) -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        if True:
            home_url = sp.get_request_url('https://xkcd.com/')
            
            comic1_url = sp.get_request_url('https://xkcd.com/1/')
            comic2_url = sp.get_request_url('https://xkcd.com/2/')
            comic_pattern = sp.get_request_url('https://xkcd.com/#/')
            
            atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
            rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
            feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
        
        # Create named temporary directory that won't be deleted automatically
        with tempfile.NamedTemporaryFile(suffix='.crystalproj', delete=False) as project_td:
            pass
        os.remove(project_td.name)
        project_dirpath = project_td.name
        
        with crystal_shell() as (crystal, _):
            with subtests.test(case='test can create project', return_if_failure=True):
                # Test can import Project
                py_exec(crystal, 'from crystal.model import Project')
                # Test can create project
                py_exec(crystal, f'p = Project({project_dirpath!r})',
                    # 2.0s isn't long enough for macOS test runners on GitHub Actions
                    timeout=4.0)
            
            with subtests.test(case='test can create project entities', return_if_failure=True):
                # Test can import Resource
                py_exec(crystal, 'from crystal.model import Resource')
                # Test can create Resource
                assertEqual(
                    f'Resource({home_url!r})\n',
                    py_eval(crystal, f'r = Resource(p, {home_url!r}); r'))
                
                # Test can import RootResource
                py_exec(crystal, 'from crystal.model import RootResource')
                # Test can create RootResource
                assertEqual(
                    f"RootResource('Home',{home_url!r})\n",
                    py_eval(crystal, f'root_r = RootResource(p, "Home", r); root_r'))
                
                # Test can download ResourceRevision
                with delay_between_downloads_minimized(crystal):
                    py_exec(crystal, 'rr_future = r.download()')
                    wait_for_sync(lambda: (py_eval_literal(crystal, 'rr_future.done()') == True))
                    assertIn('<ResourceRevision ', py_eval(crystal, 'rr = rr_future.result(); rr'))
                
                # Test can import ResourceGroup
                py_exec(crystal, 'from crystal.model import ResourceGroup')
                # Test can create ResourceGroup
                assertEqual(
                    f"ResourceGroup('Comic',{comic_pattern!r})\n",
                    py_eval(crystal, f'rg = ResourceGroup(p, "Comic", {comic_pattern!r}); rg'))
                # Ensure ResourceGroup includes some members discovered by downloading resource Home
                def rg_member_count() -> int:
                    count = py_eval_literal(crystal, f'len(rg.members)')
                    assert isinstance(count, int)
                    return count
                wait_for_sync(lambda: 9 == rg_member_count())
            
            with subtests.test(case='test can delete project entities', return_if_failure=True):
                # Test can delete ResourceGroup
                py_exec(crystal, f'rg_m = list(rg.members)[0]')
                py_exec(crystal, f'rg.delete()')
                # Ensure ResourceGroup itself is deleted
                py_exec(crystal, f'p.get_resource_group(rg.name)')
                # Ensure former members of ResourceGroup still exist
                assertEqual('True\n', py_eval(crystal, f'p.get_resource(rg_m.url) == rg_m'))
                
                # Test can delete RootResource
                py_exec(crystal, f'root_r_r = root_r.resource')
                py_exec(crystal, f'root_r.delete()')
                # Ensure RootResource itself is deleted
                py_exec(crystal, f'p.get_root_resource(root_r_r)')
                # Ensure former target of RootResource still exists
                assertEqual('True\n', py_eval(crystal, f'p.get_resource(root_r_r.url) == root_r_r'))
                
                # Test can delete ResourceRevision
                py_exec(crystal, f'rr_r = rr.resource')
                assertEqual('1\n', py_eval(crystal, f'len(list(rr_r.revisions()))'))
                py_exec(crystal, f'rr.delete()')
                # Ensure ResourceRevision itself is deleted
                assertEqual('0\n', py_eval(crystal, f'len(list(rr_r.revisions()))'))
                
                # Test can delete Resource
                py_exec(crystal, f'r.delete()')
                # Ensure Resource itself is deleted
                py_exec(crystal, f'p.get_resource(r.url)')
            
            with subtests.test(case='test can download project entities', return_if_failure=True):
                # Recreate home Resource
                assertEqual(
                    f'Resource({home_url!r})\n',
                    py_eval(crystal, f'r = Resource(p, {home_url!r}); r'))
                # Recreate home RootResource
                assertEqual(
                    f"RootResource('Home',{home_url!r})\n",
                    py_eval(crystal, f'root_r = RootResource(p, "Home", r); root_r'))
                
                # Test can download RootResource
                with delay_between_downloads_minimized(crystal):
                    py_exec(crystal, 'rr_future = root_r.download()')
                    wait_for_sync(lambda: (py_eval_literal(crystal, 'rr_future.done()') == True))
                    assertIn('<ResourceRevision ', py_eval(crystal, 'rr = rr_future.result(); rr'))
                
                # Create feed ResourceGroup
                assertEqual(
                    f"ResourceGroup('Feed',{feed_pattern!r})\n",
                    py_eval(crystal, f'rg = ResourceGroup(p, "Feed", {feed_pattern!r}); rg'))
                py_exec(crystal, f'rg.source = root_r')
                # Ensure ResourceGroup includes some members discovered by downloading resource Home
                assertEqual(
                    2,
                    py_eval_literal(crystal, f'len(rg.members)'))
                
                # Test can download ResourceGroup
                with delay_between_downloads_minimized(crystal):
                    py_exec(crystal, 'drgt = rg.download()')
                    wait_for_sync(lambda: (py_eval_literal(crystal, 'drgt.complete') == True))
                assertEqual(
                    [True] * 2,
                    py_eval_literal(crystal, '[r.has_any_revisions() for r in rg.members]'))


@skip('covered by: test_can_write_project_with_shell')
def test_can_open_or_create_project() -> None:
    pass


@skip('covered by: test_can_write_project_with_shell')
def test_can_create_project_entities() -> None:
    pass


@skip('covered by: test_can_read_project_with_shell')
def test_can_read_project_entities() -> None:
    pass


@skip('covered by: test_can_write_project_with_shell')
def test_can_download_project_entities() -> None:
    pass


@skip('covered by: test_can_write_project_with_shell')
def test_can_delete_project_entities() -> None:
    pass


def test_can_import_guppy_in_shell() -> None:
    if sys.version_info >= (3, 14, 0):
        skipTest('guppy does not support this version of Python')
    
    with crystal_shell() as (crystal, _):
        # Ensure can import guppy
        import_result = py_eval_literal(crystal, 'import guppy; guppy.__version__')
        assert isinstance(import_result, str)
        
        # Ensure can create hpy instance
        py_exec(crystal, 'from guppy import hpy; h = hpy()')
        
        # Ensure can take memory sample
        result = py_eval(crystal, 'import gc; gc.collect(); heap = h.heap(); heap; _.more')
        assertNotIn('Traceback', result)
        
        # Ensure can create checkpoint
        py_exec(crystal, 'h.setref()')
        
        # Ensure can take memory sample since checkpoint
        result = py_eval(crystal, 'import gc; gc.collect(); heap = h.heap(); heap; _.more')
        assertNotIn('Traceback', result)


# ------------------------------------------------------------------------------
# Tests: Ctrl-C (and KeyboardInterrupt)

def test_given_crystal_started_without_shell_when_ctrl_c_pressed_then_exits_with_exit_code_sigint() -> None:
    with crystal_running(args=[], kill=False) as crystal:
        # Wait for Crystal to start up
        # TODO: Find a way to actually detect when Crystal finished starting,
        #       that doesn't require the shell, which isn't available for this test
        time.sleep(1.0)
        
        # Send SIGINT (Ctrl-C)
        os.kill(crystal.pid, signal.SIGINT)
        
        # Wait for process to exit
        try:
            wait_for_crystal_to_exit(crystal, timeout=5.0)
        except WaitTimedOut as e:
            if 'Launch error\nSee the py2app website for debugging launch issues\n' in str(e):
                raise AssertionError('Crystal did not finish starting before it received SIGINT')
            else:
                raise
        
        # Verify exit code
        assertEqual(-signal.SIGINT, crystal.returncode)


def test_given_crystal_started_with_shell_and_waiting_for_input_when_ctrl_c_pressed_then_prints_keyboardinterrupt_and_a_new_prompt() -> None:
    with crystal_shell() as (crystal, banner):
        # Send SIGINT (Ctrl-C) while waiting for input
        os.kill(crystal.pid, signal.SIGINT)
        
        # Wait for KeyboardInterrupt message and new prompt
        assert isinstance(crystal.stdout, TextIOBase)
        (output, matched) = read_until(crystal.stdout, '\n>>> ', timeout=2.0)
        
        # Verify "KeyboardInterrupt" was printed
        assertIn('KeyboardInterrupt', output,
            'Expected "KeyboardInterrupt" to be printed when Ctrl-C is pressed at prompt')
        
        # Verify a new prompt appears (matched by read_until)
        assertEqual('\n>>> ', matched)
        
        # Verify shell is still responsive
        assertEqual('2\n', py_eval(crystal, '1 + 1'))


def test_given_crystal_started_with_shell_and_running_a_command_when_ctrl_c_pressed_then_raises_keyboardinterrupt_and_prints_a_new_prompt() -> None:
    with crystal_shell() as (crystal, banner):
        # Start a long-running command that prints output periodically
        assert isinstance(crystal.stdout, TextIOBase)
        assert isinstance(crystal.stdin, TextIOBase)
        crystal.stdin.write("exec('import time\\nwhile True:\\n    print(\"loop\")\\n    time.sleep(0.1)\\n')\n")
        crystal.stdin.flush()
        
        # Wait for the command to start printing output
        (output, _) = read_until(crystal.stdout, 'loop\n', timeout=2.0)
        
        # Send SIGINT (Ctrl-C) to interrupt the running command
        os.kill(crystal.pid, signal.SIGINT)
        
        # Wait for KeyboardInterrupt traceback and new prompt
        (output, matched) = read_until(crystal.stdout, '\n>>> ', timeout=2.0)
        
        # Verify KeyboardInterrupt was raised
        assertIn('KeyboardInterrupt', output,
            'Expected KeyboardInterrupt to be raised when Ctrl-C is pressed during command execution')
        assertIn('Traceback', output,
            'Expected a traceback to be shown for the KeyboardInterrupt')
        
        # Verify a new prompt appears (matched by read_until)
        assertEqual('\n>>> ', matched)
        
        # Verify shell is still responsive
        assertEqual('2\n', py_eval(crystal, '1 + 1'))


# ------------------------------------------------------------------------------
# Tests: Ctrl-D (and EOFError)

def test_given_ai_agent_detected_when_ctrl_d_pressed_then_exits_immediately_with_success_code() -> None:
    with crystal_shell(env_extra={'CRYSTAL_AI_AGENT': 'True'}, kill=False) as (crystal, _):
        # Close stdin to simulate Ctrl-D (EOF)
        assert isinstance(crystal.stdin, TextIOBase)
        crystal.stdin.close()
        
        # Wait for process to exit
        wait_for_crystal_to_exit(crystal, timeout=2.0)
        
        # Verify exit code is 0 (success)
        assertEqual(0, crystal.returncode,
            'Expected Crystal to exit with code 0 when Ctrl-D is pressed at prompt')


@skip('covered by: test_when_launched_with_shell_and_ctrl_d_pressed_then_exits')
def test_given_no_ai_agent_and_windows_exist_when_ctrl_d_pressed_then_prints_waiting_for_windows_to_close() -> None:
    pass


# ------------------------------------------------------------------------------
# Tests: Shell Usability

def test_exception_raised_by_sync_code_only_shows_frames_back_to_the_console_file() -> None:
    with crystal_shell() as (crystal, _):
        result = py_eval(crystal, 'raise ValueError("boom")')
        
        expected_traceback = (
            'Traceback (most recent call last):\n'
            '  File "<console>", line 1, in <module>\n'
            'ValueError: boom\n'
        )
        assertEqual(expected_traceback, result)


def test_exception_raised_by_async_code_only_shows_frames_back_to_the_console_file() -> None:
    with crystal_shell() as (crystal, _):
        py_exec(crystal, textwrap.dedent('''\
            async def async_raise_error():
                raise ValueError("boom from async")
            '''
        ))
        result = py_eval(crystal, 'await async_raise_error()')
        
        source_available = (getattr(sys, 'frozen', None) != 'macosx_app')
        if source_available:
            # Match traceback exactly
            expected_traceback = (
                'Traceback (most recent call last):\n'
                '  File "<console>", line 1, in <module>\n'
                '  File "<string>", line 2, in async_raise_error\n'
                'ValueError: boom from async\n'
            )
            assertEqual(expected_traceback, result)
        else:
            expected_traceback_lines = [
                'Traceback (most recent call last):\n',
                #'   File "crystal/util/xthreading.py", line 131, in wrapper',
                #'   File "crystal/tests/util/runner.py", line 50, in run_test_coro',
                #'   File "crystal/shell.py", line 589, in _fg_call_and_wait_noprofile',
                #'   File "crystal/util/xthreading.py", line 366, in fg_call_and_wait',
                #'   File "crystal/util/xthreading.py", line 337, in fg_task',
                #'   File "crystal/tests/util/runner.py", line 51, in <lambda>',
                '  File "<console>", line 1, in <module>\n',
                '  File "<string>", line 2, in async_raise_error\n',
                'ValueError: boom from async\n',
            ]
            for line in expected_traceback_lines:
                assertIn(line, result)


# ------------------------------------------------------------------------------
# Tests: AI Agents: Custom Behavior

def test_help_T_shows_custom_docstring() -> None:
    """
    When help(T) is called, the custom docstring for the T navigator should be displayed,
    explaining how to use T to view and control the UI.
    """
    with crystal_shell(env_extra={'CRYSTAL_AI_AGENT': 'True'}) as (crystal, banner):
        # Call help(T) and capture the output
        result = py_eval(crystal, 'help(T)')
        
        # Verify the custom docstring is shown
        assertIn('The top navigator', result,
            'Expected custom docstring to mention "The top navigator"')
        assertIn('Examples', result,
            'Expected custom docstring to include an Examples section')
        assertIn('Look at the entire UI', result,
            'Expected custom docstring to include usage examples')
        assertIn('Click a button, checkbox, or radio button', result,
            'Expected custom docstring to explain how to click buttons')
        assertIn('Wait for UI changes', result,
            'Expected custom docstring to explain how to wait for UI changes')
        assertIn('Type in an input field', result,
            'Expected custom docstring to explain how to type in fields')
        assertIn('Manipulate a TreeItem', result,
            'Expected custom docstring to explain how to manipulate tree items')
        
        # Verify it's not just showing the generic Navigator class docstring
        assertNotIn('Points to a wx.Window', result,
            'Expected custom instance docstring, not the WindowNavigator class docstring')


def test_given_ai_agent_when_T_accessed_without_help_T_then_warning_shown() -> None:
    """
    When an AI agent accesses T without first reading help(T),
    a warning message should be displayed recommending they read help(T).
    """
    with crystal_shell(env_extra={'CRYSTAL_AI_AGENT': 'True'}) as (crystal, banner):
        # Access T without calling help(T) first
        result = py_eval(crystal, 'T')
        
        # Verify the warning is shown before T's repr
        assertIn('🤖 T accessed but help(T) not read. Recommend reading help(T).', result,
            'Expected warning message when T is accessed without help(T)')
        assertIn('T[0].W', result,
            'Expected T repr to still be shown after warning')


def test_given_ai_agent_when_help_T_called_then_T_accessed_then_no_warning_shown() -> None:
    """
    When an AI agent calls help(T) first, then accesses T,
    no warning should be displayed.
    """
    with crystal_shell(env_extra={'CRYSTAL_AI_AGENT': 'True'}) as (crystal, banner):
        # Call help(T) first
        help_result = py_eval(crystal, 'help(T)')
        assertIn('The top navigator', help_result,
            'Expected help(T) to show T documentation')
        
        # Now access T - should not show warning
        t_result = py_eval(crystal, 'T')
        assertNotIn('🤖 T accessed but help(T) not read', t_result,
            'Expected no warning when T accessed after help(T)')
        assertIn('T[0].W', t_result,
            'Expected T repr to be shown')


def test_given_ai_agent_when_T_accessed_multiple_times_without_help_T_then_warning_shown_once() -> None:
    """
    When an AI agent accesses T multiple times without reading help(T),
    the warning should only be displayed once (on the first access).
    """
    with crystal_shell(env_extra={'CRYSTAL_AI_AGENT': 'True'}) as (crystal, banner):
        # Access T first time - should show warning
        result1 = py_eval(crystal, 'T')
        assertIn('🤖 T accessed but help(T) not read. Recommend reading help(T).', result1,
            'Expected warning on first T access')
        
        # Access T second time - should not show warning again
        result2 = py_eval(crystal, 'T')
        assertNotIn('🤖 T accessed but help(T) not read', result2,
            'Expected no warning on second T access')
        assertIn('T[0].W', result2,
            'Expected T repr to still be shown')
        
        # Access T third time - should not show warning again
        result3 = py_eval(crystal, 'T')
        assertNotIn('🤖 T accessed but help(T) not read', result3,
            'Expected no warning on third T access')


def test_given_non_ai_agent_when_T_accessed_without_help_T_then_no_warning_shown() -> None:
    """
    When NOT running as an AI agent, no warning should be shown
    even if T is accessed without reading help(T).
    """
    # Note: Not setting CRYSTAL_AI_AGENT, so this runs as a regular user
    with crystal_shell() as (crystal, banner):
        # Verify T is not available (it's only available for AI agents)
        result = py_eval(crystal, 'T')
        assertIn('NameError', result,
            'Expected T to not be defined for non-AI agents')
        assertIn("name 'T' is not defined", result,
            'Expected NameError about T not being defined')


def test_cannot_set_unexpected_attributes_of_T() -> None:
    """
    Setting unexpected attributes on T (like T.Name) should raise an AttributeError,
    even though setting Name on a normal wx.Window would work.
    This verifies that the Navigator attribute protection works correctly.
    """
    with crystal_shell(env_extra={'CRYSTAL_AI_AGENT': 'True'}) as (crystal, banner):
        # Try to set T.Name, which would work on a wx.Window but not on a Navigator
        result = py_eval(crystal, 'T.Name = "test"')
        
        # Verify AttributeError was raised
        assertIn('Traceback', result,
            'Expected an exception to be raised')
        assertIn('AttributeError', result,
            'Expected AttributeError to be raised')
        assertIn("Cannot set attribute 'Name'", result,
            'Expected error message to mention the Name attribute')
        assertIn('WindowNavigator', result,
            'Expected error message to mention WindowNavigator')
        
        # Verify we can still access T normally after the error
        result = py_eval(crystal, 'T')
        assertNotIn('Traceback', result,
            'Expected T to still be accessible after the error')


def test_shell_detects_and_reports_ui_changes_to_ai_agents() -> None:
    """
    When an AI agent is detected, the shell should automatically detect
    and report UI changes that occur between commands.
    """
    with crystal_shell(env_extra={'CRYSTAL_AI_AGENT': 'True'}) as (crystal, banner):
        # Verify AI agent banner appears
        assertIn('AI agents:', banner)
        assertIn('Use `T` to view/control the UI', banner)
        
        # Click 'New Project' button.
        # Should report: Dialog replaced with main window
        result = py_eval(crystal, 'click(T(Id=wx.ID_YES).W)')
        assertIn('🤖 UI changed at: S :=', result,
            'Expected UI change detection when opening main window')
        assertIn("- crystal.ui.dialog.BetterMessageDialog(Name='cr-open-or-create-project'", result,
            'Expected old dialog to be reported as deleted')
        assertIn("+ wx.Frame(Name='cr-main-window'", result,
            'Expected new main window to be reported as added')
        
        # Click 'New Root URL...' button.
        # Should report: New dialog opened
        result = py_eval(crystal, "click(T['cr-empty-state-new-root-url-button'].W)")
        assertIn('🤖 UI changed at: S :=', result,
            'Expected UI change detection when opening dialog')
        if is_linux():
            assertIn("+ wx.Dialog(Name='cr-new-root-url-dialog'", result,
                'Expected new dialog to be reported as added')
        else:
            assertIn("+ wx.Dialog(IsModal=True, Name='cr-new-root-url-dialog'", result,
                'Expected new dialog to be reported as added')
        assertIn("+ wx.TextCtrl(Name='cr-new-root-url-dialog__url-field'", result,
            'Expected URL field to be reported as added')
        
        # Set URL field value.
        # Should report: Field value changed
        result = py_eval(crystal, "T['cr-new-root-url-dialog__url-field'].W.Value = 'https://example.com/'")
        assertIn('🤖 UI changed at: S :=', result,
            'Expected UI change detection when setting field value')
        assertIn("~ wx.TextCtrl(Name='cr-new-root-url-dialog__url-field'", result,
            'Expected URL field to be reported as modified')
        assertIn("Value='{→https://example.com/}'", result,
            'Expected URL value change to be shown in diff')
        
        # Verify S variable is accessible and has correct structure
        if True:
            result = py_eval(crystal, 'S')
            assertIn('S := T[', result,
                'Expected S variable to exist and contain a diff')
            
            # Verify S.old and S.new are accessible
            result = py_eval(crystal, 'S.old')
            assertNotIn('Traceback', result,
                'Expected S.old to be accessible')
            assertIn("wx.TextCtrl(Name='cr-new-root-url-dialog__url-field'", result,
                'Expected S.old to contain the old snapshot')
            
            result = py_eval(crystal, 'S.new')
            assertNotIn('Traceback', result,
                'Expected S.new to be accessible')
            assertIn("wx.TextCtrl(Name='cr-new-root-url-dialog__url-field'", result,
                'Expected S.new to contain the new snapshot')
        
        # Verify S[...] raises an error suggesting use of S.old[...] or S.new[...]
        result = py_eval(crystal, 'S[1]')
        assertIn('Traceback', result,
            'Expected S[1] to raise an error')
        assertIn('ValueError', result,
            'Expected ValueError to be raised')
        assertIn('S[1] is ambiguous', result,
            'Expected error message to suggest using S.old or S.new')
        assertIn('Use S.new[1] or S.old[1] instead', result,
            'Expected error message to suggest using S.old or S.new')
        
        # Close the dialog.
        # Should report: Dialog closed
        result = py_eval(crystal, 'click(T(Id=wx.ID_CANCEL).W)')
        assertIn('🤖 UI changed at: S :=', result,
            'Expected UI change detection when closing dialog')
        if is_linux():
            assertIn("- wx.Dialog(Name='cr-new-root-url-dialog'", result,
                'Expected dialog to be reported as deleted')
        else:
            assertIn("- wx.Dialog(IsModal=True, Name='cr-new-root-url-dialog'", result,
                'Expected dialog to be reported as deleted')


def test_given_terminal_operate_tool_then_banner_says_to_use_exec_for_multi_line_input_and_exec_works() -> None:
    """
    The shell banner should mention using exec() for multi-line inputs,
    and exec() should successfully execute multi-line code.
    """
    with crystal_shell(env_extra={'CRYSTAL_AI_AGENT': 'True', 'CRYSTAL_MCP_SHELL_SERVER': 'True'}) as (crystal, banner):
        # Verify the banner mentions using exec() for multi-line input
        assertIn('Run multi-line code with exec()', banner,
            'Expected banner to mention using exec() for multi-line input')
        
        # Test that exec() successfully runs multi-line code
        result = py_eval(crystal, 'exec("for i in range(1, 6):\\n    print(i)")')
        
        # Verify the output shows all numbers printed
        assertIn('1', result,
            'Expected number 1 to be printed')
        assertIn('2', result,
            'Expected number 2 to be printed')
        assertIn('3', result,
            'Expected number 3 to be printed')
        assertIn('4', result,
            'Expected number 4 to be printed')
        assertIn('5', result,
            'Expected number 5 to be printed')
        
        # Verify no error/traceback
        assertNotIn('Traceback', result,
            'Expected exec() to run without error')


def test_given_terminal_operate_tool_when_multi_line_input_used_directly_then_prints_error() -> None:
    """
    When multi-line input is attempted without using exec(),
    an error message should be printed to guide the user.
    """
    with crystal_shell(env_extra={'CRYSTAL_AI_AGENT': 'True', 'CRYSTAL_MCP_SHELL_SERVER': 'True'}) as (crystal, banner):
        # Attempt to start a for loop without exec()
        result = py_eval(crystal, 'for i in range(1, 6):')
        
        # Verify the error message is shown
        assertIn('🤖 Multi-line input without exec() detected', result,
            'Expected error message when multi-line input is attempted')
        assertIn('Use exec() to run multi-line inputs as a single line', result,
            'Expected error message to suggest using exec()')


def test_given_terminal_operate_tool_when_multi_line_exec_attempted_then_prints_error() -> None:
    """
    When multi-line input is attempted without using exec(),
    an error message should be printed to guide the user.
    """
    with crystal_shell(env_extra={'CRYSTAL_AI_AGENT': 'True', 'CRYSTAL_MCP_SHELL_SERVER': 'True'}) as (crystal, banner):
        # Attempt to start an exec() with a multi-line string
        result = py_eval(crystal, 'exec("""')
        
        # Verify the error message is shown
        assertIn('🤖 Multi-line exec() call detected.', result,
            'Expected error message when multi-line input is attempted')
        assertIn('Use only a single line with exec() to run multi-line inputs', result,
            'Expected error message to exphasize using a single line only')


# ------------------------------------------------------------------------------
# Tests: Waiting for Shell to Close

@with_subtests
def test_given_shell_running_when_all_windows_closed_then_shell_exits_and_app_exits(subtests: SubtestsContext) -> None:
    with subtests.test(case='The Open Or Create Dialog is closed immediately after app launch'):
        with crystal_shell(kill=False) as (crystal, _):
            assert isinstance(crystal.stdout, TextIOBase)
            
            result = py_eval_await(crystal, textwrap.dedent('''\
                from crystal.tests.util.wait import wait_for, window_condition
                from crystal.tests.util.windows import OpenOrCreateDialog
                
                async def crystal_task() -> None:
                    ocd = await OpenOrCreateDialog.wait_for()
                    ocd.open_or_create_project_dialog.Close()
                '''
            ), 'crystal_task', [], stop_suffix=_OK_THREAD_STOP_SUFFIX + ('>>> OK',))
            
            wait_for_crystal_to_exit(
                crystal,
                timeout=DEFAULT_WAIT_TIMEOUT)
    
    with subtests.test(case='A project is opened & closed, then the Open Or Create Dialog reappears and is closed'):
        with crystal_shell(kill=False) as (crystal, _):
            assert isinstance(crystal.stdout, TextIOBase)
            
            result = py_eval_await(crystal, textwrap.dedent('''\
                from crystal.tests.util.windows import OpenOrCreateDialog
                
                async def crystal_task() -> None:
                    # Create and close a project
                    ocd = await OpenOrCreateDialog.wait_for()
                    mw = await ocd.create_and_leave_open()
                    await mw.close()
                    
                    # Close the Open Or Create Dialog that reappears
                    ocd2 = await OpenOrCreateDialog.wait_for()
                    ocd2.open_or_create_project_dialog.Close()
                '''
            ), 'crystal_task', [], timeout=8.0)
            
            wait_for_crystal_to_exit(
                crystal,
                timeout=DEFAULT_WAIT_TIMEOUT)


# ------------------------------------------------------------------------------
# Tests: AI Agents: Modal Dialog Handling

def test_given_ai_agent_when_modal_message_dialog_shown_then_shell_remains_responsive() -> None:
    """
    When an AI agent is detected and a modal MessageDialog is shown,
    the shell should remain responsive and able to interact with the dialog.
    
    This test simulates the scenario where:
    1. Agent creates a new project
    2. Agent adds a root URL
    3. Agent tries to add the same root URL again
    4. A modal MessageDialog appears saying "Root URL Exists"
    5. Shell should remain responsive and able to click OK on the dialog
    """
    # NOTE: Must set CRYSTAL_RUNNING_TESTS=False so that ShowModal will
    #       actually try to show a modal wx.MessageDialog without raising
    #       an AssertionError
    with crystal_shell(env_extra={'CRYSTAL_AI_AGENT': 'True', 'CRYSTAL_RUNNING_TESTS': 'False'}) as (crystal, banner):
        # Verify AI agent banner appears
        assertIn('AI agents:', banner)
        
        # Create a new project
        result = py_eval(crystal, 'click(T(Id=wx.ID_YES).W)')
        assertIn('🤖 UI changed', result)
        
        # Add a root URL
        home_url = 'https://xkcd.daarchive.net/'
        py_exec(crystal, 'from crystal.model import Resource')
        py_exec(crystal, 'from crystal.model import RootResource')
        py_eval(crystal, f'r = Resource(project, {home_url!r})', empty_ok=True)
        py_eval(crystal, f'root_r = RootResource(project, "Home", r)', empty_ok=True)
        
        # Try to add the same root URL again.
        # Should fail with a modal MessageDialog.
        if True:
            result = py_eval(crystal, "click(T['cr-add-url-button'].W)")
            assertIn('🤖 UI changed', result)
            
            if True:
                # URL will already be populated from the newly-added root resource
                result = py_eval_literal(crystal, f"T['cr-new-root-url-dialog__url-field'].W.Value")
                assertEqual(home_url, result)
            else:
                # NOTE: The code has been observed to hang, for an unknown reason
                result = py_eval(crystal, f"T['cr-new-root-url-dialog__url-field'].W.Value = {home_url!r}")
                assertIn('🤖 UI changed', result)
            
            result = py_eval(crystal, 'click(T(Id=wx.ID_NEW).W)')
            assertIn('🤖 UI changed', result)
            assertIn("MessageDialog(IsModal=True, Name='cr-root-url-exists'", result,
                'Expected the "Root URL Exists" dialog to be visible')
            
            # Verify the shell is still responsive
            result = py_eval(crystal, 'click(T(Id=wx.ID_OK).W)')
            assertIn('🤖 UI changed', result)
            
            # Close the New Root URL dialog
            result = py_eval(crystal, 'click(T(Id=wx.ID_CANCEL).W)')
            assertIn('🤖 UI changed', result)
        
        # Close the main window
        result = py_eval(crystal, 'window.close()')


# ------------------------------------------------------------------------------
