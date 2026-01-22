from crystal.model import Alias, Resource, RootResource
from crystal.tests.util.asserts import assertIn, assertEqual
from crystal.tests.util.clipboard import FakeClipboard
from crystal.tests.util.mark import reacts_to_focus_changes
from crystal.tests.util.server import MockHttpServer
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util.tasks import wait_for_download_task_to_start_and_finish
from crystal.tests.util.wait import first_child_of_tree_item_is_not_loading_condition, wait_for
from crystal.tests.util.windows import OpenOrCreateDialog, NewAliasDialog
from crystal.util.controls import click_button, TreeItem
from crystal.util.wx_dialog import mocked_show_modal
from crystal.util.wx_window import SetFocus
from textwrap import dedent
from unittest.mock import patch
import wx


# === Test: Create & Delete ===

@awith_subtests
async def test_can_create_alias(subtests: SubtestsContext) -> None:
    """Test that aliases can be created and appear in the entity tree."""
    with subtests.test(layer='model'):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Initially empty entity tree
            assert mw.entity_tree.is_empty_state_visible(), \
                'Should start in empty state'
            
            with subtests.test(target_is_external=False):
                # Create an alias with internal target
                alias = Alias(
                    project,
                    'https://www.example.com/',
                    'https://example.com/',
                    target_is_external=False
                )
                
                # Entity tree should now be visible (not empty)
                assert not mw.entity_tree.is_empty_state_visible(), \
                    'Should enter non-empty state after adding alias'
                
                # Verify alias appears in entity tree
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                (alias_ti,) = root_ti.Children
                
                # Verify label format
                assertEqual(
                    'https://www.example.com/** → https://example.com/**',
                    alias_ti.Text)
                
                # Clean up for next subtest
                alias.delete()
            
            with subtests.test(target_is_external=True):
                # Create an alias with external target
                alias = Alias(
                    project,
                    'https://archive.example.com/',
                    'https://live.example.com/',
                    target_is_external=True
                )
                
                # Verify alias appears in entity tree with globe icon
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                (alias_ti,) = root_ti.Children
                
                # Verify label format includes globe icon
                assertEqual(
                    'https://archive.example.com/** → 🌐 https://live.example.com/**',
                    alias_ti.Text)
    
    with subtests.test(layer='ui'):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Initially empty entity tree
            assert mw.entity_tree.is_empty_state_visible(), \
                'Should start in empty state'
            
            # Create an alias using the NewAliasDialog
            if True:
                await mw.start_new_alias_with_menuitem()
                nad = await NewAliasDialog.wait_for()
                
                nad.source_url_prefix_field.Value = 'https://www.example.com/'
                nad.target_url_prefix_field.Value = 'https://example.com/'
                
                assert nad.ok_button is not None and nad.ok_button.Enabled, \
                    'OK button should be enabled when both fields are filled'
                
                await nad.ok()
            
            # Entity tree should now be visible (not empty)
            assert not mw.entity_tree.is_empty_state_visible(), \
                'Should enter non-empty state after adding alias'
            
            # Verify alias appears in entity tree
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            (alias_ti,) = root_ti.Children
            
            # Verify label format
            assertEqual(
                'https://www.example.com/** → https://example.com/**',
                alias_ti.Text)


@awith_subtests
async def test_can_forget_alias(subtests: SubtestsContext) -> None:
    """Test that aliases can be deleted and entity tree is updated."""
    with subtests.test(layer='model'):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create an alias
            alias = Alias(
                project,
                'https://temp.example.com/',
                'https://example.com/',
            )
            
            # Verify alias is in tree
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            assertEqual(1, len(root_ti.Children))
            
            # Delete the alias
            alias.delete()
            
            # Verify alias is removed from tree
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            assertEqual(0, len(root_ti.Children))
            
            # Entity tree should return to empty state
            assert mw.entity_tree.is_empty_state_visible(), \
                'Should return to empty state after deleting only entity'
    
    with subtests.test(layer='ui'):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create an alias
            alias = Alias(
                project,
                'https://temp.example.com/',
                'https://example.com/',
            )
            
            # Verify alias is in tree
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            assertEqual(1, len(root_ti.Children))
            (alias_ti,) = root_ti.Children
            
            # Select the alias and click Forget button
            alias_ti.SelectItem()
            assert mw.forget_button.Enabled, \
                'Forget button should be enabled when alias is selected'
            click_button(mw.forget_button)
            
            # Verify alias is removed from tree
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            assertEqual(0, len(root_ti.Children))
            
            # Entity tree should return to empty state
            assert mw.entity_tree.is_empty_state_visible(), \
                'Should return to empty state after deleting only entity'


