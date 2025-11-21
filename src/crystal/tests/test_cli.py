"""
Tests Crystal's command-line interface (CLI).

See also:
* test_shell.py -- Tests related to the --shell option
"""

from collections.abc import Iterator
from contextlib import closing, contextmanager
from crystal import APP_NAME, __version__
from crystal.model import Project, Resource
from crystal.tests.util.asserts import (
    assertEqual, assertIn, assertNotEqual, assertNotIn, assertRegex
)
from crystal.tests.util.cli import (
    _OK_THREAD_STOP_SUFFIX, ReadUntilTimedOut, close_open_or_create_dialog, crystal_running, drain, py_eval, py_eval_await, py_eval_literal, py_exec, read_until,
    crystal_shell, crystal_running_with_banner, run_crystal, wait_for_main_window,
)
from crystal.tests.util.server import extracted_project, served_project
from crystal.tests.util.skip import skipTest
from crystal.tests.util.subtests import awith_subtests, SubtestsContext, with_subtests
from crystal.tests.util.tasks import scheduler_disabled, step_scheduler_until_done
from crystal.tests.util.wait import DEFAULT_WAIT_TIMEOUT
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.ports import port_in_use
from crystal.util.xos import is_mac_os
from io import TextIOBase
import datetime
import os
import signal
import socket
import tempfile
import textwrap
from unittest import skip
import urllib.request


def _is_port_in_use(port: int, hostname: str = '127.0.0.1') -> bool:
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((hostname, port))
            return False
        except OSError:
            return True


# === Basic Launch Tests (<nothing>, --help) ===

def test_when_launched_with_no_arguments_then_shows_open_or_create_project_dialog() -> None:
    with crystal_shell() as (crystal, banner):
        # When Crystal launches with no arguments, it should show the open/create dialog
        # The shell should start successfully, indicating the GUI started
        assertIn('Crystal', banner)
        
        # Clean up by closing the dialog
        close_open_or_create_dialog(crystal)


def test_when_launched_with_help_argument_then_prints_help_and_exits() -> None:
    result = run_crystal(['--help'])
    assertEqual(0, result.returncode)
    assertIn('Crystal: A tool for archiving websites in high fidelity.', result.stdout)
    assertIn('usage:', result.stdout)
    assertIn('--shell', result.stdout)
    assertIn('--serve', result.stdout)
    assertIn('project_filepath', result.stdout)


def test_when_launched_with_version_argument_then_prints_version_and_exits() -> None:
    result = run_crystal(['--version'])
    assertEqual(0, result.returncode)
    assertIn(APP_NAME, result.stdout)
    assertIn(__version__, result.stdout)


def test_when_launched_with_invalid_argument_then_prints_error_and_exits() -> None:
    result = run_crystal(['--invalid-argument'])
    assert result.returncode != 0
    assertIn('error: unrecognized arguments: --invalid-argument', result.stderr)
    assertIn('usage:', result.stderr)


# === Project Open & Create Tests (project_filepath, --readonly) ===

def test_can_open_project_as_writable() -> None:
    with _temporary_project() as project_path:
        # First create the project by running Crystal with the path
        with crystal_shell(args=[project_path]) as (crystal, banner):
            wait_for_main_window(crystal)
        
        # Now test opening the existing project as writable (default)
        with crystal_shell(args=[project_path]) as (crystal, banner):
            wait_for_main_window(crystal)
            
            # Verify project is writable by checking readonly property
            result = py_eval_literal(crystal, 'project.readonly')
            assert False == result


def test_can_open_project_as_readonly() -> None:
    with _temporary_project() as project_path:
        # First create the project
        with crystal_shell(args=[project_path]) as (crystal, banner):
            wait_for_main_window(crystal)
        
        # Now test opening the project as readonly
        with crystal_shell(args=['--readonly', project_path]) as (crystal, banner):
            wait_for_main_window(crystal)
            
            # Verify project is readonly
            result = py_eval_literal(crystal, 'project.readonly')
            assert True == result


def test_when_opened_project_filepath_does_not_exist_then_creates_new_project_at_filepath() -> None:
    with _temporary_project() as project_path:
        # Project path doesn't exist yet. Crystal should create it.
        assert not os.path.exists(project_path)
        
        with crystal_shell(args=[project_path]) as (crystal, banner):
            wait_for_main_window(crystal)
            
            # Verify the project was created at the specified path
            result = py_eval_literal(crystal, 'project.path')
            assertEqual(project_path, result)
            
            # Verify it's a new project (writable by default)
            result = py_eval_literal(crystal, 'project.readonly')
            assert False == result
        
        # Verify the project directory was actually created on disk
        assert os.path.exists(project_path)


