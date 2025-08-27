"""
Tests functionality of the MainWindow which isn't covered by more-specific suites.

For high-level tests of complete user workflows, see test_workflows.py
"""

from unittest import skip


# === Test: Open ===

# (See test_open_project.py)
# (See test_untitled_projects.py)
# (See test_project_migrate.py)
# (See test_readonly_mode.py)


# === Test: Menus ===

# (See test_menus.py)


# === Test: Entity Tree: Tree ===

# (See test_entitytree.py)


# === Test: Entity Tree: Button Bar ===

# "New Root URL..." button -> (See test_new_root_url.py)
# "New Group..." button -> (See test_new_group.py)
# "Edit..." button -> (See test_edit_root_url.py and test_edit_group.py)
# "View" button -> (See test_server.py)

# View button callout -> (See test_entitytree.py)
# Callouts -> (See test_callout.py)

# === Test: Task Tree ===

# (See test_tasktree.py)
# (See test_tasks.py)


# === Test: Status Bar ===

@skip('not yet automated')
async def test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors() -> None:
    pass


@skip('not yet automated')
async def test_branding_area_looks_good_in_light_mode_and_dark_mode() -> None:
    pass


@skip('not yet automated')
async def test_when_contributors_link_clicked_then_opens_webbrowser_to_github_contributor_list() -> None:
    pass


@skip('not yet automated')
async def test_branding_area_updates_correctly_when_system_appearance_changes_between_light_and_dark_mode() -> None:
    # Procedure:
    # 1. Open a project and verify branding area appears correctly in current mode
    # 2. Simulate a system appearance change event (wx.SysColourChangedEvent)
    # 3. Verify that the branding area updates to reflect the new appearance:
    #    - Logo bitmap changes (logotext.png vs logotext-dark.png)
    #    - Text colors change appropriately
    # 
    # Test both light->dark and dark->light transitions
    pass


# === Test: Log Drawer ===

# (See test_log_drawer.py)


# === Test: Close ===

# (See test_hibernate.py)
