"""
Tests that projects in older on-disk formats are upgraded to the latest
format properly.

In particular this module tests the Project._apply_migrations() method.

All tests below implicitly include the condition:
* given_project_opened_as_writable
"""
from unittest import skip


# === .crystalopen & README ===

@skip('not yet automated')
def test_given_project_lacks_crystalopen_and_lacks_readme_when_project_opened_then_crystalopen_and_readme_created(self) -> None:
    pass


@skip('not yet automated')
def test_given_project_lacks_crystalopen_and_has_maybe_modified_readme_when_project_opened_then_readme_content_preserved(self) -> None:
    pass


@skip('not yet automated')
def test_given_project_has_crystalopen_with_nondefault_name_when_project_opened_then_crystalopen_name_preserved(self) -> None:
    pass


@skip('not yet automated')
def test_given_project_has_crystalopen_and_has_maybe_modified_readme_when_project_opened_then_readme_content_preserved(self) -> None:
    pass


@skip('not yet automated')
def test_given_project_has_crystalopen_and_readme_was_deleted_when_project_opened_then_readme_stays_deleted(self) -> None:
    pass


# === Windows desktop.ini ===

@skip('not yet automated')
def test_given_project_lacks_desktop_ini_file_then_desktop_ini_and_icons_directory_created(self) -> None:
    pass


@skip('not yet automated')
def test_given_project_has_desktop_ini_file_then_desktop_ini_content_preserved(self) -> None:
    pass


# === Linux .directory ===

@skip('not yet automated')
def test_given_project_lacks_dot_directory_file_then_dot_directory_file_created(self) -> None:
    pass


@skip('not yet automated')
def test_given_project_has_dot_directory_file_then_dot_directory_file_content_preserved(self) -> None:
    pass


# === Hide special files on Windows ===

@skip('not yet automated')
def test_given_windows_then_desktop_ini_file_and_dot_directory_file_marked_as_hidden(self) -> None:
    pass
