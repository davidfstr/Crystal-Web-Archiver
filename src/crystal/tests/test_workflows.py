from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from crystal.browser.entitytree import get_tree_item_icon_tooltip
from crystal.model import Project
from crystal.server import get_request_url, ProjectServer
import crystal.tests.test_data as test_data
from crystal.tests.util.console import console_output_copied
from crystal.tests.util.controls import (
    click_button, set_checkbox_value, TreeItem
)
from crystal.tests.util.server import (
    assert_does_open_webbrowser_to, fetch_archive_url,
    is_url_not_in_archive,
)
from crystal.tests.util.tasks import wait_for_download_to_start_and_finish
from crystal.tests.util.wait import (
    wait_for, window_condition, first_child_of_tree_item_is_not_loading_condition,
    tree_has_no_children_condition,
)
from crystal.tests.util.windows import (
    AddGroupDialog, AddUrlDialog, MainWindow, OpenOrCreateDialog, PreferencesDialog,
)
from crystal.util import http_date
from crystal.util.xdatetime import datetime_is_aware
from crystal.util.xthreading import is_foreground_thread
import datetime
import json
import os
import re
import tempfile
from typing import Iterator, List, Optional, Union
from unittest import skip
import wx
from zipfile import ZipFile


# ------------------------------------------------------------------------------
# Tests

async def test_can_download_and_serve_a_static_site() -> None:
    """
    Test that can successfully download and serve a mostly-static site.
    
    Example site: https://xkcd.com/
    """
    assert is_foreground_thread()
    
    with served_project('xkcd.crystalproj.zip') as sp:
        # Define URLs
        if True:
            home_url = sp.get_request_url('https://xkcd.com/')
            
            comic1_url = sp.get_request_url('https://xkcd.com/1/')
            comic2_url = sp.get_request_url('https://xkcd.com/2/')
            comic_pattern = sp.get_request_url('https://xkcd.com/#/')
            
            atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
            rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
            feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
            
            feed_item_pattern = sp.get_request_url('https://xkcd.com/##/')
            assert feed_item_pattern != comic_pattern
        
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
                    aud = await AddUrlDialog.wait_for()
                    
                    aud.name_field.Value = 'Home'
                    aud.url_field.Value = home_url
                    await aud.ok()
                    home_ti = root_ti.GetFirstChild()
                    assert home_ti is not None  # entity was created
                    assert f'{home_url} - Home' == home_ti.Text
                
                # Test can view resource (that has zero downloaded revisions)
                home_ti.SelectItem()
                home_request_url = get_request_url(home_url)
                expected_home_request_url = (
                    'http://localhost:2797/_/' + home_url.replace('://', '/')
                )
                assert expected_home_request_url == home_request_url
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
                    assert 'Home' == agd.source  # default source = (from resource parent)
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
                        assert re.fullmatch(
                            rf'{re.escape(comic_pattern)} - \d+ of Comic',  # title format of grouped sub-resources
                            grouped_subresources_ti.Text)
                        
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
                
                # Test can download resource group, when root resource is source
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
            
                # Test can update membership of resource group, when other resource group is source
                if True:
                    # Undownload all members of the feed group
                    await _undownload_url([atom_feed_url, rss_feed_url], mw, project_dirpath)
                    
                    root_ti = TreeItem.GetRootItem(mw.entity_tree)
                    assert root_ti is not None
                    
                    # Create feed item group, with feed group as source
                    if True:
                        click_button(mw.add_group_button)
                        agd = await AddGroupDialog.wait_for()
                        
                        agd.name_field.Value = 'Feed Item'
                        agd.pattern_field.Value = feed_item_pattern
                        agd.source = 'Feed'
                        await agd.ok()
                        
                        (feed_item_group_ti,) = [
                            child for child in root_ti.Children
                            if child.Text.startswith(f'{feed_item_pattern} - ')
                        ]
                    
                    # Update members of feed item group,
                    # which should download members of feed group automatically
                    assert tree_has_no_children_condition(mw.task_tree)()
                    feed_item_group_ti.SelectItem()
                    click_button(mw.update_membership_button)
                    await wait_for_download_to_start_and_finish(mw.task_tree)
                
                # Ensure members of the feed group were downloaded
                with Project(project_dirpath) as project:
                    for feed_url in [atom_feed_url, rss_feed_url]:
                        feed_resource = project.get_resource(feed_url)
                        assert feed_resource is not None
                        assert feed_resource.default_revision() is not None
            
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


