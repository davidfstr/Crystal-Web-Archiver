from collections.abc import Iterator
from contextlib import contextmanager
from crystal.model import Project, Resource, ResourceGroup, RootResource
from crystal.tests.util.asserts import assertEqual
from crystal.tests.util.controls import click_button, click_checkbox, TreeItem
from crystal.tests.util.server import MockHttpServer, served_project
from crystal.tests.util.ssd import database_on_ssd
from crystal.tests.util.tasks import wait_for_download_to_start_and_finish
from crystal.tests.util.wait import (
    first_child_of_tree_item_is_not_loading_condition,
    tree_has_no_children_condition, tree_item_has_no_children_condition,
    wait_for,
)
from crystal.tests.util.windows import (
    EntityTree, MainWindow, NewGroupDialog, NewRootUrlDialog,
    OpenOrCreateDialog,
)
from crystal.tests.util.xurlparse import urlpatternparse
from crystal.util.wx_dialog import mocked_show_modal
from crystal.util.xos import is_windows
import re
from unittest import skip
from unittest.mock import patch
import wx

# === Test: Create & Delete Standalone ===

async def test_can_create_group_with_source(
        *, with_source: bool=True,
        add_surrounding_whitespace: bool=False) -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            () = root_ti.Children
            
            # If will need a source later, create one now
            if with_source:
                assert mw.new_root_url_button.Enabled
                click_button(mw.new_root_url_button)
                nud = await NewRootUrlDialog.wait_for()
                
                nud.name_field.Value = 'Home'
                nud.url_field.Value = home_url
                nud.do_not_download_immediately()
                nud.do_not_set_default_url_prefix()
                await nud.ok()
                
                home_ti = root_ti.find_child(home_url)
            
            # Create a group
            if True:
                selected_ti = TreeItem.GetSelection(mw.entity_tree.window)
                if with_source:
                    # Ensure source selected
                    assert selected_ti == home_ti
                else:
                    # Ensure nothing selected
                    assert (selected_ti is None) or (selected_ti == root_ti)
                
                assert mw.new_group_button.Enabled
                click_button(mw.new_group_button)
                ngd = await NewGroupDialog.wait_for()
                
                # Ensure prepopulates reasonable information
                if with_source:
                    assert home_url == ngd.pattern_field.Value
                    assert 'Home' == ngd.name_field.Value
                    assert None == ngd.source
                else:
                    assert '' == ngd.pattern_field.Value
                    assert '' == ngd.name_field.Value
                    assert None == ngd.source
                assert ngd.pattern_field.HasFocus  # default focused field
                
                # Input new URL pattern with wildcard, to match comics
                ngd.pattern_field.Value = (
                    (' ' if add_surrounding_whitespace else '') +
                    comic_pattern +
                    (' ' if add_surrounding_whitespace else '')
                )
                
                # Ensure preview members show the new matching URLs (i.e. none)
                member_urls = [
                    ngd.preview_members_list.GetString(i)
                    for i in range(ngd.preview_members_list.GetCount())
                ]
                assert [] == member_urls  # no comics discovered yet
                
                if with_source:
                    ngd.source = 'Home'
                ngd.name_field.Value = 'Comic'
                await ngd.ok()
                
                # Ensure appearance is correct
                comic_ti = root_ti.find_child(comic_pattern)
                assert f'{comic_pattern} - Comic' == comic_ti.Text
                await _assert_tree_item_icon_tooltip_contains(comic_ti, 'Group')
                
                if not with_source:
                    # Ensure new group is selected automatically,
                    # given that nothing was previously selected
                    selected_ti = TreeItem.GetSelection(mw.entity_tree.window)
                    assert selected_ti == comic_ti
            
            # Forget group
            if True:
                comic_ti.SelectItem()
                assert mw.forget_button.IsEnabled()
                click_button(mw.forget_button)
                
                # Ensure cannot find group
                assert None == root_ti.try_find_child(comic_pattern)
                selected_ti = TreeItem.GetSelection(mw.entity_tree.window)
                if with_source and is_windows():
                    # Windows will retarget the selection to the remaining node at the root
                    assert selected_ti == home_ti
                else:
                    # Other platforms will retarget the selection to nothing
                    assert (selected_ti is None) or (selected_ti == root_ti)