def test_can_open_crystalopen_file() -> None:
    with _temporary_project() as project_path:
        # Create the project
        with crystal_shell(args=[project_path]) as (crystal, banner):
            wait_for_main_window(crystal)
        
        # Locate the project's .crystalopen file
        crystalopen_path = os.path.join(project_path, Project._OPENER_DEFAULT_FILENAME)
        assert os.path.exists(crystalopen_path)
        
        # Test opening the .crystalopen file
        with crystal_shell(args=[crystalopen_path]) as (crystal, banner):
            wait_for_main_window(crystal)
            
            # Verify it opened the underlying project
            result = py_eval_literal(crystal, 'project.path')
            assertEqual(project_path, result)


def test_when_launched_with_readonly_and_no_project_filepath_then_open_or_create_dialog_defaults_to_readonly_checked() -> None:
    with crystal_shell(args=['--readonly']) as (crystal, banner):
        # Check readonly checkbox state
        result = py_eval_await(crystal, textwrap.dedent('''\
            from crystal.tests.util.windows import OpenOrCreateDialog
            
            async def crystal_task() -> None:
                ocd = await OpenOrCreateDialog.wait_for()
                readonly_checked = ocd.open_as_readonly.Value
                create_enabled = ocd.create_button.Enabled
                print(f"readonly_checked={readonly_checked}")
                print(f"create_enabled={create_enabled}")
            '''
        ), 'crystal_task', [], timeout=8.0)
        assertIn('readonly_checked=True', result)
        assertIn('create_enabled=False', result)
        
        # Clean up by closing the dialog
        close_open_or_create_dialog(crystal)


def test_when_ctrl_r_pressed_in_open_or_create_dialog_then_readonly_checkbox_is_toggled() -> None:
    with crystal_shell(args=[]) as (crystal, banner):
        # Test Ctrl+R key toggles readonly checkbox
        result = py_eval_await(crystal, textwrap.dedent('''\
            from crystal.tests.util.windows import OpenOrCreateDialog
            import wx
            
            async def crystal_task() -> None:
                ocd = await OpenOrCreateDialog.wait_for()
                #
                # Spy on calls to ocd.open_as_readonly.SetFocus()
                setfocus_call_count_cell = [0]
                original_setfocus = ocd.open_as_readonly.SetFocus
                def patched_setfocus():
                    setfocus_call_count_cell[0] += 1
                    return original_setfocus()
                ocd.open_as_readonly.SetFocus = patched_setfocus
                #
                # Initial state should be unchecked
                initial_checked = ocd.open_as_readonly.Value
                initial_create_enabled = ocd.create_button.Enabled
                print(f"initial_checked={initial_checked}")
                print(f"initial_create_enabled={initial_create_enabled}")
                #
                # Simulate Ctrl+R key press using EVT_CHAR_HOOK
                key_event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
                key_event.SetControlDown(True)
                key_event.SetKeyCode(ord('R'))
                key_event.SetId(ocd.open_or_create_project_dialog.GetId())
                key_event.SetEventObject(ocd.open_or_create_project_dialog)
                ocd.open_or_create_project_dialog.ProcessEvent(key_event)
                #
                # Check new state after Ctrl+R press
                after_r_checked = ocd.open_as_readonly.Value
                after_r_create_enabled = ocd.create_button.Enabled
                print(f"after_r_checked={after_r_checked}")
                print(f"after_r_create_enabled={after_r_create_enabled}")
                print(f"setfocus_called_after_first_toggle={setfocus_call_count_cell[0] >= 1}")
                #
                # Press Alt+r to toggle back (test different modifier and lowercase)
                key_event2 = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
                key_event2.SetAltDown(True)
                key_event2.SetKeyCode(ord('r'))  # test lowercase too
                key_event2.SetId(ocd.open_or_create_project_dialog.GetId())
                key_event2.SetEventObject(ocd.open_or_create_project_dialog)
                ocd.open_or_create_project_dialog.ProcessEvent(key_event2)
                #
                # Check final state
                final_checked = ocd.open_as_readonly.Value
                final_create_enabled = ocd.create_button.Enabled
                print(f"final_checked={final_checked}")
                print(f"final_create_enabled={final_create_enabled}")
                print(f"setfocus_called_after_second_toggle={setfocus_call_count_cell[0] >= 2}")
                # 
                # Cleanup spy on ocd.open_as_readonly.SetFocus()
                ocd.open_as_readonly.SetFocus = original_setfocus
            '''
        ), 'crystal_task', [], timeout=8.0)
        
        # Verify Ctrl+R properly toggled the checkbox
        assertIn('initial_checked=False', result)
        assertIn('initial_create_enabled=True', result)
        assertIn('after_r_checked=True', result)  # Ctrl+R toggled to checked
        assertIn('after_r_create_enabled=False', result)  # Create button disabled when readonly
        assertIn('final_checked=False', result)  # Alt+r toggled back to unchecked
        assertIn('final_create_enabled=True', result)  # Create button re-enabled
        
        # On macOS, verify SetFocus() was called on the checkbox after each toggle
        if is_mac_os():
            assertIn('setfocus_called_after_first_toggle=True', result)
            assertIn('setfocus_called_after_second_toggle=True', result)
        
        # Clean up by closing the dialog
        close_open_or_create_dialog(crystal)


