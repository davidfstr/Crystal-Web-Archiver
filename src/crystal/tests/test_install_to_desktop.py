"""
Tests the --install-to-desktop command line option on Linux,
implemented by the install.py module.
"""
from unittest import skip

# === Not Linux ===

@skip('not yet automated')
def test_given_not_linux_when_install_to_desktop_then_exits_with_error_message(self) -> None:
    pass


# === Non-Root vs. Root User ===

@skip('not yet automated')
def test_given_linux_and_non_root_user_is_using_sudo_when_install_to_desktop_then_exits_with_error_message(self) -> None:
    pass


@skip('not yet automated')
def test_given_linux_and_non_root_user_is_not_using_sudo_when_install_to_desktop_then_does_not_exit_with_error_message(self) -> None:
    pass


@skip('not yet automated')
def test_given_linux_and_is_root_user_when_install_to_desktop_then_does_not_exit_with_error_message(self) -> None:
    pass


# === Installs to Desktop ===

@skip('not yet automated')
def test_given_linux_when_install_to_desktop_then_crystal_app_appears_on_desktop_with_custom_icon_and_can_be_double_clicked_to_open_crystal(self) -> None:
    pass


# === Installs to Application Launcher ===

@skip('not yet automated')
def test_given_linux_and_gnome_desktop_environment_when_install_to_desktop_then_crystal_app_appears_in_application_launcher_menus(self) -> None:
    pass


@skip('not yet automated')
def test_given_linux_and_kde_desktop_environment_when_install_to_desktop_then_crystal_app_appears_in_application_launcher_menus(self) -> None:
    pass