async def test_can_create_group_with_no_source() -> None:
    await test_can_create_group_with_source(with_source=False)


async def test_cannot_create_group_with_empty_url_pattern() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
            assert mw.new_group_button.Enabled
            click_button(mw.new_group_button)
            ngd = await NewGroupDialog.wait_for()
            
            ngd.pattern_field.Value = ''
            ngd.name_field.Value = 'Comic'
            with patch(
                    'crystal.browser.new_group.ShowModal',
                    mocked_show_modal('cr-empty-url-pattern', wx.ID_OK)
                    ) as show_modal_method:
                click_button(ngd.ok_button)
                assert 1 == show_modal_method.call_count
            
            await ngd.cancel()


@skip('covered by: test_can_create_group_with_source')
async def test_can_forget_group() -> None:
    pass


@skip('not yet automated')
async def test_when_forget_group_then_related_root_urls_and_revisions_are_not_deleted() -> None:
    pass


async def test_given_url_pattern_with_surrounding_whitespace_when_create_group_then_surrounding_whitespace_ignored() -> None:
    await test_can_create_group_with_source(add_surrounding_whitespace=True)


# === Test: Create & Delete from Links ===

async def test_given_resource_node_with_multiple_link_children_matching_url_pattern_can_create_new_group_to_bundle_those_links_together() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        if True:
            home_url = sp.get_request_url('https://xkcd.com/')
            
            comic1_url = sp.get_request_url('https://xkcd.com/1/')
            comic2_url = sp.get_request_url('https://xkcd.com/2/')
            comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create home URL
            if True:
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                () = root_ti.Children
                
                assert mw.new_root_url_button.Enabled
                click_button(mw.new_root_url_button)
                nud = await NewRootUrlDialog.wait_for()
                
                nud.name_field.Value = 'Home'
                nud.url_field.Value = home_url
                nud.do_not_download_immediately()
                await nud.ok()
                (home_ti,) = root_ti.Children
            
            # Expand home URL
            home_ti.Expand()
            await wait_for_download_to_start_and_finish(mw.task_tree)
            assert first_child_of_tree_item_is_not_loading_condition(home_ti)()
            
            # Select a comic link from the home URL
            comic1_ti = home_ti.find_child(comic1_url, project.default_url_prefix)  # ensure did find sub-resource for Comic #1
            assert f'{urlpatternparse(comic1_url).path} - Link: |<, Link: |<' == comic1_ti.Text  # ensure expected links grouped
            comic1_ti.SelectItem()
            
            # Create a group to bundle the comic links together
            if True:
                assert mw.new_group_button.Enabled
                click_button(mw.new_group_button)
                ngd = await NewGroupDialog.wait_for()
                
                # Ensure prepopulates reasonable information
                assert comic1_url == ngd.pattern_field.Value  # default pattern = (from resource)
                assert '|<' == ngd.name_field.Value  # default name = (from first text link)
                assert 'Home' == ngd.source  # default source = (from resource parent)
                assert ngd.pattern_field.HasFocus  # default focused field
                
                # Ensure preview members show the 1 URL
                assert (
                    ngd.preview_members_pane is None or  # always expanded
                    ngd.preview_members_pane.IsExpanded()  # expanded by default
                )
                member_urls = [
                    ngd.preview_members_list.GetString(i)
                    for i in range(ngd.preview_members_list.GetCount())
                ]
                assert [comic1_url] == member_urls  # contains exact match of pattern
                
                # Input new URL pattern with wildcard, to match other comics
                ngd.pattern_field.Value = comic_pattern
                
                # Ensure preview members show the new matching URLs
                member_urls = [
                    ngd.preview_members_list.GetString(i)
                    for i in range(ngd.preview_members_list.GetCount())
                ]
                assert comic1_url in member_urls  # contains first comic
                assert len(member_urls) >= 2  # contains last comic too
                
                # Input new name
                ngd.name_field.Value = 'Comic'
                
                await ngd.ok()
            
            # 1. Ensure the new resource group does now bundle the comic links together
            # 2. Ensure the bundled link is selected immediately after closing the add group dialog
            if True:
                grouped_subresources_ti = home_ti.find_child(comic_pattern, project.default_url_prefix)  # ensure did find grouped sub-resources
                assert re.fullmatch(
                    rf'{re.escape(urlpatternparse(comic_pattern).path)} - \d+ of Comic',  # title format of grouped sub-resources
                    grouped_subresources_ti.Text)
                
                # Ensure the bundled link is selected immediately after closing the add group dialog
                assert grouped_subresources_ti.IsExpanded()
                comic1_ti = grouped_subresources_ti.find_child(comic1_url, project.default_url_prefix)  # contains first comic
                assert len(grouped_subresources_ti.Children) >= 2  # contains last comic too
                assert comic1_ti.IsSelected()
            
            # Download the group to download the links
            if True:
                grouped_subresources_ti.SelectItem()
                assert mw.download_button.IsEnabled()
                await mw.click_download_button()
                await wait_for_download_to_start_and_finish(mw.task_tree)
            
            # Forget the group to unbundle the links
            if True:
                grouped_subresources_ti.SelectItem()
                assert mw.forget_button.IsEnabled()
                click_button(mw.forget_button)
                
                # 1. Ensure can find the first unbundled link
                # 2. Ensure that first unbundled link is selected immediately after forgetting the group
                comic1_ti = home_ti.find_child(comic1_url, project.default_url_prefix)  # ensure did find sub-resource for Comic #1
                assert comic1_ti.IsSelected()