def test_when_launched_with_multiple_filepaths_then_prints_error_and_exits() -> None:
    result = run_crystal(['first.crystalproj', 'second.crystalproj'])
    assert result.returncode != 0
    assertIn('error: unrecognized arguments: second.crystalproj', result.stderr)
    assertIn('usage:', result.stderr)


# === Server Mode Tests (--serve) ===
# NOTE: Detailed server tests are in test_server.py

def test_when_launched_with_serve_and_project_filepath_then_opens_project_and_serves_immediately() -> None:
    with _temporary_project() as project_path:
        with _crystal_shell_with_serve(project_path) as server_start_message:
            assertRegex(server_start_message, r'Server started at: http://127\.0\.0\.1:\d+')


def test_when_launched_with_serve_and_port_then_binds_to_specified_port() -> None:
    with _temporary_project() as project_path:
        with _crystal_shell_with_serve(project_path, port=8080) as server_start_message:
            assertIn('Server started at: http://127.0.0.1:8080', server_start_message)


def test_when_launched_with_serve_and_host_then_binds_to_specified_host() -> None:
    with _temporary_project() as project_path:
        # Create empty project
        with _crystal_shell_with_serve(project_path) as _:
            pass
        
        # Open empty project (as --readonly by default)
        with _crystal_shell_with_serve(project_path, host='0.0.0.0') as server_start_message:
            assertRegex(server_start_message, r'Server started at: http://0\.0\.0\.0:\d+')


def test_when_launched_with_port_but_no_serve_then_prints_error_and_exits() -> None:
    result = run_crystal(['--port', '8080'])
    assert result.returncode != 0
    assertIn('--port and --host can only be used with --serve', result.stderr)


def test_when_launched_with_host_but_no_serve_then_prints_error_and_exits() -> None:
    result = run_crystal(['--host', '0.0.0.0'])
    assert result.returncode != 0
    assertIn('--port and --host can only be used with --serve', result.stderr)


def test_given_launched_with_serve_and_port_when_port_already_in_use_then_fails_immediately() -> None:
    with port_in_use(0, '127.0.0.1') as conflicting_port:  # bind to any free port
        # Try to start Crystal server on the same port - should fail
        with _temporary_project() as project_path:
            result = run_crystal(['--serve', '--port', str(conflicting_port), project_path])
            assert result.returncode != 0
            assertIn('address already in use', result.stderr)


def test_given_launched_with_serve_and_no_port_and_default_port_in_use_then_uses_next_higher_open_port() -> None:
    if _is_port_in_use(2797) or _is_port_in_use(2798):
        skipTest('Port 2797 or 2798 already in use, cannot run test')
    
    with port_in_use(2797, '127.0.0.1'):
        with _temporary_project() as project_path:
            with _crystal_shell_with_serve(project_path) as server_start_message:
                assertIn('Server started at: http://127.0.0.1:2798', server_start_message)


def test_when_launched_with_serve_and_without_readonly_then_serves_as_writable() -> None:
    with _temporary_project() as project_path:
        with _crystal_shell_with_serve(project_path) as server_start_message:
            assertRegex(server_start_message, r'Server started at: http://127\.0\.0\.1:\d+')
            
            # Should not contain readonly messages for default 127.0.0.1 host
            assertNotIn('Read-only mode automatically enabled', server_start_message)
            assertNotIn('To allow remote modifications', server_start_message)


def test_when_launched_with_serve_and_host_equal_to_127_0_0_1_and_without_readonly_then_serves_as_writable() -> None:
    with _temporary_project() as project_path:
        with _crystal_shell_with_serve(project_path, host='127.0.0.1') as server_start_message:
            assertRegex(server_start_message, r'Server started at: http://127\.0\.0\.1:\d+')
            
            # Should not contain readonly messages for explicit 127.0.0.1 host
            assertNotIn('Read-only mode automatically enabled', server_start_message)
            assertNotIn('To allow remote modifications', server_start_message)


def test_when_launched_with_serve_and_host_other_than_127_0_0_1_and_without_no_readonly_then_serves_as_readonly() -> None:
    with _temporary_project() as project_path:
        # Create empty project
        with _crystal_shell_with_serve(project_path) as _:
            pass
        
        # Open empty project (as --readonly by default for remote host)
        with _crystal_shell_with_serve(project_path, host='0.0.0.0') as server_start_message:
            assertRegex(server_start_message, r'Server started at: http://0\.0\.0\.0:\d+')
            
            # Should contain readonly messages for remote host
            assertIn('Read-only mode automatically enabled for remote access (--host 0.0.0.0)', server_start_message)
            assertIn('To allow remote modifications, restart with --no-readonly', server_start_message)