async def test_can_download_and_serve_a_site_requiring_dynamic_url_discovery() -> None:
    """
    Tests that can successfully download and serve a site containing
    JavaScript which dynamically fetches URLs that cannot be discovered
    statically by Crystal.
    """
    with served_project('xkcd.crystalproj.zip') as sp:
        # Define URLs
        if True:
            home_url = sp.get_request_url('https://xkcd.com/')
            target_url = sp.get_request_url('https://c.xkcd.com/xkcd/news')
            
            # NOTE: Crystal IS actually smart enough to discover that a link to
            #       this URL does exist in the <script> tag. However it is NOT 
            #       smart enough to determine that the link should be considered
            #       EMBEDDED, so Crystal will not automatically download it.
            target_reference = f'''client.open("GET", "{get_request_url(target_url)}", true);'''
            
            target_group_name = 'Target Group'
            target_group_pattern = target_url + '*'
            
            target_root_resource_name = 'Target'
        
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                root_ti = TreeItem.GetRootItem(mw.entity_tree)
                assert root_ti is not None
                assert root_ti.GetFirstChild() is None  # no entities
                
                # Download home page
                if True:
                    click_button(mw.add_url_button)
                    aud = await AddUrlDialog.wait_for()
                    aud.name_field.Value = 'Home'
                    aud.url_field.Value = home_url
                    await aud.ok()
                    home_ti = root_ti.GetFirstChild()
                    assert home_ti is not None  # entity was created
                    assert f'{home_url} - Home' == home_ti.Text
                    
                    home_ti.SelectItem()
                    click_button(mw.download_button)
                    await wait_for_download_to_start_and_finish(mw.task_tree)
                    
                    # Start server
                    with assert_does_open_webbrowser_to(get_request_url(home_url)):
                        click_button(mw.view_button)
                    
                    assert False == (await is_url_not_in_archive(home_url))
                    
                    # Ensure home page ONLY has <script> reference to target
                    if True:
                        # Ensure home page has <script> reference to target
                        home_page = await fetch_archive_url(home_url)
                        assert target_reference in home_page.content
                        
                        # Ensure target was not discovered as embedded resource of home page
                        assert False == (await is_url_not_in_archive(home_url))
                        assert True == (await is_url_not_in_archive(target_url))
                
                def start_server_again():
                    nonlocal root_ti
                    nonlocal home_ti
                    
                    root_ti = TreeItem.GetRootItem(mw.entity_tree)
                    assert root_ti is not None
                    home_ti = root_ti.GetFirstChild()
                    assert home_ti is not None
                    home_ti.SelectItem()
                    with assert_does_open_webbrowser_to(get_request_url(home_url)):
                        click_button(mw.view_button)
                
                # View the home page.
                # Ensure console does reveal that target was not downloaded successfully.
                if True:
                    # Simulate opening home page in browser,
                    # which should evaluate the <script>-only reference,
                    # and try to fetch the target automatically
                    with console_output_copied() as console_output:
                        home_page = await fetch_archive_url(home_url)
                        # TODO: Use a *dynamic* timeout that looks for progress in
                        #       download tasks in the UI, similar to
                        #       wait_for_download_to_start_and_finish
                        target_page = await fetch_archive_url(target_url, timeout=10)
                    
                    # Ensure console does log that target in not in the archive
                    # so that user knows they must take special action to download it
                    assert (
                        f'*** Requested resource not in archive: '
                        f'{target_url}'
                    ) in console_output.getvalue()
                
                # Test will dynamically download a new resource group member upon request
                if True:
                    assert True == (await is_url_not_in_archive(target_url))
                    
                    # Undiscover the target
                    await _undiscover_url(target_url, mw, project_dirpath)
                    start_server_again()
                    
                    # Add resource group matching target
                    click_button(mw.add_group_button)
                    agd = await AddGroupDialog.wait_for()
                    agd.name_field.Value = target_group_name
                    agd.pattern_field.Value = target_group_pattern
                    await agd.ok()
                    
                    # Refresh the home page.
                    # Ensure console does log that target is being dynamically fetched.
                    if True:
                        # Simulate refreshing home page in browser,
                        # which should evaluate the <script>-only reference,
                        # and try to fetch the target automatically
                        with console_output_copied() as console_output:
                            home_page = await fetch_archive_url(home_url)
                            # TODO: Use a *dynamic* timeout that looks for progress in
                            #       download tasks in the UI, similar to
                            #       wait_for_download_to_start_and_finish
                            target_page = await fetch_archive_url(target_url, timeout=10)
                        
                        # Ensure console does log that target is being dynamically fetched,
                        # so that user knows they were successful in creating a matching group
                        assert (
                            f'*** Dynamically downloading new resource in group '
                            f'{target_group_name!r}: {target_url}'
                        ) in console_output.getvalue()
                        
                    assert False == (await is_url_not_in_archive(target_url))
                    
                    # Undownload target
                    await _undownload_url(target_url, mw, project_dirpath)
                    start_server_again()
                
                # Test will dynamically download an existing resource group member upon request
                if True:
                    # Refresh the home page.
                    # Ensure console does log that target is being dynamically fetched.
                    if True:
                        # Simulate refreshing home page in browser,
                        # which should evaluate the <script>-only reference,
                        # and try to fetch the target automatically
                        with console_output_copied() as console_output:
                            home_page = await fetch_archive_url(home_url)
                            # TODO: Use a *dynamic* timeout that looks for progress in
                            #       download tasks in the UI, similar to
                            #       wait_for_download_to_start_and_finish
                            target_page = await fetch_archive_url(target_url, timeout=10)
                        
                        # Ensure console does log that target is being dynamically fetched,
                        # so that user knows they were successful in creating a matching group
                        assert (
                            f'*** Dynamically downloading existing resource in group '
                            f'{target_group_name!r}: {target_url}'
                        ) in console_output.getvalue()
                    
                    assert False == (await is_url_not_in_archive(target_url))
                    
                    # Forget resource group matching target
                    (target_group_ti,) = [
                        child for child in root_ti.Children
                        if child.Text.startswith(f'{target_group_pattern} - ')
                    ]
                    target_group_ti.SelectItem()
                    click_button(mw.forget_button)
                    
                    # Undownload target
                    await _undownload_url(target_url, mw, project_dirpath)
                    start_server_again()
                
                # Test will dynamically download a root resource upon request
                if True:
                    assert True == (await is_url_not_in_archive(target_url))
                    
                    # Add root resource: https://c.xkcd.com/xkcd/news
                    click_button(mw.add_url_button)
                    aud = await AddUrlDialog.wait_for()
                    aud.name_field.Value = target_root_resource_name
                    aud.url_field.Value = target_url
                    await aud.ok()
                    
                    # Refresh the home page.
                    # Ensure console does log that target is being dynamically fetched.
                    if True:
                        # Simulate refreshing home page in browser,
                        # which should evaluate the <script>-only reference,
                        # and try to fetch the target automatically
                        with console_output_copied() as console_output:
                            home_page = await fetch_archive_url(home_url)
                            # TODO: Use a *dynamic* timeout that looks for progress in
                            #       download tasks in the UI, similar to
                            #       wait_for_download_to_start_and_finish
                            target_page = await fetch_archive_url(target_url, timeout=10)
                        
                        # Ensure console does log that target is being dynamically fetched,
                        # so that user knows they were successful in creating a matching root resource
                        assert (
                            f'*** Dynamically downloading root resource '
                            f'{target_root_resource_name!r}: {target_url}'
                        ) in console_output.getvalue()
                    
                    assert False == (await is_url_not_in_archive(target_url))
                    
                    # Forget root resource matching target
                    (target_rr_ti,) = [
                        child for child in root_ti.Children
                        if child.Text.startswith(f'{target_url} - ')
                    ]
                    target_rr_ti.SelectItem()
                    click_button(mw.forget_button)
                    
                    # Undownload target
                    await _undownload_url(target_url, mw, project_dirpath)


