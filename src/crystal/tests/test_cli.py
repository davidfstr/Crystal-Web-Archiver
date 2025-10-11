"""
Tests Crystal's command-line interface (CLI).

See also:
* test_shell.py -- Tests related to the --shell option
"""

from collections.abc import Iterator
from contextlib import closing, contextmanager
import signal
from crystal.model import Project, Resource
from crystal.tests.util.asserts import assertEqual, assertIn, assertNotIn
from crystal.tests.util.cli import (
    _OK_THREAD_STOP_SUFFIX, ReadUntilTimedOut, close_open_or_create_dialog, drain, py_eval, read_until,
    crystal_shell, crystal_running_with_banner, run_crystal, wait_for_main_window,
)
from crystal.tests.util.server import extracted_project, served_project
from crystal.tests.util.subtests import awith_subtests, SubtestsContext, with_subtests
from crystal.tests.util.tasks import scheduler_disabled, step_scheduler_until_done
from crystal.tests.util.wait import DEFAULT_WAIT_TIMEOUT
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.ports import port_in_use
from crystal.util.xos import is_mac_os
from io import TextIOBase
import datetime
import os
import socket
import tempfile
import textwrap
from unittest import skip
import urllib.request


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
    assert result.returncode == 0
    assertIn('Crystal: A tool for archiving websites in high fidelity.', result.stdout)
    assertIn('usage:', result.stdout)
    assertIn('--shell', result.stdout)
    assertIn('--serve', result.stdout)
    assertIn('project_filepath', result.stdout)


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
            result = py_eval(crystal, 'project.readonly')
            assertIn('False', result)


def test_can_open_project_as_readonly() -> None:
    with _temporary_project() as project_path:
        # First create the project
        with crystal_shell(args=[project_path]) as (crystal, banner):
            wait_for_main_window(crystal)
        
        # Now test opening the project as readonly
        with crystal_shell(args=['--readonly', project_path]) as (crystal, banner):
            wait_for_main_window(crystal)
            
            # Verify project is readonly
            result = py_eval(crystal, 'project.readonly')
            assertIn('True', result)


def test_when_opened_project_filepath_does_not_exist_then_creates_new_project_at_filepath() -> None:
    with _temporary_project() as project_path:
        # Project path doesn't exist yet. Crystal should create it.
        assert not os.path.exists(project_path)
        
        with crystal_shell(args=[project_path]) as (crystal, banner):
            wait_for_main_window(crystal)
            
            # Verify the project was created at the specified path
            result = py_eval(crystal, 'project.path')
            assertIn(project_path, result)
            
            # Verify it's a new project (writable by default)
            result = py_eval(crystal, 'project.readonly')
            assertIn('False', result)
        
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
            result = py_eval(crystal, 'project.path')
            assertIn(project_path, result)


def test_when_launched_with_readonly_and_no_project_filepath_then_open_or_create_dialog_defaults_to_readonly_checked() -> None:
    with crystal_shell(args=['--readonly']) as (crystal, banner):
        # Check readonly checkbox state
        result = py_eval(crystal, textwrap.dedent('''\
            if True:
                from crystal.tests.util.runner import run_test
                from crystal.tests.util.windows import OpenOrCreateDialog
                from threading import Thread
                #
                async def check_readonly_state():
                    ocd = await OpenOrCreateDialog.wait_for()
                    readonly_checked = ocd.open_as_readonly.Value
                    create_enabled = ocd.create_button.Enabled
                    print(f"readonly_checked={readonly_checked}")
                    print(f"create_enabled={create_enabled}")
                #
                result_cell = [Ellipsis]
                def get_result(result_cell):
                    result_cell[0] = run_test(lambda: check_readonly_state())
                    print('OK')
                #
                t = Thread(target=lambda: get_result(result_cell))
                t.start()
        '''), stop_suffix=_OK_THREAD_STOP_SUFFIX, timeout=8.0)
        assertIn('readonly_checked=True', result)
        assertIn('create_enabled=False', result)
        
        # Clean up by closing the dialog
        close_open_or_create_dialog(crystal)


