"""
Index of all tests.

Symbol key:
- 👑 = Central file for its parent directory

Tests, by hierarchy:
- crystal/tests
    - aspects -- Cross-cutting behaviors that affect multiple systems
        - test_do_not_download_groups.py
        - test_external_urls.py
        - test_readonly_mode.py
        - test_untitled_projects.py
    - cli -- Command Line Interface tests for the `crystal` command
        - test_cli.py 👑
        - test_runner.py
        - test_shell.py
    - desktop_integration -- Integration with macOS Finder, Windows Explorer, GNOME Files/Nautilus, KDE Dolphin
        - test_file_extension_visibility.py
        - test_icons.py
        - test_install_to_desktop.py
    - model -- Model layer tests
        - test_disk_io_errors.py
        - test_hibernate.py
        - test_model_durability_and_atomicity.py
        - test_project_migrate.py
        - test_url_normalization.py
    - task -- Task tests, which make changes to a project
        - test_download_body.py
        - test_download.py
        - test_tasks.py 👑
    - test_parse_html.py -- HTML document parsing (crystal.doc.html)
    - test_server.py -- ProjectServer
    - ui -- UI layer tests; Use cases accomplished through the UI
        - main_window
            - test_entitytree.py
            - test_load_urls.py
            - test_log_drawer.py
            - test_main_window.py 👑
            - test_tasktree.py
        - test_about_box.py
        - test_callout.py
        - test_edit_alias.py
        - test_edit_group.py
        - test_edit_root_url.py
        - test_menus.py
        - test_new_alias.py
        - test_new_group.py
        - test_new_root_url.py
        - test_preferences.py
        - test_window_modal_titles.py
    - util_tests -- crystal.util module unit tests
        - test_bulkheads.py
        - test_profile.py
        - test_ssd.py
        - test_xthreading.py
    - workflows -- Complete workflows a user may want to accomplish using the Crystal app
        - test_open_project.py
        - test_workflows.py 👑
"""

from collections.abc import Callable
from crystal.tests import (
    test_parse_html,
    test_server,
)
from crystal.tests.aspects import test_do_not_download_groups, test_external_urls, test_readonly_mode, test_untitled_projects
from crystal.tests.cli import test_cli, test_runner, test_shell
from crystal.tests.desktop_integration import test_file_extension_visibility, test_icons, test_install_to_desktop
from crystal.tests.model import test_disk_io_errors, test_hibernate, test_model_durability_and_atomicity, test_project_migrate, test_url_normalization
from crystal.tests.task import test_download, test_download_body, test_tasks
from crystal.tests.ui import test_about_box, test_callout, test_edit_alias, test_edit_group, test_edit_root_url, test_menus, test_new_alias, test_new_group, test_new_root_url, test_preferences, test_window_modal_titles
from crystal.tests.ui.main_window import test_entitytree, test_load_urls, test_log_drawer, test_main_window, test_tasktree
from crystal.tests.util_tests import test_bulkheads, test_profile, test_ssd, test_xthreading
from crystal.tests.workflows import test_open_project, test_workflows


# === Index ===

def _test_functions_in_module(mod) -> list[Callable]:
    return [
        f for f in mod.__dict__.values() 
        if (
            callable(f) and 
            getattr(f, '__name__', '').startswith('test_') and
            # NOTE: Need to check stringness explicitly to exclude "call" from 
            #       "from unittest.mock import call"
            isinstance(getattr(f, '__name__', ''), str)
        )
    ]

# TODO: Avoid the need to manually enumerate all test modules individually.
#       
#       Dynamic imports alone won't work to eliminate manual enumeration
#       because both py2app and py2exe trace explicit imports to determine
#       what code to bundle in the executables they generate.
TEST_FUNCS = (
    _test_functions_in_module(test_about_box) +
    _test_functions_in_module(test_bulkheads) +
    _test_functions_in_module(test_callout) +
    _test_functions_in_module(test_cli) +
    _test_functions_in_module(test_disk_io_errors) +
    _test_functions_in_module(test_do_not_download_groups) +
    _test_functions_in_module(test_download) +
    _test_functions_in_module(test_download_body) +
    _test_functions_in_module(test_edit_alias) +
    _test_functions_in_module(test_edit_group) +
    _test_functions_in_module(test_edit_root_url) +
    _test_functions_in_module(test_entitytree) +
    _test_functions_in_module(test_external_urls) +
    _test_functions_in_module(test_file_extension_visibility) +
    _test_functions_in_module(test_hibernate) +
    _test_functions_in_module(test_icons) +
    _test_functions_in_module(test_install_to_desktop) +
    _test_functions_in_module(test_load_urls) +
    _test_functions_in_module(test_log_drawer) +
    _test_functions_in_module(test_main_window) +
    _test_functions_in_module(test_menus) +
    _test_functions_in_module(test_model_durability_and_atomicity) +
    _test_functions_in_module(test_new_alias) +
    _test_functions_in_module(test_new_group) +
    _test_functions_in_module(test_new_root_url) +
    _test_functions_in_module(test_open_project) +
    _test_functions_in_module(test_parse_html) +
    _test_functions_in_module(test_preferences) +
    _test_functions_in_module(test_profile) +
    _test_functions_in_module(test_project_migrate) +
    _test_functions_in_module(test_readonly_mode) +
    _test_functions_in_module(test_runner) +
    _test_functions_in_module(test_server) +
    _test_functions_in_module(test_shell) +
    _test_functions_in_module(test_ssd) +
    _test_functions_in_module(test_tasks) +
    _test_functions_in_module(test_tasktree) +
    _test_functions_in_module(test_untitled_projects) +
    _test_functions_in_module(test_url_normalization) +
    _test_functions_in_module(test_window_modal_titles) +
    _test_functions_in_module(test_workflows) +
    _test_functions_in_module(test_xthreading) +
    []
)
