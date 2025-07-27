"""
Tests Crystal's command-line interface (CLI).

See also:
* test_shell.py -- Tests related to the --shell option
"""

from contextlib import contextmanager
from crystal.tests.util.asserts import assertIn
from crystal.tests.util.cli import (
    close_open_or_create_dialog, _py_eval, _read_until, drain,
    wait_for_crystal_to_exit, crystal_shell, run_crystal,
)
from crystal.tests.util.wait import DEFAULT_WAIT_TIMEOUT
from io import TextIOBase
import os
import tempfile
from unittest import skip

# === Basic Launch Tests ===

@skip('not yet automated')
def test_when_launched_with_no_arguments_then_shows_open_or_create_project_dialog() -> None:
    pass


@skip('not yet automated')
def test_when_launched_with_help_argument_then_prints_help_and_exits() -> None:
    pass


@skip('not yet automated')
def test_when_launched_with_invalid_argument_then_prints_error_and_exits() -> None:
    pass


# === Project Open & Create Tests (project_filepath, --readonly) ===

@skip('not yet automated')
def test_can_open_project_as_writable() -> None:
    pass


@skip('not yet automated')
def test_can_open_project_as_readonly() -> None:
    pass


@skip('not yet automated')
def test_when_opened_project_filepath_does_not_exist_then_creates_new_project_at_filepath() -> None:
    pass


@skip('not yet automated')
def test_can_open_crystalopen_file() -> None:
    # ...in addition to .crystalproj files
    pass


@skip('fails: see https://github.com/davidfstr/Crystal-Web-Archiver/issues/63')
def test_when_launched_with_readonly_and_no_project_filepath_then_open_or_create_dialog_defaults_to_readonly_checked() -> None:
    pass


@skip('not yet automated')
def test_when_launched_with_multiple_filepaths_then_prints_error_and_exits() -> None:
    pass


# === Server Mode Tests (--serve) ===
# NOTE: Detailed server tests are in test_server.py

def test_when_launched_with_serve_and_project_filepath_then_opens_project_and_serves_immediately() -> None:
    with _temp_project() as project_path:
        with _crystal_shell_with_serve(project_path) as server_start_message:
            assertIn('Server started at: http://127.0.0.1:2797', server_start_message)


def test_when_launched_with_serve_and_port_then_binds_to_specified_port() -> None:
    with _temp_project() as project_path:
        with _crystal_shell_with_serve(project_path, port=8080) as server_start_message:
            assertIn('Server started at: http://127.0.0.1:8080', server_start_message)


def test_when_launched_with_serve_and_host_then_binds_to_specified_host() -> None:
    with _temp_project() as project_path:
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


def test_when_launched_with_serve_and_port_already_in_use_then_fails_immediately() -> None:
    import socket
    from contextlib import closing
    
    # Find a free port for testing
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(('127.0.0.1', 0))  # bind to any free port
        test_port = sock.getsockname()[1]
    
    # Create a simple server on the test port to create a conflict
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as conflicting_server:
        conflicting_server.bind(('127.0.0.1', test_port))
        conflicting_server.listen(1)  # Start listening to reserve the port
        
        with _temp_project() as project_path:
            # Try to start Crystal server on the same port - should fail
            result = run_crystal(['--serve', '--port', str(test_port), project_path])
            assert result.returncode != 0
            # Check for common error messages that indicate port conflict
            error_output = result.stderr.lower()
            assert ('address already in use' in error_output or 
                    'bind' in error_output or 
                    'port' in error_output), f"Expected port conflict error, got: {result.stderr}"


# === Shell Mode Tests (--shell) ===
# NOTE: Detailed shell tests are in test_shell.py

# NOTE: Also covered by: test_can_launch_with_shell
@skip('not yet automated')
def test_when_launched_with_shell_and_no_project_filepath_then_shell_starts_with_no_project() -> None:
    # ...and `project` variable is an unset proxy
    # ...and `window` variable is an unset proxy
    pass


@skip('not yet automated')
def test_when_launched_with_shell_and_project_filepath_then_shell_starts_with_opened_project() -> None:
    # ...and `project` variable is set to a Project
    # ...and `window` variable is set to a MainWindow
    pass


# === Cookie Configuration Tests (--cookie) ===

@skip('not yet automated')
def test_when_project_opened_with_cookie_then_downloads_use_cookie() -> None:
    pass


@skip('not yet automated')
def test_when_cookie_argument_missing_value_then_prints_error_and_exits() -> None:
    pass


# === Stale Date Configuration Tests (--stale-before) ===

@skip('not yet automated')
def test_when_project_opened_with_stale_before_then_old_revisions_considered_stale() -> None:
    pass


@skip('not yet automated')
def test_stale_before_option_recognizes_many_date_formats() -> None:
    # iso_date: ISO date format like "2022-07-17"
    # iso_datetime: ISO datetime format like "2022-07-17T12:47:42", interpreted with local timezone
    # iso_datetime_with_timezone: ISO datetime with timezone like "2022-07-17T12:47:42+00:00"
    pass


@skip('not yet automated')
def test_when_stale_before_has_invalid_format_then_prints_error_and_exits() -> None:
    pass


@skip('not yet automated')
def test_when_stale_before_argument_missing_value_then_prints_error_and_exits() -> None:
    pass


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


# === Utility Functions ===

@contextmanager
def _temp_project():
    """Create a temporary project file for testing."""
    with tempfile.NamedTemporaryFile(suffix='.crystalproj', delete=False) as temp_file:
        project_path = temp_file.name
    
    try:
        # Remove the temporary file so Crystal can create the project
        os.remove(project_path)
        yield project_path
    finally:
        # Clean up the project directory if it was created
        if os.path.exists(project_path):
            import shutil
            shutil.rmtree(project_path)


@contextmanager
def _crystal_shell_with_serve(project_path: str, port: int | None = None, host: str | None = None):
    """
    Context which starts "crystal --serve [--port PORT] [--host HOST] PROJECT_PATH --shell"
    and cleans up the associated process upon exit.
    """
    # Build arguments
    args = ['--serve']
    if port is not None:
        args.extend(['--port', str(port)])
    if host is not None:
        args.extend(['--host', host])
    args.extend([project_path])
    
    with crystal_shell(args=args) as (crystal, banner):
        assert isinstance(crystal.stdout, TextIOBase)
        try:
            (server_start_message, _) = _read_until(crystal.stdout, '\n')
            yield server_start_message
        except:
            print(f'FIXME: {banner=}')
            print(f'FIXME: {drain(crystal.stdout)=}')
            raise
        
        # TODO: Consider quitting using Ctrl-C instead,
        #       which would probably be easier and more reliable
        _py_eval(crystal, 'window.close()')
        close_open_or_create_dialog(crystal)
        _py_eval(crystal, 'exit()', stop_suffix='')
        wait_for_crystal_to_exit(
            crystal,
            timeout=DEFAULT_WAIT_TIMEOUT)
