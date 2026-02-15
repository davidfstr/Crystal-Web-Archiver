"""
Tests preferences in the PreferencesDialog.
"""

from collections.abc import Callable
from crystal.app_preferences import app_prefs
from crystal.model import Project, Resource, ResourceRevision as RR
from crystal.tests.model.test_project_migrate import project_opened_without_migrating
from crystal.tests.util.asserts import assertEqual
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import extracted_project
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util.windows import MainWindow, OpenOrCreateDialog
from crystal.util.controls import click_button, click_radio_button
from crystal.util.features import feature_enabled
from crystal.util.wx_dialog import mocked_show_modal
from crystal.util.xtyping import not_none
from io import BytesIO
from unittest import skip
from unittest.mock import patch
import wx


# === Test: Project Preferences ===

@skip('covered by: test_uses_html_parser_specified_in_preferences, test_uses_html_parser_parser_for_classic_projects')
def test_html_parser_saves_and_loads_correctly() -> None:
    pass


# === Test: Project Preferences: Revision Storage Format ===

@awith_subtests
async def test_preferences_dialog_shows_current_revision_storage_format(subtests: SubtestsContext) -> None:
    with subtests.test(major_version=1):  # Flat
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
            async with project_opened_without_migrating(project_dirpath) as (mw, project):
                assertEqual(1, project.major_version)

                prefs = await mw.open_preferences_with_menuitem()
                assertEqual('Flat', prefs.revision_format_label.Label)
                assert prefs.migrate_checkbox is not None
                assert 'Hierarchical' in prefs.migrate_checkbox.Label
                assert prefs.migrate_checkbox.Enabled == True
                await prefs.cancel()

    with subtests.test(major_version=2):  # Hierarchical
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                assertEqual(2, project.major_version)

                prefs = await mw.open_preferences_with_menuitem()
                assertEqual('Hierarchical', prefs.revision_format_label.Label)
                assert prefs.migrate_checkbox is not None
                assert 'Pack16' in prefs.migrate_checkbox.Label
                assert prefs.migrate_checkbox.Enabled == True
                await prefs.cancel()

    with subtests.test(major_version=3):  # Pack16
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            project._set_major_version_for_test(3)

            prefs = await mw.open_preferences_with_menuitem()
            assertEqual('Pack16', prefs.revision_format_label.Label)
            assert prefs.migrate_checkbox is None
            await prefs.cancel()


@awith_subtests
async def test_given_hierarchical_project_when_migrate_to_pack16_via_preferences_and_user_confirms_then_migration_completes(subtests: SubtestsContext) -> None:
    def setup_project_with_revisions(project1: Project) -> None:
        for i in range(1, 21):
            resource = Resource(project1, f'http://example.com/migrate/{i}')
            RR.create_from_response(
                resource,
                metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                body_stream=BytesIO(f'body {i}'.encode()),
            )
    
    async def start_migration_via_preferences(mw: MainWindow) -> None:
        prefs = await mw.open_preferences_with_menuitem()
        assert prefs.migrate_checkbox is not None
        prefs.migrate_checkbox.Value = True

        with patch(
                'crystal.browser.preferences.ShowModal',
                mocked_show_modal('cr-migrate-to-pack16-warning', wx.ID_OK)):
            await prefs.ok()
        
        # HACK: Wait minimum duration to allow open to finish
        await bg_sleep(0.5)
    
    async def continue_migration_after_reopen_and_verify_revisions(
            project1: Project,
            *, pre_verify: Callable[[Project], None] | None = None,
            ) -> None:
        # Wait for new main window to appear after migration.
        # NOTE: No second dialog appears on project reopen since migration is
        #       already in progress. User already confirmed the desire to start
        #       the migration via Preferences.
        mw2 = await MainWindow.wait_for()
        try:
            project2 = Project._last_opened_project
            assert project2 is not None
            assert project2 is not project1, 'Expected project to be reopened'
            
            assertEqual(3, project2.major_version)
            assert project2._get_property('major_version_old', None) is None, \
                'major_version_old should be removed after migration completes'
            
            if pre_verify is not None:
                pre_verify(project2)

            # Verify all revisions are still readable
            for i in range(1, 21):
                resource = not_none(project2.get_resource(url=f'http://example.com/migrate/{i}'))
                revision = resource.default_revision()
                assert revision is not None
                with revision.open() as f:
                    assertEqual(f'body {i}'.encode(), f.read())
        finally:
            await mw2.close()
    
    # Case 1: Titled Project
    with subtests.test(is_untitled=False):
        # Create titled project
        async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project1):
            project_dirpath = project1.path
            assertEqual(2, project1.major_version)

            setup_project_with_revisions(project1)

        # Reopen titled project and trigger migration
        async with (await OpenOrCreateDialog.wait_for()).open(
                project_dirpath, autoclose=False) as (mw, project1):
            assertEqual(2, project1.major_version)

            await start_migration_via_preferences(mw)

        await continue_migration_after_reopen_and_verify_revisions(project1)
    
    # Case 2: Untitled Project
    with subtests.test(is_untitled=True):
        # Create untitled project and trigger migration
        async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw, project1):
            assertEqual(2, project1.major_version)
            assertEqual(True, project1.is_untitled)
            
            setup_project_with_revisions(project1)
            
            await start_migration_via_preferences(mw)
            
            await continue_migration_after_reopen_and_verify_revisions(
                project1,
                pre_verify=lambda project2: assertEqual(True, project2.is_untitled),
            )