@skip('not yet automated')
async def test_can_download_and_serve_a_site_requiring_dynamic_link_rewriting() -> None:
    pass


async def test_cannot_download_anything_given_project_is_opened_as_readonly() -> None:
    """
    Test that can open project in a read-only mode. In this mode it should be
    impossible to download anything or make any kind of project change.
    Various parts of the UI should be disabled to reflect this limitation.
    """
    
    with served_project('xkcd.crystalproj.zip') as sp:
        # Define URLs
        if True:
            home_url = sp.get_request_url('https://xkcd.com/')
            
            comic1_url = sp.get_request_url('https://xkcd.com/1/')
            comic2_url = sp.get_request_url('https://xkcd.com/2/')
            comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                root_ti = TreeItem.GetRootItem(mw.entity_tree)
                assert root_ti is not None
                assert root_ti.GetFirstChild() is None  # no entities
                
                # Download home page
                if True:
                    click_button(mw.add_url_button)
                    aud = await AddUrlDialog.wait_for()
                    aud.name_field.Value = 'Home'
                    aud.url_field.Value = home_url
                    await aud.ok()
                    home_ti = root_ti.GetFirstChild()
                    assert home_ti is not None  # entity was created
                    assert f'{home_url} - Home' == home_ti.Text
                    
                    home_ti.SelectItem()
                    click_button(mw.download_button)
                    await wait_for_download_to_start_and_finish(mw.task_tree)
                
                # Ensure home page has link to Comic #1
                home_ti.Expand()
                await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
                await wait_for(tree_has_no_children_condition(mw.task_tree))
                (comic1_ti,) = [
                    child for child in home_ti.Children
                    if child.Text.startswith(f'{comic1_url} - ')
                ]  # ensure did find sub-resource for Comic #1
                
                # Create group Comic
                if True:
                    click_button(mw.add_group_button)
                    agd = await AddGroupDialog.wait_for()
                    
                    agd.name_field.Value = 'Comic'
                    agd.pattern_field.Value = comic_pattern
                    await agd.ok()
            
            # Ensure "Create" is disabled when preparing to open/create in read-only mode
            ocd = await OpenOrCreateDialog.wait_for()
            set_checkbox_value(ocd.open_as_readonly, True)
            assert False == ocd.create_button.Enabled
            
            async with ocd.open(project_dirpath) as mw:
                # Ensure icon shows that project is read-only
                assert True == mw.readonly, 'Expected read-only icon to be visible'
                
                # Ensure "Add URL" and "Add Group" are disabled
                assert False == mw.add_url_button.Enabled
                assert False == mw.add_group_button.Enabled
                
                root_ti = TreeItem.GetRootItem(mw.entity_tree)
                assert root_ti is not None
                
                # Ensure "Forget" and "Download" are disabled when resource is selected
                (home_ti,) = [
                    child for child in root_ti.Children
                    if child.Text.startswith(f'{home_url} - ')
                ]
                home_ti.SelectItem()
                assert False == mw.forget_button.Enabled
                assert False == mw.download_button.Enabled
                
                # 1. Ensure can expand a downloaded resource (Home)
                # 2. Ensure home page has reference to Comic #1
                home_ti.Expand()
                await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
                await wait_for(tree_has_no_children_condition(mw.task_tree))
                (linked_comic_group_ti,) = [
                    child for child in home_ti.Children
                    if child.Text.startswith(f'{comic_pattern} - ')
                ]
                linked_comic_group_ti.Expand()
                (comic1_ti,) = [
                    child for child in linked_comic_group_ti.Children
                    if child.Text.startswith(f'{comic1_url} - ')
                ]  # ensure did find sub-resource for Comic #1
                
                # Ensure expanding an undownloaded resource (Comic #1)
                # does show a "Cannot download" placeholder node
                comic1_ti.Expand()
                await wait_for(first_child_of_tree_item_is_not_loading_condition(comic1_ti))
                cannot_download_ti = comic1_ti.GetFirstChild()
                assert cannot_download_ti is not None
                assert 'Cannot download children: Project is read only' == cannot_download_ti.Text
                
                # Ensure "Forget" and "Download" are disabled when group is selected
                (comic_group_ti,) = [
                    child for child in root_ti.Children
                    if child.Text.startswith(f'{comic_pattern} - ')
                ]  # ensure did find resource group at root of entity tree
                comic_group_ti.SelectItem()
                assert False == mw.forget_button.Enabled
                assert False == mw.download_button.Enabled
                
                # Ensure can serve downloaded resource (Home)
                home_ti.SelectItem()
                with assert_does_open_webbrowser_to(get_request_url(home_url)):
                    click_button(mw.view_button)
                assert False == (await is_url_not_in_archive(home_url))
                
                # Ensure does NOT dynamically download a resource (Comic #1)
                # matching an existing group (Comic) when in read-only mode
                comic1_ti.SelectItem()
                with assert_does_open_webbrowser_to(get_request_url(comic1_url)):
                    click_button(mw.view_button)
                assert True == (await is_url_not_in_archive(comic1_url))