@skip('covered by: test_given_resource_node_with_multiple_link_children_matching_url_pattern_can_create_new_group_to_bundle_those_links_together')
async def test_given_resource_node_with_multiple_link_children_bundled_as_a_group_can_easily_download_the_group_to_download_the_links() -> None:
    pass


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
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create entities, which will appear in Entity Tree
            if True:
                home_rr = RootResource(project, 'Home', Resource(project, home_url))
                RootResource(project, 'About', Resource(project, about_url))
                RootResource(project, 'Atom Feed', Resource(project, atom_feed_url))
                
                ResourceGroup(project, 'Feed', feed_pattern, source=None)
                ResourceGroup(project, 'Comic', comic_pattern, source=home_rr)
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            
            # Set Default URL Prefix so that Offsite clusters appear
            await mw.entity_tree.set_default_directory_to_entity_at_tree_item(
                _find_child(root_ti, home_url))
            url_prefix = project.default_url_prefix
            
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


async def _expand_node(node_ti: TreeItem, mw: MainWindow | None=None, *, will_download: bool=False) -> None:
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


async def _source_name_for_node(node_ti: TreeItem, mw: MainWindow) -> str | None:
    node_ti.SelectItem()
    
    click_button(mw.new_group_button)
    ngd = await NewGroupDialog.wait_for()
    source_name = ngd.source  # capture
    await ngd.cancel()
    return source_name


# === Test: Preview Members ===

@skip('covered by: test_given_resource_node_with_multiple_link_children_matching_url_pattern_can_create_new_group_to_bundle_those_links_together')
async def test_given_pattern_contains_no_wildcards_then_preview_members_show_1_matching_url() -> None:
    pass


@skip('covered by: test_given_resource_node_with_multiple_link_children_matching_url_pattern_can_create_new_group_to_bundle_those_links_together')
async def test_given_pattern_contains_wildcards_then_preview_members_show_all_matching_urls() -> None:
    pass


