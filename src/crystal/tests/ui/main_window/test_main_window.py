"""
Tests functionality of the MainWindow which isn't covered by more-specific suites.

For high-level tests of complete user workflows, see test_workflows.py
"""

from crystal import __version__ as CRYSTAL_VERSION
from crystal.tests.util.cli import (
    crystal_shell, py_eval, py_eval_await, wait_for_crystal_to_exit,
)
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.tests.util.wait import DEFAULT_WAIT_TIMEOUT
from crystal.ui.branding import AUTHORS_1_TEXT, AUTHORS_2_TEXT
from crystal.util.xos import is_wx_gtk
import textwrap
from unittest import SkipTest, skip
import wx


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

async def test_branding_area_shows_crystal_logo_and_program_name_and_version_number_and_authors() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Verify app icon is present
        app_icon = mw.main_window.FindWindow(name='cr-branding-area__icon')
        assert app_icon is not None, 'Should have app icon'
        assert isinstance(app_icon, wx.StaticBitmap)
        
        # Verify program name (Crystal) is present (either as bitmap or text)
        program_name_bitmap = mw.main_window.FindWindow(name='cr-branding-area__program-name-bitmap')
        program_name_text = mw.main_window.FindWindow(name='cr-branding-area__program-name-text')
        assert (program_name_bitmap is not None or program_name_text is not None), \
            'Should have program name (as bitmap or text)'
        
        # Verify version number is present
        version_label = mw.main_window.FindWindow(name='cr-branding-area__version')
        assert version_label is not None, 'Should have version label'
        assert isinstance(version_label, wx.StaticText)
        assert f'v{CRYSTAL_VERSION}' in version_label.GetLabel(), \
            f'Version label should contain v{CRYSTAL_VERSION}'
        
        # Verify author text is present
        authors_1 = mw.main_window.FindWindow(name='cr-branding-area__authors-1')
        assert authors_1 is not None, 'Should have authors-1 text'
        assert isinstance(authors_1, wx.StaticText)
        assert AUTHORS_1_TEXT.strip() in authors_1.GetLabel(), \
            f'Should display author text: {AUTHORS_1_TEXT}'
        
        # Verify contributors link is present
        authors_2 = mw.main_window.FindWindow(name='cr-branding-area__authors-2')
        assert authors_2 is not None, 'Should have contributors link'
        assert AUTHORS_2_TEXT in authors_2.GetLabel(), \
            f'Should display contributors link: {AUTHORS_2_TEXT}'


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
# (See "Logout Tests" in test_untitled_projects.py)


async def test_given_open_or_create_dialog_visible_when_os_logout_then_crystal_actually_quits() -> None:
    _simulate_logout_in_crystal_subprocess(open_main_window=False)


async def test_given_main_window_visible_when_os_logout_then_crystal_actually_quits() -> None:
    _simulate_logout_in_crystal_subprocess(open_main_window=True)


def _simulate_logout_in_crystal_subprocess(*, open_main_window: bool) -> None:
    if is_wx_gtk():
        # https://github.com/wxWidgets/wxWidgets/issues/17582
        raise SkipTest('wxGTK/Linux does not fire wx.EVT_END_SESSION')
    
    with crystal_shell() as (crystal, banner):
        # Simulate OS logout by firing wx.EVT_QUERY_END_SESSION and wx.EVT_END_SESSION events
        py_eval_await(crystal, textwrap.dedent(f'''\
            from crystal.tests.util.windows import OpenOrCreateDialog
            import wx
            
            async def simulate_os_logout():
                ocd = await OpenOrCreateDialog.wait_for()
                {'await ocd.create_and_leave_open()' if open_main_window else ''}
                
                app = wx.GetApp()
                
                # Fire wx.EVT_QUERY_END_SESSION event.
                # Should not be veto-ed for OpenOrCreateDialog.
                query_event = wx.CloseEvent(wx.EVT_QUERY_END_SESSION.typeId)
                app.ProcessEvent(query_event)
                if query_event.GetVeto():
                    raise AssertionError("EVT_QUERY_END_SESSION was veto-ed but should not have been")
                
                # Fire wx.EVT_END_SESSION event
                end_event = wx.CloseEvent(wx.EVT_END_SESSION.typeId)
                app.ProcessEvent(end_event)
            '''), 'simulate_os_logout')
        
        # Close the shell so that it doesn't prevent Crystal from exiting
        py_eval(crystal, 'exit()', stop_suffix='')
        
        # Ensure that the Crystal process quits cleanly
        wait_for_crystal_to_exit(crystal, timeout=4.0)  # 2.0 not long enough for macOS CI