def test_when_launched_with_serve_and_host_other_than_127_0_0_1_and_with_no_readonly_then_serves_as_writable() -> None:
    with _temporary_project() as project_path:
        # Create empty project
        with _crystal_shell_with_serve(project_path) as _:
            pass
        
        # Open empty project with --no-readonly to override auto-readonly for remote host
        with _crystal_shell_with_serve(
                project_path, host='0.0.0.0', extra_args=['--no-readonly']
                ) as server_start_message:
            assertRegex(server_start_message, r'Server started at: http://0\.0\.0\.0:\d+')
            
            # Should not contain readonly messages when --no-readonly is specified
            assertNotIn('Read-only mode automatically enabled', server_start_message)
            assertNotIn('To allow remote modifications', server_start_message)


# === Shell Mode Tests (--shell) ===
# NOTE: Detailed shell tests are in test_shell.py

# NOTE: Also covered by: test_can_launch_with_shell
def test_when_launched_with_shell_and_no_project_filepath_then_shell_starts_with_no_project() -> None:
    # ...and `project` variable is an unset proxy
    # ...and `window` variable is an unset proxy
    with crystal_shell() as (crystal, banner):
        # Verify project and window variables are unset proxies (not real objects)
        result = py_eval_literal(crystal, 'repr(project)')
        assertIn('<unset crystal.model.Project proxy>', result)
        
        result = py_eval_literal(crystal, 'repr(window)')
        assertIn('<unset crystal.browser.MainWindow proxy>', result)
        
        # Clean up by closing the open/create dialog
        close_open_or_create_dialog(crystal)


def test_when_launched_with_shell_and_project_filepath_then_shell_starts_with_opened_project() -> None:
    # ...and `project` variable is set to a Project
    # ...and `window` variable is set to a MainWindow
    with _temporary_project() as project_path:
        # First create the project
        with crystal_shell(args=[project_path]) as (crystal, banner):
            wait_for_main_window(crystal)
        
        # Now test opening the project with shell
        with crystal_shell(args=[project_path]) as (crystal, banner):
            wait_for_main_window(crystal)
            
            # Verify project variable is set to a real Project object
            result = py_eval_literal(crystal, 'repr(project)')
            assertIn('<crystal.model.Project object at 0x', result)
            
            # Verify window variable is set to a real MainWindow object
            result = py_eval_literal(crystal, 'repr(window)')
            assertIn('<crystal.browser.MainWindow object at 0x', result)
            
            # Verify the project path is correct
            result = py_eval_literal(crystal, 'project.path')
            assertEqual(project_path, result)


async def test_when_launched_with_shell_and_ctrl_d_pressed_then_exits() -> None:
    with crystal_shell() as (crystal, banner):
        await OpenOrCreateDialog.wait_for()
        
        # Simulate Ctrl-D to exit the shell
        assert crystal.stdin is not None
        crystal.stdin.close()
        assert isinstance(crystal.stdout, TextIOBase)
        read_until(crystal.stdout, 'now waiting for all windows to close...\n')
        
        # TODO: Simulate this case. Difficult because stdin is already closed
        #       so close_open_or_create_dialog() won't work.
        ## Close last window to quit the process
        #close_open_or_create_dialog`(crystal)
        #crystal.wait(timeout=DEFAULT_WAIT_TIMEOUT)


async def test_when_launched_with_shell_and_ctrl_c_pressed_then_exits() -> None:
    with crystal_shell() as (crystal, banner):
        await OpenOrCreateDialog.wait_for()
        
        # Simulate Ctrl-C to quit the process
        os.kill(crystal.pid, signal.SIGINT)
        crystal.wait(timeout=DEFAULT_WAIT_TIMEOUT)


# === Headless Mode Tests (---headless) ===

def test_when_headless_used_without_serve_or_shell_then_prints_error_and_exits() -> None:
    result = run_crystal(['--headless'])
    assert result.returncode == 2
    assertIn('error: --headless must be combined with --serve or --shell', result.stderr)


def test_when_headless_used_without_project_filepath_then_prints_error_and_exits() -> None:
    result = run_crystal(['--headless', '--serve'])
    assert result.returncode == 2
    assertIn('error: --headless --serve requires a project file path', result.stderr)