async def test_can_update_downloaded_site_with_newer_page_revisions() -> None:
    # Define original URLs
    home_original_url = 'https://xkcd.com/'
    comic1_original_url = 'https://xkcd.com/1/'
    
    # Define versions
    home_v1_etag = '"62e1f036-1edc"'
    home_v2_etag = '"62e1f036-1f64"'
    comic1_v1_etag = '"62e1f036-1f21"'
    
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
            # Start xkcd v1
            with served_project('xkcd.crystalproj.zip') as sp1:
                # Define URLs
                home_url = sp1.get_request_url(home_original_url)
                comic1_url = sp1.get_request_url(comic1_original_url)
                
                # Download: Home, Comic #1
                if True:
                    click_button(mw.add_url_button)
                    aud = await AddUrlDialog.wait_for()
                    aud.name_field.Value = 'Home'
                    aud.url_field.Value = home_url
                    await aud.ok()
                    
                    click_button(mw.add_url_button)
                    aud = await AddUrlDialog.wait_for()
                    aud.name_field.Value = 'Comic #1'
                    aud.url_field.Value = comic1_url
                    await aud.ok()
                    
                    root_ti = TreeItem.GetRootItem(mw.entity_tree)
                    assert root_ti is not None
                    (home_ti, comic1_ti) = root_ti.Children
                    
                    # Ensure resource status badge says URL is undownloaded
                    await _assert_tree_item_icon_tooltip_contains(home_ti, 'Undownloaded')
                    await _assert_tree_item_icon_tooltip_contains(comic1_ti, 'Undownloaded')
                    
                    home_ti.SelectItem()
                    click_button(mw.download_button)
                    await wait_for_download_to_start_and_finish(mw.task_tree)
                    
                    comic1_ti.SelectItem()
                    click_button(mw.download_button)
                    await wait_for_download_to_start_and_finish(mw.task_tree)
                    
                    # Ensure resource status badge says URL is fresh
                    await _assert_tree_item_icon_tooltip_contains(home_ti, 'Fresh')
                    await _assert_tree_item_icon_tooltip_contains(comic1_ti, 'Fresh')
                
                # Start server
                home_ti.SelectItem()
                with assert_does_open_webbrowser_to(get_request_url(home_url)):
                    click_button(mw.view_button)
                
                # Verify etag is v1 for both
                assert home_v1_etag == (await fetch_archive_url(home_url)).etag
                assert comic1_v1_etag == (await fetch_archive_url(comic1_url)).etag
            
            # Start xkcd v2
            with served_project(
                    'xkcd-v2.crystalproj.zip',
                    fetch_date_of_resources_set_to=datetime.datetime.now(datetime.timezone.utc)) as sp2:
                # Define URLs
                assert home_url == sp2.get_request_url(home_original_url)
                assert comic1_url == sp2.get_request_url(comic1_original_url)
                
                # Download: Home, Comic #1
                if True:
                    home_ti.SelectItem()
                    click_button(mw.download_button)
                    await wait_for_download_to_start_and_finish(mw.task_tree,
                        immediate_finish_ok=True)
                    
                    comic1_ti.SelectItem()
                    click_button(mw.download_button)
                    await wait_for_download_to_start_and_finish(mw.task_tree,
                        immediate_finish_ok=True)
                
                # Verify etag is still v1 for both
                assert home_v1_etag == (await fetch_archive_url(home_url)).etag
                assert comic1_v1_etag == (await fetch_archive_url(comic1_url)).etag
                
                # Ensure resource status badge says URL is fresh
                await _assert_tree_item_icon_tooltip_contains(home_ti, 'Fresh')
                await _assert_tree_item_icon_tooltip_contains(comic1_ti, 'Fresh')
                
                # Change preferences: Stale if downloaded before today
                click_button(mw.preferences_button)
                pd = await PreferencesDialog.wait_for()
                pd.stale_before_checkbox.Value = True
                await pd.ok()
                
                # Ensure resource status badge says URL is stale
                await _assert_tree_item_icon_tooltip_contains(home_ti, 'Stale')
                await _assert_tree_item_icon_tooltip_contains(comic1_ti, 'Stale')
                
                # Download: Home, Comic #1
                if True:
                    home_ti.SelectItem()
                    click_button(mw.download_button)
                    await wait_for_download_to_start_and_finish(mw.task_tree,
                        immediate_finish_ok=True)
                    
                    comic1_ti.SelectItem()
                    click_button(mw.download_button)
                    await wait_for_download_to_start_and_finish(mw.task_tree,
                        immediate_finish_ok=True)
                
                # Ensure resource status badge says URL is fresh
                await _assert_tree_item_icon_tooltip_contains(home_ti, 'Fresh')
                await _assert_tree_item_icon_tooltip_contains(comic1_ti, 'Fresh')
                
                # Change preferences: Undo: Stale if downloaded before today
                click_button(mw.preferences_button)
                pd = await PreferencesDialog.wait_for()
                pd.stale_before_checkbox.Value = False
                await pd.ok()
                
                # Verify etag is v2 for Home, but still v1 for Comic #1
                assert home_v2_etag == (await fetch_archive_url(home_url)).etag
                assert comic1_v1_etag == (await fetch_archive_url(comic1_url)).etag
        
        with Project(project_dirpath) as project:
            # Ensure Home was downloaded twice, each time with HTTP 200
            home_r = project.get_resource(home_url)
            assert home_r is not None
            (home_rr1, home_rr2) = home_r.revisions()
            assert 200 == home_rr1.status_code
            assert 200 == home_rr2.status_code
            
            # Ensure Comic #1 was downloaded twice, first with HTTP 200, then with HTTP 304
            comic1_r = project.get_resource(comic1_url)
            assert comic1_r is not None
            (comic1_rr1, comic1_rr2) = comic1_r.revisions()
            assert 200 == comic1_rr1.status_code
            assert 304 == comic1_rr2.status_code
            
            # Ensure Comic #1's second revision does redirect to its first revision
            assert comic1_rr1.etag == comic1_rr2.resolve_http_304().etag


