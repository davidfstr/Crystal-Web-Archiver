from __future__ import annotations

from crystal.tests.util.controls import TreeItem, click_button
from crystal.tests.util.server import (
    assert_does_open_webbrowser_to, get_request_url, is_url_not_in_archive,
)
from crystal.tests.util.tasks import wait_for_download_to_start_and_finish
from crystal.tests.util.wait import (
    wait_for, window_condition, first_child_of_tree_item_is_not_loading_condition,
    tree_has_no_children_condition,
)
from crystal.tests.util.windows import OpenOrCreateDialog, AddGroupDialog
from crystal.util.xthreading import is_foreground_thread
import tempfile
from unittest import skip
import wx


# ------------------------------------------------------------------------------
# Tests

async def test_can_download_and_serve_a_static_site() -> None:
    """
    Test that can successfully download and serve a mostly-static site.
    
    Example site: https://xkcd.com/
    """
    assert is_foreground_thread()
    
    # TODO: Use a pre-downloaded version of xkcd rather than the real xkcd
    if True:
        home_url = 'https://xkcd.com/'
        
        comic1_url = 'https://xkcd.com/1/'
        comic2_url = 'https://xkcd.com/2/'
        comic_pattern = 'https://xkcd.com/#/'
        
        atom_feed_url = 'https://xkcd.com/atom.xml'
        rss_feed_url = 'https://xkcd.com/rss.xml'
        feed_pattern = 'https://xkcd.com/*.xml'
    
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        # 1. Test can create project
        # 2. Test can quit
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
            assert False == mw.readonly
            
            # Test can create root resource
            if True:
                root_ti = TreeItem.GetRootItem(mw.entity_tree)
                assert root_ti is not None
                assert root_ti.GetFirstChild() is None  # no entities
                
                click_button(mw.add_url_button)
                add_url_dialog = await wait_for(window_condition('cr-add-url-dialog'))  # type: wx.Window
                name_field = add_url_dialog.FindWindowByName('cr-add-url-dialog__name-field')
                assert isinstance(name_field, wx.TextCtrl)
                url_field = add_url_dialog.FindWindowByName('cr-add-url-dialog__url-field')
                assert isinstance(url_field, wx.TextCtrl)
                ok_button = add_url_dialog.FindWindowById(wx.ID_OK)
                assert isinstance(ok_button, wx.Button)
                
                name_field.Value = 'Home'
                url_field.Value = home_url
                click_button(ok_button)
                home_ti = root_ti.GetFirstChild()
                assert home_ti is not None  # entity was created
                assert f'{home_url} - Home' == home_ti.Text
            
            # Test can view resource (that has zero downloaded revisions)
            home_ti.SelectItem()
            home_request_url = get_request_url(home_url)
            assert 'http://localhost:2797/_/https/xkcd.com/' == home_request_url
            with assert_does_open_webbrowser_to(home_request_url):
                click_button(mw.view_button)
            assert True == (await is_url_not_in_archive(home_url))
            
            # Test can download root resource (using download button)
            assert home_ti.id == mw.entity_tree.GetSelection()
            click_button(mw.download_button)
            await wait_for_download_to_start_and_finish(mw.task_tree)
            
            # Test can view resource (that has a downloaded revision)
            assert False == (await is_url_not_in_archive(home_url))
            
            # Test can re-download resource (by expanding tree node)
            home_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
            await wait_for(tree_has_no_children_condition(mw.task_tree))
            (comic1_ti,) = [
                child for child in home_ti.Children
                if child.Text.startswith(f'{comic1_url} - ')
            ]  # ensure did find sub-resource for Comic #1
            assert f'{comic1_url} - Link: |<, Link: |<' == comic1_ti.Text  # title format of sub-resource
            
            # Test can download resource (by expanding tree node)
            if True:
                comic1_ti.Expand()
                await wait_for_download_to_start_and_finish(mw.task_tree)
                assert first_child_of_tree_item_is_not_loading_condition(comic1_ti)()
                
                (comic2_ti,) = [
                    child for child in comic1_ti.Children
                    if child.Text.startswith(f'{comic2_url} - ')
                ]  # ensure did find sub-resource for Comic #2
                assert f'{comic2_url} - Link: Next >, Link: Next >' == comic2_ti.Text  # title format of sub-resource
                
                comic1_ti.Collapse()
            
            # Test can create resource group (using selected resource as template)
            if True:
                comic1_ti.SelectItem()
                
                click_button(mw.add_group_button)
                agd = await AddGroupDialog.wait_for()
                
                assert '' == agd.name_field.Value  # default name = (nothing)
                assert comic1_url == agd.pattern_field.Value  # default pattern = (from resource)
                selection_ci = agd.source_field.GetSelection()
                assert selection_ci != wx.NOT_FOUND
                assert 'Home' == agd.source_field.GetString(selection_ci)  # default source = (from resource parent)
                assert agd.name_field.HasFocus  # default focused field
                
                agd.name_field.Value = 'Comic'
                
                assert not agd.preview_members_pane.IsExpanded()  # collapsed by default
                agd.preview_members_pane.Expand()
                member_urls = [
                    agd.preview_members_list.GetString(i)
                    for i in range(agd.preview_members_list.GetCount())
                ]
                assert [comic1_url] == member_urls  # contains exact match of pattern
                
                agd.pattern_field.Value = comic_pattern
                
                member_urls = [
                    agd.preview_members_list.GetString(i)
                    for i in range(agd.preview_members_list.GetCount())
                ]
                assert comic1_url in member_urls  # contains first comic
                assert len(member_urls) >= 2  # contains last comic too
                
                await agd.ok()
                
                # Ensure the new resource group does now group sub-resources
                if True:
                    (grouped_subresources_ti,) = [
                        child for child in home_ti.Children
                        if child.Text.startswith(f'{comic_pattern} - ')
                    ]  # ensure did find grouped sub-resources
                    assert f'{comic_pattern} - Comic' == grouped_subresources_ti.Text  # title format of grouped sub-resources
                    
                    grouped_subresources_ti.Expand()
                    await wait_for(first_child_of_tree_item_is_not_loading_condition(grouped_subresources_ti))
                    
                    (comic1_ti,) = [
                        child for child in grouped_subresources_ti.Children
                        if child.Text.startswith(f'{comic1_url} - ')
                    ]  # contains first comic
                    assert len(grouped_subresources_ti.Children) >= 2  # contains last comic too
                    
                    grouped_subresources_ti.Collapse()
                
                home_ti.Collapse()
                
                # Ensure the new resource group appears at the root of the entity tree
                (comic_group_ti,) = [
                    child for child in root_ti.Children
                    if child.Text.startswith(f'{comic_pattern} - ')
                ]  # ensure did find resource group at root of entity tree
                assert f'{comic_pattern} - Comic' == comic_group_ti.Text  # title format of resource group
                
                comic_group_ti.Expand()
                await wait_for(first_child_of_tree_item_is_not_loading_condition(comic_group_ti))
                
                # Ensure the new resource group does contain the expected members
                (comic1_ti,) = [
                    child for child in comic_group_ti.Children
                    if child.Text == f'{comic1_url}'
                ]  # contains first comic
                assert len(comic_group_ti.Children) >= 2  # contains last comic too
                
                comic_group_ti.Collapse()
            
            # Test can download resource group
            if True:
                # Create small resource group (with only 2 members)
                if True:
                    home_ti.Expand()
                    await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
                    
                    (atom_feed_ti,) = [
                        child for child in home_ti.Children
                        if child.Text.startswith(f'{atom_feed_url} - ')
                    ]  # contains atom feed
                    (rss_feed_ti,) = [
                        child for child in home_ti.Children
                        if child.Text.startswith(f'{rss_feed_url} - ')
                    ]  # contains rss feed
                    
                    atom_feed_ti.SelectItem()
                    
                    click_button(mw.add_group_button)
                    agd = await AddGroupDialog.wait_for()
                    
                    agd.name_field.Value = 'Feed'
                    agd.pattern_field.Value = feed_pattern
                    await agd.ok()
                    
                    home_ti.Collapse()
                    
                    (feed_group_ti,) = [
                        child for child in root_ti.Children
                        if child.Text.startswith(f'{feed_pattern} - ')
                    ]
                    
                    feed_group_ti.Expand()
                    await wait_for(first_child_of_tree_item_is_not_loading_condition(feed_group_ti))
                    (atom_feed_ti,) = [
                        child for child in feed_group_ti.Children
                        if child.Text == f'{atom_feed_url}'
                    ]
                    (rss_feed_ti,) = [
                        child for child in feed_group_ti.Children
                        if child.Text == f'{rss_feed_url}'
                    ]
                    assert 2 == len(feed_group_ti.Children)  # == [atom feed, rss feed]
                    
                    feed_group_ti.Collapse()
                
                assert True == (await is_url_not_in_archive(atom_feed_url))
                assert True == (await is_url_not_in_archive(rss_feed_url))
                
                feed_group_ti.SelectItem()
                click_button(mw.download_button)
                await wait_for_download_to_start_and_finish(mw.task_tree)
                
                assert False == (await is_url_not_in_archive(atom_feed_url))
                assert False == (await is_url_not_in_archive(rss_feed_url))
        
        # Test can open project (as writable)
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as mw:
            assert False == mw.readonly
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree)
            assert root_ti is not None
            
            # Start server
            (home_ti,) = [
                child for child in root_ti.Children
                if child.Text.startswith(f'{home_url} - ')
            ]
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(get_request_url(home_url)):
                click_button(mw.view_button)
            
            # Test can still view resource (that has a downloaded revision)
            assert False == (await is_url_not_in_archive(home_url))
            
            # Test can still re-download resource (by expanding tree node)
            home_ti.Expand()
            await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
            await wait_for(tree_has_no_children_condition(mw.task_tree))
            (grouped_subresources_ti,) = [
                child for child in home_ti.Children
                if child.Text.startswith(f'{comic_pattern} - ')
            ]
            
            # Test can forget resource group
            if True:
                grouped_subresources_ti.SelectItem()
                click_button(mw.forget_button)
                
                # Ensure the forgotten resource group no longer groups sub-resources
                () = [
                    child for child in home_ti.Children
                    if child.Text.startswith(f'{comic_pattern} - ')
                ]  # ensure did not find grouped sub-resources
                (comic1_ti,) = [
                    child for child in home_ti.Children
                    if child.Text.startswith(f'{comic1_url} - ')
                ]  # ensure did find sub-resource for Comic #1
                
                # Ensure the forgotten resource group no longer appears at the root of the entity tree
                home_ti.Collapse()
                () = [
                    child for child in root_ti.Children
                    if child.Text.startswith(f'{comic_pattern} - ')
                ]  # ensure did not find resource group at root of entity tree
            
            # Test can forget root resource
            if True:
                home_ti.SelectItem()
                click_button(mw.forget_button)
                
                # Ensure the forgotten root resource no longer appears at the root of the entity tree
                () = [
                    child for child in root_ti.Children
                    if child.Text.startswith(f'{home_url} - ')
                ]  # ensure did not find resource
                
                # Ensure that the resource for the forgotten root resource is NOT deleted
                assert False == (await is_url_not_in_archive(home_url))
        
        # Test can open project (as read only)
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as mw:
            assert True == mw.readonly
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree)
            assert root_ti is not None
            
            # 1. Test cannot add new root resource in read-only project
            # 2. Test cannot add new resource group in read-only project
            selected_ti = TreeItem.GetSelection(mw.entity_tree)
            # NOTE: Cannot test the selection on Windows
            #assert (selected_ti is None) or (selected_ti == root_ti)
            assert False == mw.add_url_button.IsEnabled()
            assert False == mw.add_group_button.IsEnabled()
            
            # Test cannot download/forget existing resource in read-only project
            if True:
                (feed_group_ti,) = [
                    child for child in root_ti.Children
                    if child.Text.startswith(f'{feed_pattern} - ')
                ]
                
                feed_group_ti.Expand()
                await wait_for(first_child_of_tree_item_is_not_loading_condition(feed_group_ti))
                
                (atom_feed_ti,) = [
                    child for child in feed_group_ti.Children
                    if child.Text == f'{atom_feed_url}'
                ]
                
                atom_feed_ti.SelectItem()
                assert False == mw.download_button.IsEnabled()
                assert False == mw.forget_button.IsEnabled()
            
            # Test cannot download/update/forget existing resource group in read-only project
            feed_group_ti.SelectItem()
            assert False == mw.download_button.IsEnabled()
            assert False == mw.update_membership_button.IsEnabled()
            assert False == mw.forget_button.IsEnabled()
            
            # Start server
            atom_feed_ti.SelectItem()
            with assert_does_open_webbrowser_to(get_request_url(atom_feed_url)):
                click_button(mw.view_button)
            
            # Test can still view resource (that has a downloaded revision)
            assert False == (await is_url_not_in_archive(atom_feed_url))


@skip('not yet automated')
async def test_can_download_and_serve_a_site_requiring_dynamic_url_discovery() -> None:
    """
    Tests that can successfully download and serve a site containing
    JavaScript which dynamically fetches URLs that cannot be discovered
    statically by Crystal.
    
    Example site: https://bongo.cat/
    """
    pass


# ------------------------------------------------------------------------------
