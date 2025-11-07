"""
Tests preferences in the PreferencesDialog.
"""

from crystal.app_preferences import app_prefs
from crystal.tests.util.controls import click_radio_button
from crystal.tests.util.server import extracted_project
from crystal.tests.util.windows import OpenOrCreateDialog
from unittest import skip


# === Test: Project Preferences ===

@skip('covered by: test_uses_html_parser_specified_in_preferences, test_uses_html_parser_parser_for_classic_projects')
def test_html_parser_saves_and_loads_correctly() -> None:
    pass


# === Test: Session Preferences ===

# (TODO: Add stubs)


# === Test: Application Preferences: Proxy ===

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