@skip('not yet automated')
async def test_can_download_and_serve_a_site_requiring_cookie_authentication() -> None:
    pass


# ------------------------------------------------------------------------------
# Utility

@contextmanager
def served_project(
        zipped_project_filename: str,
        *, fetch_date_of_resources_set_to: Optional[datetime.datetime]=None,
        ) -> Iterator[ProjectServer]:
    if fetch_date_of_resources_set_to is not None:
        if not datetime_is_aware(fetch_date_of_resources_set_to):
            raise ValueError('Expected fetch_date_of_resources_set_to to be an aware datetime')
    
    with tempfile.TemporaryDirectory() as project_parent_dirpath:
        # Extract project
        with test_data.open_binary(zipped_project_filename) as zipped_project_file:
            with ZipFile(zipped_project_file, 'r') as project_zipfile:
                project_zipfile.extractall(project_parent_dirpath)
        
        # Open project
        (project_filename,) = [
            fn for fn in os.listdir(project_parent_dirpath)
            if fn.endswith('.crystalproj')
        ]
        project_filepath = os.path.join(project_parent_dirpath, project_filename)
        with Project(project_filepath, readonly=True) as project:
            # Alter the fetch date of every ResourceRevision in the project
            # to match "fetch_date_of_resources_set_to", if provided
            if fetch_date_of_resources_set_to is not None:
                for r in project.resources:
                    for rr in r.revisions():
                        if rr.metadata is None:
                            print(
                                f'Warning: Unable to alter fetch date of '
                                f'resource revision lacking HTTP headers: {rr}')
                            continue
                        
                        rr_new_date = http_date.format(fetch_date_of_resources_set_to)
                        
                        # New Metadata = Old Metadata with Date and Age headers replaced
                        rr_new_metadata = deepcopy(rr.metadata)
                        rr_new_metadata['headers'] = [
                            (cur_name, cur_value)
                            for (cur_name, cur_value) in
                            rr_new_metadata['headers']
                            if cur_name.lower() not in ['date', 'age']
                        ] + [('Date', rr_new_date)]
                        
                        # Alter ResourceRevision's metadata in memory
                        rr.metadata = rr_new_metadata
                        
                        # Alter ResourceRevision's metadata in database
                        c = project._db.cursor()
                        c.execute(
                            'update resource_revision set metadata = ? where id = ?',
                            (json.dumps(rr_new_metadata), rr._id),  # type: ignore[attr-defined]
                            ignore_readonly=True)
                        project._db.commit()
            
            # Start server
            yield project.start_server(
                port=2798,  # CRYT on telephone keypad
                verbosity='indent',
            )