def test_when_headless_serve_with_project_then_starts_server_without_gui() -> None:
    # ...and pressing Ctrl-C quits the process
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        with crystal_running_with_banner(
            args=['--headless', '--serve', project_dirpath],
            expects=['server_started', 'ctrl_c']
        ) as (crystal, banner_metadata):
            assert banner_metadata.server_url is not None
            _ensure_server_is_accessible(banner_metadata.server_url)

            # Simulate Ctrl-C to quit the process
            os.kill(crystal.pid, signal.SIGINT)
            crystal.wait(timeout=DEFAULT_WAIT_TIMEOUT)


def test_when_headless_serve_with_custom_port_then_starts_server_on_custom_port() -> None:
    custom_port = 8765  # arbitrary
    
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_path:
        with crystal_running_with_banner(
            args=['--headless', '--serve', '--port', str(custom_port), project_path],
            expects=['server_started', 'ctrl_c']
        ) as (crystal, banner_metadata):
            assert banner_metadata.server_url is not None
            assertIn(f':{custom_port}', banner_metadata.server_url)
            _ensure_server_is_accessible(banner_metadata.server_url)


def test_when_headless_serve_with_project_then_prints_server_url_and_ctrl_c_instruction() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_path:
        with crystal_running_with_banner(
            args=['--headless', '--serve', project_path],
            expects=['server_started', 'ctrl_c']
        ) as (crystal, banner_metadata):
            assert banner_metadata.server_url is not None
            _ensure_server_is_accessible(banner_metadata.server_url)


def test_when_headless_shell_with_project_then_starts_shell_without_gui() -> None:
    # ...and project variable is available in shell
    # ...and window variable is not available in shell
    # ...and Ctrl-D quits the process
    
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_path:
        with crystal_running_with_banner(
            args=['--headless', '--shell', project_path],
            expects=['version', 'help', 'variables', 'exit', 'prompt']
        ) as (crystal, banner_metadata):
            assertIn('<crystal.model.Project object at 0x', py_eval_literal(crystal, 'repr(project)'))
            assertEqual(project_path, py_eval_literal(crystal, 'project.path'))
            assertIn('<unset crystal.browser.MainWindow proxy>', py_eval_literal(crystal, 'repr(window)'))
            
            # Simulate Ctrl-D to exit the shell
            assert crystal.stdin is not None
            crystal.stdin.close()
            crystal.wait(timeout=DEFAULT_WAIT_TIMEOUT)


def test_when_headless_shell_without_project_then_starts_shell_without_gui() -> None:
    # ...and project variable is not available in shell
    # ...and window variable is not available in shell
    
    # Start headless shell without a project
    with crystal_running_with_banner(
        args=['--headless', '--shell'],
        expects=[
            'version', 'help', 'variables', 'exit', 'prompt'
        ]
    ) as (crystal, banner_metadata):
        assertIn('<unset crystal.model.Project proxy>', py_eval_literal(crystal, 'repr(project)'))
        assertIn('<unset crystal.browser.MainWindow proxy>', py_eval_literal(crystal, 'repr(window)'))


def test_when_headless_serve_shell_with_project_then_starts_both_server_and_shell() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_path:
        with crystal_running_with_banner(
            args=['--headless', '--serve', '--shell', project_path],
            expects=[
                'version', 'help', 'variables', 'exit', 'prompt',
                'server_started', 'ctrl_c',
            ]
        ) as (crystal, banner_metadata):
            assertIn('<crystal.model.Project object at 0x', py_eval_literal(crystal, 'repr(project)'))
            assertEqual(project_path, py_eval_literal(crystal, 'project.path'))
            assertIn('<unset crystal.browser.MainWindow proxy>', py_eval_literal(crystal, 'repr(window)'))
            
            assert banner_metadata.server_url is not None
            _ensure_server_is_accessible(banner_metadata.server_url)


# === Cookie Configuration Tests (--cookie) ===

@skip('not yet automated')
def test_when_project_opened_with_cookie_then_downloads_use_cookie() -> None:
    pass


@skip('not yet automated')
def test_when_cookie_argument_missing_value_then_prints_error_and_exits() -> None:
    pass


# === Stale Date Configuration Tests (--stale-before) ===