async def test_given_urls_loaded_and_new_url_created_when_show_new_group_dialog_and_input_pattern_matching_new_url_then_preview_members_shows_new_url() -> None:
    with database_on_ssd(False), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        if True:
            home_url = sp.get_request_url('https://xkcd.com/')
            
            comic1_url = sp.get_request_url('https://xkcd.com/1/')
            comic2_url = sp.get_request_url('https://xkcd.com/2/')
            comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create initial entities
            home_rr = RootResource(project, 'Home', Resource(project, home_url))
            ResourceGroup(project, 'Comic', comic_pattern, source=home_rr)
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            home_ti = _find_child(root_ti, home_url)
            comic_ti = _find_child(root_ti, comic_pattern)
            
            # Expand Comic group, to formally load URLs
            # Prepare to spy on whether LoadUrlsProgressDialog appears
            with patch.object(
                    project._load_urls_progress_listener,
                    'will_load_resources',
                    wraps=project._load_urls_progress_listener.will_load_resources) as progress_listener_method:
                comic_ti.Expand()
                await wait_for(tree_item_has_no_children_condition(comic_ti))
                assert 0 == len(comic_ti.Children)
                
                # Ensure did show LoadUrlsProgressDialog
                assert progress_listener_method.call_count >= 1
            
            # Expand home URL, to discover initial comic URLs
            home_ti.Expand()
            await wait_for_download_to_start_and_finish(mw.task_tree)
            assert first_child_of_tree_item_is_not_loading_condition(home_ti)()
            assert len(comic_ti.Children) >= 2  # contains at least the first and last comics
            
            # Start creating a duplicate Comic group
            if True:
                assert mw.new_group_button.Enabled
                click_button(mw.new_group_button)
                ngd = await NewGroupDialog.wait_for()
                
                # Input new URL pattern with wildcard, to match comics
                ngd.pattern_field.Value = comic_pattern
                
                # Ensure preview members show the appropriate matching URLs
                member_urls = [
                    ngd.preview_members_list.GetString(i)
                    for i in range(ngd.preview_members_list.GetCount())
                ]
                assert comic1_url in member_urls  # contains first comic
                assert len(member_urls) >= 2  # contains last comic too
                
                await ngd.cancel()


# === Test: New Group Options ===

async def test_when_add_group_then_does_not_download_immediately_by_default() -> None:
    with _served_simple_site_with_group() as (home_url, comic_pattern):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            rr = RootResource(project, 'Home', Resource(project, home_url))
            rr.download()
            await wait_for_download_to_start_and_finish(mw.task_tree)
            
            assert mw.new_group_button.Enabled
            click_button(mw.new_group_button)
            ngd = await NewGroupDialog.wait_for()
            
            ngd.pattern_field.Value = comic_pattern
            ngd.name_field.Value = 'Comic'
            await ngd.ok()
            
            # Ensure did NOT start downloading
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            root_ti.find_child(comic_pattern, project.default_url_prefix)
            assert tree_has_no_children_condition(mw.task_tree)()


async def test_when_add_group_can_download_group_immediately_with_1_extra_click() -> None:
    with _served_simple_site_with_group() as (home_url, comic_pattern):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            rr = RootResource(project, 'Home', Resource(project, home_url))
            rr.download()
            await wait_for_download_to_start_and_finish(mw.task_tree)
            
            assert mw.new_group_button.Enabled
            click_button(mw.new_group_button)
            ngd = await NewGroupDialog.wait_for()
            
            ngd.pattern_field.Value = comic_pattern
            ngd.name_field.Value = 'Comic'
            click_checkbox(ngd.download_immediately_checkbox)  # extra click #1
            await ngd.ok()
            
            # Ensure started downloading
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            root_ti.find_child(comic_pattern, project.default_url_prefix)
            await wait_for_download_to_start_and_finish(mw.task_tree)


async def test_when_edit_group_then_new_group_options_not_shown() -> None:
    with _served_simple_site_with_group() as (_, comic_pattern):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            ResourceGroup(project, 'Comic', comic_pattern)
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            comic_ti = root_ti.find_child(comic_pattern, project.default_url_prefix)
            comic_ti.SelectItem()
            
            assert mw.edit_button.Enabled
            click_button(mw.edit_button)
            ngd = await NewGroupDialog.wait_for()
            
            assert not ngd.new_options_shown
            await ngd.cancel()


@contextmanager
def _served_simple_site_with_group() -> Iterator[tuple[str, str]]:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=b'<a href="/assets/image.png">Comic 1</a>'
        ),
        '/assets/image.png': dict(
            status_code=200,
            headers=[('Content-Type', 'image/png')],
            content=b''
        )
    })
    with server:
        home_url = server.get_url('/')
        comic_pattern = server.get_url('/**')
        
        yield (home_url, comic_pattern)


# === Utility ===

_find_child = TreeItem.find_child
_find_child_by_title = TreeItem.find_child_by_title

# NOTE: Only for use with tree items in EntityTree
_assert_tree_item_icon_tooltip_contains = EntityTree.assert_tree_item_icon_tooltip_contains
