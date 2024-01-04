from crystal.tests.util.controls import click_button, TreeItem
from crystal.tests.util.server import served_project
from crystal.tests.util.tasks import wait_for_download_to_start_and_finish
from crystal.tests.util.wait import (
    first_child_of_tree_item_is_not_loading_condition,
    wait_for,
)
from crystal.tests.util.windows import (
    AddGroupDialog, AddUrlDialog, EntityTree, OpenOrCreateDialog,
)
from crystal.util.xos import is_windows
import re
from unittest import skip


# === Test: Create & Delete Standalone ===

async def test_can_create_group_with_source(*, with_source: bool=True) -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            assert root_ti is not None
            () = root_ti.Children
            
            # If will need a source later, create one now
            if with_source:
                assert mw.add_url_button.Enabled
                click_button(mw.add_url_button)
                aud = await AddUrlDialog.wait_for()
                
                aud.name_field.Value = 'Home'
                aud.url_field.Value = home_url
                await aud.ok()
            
            # Create a group
            if True:
                # Ensure nothing selected
                if not is_windows():
                    selected_ti = TreeItem.GetSelection(mw.entity_tree.window)
                    assert (selected_ti is None) or (selected_ti == root_ti)
                
                assert mw.add_group_button.Enabled
                click_button(mw.add_group_button)
                agd = await AddGroupDialog.wait_for()
                
                # Ensure prepopulates reasonable information
                if not is_windows():
                    assert '' == agd.pattern_field.Value
                    assert '' == agd.name_field.Value
                    assert None == agd.source
                else:
                    # Windows appears to have some kind of race condition that
                    # sometimes causes the Home tree item to be selected initially
                    assert agd.pattern_field.Value in ['', home_url]
                    assert agd.name_field.Value in ['', 'Home']
                    assert None == agd.source
                assert agd.pattern_field.HasFocus  # default focused field
                
                # Input new URL pattern with wildcard, to match comics
                agd.pattern_field.Value = comic_pattern
                
                # Ensure preview members show the new matching URLs (i.e. none)
                member_urls = [
                    agd.preview_members_list.GetString(i)
                    for i in range(agd.preview_members_list.GetCount())
                ]
                assert [] == member_urls  # no comics discovered yet
                
                if with_source:
                    agd.source = 'Home'
                agd.name_field.Value = 'Comic'
                await agd.ok()
                
                # Ensure appearance is correct
                (comic_ti,) = [
                    child for child in root_ti.Children
                    if child.Text.startswith(f'{comic_pattern} - ')
                ]
                assert f'{comic_pattern} - Comic' == comic_ti.Text
                await _assert_tree_item_icon_tooltip_contains(comic_ti, 'Group')
                
                # Currently, an entirely new group is NOT selected automatically.
                # This behavior might be changed in the future.
                if not is_windows():
                    selected_ti = TreeItem.GetSelection(mw.entity_tree.window)
                    assert (selected_ti is None) or (selected_ti == root_ti)
            
            # Forget group
            if True:
                comic_ti.SelectItem()
                assert mw.forget_button.IsEnabled()
                click_button(mw.forget_button)
                
                # Ensure cannot find group
                () = [
                    child for child in root_ti.Children
                    if child.Text.startswith(f'{comic_pattern} - ')
                ]
                if not is_windows():
                    selected_ti = TreeItem.GetSelection(mw.entity_tree.window)
                    assert (selected_ti is None) or (selected_ti == root_ti)


async def test_can_create_group_with_no_source() -> None:
    await test_can_create_group_with_source(with_source=False)


@skip('covered by: test_can_create_group_with_source')
async def test_can_forget_group() -> None:
    pass


@skip('not yet automated')
async def test_when_forget_group_then_related_root_urls_and_revisions_are_not_deleted() -> None:
    pass


# === Test: Create & Delete from Links ===

