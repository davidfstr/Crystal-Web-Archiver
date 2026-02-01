"""
Tests that .crystalproj packages show/hide their file extension appropriately
in the desktop environment and in the main window title.
"""
from unittest import skip

# === macOS ===

@skip('not yet automated')
def test_given_macos_when_crystalproj_created_then_crystalproj_file_extension_is_hidden_in_finder(self) -> None:
    pass


@skip('not yet automated')
def test_given_macos_and_crystalproj_hides_file_extension_when_crystalproj_opened_then_crystalproj_file_extension_is_hidden_in_main_window_title(self) -> None:
    pass


@skip('not yet automated')
def test_given_macos_and_crystalproj_shows_file_extension_when_crystalproj_opened_as_read_only_then_crystalproj_file_extension_is_shown_in_main_window_title(self) -> None:
    pass


@skip('not yet automated')
def test_given_macos_when_crystalproj_opened_as_writable_then_crystalproj_file_extension_is_hidden_in_finder_and_is_hidden_in_main_window_title(self) -> None:
    pass


# === Windows ===

# TODO: Find way to hide .crystalproj extension in Windows
@skip('not yet automated')
def test_given_windows_when_crystalproj_created_then_crystalproj_file_extension_is_shown_in_explorer(self) -> None:
    pass


@skip('not yet automated')
def test_given_windows_and_crystalproj_shows_file_extension_when_crystalproj_opened_then_crystalproj_file_extension_is_shown_in_main_window_title(self) -> None:
    pass


# === Linux ===

# TODO: Find way to hide .crystalproj extension in Linux
@skip('not yet automated')
def test_given_linux_when_crystalproj_created_then_crystalproj_file_extension_is_shown_in_explorer(self) -> None:
    pass


@skip('not yet automated')
def test_given_linux_and_crystalproj_shows_file_extension_when_crystalproj_opened_then_crystalproj_file_extension_is_shown_in_main_window_title(self) -> None:
    pass
