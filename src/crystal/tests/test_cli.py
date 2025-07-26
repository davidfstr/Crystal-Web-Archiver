"""
Tests Crystal's command-line interface (CLI).

See also:
* test_shell.py -- Tests related to the --shell option
"""

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

@skip('not yet automated')
def test_when_launched_with_serve_and_project_filepath_then_opens_project_and_serves_immediately() -> None:
    pass


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