async def test_given_resource_node_with_multiple_link_children_matching_url_pattern_can_create_new_group_to_bundle_those_links_together() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        if True:
            home_url = sp.get_request_url('https://xkcd.com/')
            
            comic1_url = sp.get_request_url('https://xkcd.com/1/')
            comic2_url = sp.get_request_url('https://xkcd.com/2/')
            comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
            # Create home URL
            if True:
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                assert root_ti is not None
                () = root_ti.Children
                
                assert mw.add_url_button.Enabled
                click_button(mw.add_url_button)
                aud = await AddUrlDialog.wait_for()
                
                aud.name_field.Value = 'Home'
                aud.url_field.Value = home_url
                await aud.ok()
                (home_ti,) = root_ti.Children
            
            # Expand home URL
            home_ti.Expand()
            await wait_for_download_to_start_and_finish(mw.task_tree)
            assert first_child_of_tree_item_is_not_loading_condition(home_ti)()
            
            # Select a comic link from the home URL
            (comic1_ti,) = [
                child for child in home_ti.Children
                if child.Text.startswith(f'{comic1_url} - ')
            ]  # ensure did find sub-resource for Comic #1
            assert f'{comic1_url} - Link: |<, Link: |<' == comic1_ti.Text  # ensure expected links grouped
            comic1_ti.SelectItem()
            
            # Create a group to bundle the comic links together
            if True:
                assert mw.add_group_button.Enabled
                click_button(mw.add_group_button)
                agd = await AddGroupDialog.wait_for()
                
                # Ensure prepopulates reasonable information
                assert comic1_url == agd.pattern_field.Value  # default pattern = (from resource)
                assert '|<' == agd.name_field.Value  # default name = (from first text link)
                assert 'Home' == agd.source  # default source = (from resource parent)
                assert agd.pattern_field.HasFocus  # default focused field
                
                # Ensure preview members show the 1 URL
                assert (
                    agd.preview_members_pane is None or  # always expanded
                    agd.preview_members_pane.IsExpanded()  # expanded by default
                )
                member_urls = [
                    agd.preview_members_list.GetString(i)
                    for i in range(agd.preview_members_list.GetCount())
                ]
                assert [comic1_url] == member_urls  # contains exact match of pattern
                
                # Input new URL pattern with wildcard, to match other comics
                agd.pattern_field.Value = comic_pattern
                
                # Ensure preview members show the new matching URLs
                member_urls = [
                    agd.preview_members_list.GetString(i)
                    for i in range(agd.preview_members_list.GetCount())
                ]
                assert comic1_url in member_urls  # contains first comic
                assert len(member_urls) >= 2  # contains last comic too
                
                # Input new name
                agd.name_field.Value = 'Comic'
                
                await agd.ok()
            
            # 1. Ensure the new resource group does now bundle the comic links together
            # 2. Ensure the bundled link is selected immediately after closing the add group dialog
            if True:
                (grouped_subresources_ti,) = [
                    child for child in home_ti.Children
                    if child.Text.startswith(f'{comic_pattern} - ')
                ]  # ensure did find grouped sub-resources
                assert re.fullmatch(
                    rf'{re.escape(comic_pattern)} - \d+ of Comic',  # title format of grouped sub-resources
                    grouped_subresources_ti.Text)
                
                # Ensure the bundled link is selected immediately after closing the add group dialog
                assert grouped_subresources_ti.IsExpanded()
                (comic1_ti,) = [
                    child for child in grouped_subresources_ti.Children
                    if child.Text.startswith(f'{comic1_url} - ')
                ]  # contains first comic
                assert len(grouped_subresources_ti.Children) >= 2  # contains last comic too
                assert comic1_ti.IsSelected()
            
            # Forget the group to unbundle the links
            if True:
                grouped_subresources_ti.SelectItem()
                assert mw.forget_button.IsEnabled()
                click_button(mw.forget_button)
                
                # 1. Ensure can find the first unbundled link
                # 2. Ensure that first unbundled link is selected immediately after forgetting the group
                (comic1_ti,) = [
                    child for child in home_ti.Children
                    if child.Text.startswith(f'{comic1_url} - ')
                ]  # ensure did find sub-resource for Comic #1
                assert comic1_ti.IsSelected()


@skip('covered by: test_given_resource_node_with_multiple_link_children_matching_url_pattern_can_create_new_group_to_bundle_those_links_together')
async def test_given_resource_node_with_multiple_link_children_bundled_as_a_group_can_easily_forget_the_group_to_unbundle_the_links() -> None:
    pass


# === Utility ===

# NOTE: Only for use with tree items in EntityTree
_assert_tree_item_icon_tooltip_contains = EntityTree.assert_tree_item_icon_tooltip_contains