@awith_subtests
async def test_when_project_opened_with_stale_before_then_old_revisions_considered_stale(subtests: SubtestsContext) -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            _temporary_project() as project_path:
        
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        # Create and populate a project with a resource revision
        with Project(project_path) as project:
            r = Resource(project, atom_feed_url)
            rr_future = r.download()
            await step_scheduler_until_done(project)
            rr = rr_future.result(timeout=0)
            
            # Verify the revision is not initially stale
            assert not rr.is_stale, "Resource revision should not be stale initially"
        
        with subtests.test(msg='reopen with past date - revision should NOT be stale'):
            past_date = '1900-01-01T00:00:00+00:00'
            with crystal_shell(args=['--stale-before', past_date, project_path]) as (crystal, banner):
                wait_for_main_window(crystal)
                
                # Get the resource revision and verify it's NOT stale
                py_exec(crystal, f'r = project.get_resource({atom_feed_url!r})')
                py_exec(crystal, 'rr = r.default_revision()')
                result = py_eval_literal(crystal, 'rr.is_stale')
                assert False == result, f"Expected resource revision to NOT be stale with past min_fetch_date, got: {result}"
        
        with subtests.test(msg='reopen with future date - revision should be stale'):
            future_date = '2099-01-01T00:00:00+00:00'
            with crystal_shell(args=['--stale-before', future_date, project_path]) as (crystal, banner):
                wait_for_main_window(crystal)
                
                # Verify the project's min_fetch_date is set correctly
                result = py_eval_literal(crystal, 'repr(project.min_fetch_date)')
                assert 'datetime.datetime(2099, 1, 1' in result, f"Expected min_fetch_date to be set to 2099, got: {result}"
                
                # Get the resource and its revision
                # TODO: Rewrite to use more-reliable py_eval_literal()
                result = py_eval(crystal, f'r = project.get_resource({atom_feed_url!r}); r')
                assert 'Resource(' in result, f"Expected to find resource, got: {result}"
                
                # TODO: Rewrite to use more-reliable py_eval_literal()
                result = py_eval(crystal, 'rr = r.default_revision(); rr')
                assert 'ResourceRevision' in result, f"Expected to find resource revision, got: {result}"
                
                # Verify the revision is now considered stale
                result = py_eval_literal(crystal, 'rr.is_stale')
                assert True == result, f"Expected resource revision to be stale with future min_fetch_date, got: {result}"


@with_subtests
def test_stale_before_option_recognizes_many_date_formats(subtests: SubtestsContext) -> None:
    with _temporary_project() as project_path:
        with subtests.test(format='ISO date'):
            result = run_crystal(['--stale-before', '2022-07-17', '--help'])
            assertEqual(0, result.returncode, f"ISO date format failed: {result.stderr}")
        
        with subtests.test(format='ISO datetime without timezone'):
            result = run_crystal(['--stale-before', '2022-07-17T12:47:42', '--help'])
            assertEqual(0, result.returncode, f"ISO datetime format failed: {result.stderr}")
        
        with subtests.test(format='ISO datetime with UTC timezone'):
            result = run_crystal(['--stale-before', '2022-07-17T12:47:42+00:00', '--help'])
            assertEqual(0, result.returncode, f"ISO datetime with timezone format failed: {result.stderr}")
        
        with subtests.test(format='ISO datetime with negative timezone offset'):
            result = run_crystal(['--stale-before', '2022-07-17T12:47:42-05:00', '--help'])
            assertEqual(0, result.returncode, f"ISO datetime with negative timezone offset failed: {result.stderr}")


@with_subtests
def test_when_stale_before_has_invalid_format_then_prints_error_and_exits(subtests: SubtestsContext) -> None:
    with subtests.test(case='completely invalid date format'):
        result = run_crystal(['--stale-before', 'invalid-date-format'])
        assert result.returncode != 0
        assertIn('invalid', result.stderr.lower())
    
    with subtests.test(case='invalid month and day'):
        result = run_crystal(['--stale-before', '2022-13-45'])  # invalid month and day
        assert result.returncode != 0
        assertIn('invalid', result.stderr.lower())
    
    with subtests.test(case='malformed datetime'):
        result = run_crystal(['--stale-before', '2022-07-17T25:99:99'])  # invalid time
        assert result.returncode != 0
        assertIn('invalid', result.stderr.lower())


def test_when_stale_before_argument_missing_value_then_prints_error_and_exits() -> None:
    result = run_crystal(['--stale-before'])
    assert result.returncode != 0
    assertIn('expected one argument', result.stderr)


# === Testing Tests (test, --test): Serial ===

def test_can_run_tests_with_test_subcommand() -> None:
    """Test that 'crystal test <test_name>' works."""
    result = run_crystal([
        'test',
        # NOTE: This is a simple, fast test
        'crystal.tests.test_main_window.test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors'
    ])
    assertEqual(0, result.returncode)
    assertIn('OK', result.stdout)
    assertIn('Ran 1 tests', result.stdout)


def test_can_run_tests_with_test_flag() -> None:
    """Test that 'crystal --test <test_name>' still works for backward compatibility."""
    result = run_crystal([
        '--test',
        # NOTE: This is a simple, fast test
        'crystal.tests.test_main_window.test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors'
    ])
    assertEqual(0, result.returncode)
    assertIn('OK', result.stdout)
    assertIn('Ran 1 tests', result.stdout)


def test_can_run_multiple_tests_with_test_subcommand() -> None:
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


def test_can_run_multiple_tests_with_test_flag() -> None:
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


def test_can_run_tests_in_interactive_mode() -> None:
    """Test that 'crystal test --interactive' works."""
    # Start Crystal in interactive test mode
    with crystal_running(args=['test', '--interactive']) as crystal:
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


