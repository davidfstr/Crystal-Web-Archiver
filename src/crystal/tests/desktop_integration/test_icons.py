"""
Tests that .crystalproj and .crystalopen icons show up correctly
in the desktop environment.
"""
from unittest import skip

# === Icon Tests for .crystalproj ===

# --- macOS ---

@skip('not yet automated')
def test_given_macos_and_did_build_app_then_crystalproj_has_custom_icon_in_finder_and_in_open_and_save_dialogs(self) -> None:
    pass


# --- Windows ---

@skip('not yet automated')
def test_given_windows_and_did_install_with_exe_then_crystalproj_has_custom_icon_in_explorer_and_in_open_and_save_dialogs(self) -> None:
    pass


# --- Linux + GNOME ---

@skip('not yet automated')
def test_given_linux_and_gnome_desktop_environment_and_did_install_to_desktop_and_crystalproj_on_desktop_then_crystalproj_has_custom_icon_on_desktop(self) -> None:
    pass


@skip('not yet automated')
def test_given_linux_and_gnome_desktop_environment_and_did_install_to_desktop_and_crystalproj_not_on_desktop_then_crystalproj_has_custom_icon_in_file_manager(self) -> None:
    pass


@skip('not yet automated')
def test_given_linux_and_gnome_desktop_environment_and_did_install_to_desktop_then_crystalproj_has_custom_icon_in_open_and_save_dialogs(self) -> None:
    pass


# --- Linux + KDE ---

@skip('not yet automated')
def test_given_linux_and_kde_desktop_environment_and_did_install_to_desktop_and_crystalproj_on_desktop_then_crystalproj_has_custom_icon_on_desktop(self) -> None:
    pass


@skip('not yet automated')
def test_given_linux_and_kde_desktop_environment_and_did_install_to_desktop_and_crystalproj_not_on_desktop_then_crystalproj_has_custom_icon_in_file_manager(self) -> None:
    pass


@skip('not yet automated')
def test_given_linux_and_kde_desktop_environment_and_did_install_to_desktop_then_crystalproj_has_custom_icon_in_open_and_save_dialogs(self) -> None:
    pass


# === Icon Tests for .crystalopen ===

# --- macOS ---

@skip('not yet automated')
def test_given_macos_and_did_build_app_then_crystalopen_has_custom_icon_in_finder_and_in_open_and_save_dialogs(self) -> None:
    pass


# --- Windows ---

@skip('not yet automated')
def test_given_windows_and_did_install_with_exe_then_crystalopen_has_custom_icon_in_explorer_and_in_open_and_save_dialogs(self) -> None:
    pass


# --- Linux + GNOME ---

@skip('not yet automated')
def test_given_linux_and_gnome_desktop_environment_and_did_install_to_desktop_and_crystalopen_not_on_desktop_then_crystalopen_has_custom_icon_in_file_manager(self) -> None:
    pass


@skip('not yet automated')
def test_given_linux_and_gnome_desktop_environment_and_did_install_to_desktop_then_crystalopen_has_custom_icon_in_open_and_save_dialogs(self) -> None:
    pass


# --- Linux + KDE ---

@skip('not yet automated')
def test_given_linux_and_kde_desktop_environment_and_did_install_to_desktop_and_crystalopen_not_on_desktop_then_crystalopen_has_custom_icon_in_file_manager(self) -> None:
    pass


@skip('not yet automated')
def test_given_linux_and_kde_desktop_environment_and_did_install_to_desktop_then_crystalopen_has_custom_icon_in_open_and_save_dialogs(self) -> None:
    pass