def test_when_ctrl_r_pressed_in_open_or_create_dialog_then_readonly_checkbox_is_toggled() -> None:
    with crystal_shell(args=[]) as (crystal, banner):
        # Test Ctrl+R key toggles readonly checkbox
        result = py_eval(crystal, textwrap.dedent('''\
            if True:
                from crystal.tests.util.runner import run_test
                from crystal.tests.util.windows import OpenOrCreateDialog
                from threading import Thread
                import wx
                #
                async def test_ctrl_r_toggle():
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
                #
                result_cell = [Ellipsis]
                def get_result(result_cell):
                    result_cell[0] = run_test(lambda: test_ctrl_r_toggle())
                    print('OK')
                #
                t = Thread(target=lambda: get_result(result_cell))
                t.start()
        '''), stop_suffix=_OK_THREAD_STOP_SUFFIX, timeout=8.0)
        
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
            assertIn('Server started at: http://127.0.0.1:2797', server_start_message)


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
            assertIn('Server started at: http://0.0.0.0:2797', server_start_message)


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
    with port_in_use(2797, '127.0.0.1'):
        with _temporary_project() as project_path:
            with _crystal_shell_with_serve(project_path) as server_start_message:
                assertIn('Server started at: http://127.0.0.1:2798', server_start_message)


def test_when_launched_with_serve_and_without_readonly_then_serves_as_writable() -> None:
    with _temporary_project() as project_path:
        with _crystal_shell_with_serve(project_path) as server_start_message:
            assertIn('Server started at: http://127.0.0.1:2797', server_start_message)
            
            # Should not contain readonly messages for default 127.0.0.1 host
            assertNotIn('Read-only mode automatically enabled', server_start_message)
            assertNotIn('To allow remote modifications', server_start_message)


def test_when_launched_with_serve_and_host_equal_to_127_0_0_1_and_without_readonly_then_serves_as_writable() -> None:
    with _temporary_project() as project_path:
        with _crystal_shell_with_serve(project_path, host='127.0.0.1') as server_start_message:
            assertIn('Server started at: http://127.0.0.1:2797', server_start_message)
            
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
            assertIn('Server started at: http://0.0.0.0:2797', server_start_message)
            
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
            assertIn('Server started at: http://0.0.0.0:2797', server_start_message)
            
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
        result = py_eval(crystal, 'project')
        assertIn('<unset crystal.model.Project proxy>', result)
        
        result = py_eval(crystal, 'window')
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
            result = py_eval(crystal, 'project')
            assertIn('<crystal.model.Project object at 0x', result)
            
            # Verify window variable is set to a real MainWindow object
            result = py_eval(crystal, 'window')
            assertIn('<crystal.browser.MainWindow object at 0x', result)
            
            # Verify the project path is correct
            result = py_eval(crystal, 'project.path')
            assertIn(project_path, result)


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
            assertIn('<crystal.model.Project object at 0x', py_eval(crystal, 'project'))
            assertIn(project_path, py_eval(crystal, 'project.path'))
            assertIn('<unset crystal.browser.MainWindow proxy>', py_eval(crystal, 'window'))
            
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
        assertIn('<unset crystal.model.Project proxy>', py_eval(crystal, 'project'))
        assertIn('<unset crystal.browser.MainWindow proxy>', py_eval(crystal, 'window'))