def test_when_test_not_found_in_interactive_mode_then_prints_error() -> None:
    """Test that 'crystal test --interactive' handles non-existent tests gracefully."""
    with crystal_running(args=['test', '--interactive']) as crystal:
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


def test_when_interactive_flag_used_with_test_names_then_prints_error() -> None:
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
            # Test 1: Fast test that should pass
            'crystal.tests.test_cli.test_special_a',
            # Test 2: Special test that simulates Ctrl-C
            'crystal.tests.test_cli.test_special_b',
            # Test 3: Fast test that should pass, if it wasn't interrupted
            'crystal.tests.test_cli.test_special_c',
        ],
        # Enable Ctrl-C simulation in test_special_b
        env_extra={'CRYSTAL_SIMULATE_CTRL_C_DURING_TEST': '1'},
        # Let the process exit naturally after Ctrl-C
        kill=False,
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
        'crystal.tests.test_cli.test_special_b '
        'crystal.tests.test_cli.test_special_c', stdout_str)
    
    # Verify exit code indicates failure
    assertNotEqual(0, returncode, f'Expected non-zero exit code, got {returncode}')


def test_when_ctrl_c_pressed_while_test_running_interactively_then_marks_that_test_as_interrupted_and_ignores_further_tests_on_stdin() -> None:
    with crystal_running(
        args=['test', '--interactive'],
        # Enable Ctrl-C simulation in test_special_b
        env_extra={'CRYSTAL_SIMULATE_CTRL_C_DURING_TEST': '1'},
        # Let the process exit naturally after Ctrl-C
        kill=False,
    ) as crystal:
        assert crystal.stdin is not None
        assert isinstance(crystal.stdout, TextIOBase)
        
        # Read the first prompt
        (_, _) = read_until(crystal.stdout, 'test>\n', timeout=2.0)
        
        # Send test 1 (should pass)
        crystal.stdin.write('crystal.tests.test_cli.test_special_a\n')
        crystal.stdin.flush()
        (early_stdout_str, _) = read_until(crystal.stdout, 'test>\n', timeout=30.0)
        assertIn('OK', early_stdout_str)
        
        # Send test 2 (will trigger Ctrl-C simulation)
        crystal.stdin.write('crystal.tests.test_cli.test_special_b\n')
        crystal.stdin.flush()
        
        # Try to send test 3 (should be ignored after Ctrl-C)
        # Note: We send this immediately, but after Ctrl-C it should be ignored
        crystal.stdin.write('crystal.tests.test_cli.test_special_c\n')
        crystal.stdin.flush()
        
        # Wait for process to exit
        (late_stdout_str, _) = crystal.communicate(input='')
        returncode = crystal.returncode
    
    # Verify "INTERRUPTED" status line was printed for the test that received Ctrl-C
    assertIn('INTERRUPTED', late_stdout_str)
    
    # Verify SUMMARY section is still printed
    assertIn('SUMMARY', late_stdout_str)
    assertIn('-' * 70, late_stdout_str)
    
    # Verify only test_special_b is marked as interrupted (not test_special_c)
    # Expected pattern: '.-' (pass, interrupted)
    # test_special_c should not appear in the summary since it was ignored
    assertIn('\n.-\n', late_stdout_str)
    
    # Verify summary status line mentions interrupted tests
    assertIn('interrupted=1', late_stdout_str)
    assertIn('FAILURE', late_stdout_str)
    
    # Verify 'Rerun interrupted tests with:' section exists
    assertIn('Rerun interrupted tests with:', late_stdout_str)
    assertIn('crystal --test crystal.tests.test_cli.test_special_b', late_stdout_str)
    
    # Verify test_special_c was NOT run (it was on stdin but ignored after Ctrl-C)
    assertNotIn('test_special_c', late_stdout_str)
    
    # Verify exit code indicates failure
    assertNotEqual(0, returncode, f'Expected non-zero exit code, got {returncode}')


# NOTE: This is not a real test. It is used by:
#       - test_when_ctrl_c_pressed_while_tests_running_then_marks_that_test_and_all_following_tests_as_interrupted
#       - test_when_ctrl_c_pressed_while_test_running_interactively_then_marks_that_test_as_interrupted_and_ignores_further_tests_on_stdin
def test_special_a() -> None:
    pass


# NOTE: This is not a real test. It is used by:
#       - test_when_ctrl_c_pressed_while_tests_running_then_marks_that_test_and_all_following_tests_as_interrupted
#       - test_when_ctrl_c_pressed_while_test_running_interactively_then_marks_that_test_as_interrupted_and_ignores_further_tests_on_stdin
def test_special_b() -> None:
    # Simulate pressing Ctrl-C if a special environment variable is set.
    if os.environ.get('CRYSTAL_SIMULATE_CTRL_C_DURING_TEST') == '1':
        raise KeyboardInterrupt


