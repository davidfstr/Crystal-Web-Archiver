from crystal.model import Project, Resource, RootResource, ResourceGroup
from crystal.tests.util.asserts import assertEqual
from crystal.tests.util.controls import click_button, TreeItem
from crystal.tests.util.server import served_project
from crystal.tests.util.tasks import wait_for_download_to_start_and_finish
from crystal.tests.util.wait import (
    first_child_of_tree_item_is_not_loading_condition,
    wait_for,
)
from crystal.tests.util.windows import (
    AddGroupDialog, AddUrlDialog, EntityTree, MainWindow, OpenOrCreateDialog,
)
from crystal.util.xos import is_windows
import re
from typing import Optional
from unittest import skip
from urllib.parse import urlparse


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


# === Test: Suggested Source when Create from Selection ===

async def test_given_node_is_selected_in_entity_tree_when_press_new_group_button_then_dialog_appears_with_reasonable_suggested_source() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        if True:
            home_url = sp.get_request_url('https://xkcd.com/')
            about_url = sp.get_request_url('https://xkcd.com/about')
            archive_url = sp.get_request_url('https://xkcd.com/archive')
            twitter_url = sp.get_request_url('https://twitter.com/xkcd/')
            stylesheet_url = sp.get_request_url('https://xkcd.com/s/7d94e0.css')
            
            comic1_url = sp.get_request_url('https://xkcd.com/1/')
            comic2_url = sp.get_request_url('https://xkcd.com/2/')
            comic_pattern = sp.get_request_url('https://xkcd.com/#/')
            
            atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
            rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
            feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
            project = Project._last_opened_project
            assert project is not None
            
            # Create entities, which will appear in Entity Tree
            if True:
                home_rr = RootResource(project, 'Home', Resource(project, home_url))
                RootResource(project, 'About', Resource(project, about_url))
                RootResource(project, 'Atom Feed', Resource(project, atom_feed_url))
                
                ResourceGroup(project, 'Feed', feed_pattern, source=None)
                ResourceGroup(project, 'Comic', comic_pattern, source=home_rr)
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            
            # Set Default URL Prefix so that Offsite clusters appear
            await mw.entity_tree.set_default_url_prefix_to_resource_at_tree_item(
                _find_child(root_ti, home_url))
            url_prefix = home_url
            
            # Locate related entity tree nodes
            if True:
                # Children of RootNode
                home_rrn = _find_child(root_ti, home_url, url_prefix)
                feed_rgn = _find_child(root_ti, feed_pattern, url_prefix)
                comic_rgn = _find_child(root_ti, comic_pattern, url_prefix)
                
                # Children of RootResourceNode (a kind of _ResourceNode) that is inside RootNode
                await _expand_node(home_rrn, mw, will_download=True)
                home_rrn__atom_feed_rrn = _find_child(
                    home_rrn, atom_feed_url, url_prefix)
                home_rrn__about_rrn = _find_child(
                    home_rrn, about_url, url_prefix)
                home_rrn__feed_glrn = _find_child(
                    home_rrn, feed_pattern, url_prefix)
                await _expand_node(home_rrn__feed_glrn)
                home_rrn__feed_glrn__atom_feed_rrn = _find_child(
                    home_rrn__feed_glrn, atom_feed_url, url_prefix)
                home_rrn__feed_glrn__rss_feed_lrn = _find_child(
                    home_rrn__feed_glrn, rss_feed_url, url_prefix)
                home_rrn__archive_lrn = _find_child(
                    home_rrn, archive_url, url_prefix)
                home_rrn__offsite_cn = _find_child_by_title(
                    home_rrn, 'Offsite')
                await _expand_node(home_rrn__offsite_cn)
                home_rrn__offsite_cn__twitter_lrn = _find_child(
                    home_rrn__offsite_cn, twitter_url, url_prefix)
                home_rrn__embedded_cn = _find_child_by_title(
                    home_rrn, 'Embedded')
                await _expand_node(home_rrn__embedded_cn)
                home_rrn__embedded_cn__stylesheet_lrn = _find_child(
                    home_rrn__embedded_cn, stylesheet_url, url_prefix)
                
                # Children of ResourceGroupNode
                await _expand_node(feed_rgn)
                feed_rgn__atom_feed_rrn = _find_child(
                    feed_rgn, atom_feed_url, url_prefix)
                feed_rgn__rss_feed_nrn = _find_child(
                    feed_rgn, rss_feed_url, url_prefix)
                
                # ---
                
                # Children of LinkedResourceNode (a kind of _ResourceNode) that is inside GroupedLinkedResourceNode
                await _expand_node(home_rrn__feed_glrn__rss_feed_lrn, mw, will_download=True)
                home_rrn__feed_glrn__rss_feed_lrn__home_rrn = _find_child(
                    home_rrn__feed_glrn__rss_feed_lrn, home_url, url_prefix)
                
                # Children of LinkedResourceNode (a kind of _ResourceNode) that is inside RootResourceNode
                # HACK: Relies on Crystal's "Not in Archive" page to provide a
                #       link to the original URL (which is offsite)
                await _expand_node(home_rrn__archive_lrn, mw)  # not in archive
                home_rrn__archive_lrn__offsite_cn = _find_child_by_title(
                    home_rrn__archive_lrn, 'Offsite')
                
                # Children of LinkedResourceNode (a kind of _ResourceNode) that is inside ClusterNode
                # HACK: Relies on Crystal's "Not in Archive" page to provide a
                #       link to the original URL (which is offsite)
                await _expand_node(home_rrn__offsite_cn__twitter_lrn, mw)  # not in archive
                home_rrn__offsite_cn__twitter_lrn__offsite_cn = _find_child_by_title(
                    home_rrn__offsite_cn__twitter_lrn, 'Offsite')
                await _expand_node(home_rrn__embedded_cn__stylesheet_lrn)  # already downloaded
                home_rrn__embedded_cn__stylesheet_lrn__embedded_cn = _find_child_by_title(
                    home_rrn__embedded_cn__stylesheet_lrn, 'Embedded')
                
                # ---
                
                # Children of NormalResourceNode (a kind of _ResourceNode) that is inside ResourceGroupNode
                await _expand_node(feed_rgn__rss_feed_nrn)
                feed_rgn__rss_feed_nrn__home_rrn = _find_child(
                    feed_rgn__rss_feed_nrn, home_url, url_prefix)
            
            # Ensure suggested source for each kind of node in the Entity Tree is reasonable
            if True:
                # Children of RootNode
                assertEqual(None, await _source_name_for_node(home_rrn, mw))
                assertEqual(None, await _source_name_for_node(feed_rgn, mw))  # = source of Feed group
                assertEqual('Home', await _source_name_for_node(comic_rgn, mw))  # = source of Comic group
                
                # Children of RootResourceNode (a kind of _ResourceNode) that is inside RootNode
                assertEqual('Home', await _source_name_for_node(home_rrn__atom_feed_rrn, mw))
                assertEqual('Home', await _source_name_for_node(home_rrn__about_rrn, mw))
                assertEqual('Home', await _source_name_for_node(home_rrn__feed_glrn, mw))
                assertEqual('Home', await _source_name_for_node(home_rrn__feed_glrn__atom_feed_rrn, mw))
                assertEqual('Home', await _source_name_for_node(home_rrn__feed_glrn__rss_feed_lrn, mw))
                assertEqual('Home', await _source_name_for_node(home_rrn__archive_lrn, mw))
                assertEqual('Home', await _source_name_for_node(home_rrn__offsite_cn, mw))
                assertEqual('Home', await _source_name_for_node(home_rrn__offsite_cn__twitter_lrn, mw))
                assertEqual('Home', await _source_name_for_node(home_rrn__embedded_cn, mw))
                assertEqual('Home', await _source_name_for_node(home_rrn__embedded_cn__stylesheet_lrn, mw))
                
                # Children of ResourceGroupNode
                assertEqual(None, await _source_name_for_node(feed_rgn__atom_feed_rrn, mw))  # = source of Feed group
                assertEqual(None, await _source_name_for_node(feed_rgn__rss_feed_nrn, mw))  # = source of Feed group
                
                # ---
                
                # Children of LinkedResourceNode (a kind of _ResourceNode) that is inside GroupedLinkedResourceNode
                assertEqual(None, await _source_name_for_node(home_rrn__feed_glrn__rss_feed_lrn__home_rrn, mw))
                
                # Children of LinkedResourceNode (a kind of _ResourceNode) that is inside RootResourceNode
                assertEqual(None, await _source_name_for_node(home_rrn__archive_lrn__offsite_cn, mw))
                
                # Children of LinkedResourceNode (a kind of _ResourceNode) that is inside ClusterNode
                assertEqual(None, await _source_name_for_node(home_rrn__offsite_cn__twitter_lrn__offsite_cn, mw))
                assertEqual(None, await _source_name_for_node(home_rrn__embedded_cn__stylesheet_lrn__embedded_cn, mw))
                
                # ---
                
                # Children of NormalResourceNode (a kind of _ResourceNode) that is inside ResourceGroupNode
                assertEqual('Feed', await _source_name_for_node(feed_rgn__rss_feed_nrn__home_rrn, mw))