async def test_given_hierarchical_project_when_migrate_to_pack16_via_preferences_and_cancel_warning_then_no_migration() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            assertEqual(2, project.major_version)

            prefs = await mw.open_preferences_with_menuitem()
            assert prefs.migrate_checkbox is not None
            prefs.migrate_checkbox.Value = True

            # Click OK. The warning dialog appears but user cancels it.
            with patch(
                    'crystal.browser.preferences.ShowModal',
                    mocked_show_modal('cr-migrate-to-pack16-warning', wx.ID_CANCEL)):
                click_button(prefs.ok_button)

            # Preferences dialog should still be open (user cancelled the warning)
            assert prefs._dialog.IsShown()

            # Close preferences normally
            await prefs.cancel()

            # Verify project was NOT migrated
            assertEqual(2, project.major_version)


# TODO: Add 1 confirmation dialog before starting migration
async def test_given_flat_project_when_migrate_to_hierarchical_via_preferences_then_migration_completes() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        # Open project without migrating (stays at v1)
        async with project_opened_without_migrating(project_dirpath) as (mw, project1):
            assertEqual(1, project1.major_version)

        # Reopen without migrating and trigger migration via preferences.
        # NOTE: Initial open doesn't migrate because of project_opened_without_migrating
        #       but the *reopen* after starting the migration SHOULD migrate
        async with project_opened_without_migrating(project_dirpath, autoclose=False) as (mw, project1):
            assertEqual(1, project1.major_version)

            prefs = await mw.open_preferences_with_menuitem()
            assert prefs.migrate_checkbox is not None
            prefs.migrate_checkbox.Value = True

            # No warning dialog for v1->v2; just press OK
            await prefs.ok()
        
        # HACK: Wait minimum duration to allow open to finish
        await bg_sleep(0.5)

        # Wait for new window to appear after migration
        mw2 = await MainWindow.wait_for()
        try:
            project2 = Project._last_opened_project
            assert project2 is not None
            assert project2 is not project1, 'Expected project to be reopened'

            assert project2.major_version >= 2, \
                'Expected project to be upgraded'
        finally:
            await mw2.close()


# === Test: Session Preferences ===

# (TODO: Add stubs)


# === Test: Application Preferences: Proxy ===

@feature_enabled('Proxy')
async def test_given_preferences_dialog_when_no_proxy_selected_then_socks5_fields_disabled() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            prefs = await mw.open_preferences_with_menuitem()

            # Verify "No proxy" is selected by default
            assert prefs.no_proxy_radio.Value == True

            # Verify SOCKS v5 fields are disabled
            assert prefs.socks5_host_field.Enabled == False
            assert prefs.socks5_port_field.Enabled == False

            await prefs.cancel()


@feature_enabled('Proxy')
async def test_given_preferences_dialog_when_socks5_selected_then_socks5_fields_enabled() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            prefs = await mw.open_preferences_with_menuitem()

            # Select SOCKS v5 proxy
            click_radio_button(prefs.socks5_proxy_radio)

            # Verify SOCKS v5 fields are now enabled
            assert prefs.socks5_host_field.Enabled == True
            assert prefs.socks5_port_field.Enabled == True

            await prefs.cancel()


@feature_enabled('Proxy')
async def test_given_preferences_dialog_when_socks5_configured_then_preferences_saved() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            prefs = await mw.open_preferences_with_menuitem()

            # Configure SOCKS v5 proxy
            click_radio_button(prefs.socks5_proxy_radio)
            prefs.socks5_host_field.Value = 'localhost'
            prefs.socks5_port_field.Value = '1080'
            await prefs.ok()

            # Verify preferences were saved
            assert app_prefs.proxy_type == 'socks5'
            assert app_prefs.socks5_proxy_host == 'localhost'
            assert app_prefs.socks5_proxy_port == 1080


@feature_enabled('Proxy')
async def test_given_preferences_dialog_when_socks5_preferences_exist_then_loaded_correctly() -> None:
    # Set up proxy preferences
    app_prefs.proxy_type = 'socks5'
    app_prefs.socks5_proxy_host = '192.168.1.100'
    app_prefs.socks5_proxy_port = 9050

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            prefs = await mw.open_preferences_with_menuitem()

            # Verify preferences are loaded
            assert prefs.socks5_proxy_radio.Value == True
            assert prefs.socks5_host_field.Value == '192.168.1.100'
            assert prefs.socks5_port_field.Value == '9050'

            # Verify fields are enabled
            assert prefs.socks5_host_field.Enabled == True
            assert prefs.socks5_port_field.Enabled == True

            await prefs.cancel()


@feature_enabled('Proxy')
async def test_given_preferences_dialog_when_invalid_port_then_port_cleared() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            prefs = await mw.open_preferences_with_menuitem()

            # Configure SOCKS v5 proxy with invalid port
            click_radio_button(prefs.socks5_proxy_radio)
            prefs.socks5_host_field.Value = 'localhost'
            prefs.socks5_port_field.Value = '999999'  # Invalid: too large
            await prefs.ok()

            # Verify port was cleared due to being invalid
            assert app_prefs.proxy_type == 'socks5'
            assert app_prefs.socks5_proxy_host == 'localhost'
            assert app_prefs.socks5_proxy_port_is_set == False


@feature_enabled('Proxy')
async def test_given_preferences_dialog_then_http_proxy_option_is_disabled() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            prefs = await mw.open_preferences_with_menuitem()

            assert prefs.http_proxy_radio.Enabled == False

            await prefs.cancel()


# === Test: Application Preferences: Other ===

@skip('covered by: test_can_reset_permanent_dismissal_from_preferences_dialog')
def test_reset_dismissed_help_messages_button_works() -> None:
    pass