# NOTE: This is not a real test. It is used by:
#       - test_when_ctrl_c_pressed_while_tests_running_then_marks_that_test_and_all_following_tests_as_interrupted
#       - test_when_ctrl_c_pressed_while_test_running_interactively_then_marks_that_test_as_interrupted_and_ignores_further_tests_on_stdin
def test_special_c() -> None:
    pass


# === Testing Tests (test): Parallel ===

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


# === Platform-Specific Options Tests ===

@skip('not yet automated')
def test_when_launched_on_linux_with_install_to_desktop_then_installs_and_exits() -> None:
    pass


@skip('not yet automated')
def test_when_launched_on_non_linux_with_install_to_desktop_then_argument_not_visible_in_help_and_does_not_work() -> None:
    pass


# === Exit Tests ===

@skip('not yet automated')
def test_when_crystal_receives_ctrl_c_or_sigint_then_exits_cleanly() -> None:
    pass


# === Utility ===

@contextmanager
def _temporary_project() -> Iterator[str]:
    """Create a temporary project directory for testing."""
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as temp_project_dirpath:
        os.rmdir(temp_project_dirpath)
        yield temp_project_dirpath


@contextmanager
def _crystal_shell_with_serve(
        project_path: str,
        port: int | None = None,
        host: str | None = None,
        *, banner_timeout: float | None = None,
        extra_args: list[str] | None = None,
        ) -> Iterator[str]:
    """
    Context which starts "crystal --serve [--port PORT] [--host HOST] [extra_args] PROJECT_PATH --shell"
    and cleans up the associated process upon exit.
    
    See also: crystal_running_with_banner()
    """
    # NOTE: wxGTK on Ubuntu 22 can print many warning lines in the format
    #       "Unable to load X from the cursor theme", which should be ignored
    MAX_BANNER_LINES = (
        # Maximum normal banner length. Example:
        # > Crystal 2.0.1 (Python 3.12.2)
        # > Type "help" for more information.
        # > Variables "project" and "window" are available.
        # > Use exit() or Ctrl-D (i.e. EOF) to exit.
        # > Server started at: http://0.0.0.0:2797
        # > Read-only mode automatically enabled for remote access (--host 0.0.0.0).
        # > To allow remote modifications, restart with --no-readonly.
        # > Cmd click to launch VS Code Native REPL
        8 +
        # Maximum additional lines
        7
    )
    
    if banner_timeout is None:
        # macOS CI has been observed to take 6.2s
        banner_timeout = 7.0
    if extra_args is None:
        extra_args = []
    
    # Build arguments
    args = ['--serve']
    if port is not None:
        args.extend(['--port', str(port)])
    if host is not None:
        args.extend(['--host', host])
    args.extend(extra_args)
    args.extend([project_path])
    
    with crystal_shell(args=args) as (crystal, banner):
        assert isinstance(crystal.stdout, TextIOBase)
        
        # Read banner until we see expected lines or reach a reasonable line limit
        # - server URL (required)
        # - readonly messages (optional)
        # - Ctrl-C instruction (optional)
        banner_line_count = 0
        while True:
            if 'Traceback ' in banner:
                raise AssertionError(
                    f'Crystal raised exception immediately after launch:\n\n'
                    f'{banner}{drain(crystal.stdout)}')
            
            seen_required_lines = 'Server started at: ' in banner
            seen_optional_lines = 'Press Ctrl-C to stop' in banner
            if seen_required_lines and (seen_optional_lines or banner_line_count >= MAX_BANNER_LINES):
                break
            try:
                (line, _) = read_until(
                    crystal.stdout,
                    '\n',
                    timeout=(
                        # Wait longer time for required lines
                        banner_timeout if not seen_required_lines
                        # Wait shorter time for optional lines
                        else 0.5
                    ),
                    stacklevel_extra=2,
                    _drain_diagnostic=(
                        True if not seen_required_lines
                        else False
                    ),
                )
            except ReadUntilTimedOut:
                if not seen_required_lines:
                    # Required lines not found after long wait. Error.
                    raise
                else:
                    # Optional lines not found after short wait. OK.
                    break
            else:
                # NOTE: Quadratic performance, but is OK for small N (<= MAX_BANNER_LINES)
                banner += line
                banner_line_count += 1
        
        yield banner

def _ensure_server_is_accessible(server_url: str) -> None:
    """
    Verify that the server at the given URL is accessible.
    
    Arguments:
    * server_url -- 
        Server URL (e.g., "http://127.0.0.1:8080")
        
    Raises:
    * AssertionError -- If server is not accessible.
    """
    with urllib.request.urlopen(server_url) as response:
        assert response.status == 200
