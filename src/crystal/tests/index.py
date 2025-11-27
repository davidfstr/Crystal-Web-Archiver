from collections.abc import Callable
from crystal.tests import (
    test_about_box,
    test_bulkheads, test_callout, test_cli, test_disk_io_errors, test_do_not_download_groups,
    test_download, test_download_body, test_edit_group, test_edit_root_url,
    test_entitytree, test_file_extension_visibility, test_hibernate,
    test_icons, test_install_to_desktop, test_load_urls, test_log_drawer,
    test_main_window,
    test_menus, test_new_group, test_new_root_url, test_open_project,
    test_parse_html, test_preferences,
    test_profile, test_project_migrate, test_readonly_mode,
    test_runner, test_server, test_shell, test_ssd, test_tasks, test_tasktree,
    test_untitled_projects,
    test_window_modal_titles, test_workflows, test_xthreading,
)


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

# TODO: Avoid the need to manually enumerate all test modules individually
TEST_FUNCS = (
    _test_functions_in_module(test_about_box) +
    _test_functions_in_module(test_bulkheads) +
    _test_functions_in_module(test_callout) +
    _test_functions_in_module(test_cli) +
    _test_functions_in_module(test_disk_io_errors) +
    _test_functions_in_module(test_do_not_download_groups) +
    _test_functions_in_module(test_download) +
    _test_functions_in_module(test_download_body) +
    _test_functions_in_module(test_edit_group) +
    _test_functions_in_module(test_edit_root_url) +
    _test_functions_in_module(test_entitytree) +
    _test_functions_in_module(test_file_extension_visibility) +
    _test_functions_in_module(test_hibernate) +
    _test_functions_in_module(test_icons) +
    _test_functions_in_module(test_install_to_desktop) +
    _test_functions_in_module(test_load_urls) +
    _test_functions_in_module(test_log_drawer) +
    _test_functions_in_module(test_main_window) +
    _test_functions_in_module(test_menus) +
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
    _test_functions_in_module(test_window_modal_titles) +
    _test_functions_in_module(test_workflows) +
    _test_functions_in_module(test_xthreading) +
    []
)