def test_when_headless_serve_shell_with_project_then_starts_both_server_and_shell() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_path:
        with crystal_running_with_banner(
            args=['--headless', '--serve', '--shell', project_path],
            expects=[
                'version', 'help', 'variables', 'exit', 'prompt',
                'server_started', 'ctrl_c',
            ]
        ) as (crystal, banner_metadata):
            assertIn('<crystal.model.Project object at 0x', py_eval(crystal, 'project'))
            assertIn(project_path, py_eval(crystal, 'project.path'))
            assertIn('<unset crystal.browser.MainWindow proxy>', py_eval(crystal, 'window'))
            
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
                py_eval(crystal, f'r = project.get_resource({atom_feed_url!r})')
                py_eval(crystal, 'rr = r.default_revision()')
                result = py_eval(crystal, 'rr.is_stale')
                assert 'False' in result, f"Expected resource revision to NOT be stale with past min_fetch_date, got: {result}"
        
        with subtests.test(msg='reopen with future date - revision should be stale'):
            future_date = '2099-01-01T00:00:00+00:00'
            with crystal_shell(args=['--stale-before', future_date, project_path]) as (crystal, banner):
                wait_for_main_window(crystal)
                
                # Verify the project's min_fetch_date is set correctly
                result = py_eval(crystal, 'project.min_fetch_date')
                assert 'datetime.datetime(2099, 1, 1' in result, f"Expected min_fetch_date to be set to 2099, got: {result}"
                
                # Get the resource and its revision
                result = py_eval(crystal, f'r = project.get_resource({atom_feed_url!r}); r')
                assert 'Resource(' in result, f"Expected to find resource, got: {result}"
                
                result = py_eval(crystal, 'rr = r.default_revision(); rr')
                assert 'ResourceRevision' in result, f"Expected to find resource revision, got: {result}"
                
                # Verify the revision is now considered stale
                result = py_eval(crystal, 'rr.is_stale')
                assert 'True' in result, f"Expected resource revision to be stale with future min_fetch_date, got: {result}"


@with_subtests
def test_stale_before_option_recognizes_many_date_formats(subtests: SubtestsContext) -> None:
    with _temporary_project() as project_path:
        with subtests.test(format='ISO date'):
            result = run_crystal(['--stale-before', '2022-07-17', '--help'])
            assert result.returncode == 0, f"ISO date format failed: {result.stderr}"
        
        with subtests.test(format='ISO datetime without timezone'):
            result = run_crystal(['--stale-before', '2022-07-17T12:47:42', '--help'])
            assert result.returncode == 0, f"ISO datetime format failed: {result.stderr}"
        
        with subtests.test(format='ISO datetime with UTC timezone'):
            result = run_crystal(['--stale-before', '2022-07-17T12:47:42+00:00', '--help'])
            assert result.returncode == 0, f"ISO datetime with timezone format failed: {result.stderr}"
        
        with subtests.test(format='ISO datetime with negative timezone offset'):
            result = run_crystal(['--stale-before', '2022-07-17T12:47:42-05:00', '--help'])
            assert result.returncode == 0, f"ISO datetime with negative timezone offset failed: {result.stderr}"


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
        extra_args: list[str] | None = None
        ) -> Iterator[str]:
    """
    Context which starts "crystal --serve [--port PORT] [--host HOST] [extra_args] PROJECT_PATH --shell"
    and cleans up the associated process upon exit.
    
    See also: crystal_running_with_banner()
    """
    # NOTE: wxGTK on Ubuntu 22 can print many warning lines in the format
    #       "Unable to load X from the cursor theme", which should be ignored
    MAX_ADDITIONAL_LINES = 7
    
    if banner_timeout is None:
        banner_timeout = 4.0  # currently (2 * DEFAULT_WAIT_TIMEOUT)
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
        (server_start_message, _) = read_until(
            crystal.stdout, '\n', timeout=banner_timeout, stacklevel_extra=1)
        if 'Traceback ' in server_start_message:
            raise AssertionError(
                f'Crystal raised exception immediately after launch:\n\n'
                f'{server_start_message}{drain(crystal.stdout)}')
        
        # Read any additional lines:
        # - server URL -- already read above
        # - readonly messages (if any)
        # - Ctrl-C instruction (optional)
        additional_lines = []
        try:
            # Read more lines with a short timeout,
            # until we see the Ctrl-C instruction or reach a reasonable line limit
            while True:
                (line, _) = read_until(
                    crystal.stdout, '\n', timeout=0.5, _drain_diagnostic=False)
                additional_lines.append(line)
                if 'Press Ctrl-C to stop' in line or len(additional_lines) >= MAX_ADDITIONAL_LINES:
                    break
        except ReadUntilTimedOut:
            pass  # OK
        
        yield (server_start_message + ''.join(additional_lines))


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