async def test_resource_nodes_corresponding_to_external_urls_are_formatted_correctly() -> None:
    """
    Test that when a resource is aliased to an external URL,
    it displays with the globe icon (🌐) in the entity tree.
    """
    # Set up a mock server with HTML that links to a URL that will be aliased
    # to an external URL
    server = MockHttpServer({
        '/page.html': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <head>
                    <link rel="stylesheet" href="/external/style.css">
                </head>
                <body>
                    <h1>Test Page</h1>
                </body>
                </html>
                """
            ).strip().encode('utf-8')
        ),
    })
    with server:
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Get URLs from server
            page_url = server.get_url('/page.html')
            external_css_url = server.get_url('/external/style.css')
            
            # Create an alias that rewrites /external/* to an external URL
            alias = Alias(
                project,
                server.get_url('/external/'),
                'https://cdn.example.com/',
                target_is_external=True
            )
            
            # Create and download a root resource that links to the external URL
            home_r = Resource(project, page_url)
            home_rr = RootResource(project, 'Home', home_r)
            
            async with wait_for_download_task_to_start_and_finish(project):
                home_r.download()
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            home_ti = root_ti.find_child(page_url, project.default_url_prefix)
            home_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
            
            (hidden_embedded_ti,) = home_ti.Children
            assertEqual('(Hidden: Embedded)', hidden_embedded_ti.Text)
            hidden_embedded_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(hidden_embedded_ti))
            
            (external_css_ti,) = hidden_embedded_ti.Children
            assertIn('🌐 https://cdn.example.com/style.css', external_css_ti.Text)


# === Test: Rewrite URLs to End in Slash ===

@reacts_to_focus_changes
@awith_subtests
async def test_given_url_input_is_nonempty_when_blur_url_input_then_appends_slash_if_input_did_not_end_in_slash(subtests: SubtestsContext) -> None:
    """
    Test that when a URL field loses focus, a trailing slash is automatically
    appended if the field is non-empty and doesn't already end with a slash.
    """
    CASES = [
        ('https://example.com', 'https://example.com/'),
        ('https://example.com/', 'https://example.com/'),
        ('https://example.com/path', 'https://example.com/path/'),
        ('https://example.com/path/', 'https://example.com/path/'),
        ('http://example.com', 'http://example.com/'),
        ('ftp://example.com/dir', 'ftp://example.com/dir/'),
    ]
    
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Test source_url_prefix field
        for (input_value, expected_value) in CASES:
            with subtests.test(field='source_url_prefix', input=input_value):
                await mw.start_new_alias_with_menuitem()
                nad = await NewAliasDialog.wait_for()
                
                await wait_for(lambda: wx.Window.FindFocus() == nad.source_url_prefix_field)
                nad.source_url_prefix_field.Value = input_value
                # Simulate tab
                SetFocus(nad.target_url_prefix_field, nad.source_url_prefix_field)
                # Verify slash appended
                assertEqual(expected_value, nad.source_url_prefix_field.Value)
                
                await nad.cancel()
        
        # Test target_url_prefix field
        for (input_value, expected_value) in CASES:
            with subtests.test(field='target_url_prefix', input=input_value):
                await mw.start_new_alias_with_menuitem()
                nad = await NewAliasDialog.wait_for()
                
                SetFocus(nad.target_url_prefix_field, nad.source_url_prefix_field)
                nad.target_url_prefix_field.Value = input_value
                # Simulate tab
                SetFocus(nad.target_is_external_checkbox, nad.target_url_prefix_field)
                # Verify slash appended
                assertEqual(expected_value, nad.target_url_prefix_field.Value)
                
                await nad.cancel()


# === Test: Disallow Create Empty Alias ===

@awith_subtests
async def test_given_any_url_input_is_empty_then_ok_button_is_disabled(subtests: SubtestsContext) -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        with subtests.test(case='both_empty'):
            await mw.start_new_alias_with_menuitem()
            nad = await NewAliasDialog.wait_for()
            
            assertEqual('', nad.source_url_prefix_field.Value)
            assertEqual('', nad.target_url_prefix_field.Value)
            assert not nad.ok_button.Enabled
            
            await nad.cancel()
        
        with subtests.test(case='source_empty'):
            await mw.start_new_alias_with_menuitem()
            nad = await NewAliasDialog.wait_for()
            
            nad.target_url_prefix_field.Value = 'https://example.com/'
            assert not nad.ok_button.Enabled
            
            await nad.cancel()
        
        with subtests.test(case='target_empty'):
            await mw.start_new_alias_with_menuitem()
            nad = await NewAliasDialog.wait_for()
            
            nad.source_url_prefix_field.Value = 'https://example.com/'
            assert not nad.ok_button.Enabled
            
            await nad.cancel()


async def test_given_any_url_input_is_empty_when_all_url_inputs_becomes_nonempty_then_ok_button_is_enabled() -> None:
    """
    Test that the OK button becomes enabled when all URL fields are filled,
    starting from a state where at least one field was empty.
    """
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        await mw.start_new_alias_with_menuitem()
        nad = await NewAliasDialog.wait_for()
        
        assertEqual('', nad.source_url_prefix_field.Value)
        assertEqual('', nad.target_url_prefix_field.Value)
        assert not nad.ok_button.Enabled
        
        nad.source_url_prefix_field.Value = 'https://www.example.com/'
        assert not nad.ok_button.Enabled
        
        nad.target_url_prefix_field.Value = 'https://example.com/'
        assert nad.ok_button.Enabled
        
        await nad.cancel()


@awith_subtests
async def test_given_all_url_inputs_are_nonempty_when_any_url_input_becomes_empty_then_ok_button_is_disabled(subtests: SubtestsContext) -> None:
    """
    Test that the OK button becomes disabled when any URL field is cleared,
    starting from a state where all fields were filled.
    """
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        with subtests.test(case='clear_source'):
            await mw.start_new_alias_with_menuitem()
            nad = await NewAliasDialog.wait_for()
            
            nad.source_url_prefix_field.Value = 'https://www.example.com/'
            nad.target_url_prefix_field.Value = 'https://example.com/'
            assert nad.ok_button.Enabled
            
            nad.source_url_prefix_field.Value = ''
            assert not nad.ok_button.Enabled
            
            await nad.cancel()
        
        with subtests.test(case='clear_target'):
            await mw.start_new_alias_with_menuitem()
            nad = await NewAliasDialog.wait_for()
            
            nad.source_url_prefix_field.Value = 'https://www.example.com/'
            nad.target_url_prefix_field.Value = 'https://example.com/'
            assert nad.ok_button.Enabled
            
            nad.target_url_prefix_field.Value = ''
            assert not nad.ok_button.Enabled
            
            await nad.cancel()


# === Test: Disallow Create Duplicate Alias ===

async def test_given_source_url_input_matches_existing_alias_when_press_ok_then_displays_error_dialog() -> None:
    """
    Test that trying to create an alias with a source URL prefix that already
    exists shows an error dialog and keeps the NewAliasDialog open.
    """
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Create an existing alias
        existing_alias = Alias(
            project,
            'https://www.example.com/',
            'https://example.com/',
        )
        
        # Try to create another alias with the same source URL prefix
        await mw.start_new_alias_with_menuitem()
        nad = await NewAliasDialog.wait_for()
        
        nad.source_url_prefix_field.Value = 'https://www.example.com/'
        nad.target_url_prefix_field.Value = 'https://different.example.com/'
        assert nad.ok_button.Enabled
        
        with patch(
                'crystal.browser.new_alias.ShowModal',
                mocked_show_modal('cr-alias-exists-dialog', wx.ID_OK)
                ) as show_modal_method:
            await nad.ok(wait_for_dismiss=False)
            assert 1 == show_modal_method.call_count
        
        await nad.cancel()


# === Test: Copy ===

@awith_subtests
async def test_when_press_copy_button_beside_url_input_then_copies_url(subtests: SubtestsContext) -> None:
    """
    Test that clicking the copy button beside either URL field copies the
    URL to the clipboard.
    """
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        with subtests.test(field='source_url_prefix'):
            await mw.start_new_alias_with_menuitem()
            nad = await NewAliasDialog.wait_for()
            
            test_url = 'https://www.example.com/'
            nad.source_url_prefix_field.Value = test_url
            
            with FakeClipboard() as clipboard:
                click_button(nad.source_url_prefix_copy_button)
                assertEqual(test_url, clipboard.text)
            
            await nad.cancel()
        
        with subtests.test(field='target_url_prefix'):
            await mw.start_new_alias_with_menuitem()
            nad = await NewAliasDialog.wait_for()
            
            test_url = 'https://example.com/'
            nad.target_url_prefix_field.Value = test_url
            
            with FakeClipboard() as clipboard:
                click_button(nad.target_url_prefix_copy_button)
                assertEqual(test_url, clipboard.text)
            
            await nad.cancel()