async def _expand_node(node_ti: TreeItem, mw: Optional[MainWindow]=None, *, will_download: bool=False) -> None:
    node_ti.Expand()
    if will_download:
        if mw is None:
            raise ValueError('Need mw parameter when will_download=True')
        await wait_for_download_to_start_and_finish(
            mw.task_tree,
            stacklevel_extra=1)
    await wait_for(
        first_child_of_tree_item_is_not_loading_condition(node_ti),
        timeout=3.0,  # took 2.2s on Windows CI
        stacklevel_extra=1)


async def _source_name_for_node(node_ti: TreeItem, mw: MainWindow) -> Optional[str]:
    node_ti.SelectItem()
    
    click_button(mw.add_group_button)
    agd = await AddGroupDialog.wait_for()
    source_name = agd.source  # capture
    await agd.cancel()
    return source_name


# === Utility ===

# TODO: Consider moving this function to a test utility module and using it
#       everywhere in existing tests
def _find_child(parent_ti: TreeItem, url_or_url_pattern: str, url_prefix: Optional[str]=None) -> TreeItem:
    """
    Returns the first child of the specified parent tree item with the
    specified URL or URL pattern.
    
    Raises if such a child is not found.
    """
    if url_prefix is not None:
        assert url_prefix.endswith('/')
        if url_or_url_pattern.startswith(url_prefix):
            url_or_url_pattern = '/' + url_or_url_pattern[len(url_prefix):]  # reinterpret
    try:
        (matching_child_ti,) = [
            child for child in parent_ti.Children
            if child.Text.startswith(f'{url_or_url_pattern} - ')
        ]
    except ValueError:
        try:
            (matching_child_ti,) = [
                child for child in parent_ti.Children
                if child.Text == url_or_url_pattern
            ]
        except ValueError:
            raise AssertionError(
                f'Child {url_or_url_pattern} not found in specified TreeItem'
            ) from None
    return matching_child_ti


# TODO: Consider moving this function to a test utility module and using it
#       everywhere in existing tests
def _find_child_by_title(parent_ti: TreeItem, title_fragment: str) -> TreeItem:
    """
    Returns the first child of the specified parent tree item whose
    title contains the specified fragment.
    
    Raises if such a child is not found.
    """
    try:
        (matching_child_ti,) = [
            child for child in parent_ti.Children
            if title_fragment in child.Text
        ]
        return matching_child_ti
    except ValueError:
        raise AssertionError(
            f'Child with title fragment {title_fragment!r} not found in specified TreeItem'
        ) from None


# NOTE: Only for use with tree items in EntityTree
_assert_tree_item_icon_tooltip_contains = EntityTree.assert_tree_item_icon_tooltip_contains