async def _undownload_url(
        url_or_urls: Union[str, List[str]],
        mw: MainWindow,
        project_dirpath: str
        ) -> None:
    """
    Deletes the default revision of the specified resource(s).
    
    Note that the prior main window will need to be temporarily closed
    and later reopened to perform the deletion.
    """
    if isinstance(url_or_urls, str):
        url_or_urls = [url_or_urls]  # reinterpret
    
    # TODO: Make it possible to do this from the UI:
    #       https://github.com/davidfstr/Crystal-Web-Archiver/issues/73
    async with mw.temporarily_closed(project_dirpath):
        with Project(project_dirpath) as project:
            for url in url_or_urls:
                resource = project.get_resource(url)
                assert resource is not None
                revision = resource.default_revision()
                assert revision is not None
                revision.delete(); del revision
                assert resource.default_revision() is None


async def _undiscover_url(
        url_or_urls: Union[str, List[str]],
        mw: MainWindow,
        project_dirpath: str
        ) -> None:
    """
    Deletes the specified resource(s), along with any related resource revisions.
    
    Note that the prior main window will need to be temporarily closed
    and later reopened to perform the deletion.
    """
    if isinstance(url_or_urls, str):
        url_or_urls = [url_or_urls]  # reinterpret
    
    async with mw.temporarily_closed(project_dirpath):
        with Project(project_dirpath) as project:
            for url in url_or_urls:
                resource = project.get_resource(url)
                assert resource is not None
                resource.delete(); del resource


async def _assert_tree_item_icon_tooltip_contains(ti: TreeItem, value: str) -> None:
    tooltip = await get_tree_item_icon_tooltip(ti.tree, ti.id)
    assert tooltip is not None and value in tooltip, \
        f'Expected tooltip to contain {value!r}, but it was: {tooltip!r}'


# ------------------------------------------------------------------------------
