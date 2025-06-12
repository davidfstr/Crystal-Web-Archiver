from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from crystal.browser.new_root_url import fields_hide_hint_when_focused
from crystal.model import Project, Resource, RootResource
from crystal.task import DownloadResourceGroupTask
from crystal.tests.util.asserts import *
from crystal.tests.util.controls import click_button, click_checkbox, TreeItem
from crystal.tests.util.server import MockHttpServer, served_project
from crystal.tests.util.subtests import (
    awith_subtests, SubtestsContext, with_subtests,
)
from crystal.tests.util.tasks import (
    append_deferred_top_level_tasks, clear_top_level_tasks_on_exit,
    scheduler_disabled, wait_for_download_to_start_and_finish,
)
from crystal.tests.util.wait import (
    DEFAULT_WAIT_PERIOD, first_child_of_tree_item_is_not_loading_condition,
    tree_has_no_children_condition, wait_for,
)
from crystal.tests.util.windows import (
    EntityTree, NewRootUrlDialog, OpenOrCreateDialog,
)
import crystal.url_input
from crystal.url_input import _candidate_urls_from_user_input as EXPAND
from crystal.util.wx_dialog import mocked_show_modal
from crystal.util.wx_window import SetFocus
import os
import time
from typing import Dict, Optional, Self, Union
from unittest import skip
from unittest.mock import ANY, patch
from urllib.parse import urlparse
import wx

# === Test: Create & Delete Standalone ===

async def test_can_create_root_url(
        *, ensure_revisions_not_deleted: bool=False,
        add_surrounding_whitespace: bool=False) -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create root URL
            if True:
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                () = root_ti.Children
                
                assert mw.new_root_url_button.Enabled
                click_button(mw.new_root_url_button)
                nud = await NewRootUrlDialog.wait_for()
                nud.do_not_download_immediately()
                
                # Ensure prepopulates reasonable information
                assert '' == nud.url_field.Value
                assert '' == nud.name_field.Value
                #assert None == ngd.source
                assert nud.url_field.HasFocus  # default focused field
                
                SetFocus(nud.name_field, None)
                nud.name_field.Value = 'Home'
                SetFocus(nud.url_field, nud.name_field)
                nud.url_field.Value = (
                    (' ' if add_surrounding_whitespace else '') +
                    home_url +
                    (' ' if add_surrounding_whitespace else '')
                )
                await nud.ok()
                
                # Ensure appearance is correct
                home_ti = root_ti.find_child(home_url, project.default_url_prefix)
                assert f'{urlparse(home_url).path} - Home' == home_ti.Text
                await _assert_tree_item_icon_tooltip_contains(home_ti, 'root URL')
                await _assert_tree_item_icon_tooltip_contains(home_ti, 'Undownloaded')
                assert f'URL: {home_url}' in (home_ti.Tooltip('label') or '')
                
                # Ensure new root URL is selected automatically,
                # given that nothing was previously selected
                selected_ti = TreeItem.GetSelection(mw.entity_tree.window)
                assert selected_ti == home_ti
            
            if ensure_revisions_not_deleted:
                # Download a revision of the root URL
                home_ti.SelectItem()
                await mw.click_download_button()
                await wait_for_download_to_start_and_finish(mw.task_tree)
                await _assert_tree_item_icon_tooltip_contains(home_ti, 'Fresh')
            
            # Forget root URL
            if True:
                home_ti.SelectItem()
                assert mw.forget_button.IsEnabled()
                click_button(mw.forget_button)
                
                # Ensure cannot find root URL
                assert None == root_ti.try_find_child(home_url, project.default_url_prefix)
                selected_ti = TreeItem.GetSelection(mw.entity_tree.window)
                assert (selected_ti is None) or (selected_ti == root_ti)
            
            if ensure_revisions_not_deleted:
                # Recreate the root URL
                click_button(mw.new_root_url_button)
                nud = await NewRootUrlDialog.wait_for()
                nud.do_not_download_immediately()
                nud.name_field.Value = 'Home'
                nud.url_field.Value = home_url
                await nud.ok()
                
                # 1. Ensure appearance is correct
                # 2. Ensure previously downloaded revisions still exist
                home_ti = root_ti.find_child(home_url, project.default_url_prefix)
                assert f'{urlparse(home_url).path} - Home' == home_ti.Text
                await _assert_tree_item_icon_tooltip_contains(home_ti, 'root URL')
                await _assert_tree_item_icon_tooltip_contains(home_ti, 'Fresh')
                assert f'URL: {home_url}' in (home_ti.Tooltip('label') or '')


@skip('covered by: test_can_create_root_url')
async def test_can_forget_root_url() -> None:
    pass


async def test_when_forget_root_url_then_revisions_of_that_url_are_not_deleted() -> None:
    await test_can_create_root_url(ensure_revisions_not_deleted=True)


async def test_given_url_with_surrounding_whitespace_when_create_root_url_then_surrounding_whitespace_ignored() -> None:
    await test_can_create_root_url(add_surrounding_whitespace=True)


# === Test: Create & Delete from Links ===

async def test_given_resource_node_with_links_can_create_new_root_url_to_label_link() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create home URL
            if True:
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                () = root_ti.Children
                
                assert mw.new_root_url_button.Enabled
                click_button(mw.new_root_url_button)
                nud = await NewRootUrlDialog.wait_for()
                nud.do_not_download_immediately()
                
                nud.name_field.Value = 'Home'
                nud.url_field.Value = home_url
                await nud.ok()
                (home_ti,) = root_ti.Children
            
            # Expand home URL
            home_ti.Expand()
            await wait_for_download_to_start_and_finish(mw.task_tree)
            assert first_child_of_tree_item_is_not_loading_condition(home_ti)()
            
            # Select the Atom Feed link from the home URL
            atom_feed_ti = home_ti.find_child(atom_feed_url, project.default_url_prefix)  # ensure did find sub-resource
            atom_feed_ti.SelectItem()
            
            # Create a root resource to label the link
            if True:
                assert mw.new_root_url_button.Enabled
                click_button(mw.new_root_url_button)
                nud = await NewRootUrlDialog.wait_for()
                nud.do_not_download_immediately()
                
                # Ensure prepopulates reasonable information
                assert atom_feed_url == nud.url_field.Value  # default pattern = (from resource)
                assert 'Feed' == nud.name_field.Value  # default name = (from first text link)
                #assert 'Home' == nud.source  # default source = (from resource parent)
                assert nud.url_field.HasFocus  # default focused field
                
                # Input new name
                nud.name_field.Value = 'Atom Feed'
                
                await nud.ok()
            
            # 1. Ensure the new root resource does now label the link
            # 2. Ensure the labeled link is selected immediately after closing the add URL dialog
            atom_feed_ti = home_ti.find_child(atom_feed_url, project.default_url_prefix)  # ensure did find sub-resource
            assert (
                # title format of labeled sub-resource
                f'{urlparse(atom_feed_url).path} - Atom Feed' ==
                atom_feed_ti.Text)
            assert atom_feed_ti.IsSelected()
            
            # Forget the root resource to unlabel the link
            if True:
                assert atom_feed_ti.IsSelected()
                assert mw.forget_button.IsEnabled()
                click_button(mw.forget_button)
                
                # 1. Ensure can find the unlabeled link
                # 2. Ensure that unlabeled link is selected immediately after forgetting the root resource
                atom_feed_ti = home_ti.find_child(atom_feed_url, project.default_url_prefix)  # ensure did find sub-resource
                assert (
                    # title format of unlabeled sub-resource
                    f'{urlparse(atom_feed_url).path} - Unknown Link (rel=alternate), Link: Feed, Link: Atom Feed' ==
                    atom_feed_ti.Text)
                assert atom_feed_ti.IsSelected()


@skip('covered by: test_given_resource_node_with_links_can_create_new_root_url_to_label_link')
async def test_given_resource_node_with_link_labeled_as_root_url_can_easily_forget_the_root_url_to_unlabel_the_link() -> None:
    pass


# === Test: New URL Options ===

async def test_when_add_url_then_downloads_url_immediately_by_default() -> None:
    with _served_simple_site_with_2_urls() as (home_url, _):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            assert mw.new_root_url_button.Enabled
            click_button(mw.new_root_url_button)
            nud = await NewRootUrlDialog.wait_for()
            
            assert nud.download_immediately_checkbox.Value
            
            nud.url_field.Value = home_url
            await nud.ok()
            
            # Ensure started downloading
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            home_ti = root_ti.find_child(home_url, project.default_url_prefix)
            await wait_for_download_to_start_and_finish(mw.task_tree)
            await _assert_tree_item_icon_tooltip_contains(home_ti, 'Fresh')


async def test_when_add_url_then_can_avoid_downloading_url_with_1_extra_click() -> None:
    with _served_simple_site_with_2_urls() as (home_url, _):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            assert mw.new_root_url_button.Enabled
            click_button(mw.new_root_url_button)
            nud = await NewRootUrlDialog.wait_for()
            
            nud.url_field.Value = home_url
            click_checkbox(nud.download_immediately_checkbox)  # extra click #1
            assert not nud.download_immediately_checkbox.Value
            await nud.ok()
            
            # Ensure did NOT start downloading
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            home_ti = root_ti.find_child(home_url, project.default_url_prefix)
            assert tree_has_no_children_condition(mw.task_tree)()
            await _assert_tree_item_icon_tooltip_contains(home_ti, 'Undownloaded')


async def test_when_add_url_at_site_root_then_can_download_site_with_1_extra_click() -> None:
    with _served_simple_site_with_2_urls() as (home_url, _), scheduler_disabled():
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                assert mw.new_root_url_button.Enabled
                click_button(mw.new_root_url_button)
                nud = await NewRootUrlDialog.wait_for()
                
                nud.url_field.Value = home_url  # at site root
                assert nud.download_immediately_checkbox.Value
                assert nud.create_group_checkbox.Enabled
                click_checkbox(nud.create_group_checkbox)  # extra click #1
                assert nud.create_group_checkbox.Value
                await nud.ok()
                append_deferred_top_level_tasks(project)
                
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                home_ti = root_ti.find_child(home_url, project.default_url_prefix)
                site_g = root_ti.find_child(home_url + '**', project.default_url_prefix)
                (download_rg_task,) = project.root_task.children
                assert isinstance(download_rg_task, DownloadResourceGroupTask)
                # (Do NOT wait for group to finish downloading)


async def test_when_add_url_not_at_site_root_then_cannot_download_site_or_create_group_for_site() -> None:
    with _served_simple_site_with_2_urls() as (home_url, image_url):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            assert mw.new_root_url_button.Enabled
            click_button(mw.new_root_url_button)
            nud = await NewRootUrlDialog.wait_for()
            
            nud.url_field.Value = image_url  # NOT at site root
            assert not nud.create_group_checkbox.Enabled
            await nud.cancel()


async def test_when_add_url_at_site_root_then_can_create_group_for_site_but_not_download_it_with_extra_clicks() -> None:
    with _served_simple_site_with_2_urls() as (home_url, _), scheduler_disabled():
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                assert mw.new_root_url_button.Enabled
                click_button(mw.new_root_url_button)
                nud = await NewRootUrlDialog.wait_for()
                
                nud.url_field.Value = home_url  # at site root
                assert nud.create_group_checkbox.Enabled
                click_checkbox(nud.create_group_checkbox)  # extra click #1
                assert nud.create_group_checkbox.Value
                click_checkbox(nud.download_immediately_checkbox)  # extra click #2
                assert not nud.download_immediately_checkbox.Value
                await nud.ok()
                append_deferred_top_level_tasks(project)
                
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                home_ti = root_ti.find_child(home_url, project.default_url_prefix)
                site_g = root_ti.find_child(home_url + '**', project.default_url_prefix)
                () = project.root_task.children


async def test_when_edit_url_then_new_url_options_not_shown() -> None:
    with _served_simple_site_with_2_urls() as (home_url, _):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            rr = RootResource(project, 'Home', Resource(project, home_url))
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            home_ti = root_ti.find_child(home_url, project.default_url_prefix)
            home_ti.SelectItem()
            
            assert mw.edit_button.Enabled
            click_button(mw.edit_button)
            nud = await NewRootUrlDialog.wait_for()
            
            assert not nud.new_options_shown
            await nud.cancel()


@contextmanager
def _served_simple_site_with_2_urls() -> Iterator[tuple[str, str]]:
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=b'<img src="/assets/image.png" />'
        ),
        '/assets/image.png': dict(
            status_code=200,
            headers=[('Content-Type', 'image/png')],
            content=b''
        )
    })
    with server:
        home_url = server.get_url('/')
        image_url = server.get_url('/assets/image.png')
        
        yield (home_url, image_url)


# === Test: Default URL Prefix: Load/Save ===

async def test_when_new_url_and_save_given_project_prefix_is_unset_then_sets_prefix_to_domain() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Case 1: HTTP URL
        assert None == project.default_url_prefix
        if True:
            assert mw.new_root_url_button.Enabled
            click_button(mw.new_root_url_button)
            nud = await NewRootUrlDialog.wait_for()
            nud.do_not_download_immediately()
            
            nud.url_field.Value = 'https://xkcd.com/'
            await nud.ok()
        assert 'https://xkcd.com' == project.default_url_prefix
        
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        rrn = root_ti.find_child('https://xkcd.com/', project.default_url_prefix)
        await mw.entity_tree.clear_default_domain_from_entity_at_tree_item(rrn)
        
        # Case 2: Non-HTTP URL
        assert None == project.default_url_prefix
        if True:
            assert mw.new_root_url_button.Enabled
            click_button(mw.new_root_url_button)
            nud = await NewRootUrlDialog.wait_for()
            nud.do_not_download_immediately()
            
            nud.url_field.Value = 'mailto:me@example.com'
            await nud.ok()
        assert None == project.default_url_prefix


async def test_when_new_url_and_save_given_project_prefix_is_set_then_maintains_prefix() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        rr1 = RootResource(project, '', Resource(project, 'https://neocities.org/'))
        rr2 = RootResource(project, '', Resource(project, 'https://neocities.org/~distantskies/'))
        
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        rrn1 = root_ti.find_child(rr1.resource.url, project.default_url_prefix)
        rrn2 = root_ti.find_child(rr2.resource.url, project.default_url_prefix)
        
        await mw.entity_tree.set_default_domain_to_entity_at_tree_item(rrn1)
        
        assert 'https://neocities.org' == project.default_url_prefix
        if True:
            assert mw.new_root_url_button.Enabled
            click_button(mw.new_root_url_button)
            nud = await NewRootUrlDialog.wait_for()
            nud.do_not_download_immediately()
            
            nud.url_field.Value = 'https://xkcd.com/'
            await nud.ok()
        assert 'https://neocities.org' == project.default_url_prefix


async def test_when_edit_url_and_save_then_maintains_prefix() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        rr1 = RootResource(project, '', Resource(project, 'https://neocities.org/'))
        rr2 = RootResource(project, '', Resource(project, 'https://neocities.org/~distantskies/'))
        rr3 = RootResource(project, '', Resource(project, 'https://xkcd.com/'))
        
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        rrn1 = root_ti.find_child(rr1.resource.url, project.default_url_prefix)
        rrn2 = root_ti.find_child(rr2.resource.url, project.default_url_prefix)
        rrn3 = root_ti.find_child(rr3.resource.url, project.default_url_prefix)
        
        assert None == project.default_url_prefix
        for rrn in [rrn1, rrn2, rrn3]:
            if True:
                rrn.SelectItem()
                assert mw.edit_button.Enabled
                click_button(mw.edit_button)
                nud = await NewRootUrlDialog.wait_for()
                
                await nud.ok()
            assert None == project.default_url_prefix
        
        await mw.entity_tree.set_default_domain_to_entity_at_tree_item(rrn1)
        assert 'https://neocities.org' == project.default_url_prefix
        for rrn in [rrn1, rrn2, rrn3]:
            if True:
                rrn.SelectItem()
                assert mw.edit_button.Enabled
                click_button(mw.edit_button)
                nud = await NewRootUrlDialog.wait_for()
                
                await nud.ok()
            assert 'https://neocities.org' == project.default_url_prefix
        
        await mw.entity_tree.set_default_directory_to_entity_at_tree_item(rrn2)
        assert 'https://neocities.org/~distantskies' == project.default_url_prefix
        for rrn in [rrn1, rrn2, rrn3]:
            if True:
                rrn.SelectItem()
                assert mw.edit_button.Enabled
                click_button(mw.edit_button)
                nud = await NewRootUrlDialog.wait_for()
                
                await nud.ok()
            assert 'https://neocities.org/~distantskies' == project.default_url_prefix


async def test_when_new_url_and_set_prefix_to_x_and_save_then_sets_prefix_to_x() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        
        # Case 1.1: given_project_prefix_is_unset, set_prefix_to_domain
        assert None == project.default_url_prefix
        if True:
            assert mw.new_root_url_button.Enabled
            click_button(mw.new_root_url_button)
            nud = await NewRootUrlDialog.wait_for()
            nud.do_not_download_immediately()
            
            nud.url_field.Value = 'https://neocities.org/'
            
            click_button(nud.options_button)
            assert (True, False) == (
                nud.set_as_default_domain_checkbox.Value,
                nud.set_as_default_directory_checkbox.Value
            )
            await nud.ok()
        assert 'https://neocities.org' == project.default_url_prefix
        
        rrn = root_ti.find_child('https://neocities.org/', project.default_url_prefix)
        await mw.entity_tree.clear_default_domain_from_entity_at_tree_item(rrn)
        rrn.SelectItem()
        click_button(mw.forget_button)
        
        # Case 1.2: given_project_prefix_is_unset, set_prefix_to_directory
        assert None == project.default_url_prefix
        if True:
            assert mw.new_root_url_button.Enabled
            click_button(mw.new_root_url_button)
            nud = await NewRootUrlDialog.wait_for()
            nud.do_not_download_immediately()
            
            nud.url_field.Value = 'https://neocities.org/~distantskies/'
            
            click_button(nud.options_button)
            assert (True, False) == (
                nud.set_as_default_domain_checkbox.Value,
                nud.set_as_default_directory_checkbox.Value
            )
            click_checkbox(nud.set_as_default_directory_checkbox)
            assert (False, True) == (
                nud.set_as_default_domain_checkbox.Value,
                nud.set_as_default_directory_checkbox.Value
            )
            await nud.ok()
        assert 'https://neocities.org/~distantskies' == project.default_url_prefix
        
        rrn = root_ti.find_child('https://neocities.org/~distantskies/', project.default_url_prefix)
        await mw.entity_tree.clear_default_directory_from_entity_at_tree_item(rrn)
        rrn.SelectItem()
        click_button(mw.forget_button)
        
        project.default_url_prefix = 'https://xkcd.com'
        
        # Case 2.1: given_project_prefix_is_set, set_prefix_to_domain
        assert 'https://xkcd.com' == project.default_url_prefix
        if True:
            assert mw.new_root_url_button.Enabled
            click_button(mw.new_root_url_button)
            nud = await NewRootUrlDialog.wait_for()
            nud.do_not_download_immediately()
            
            nud.url_field.Value = 'https://neocities.org/'
            
            click_button(nud.options_button)
            assert (False, False) == (
                nud.set_as_default_domain_checkbox.Value,
                nud.set_as_default_directory_checkbox.Value
            )
            click_checkbox(nud.set_as_default_domain_checkbox)
            assert (True, False) == (
                nud.set_as_default_domain_checkbox.Value,
                nud.set_as_default_directory_checkbox.Value
            )
            await nud.ok()
        assert 'https://neocities.org' == project.default_url_prefix
        
        # Case 2.2: given_project_prefix_is_set, set_prefix_to_directory
        assert 'https://neocities.org' == project.default_url_prefix
        if True:
            assert mw.new_root_url_button.Enabled
            click_button(mw.new_root_url_button)
            nud = await NewRootUrlDialog.wait_for()
            nud.do_not_download_immediately()
            
            nud.url_field.Value = 'https://neocities.org/~distantskies/'
            
            click_button(nud.options_button)
            assert (False, False) == (
                nud.set_as_default_domain_checkbox.Value,
                nud.set_as_default_directory_checkbox.Value
            )
            click_checkbox(nud.set_as_default_directory_checkbox)
            assert (False, True) == (
                nud.set_as_default_domain_checkbox.Value,
                nud.set_as_default_directory_checkbox.Value
            )
            await nud.ok()
        assert 'https://neocities.org/~distantskies' == project.default_url_prefix


async def test_when_edit_url_and_set_prefix_to_x_and_save_then_sets_prefix_to_x() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        rr = RootResource(project, '', Resource(project, 'https://neocities.org/~distantskies/'))
        
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        rrn = root_ti.find_child(rr.resource.url, project.default_url_prefix)
        
        # Case 1: set_prefix_to_domain
        rrn.SelectItem()
        if True:
            assert mw.edit_button.Enabled
            click_button(mw.edit_button)
            nud = await NewRootUrlDialog.wait_for()
            
            click_button(nud.options_button)
            assert (False, False) == (
                nud.set_as_default_domain_checkbox.Value,
                nud.set_as_default_directory_checkbox.Value
            )
            click_checkbox(nud.set_as_default_domain_checkbox)
            assert (True, False) == (
                nud.set_as_default_domain_checkbox.Value,
                nud.set_as_default_directory_checkbox.Value
            )
            await nud.ok()
        assert 'https://neocities.org' == project.default_url_prefix
        
        # Case 2: set_prefix_to_directory
        rrn.SelectItem()
        if True:
            assert mw.edit_button.Enabled
            click_button(mw.edit_button)
            nud = await NewRootUrlDialog.wait_for()
            
            click_button(nud.options_button)
            assert (True, False) == (
                nud.set_as_default_domain_checkbox.Value,
                nud.set_as_default_directory_checkbox.Value
            )
            click_checkbox(nud.set_as_default_directory_checkbox)
            assert (False, True) == (
                nud.set_as_default_domain_checkbox.Value,
                nud.set_as_default_directory_checkbox.Value
            )
            await nud.ok()
        assert 'https://neocities.org/~distantskies' == project.default_url_prefix
        
        # Case 3: unset_prefix
        rrn.SelectItem()
        if True:
            assert mw.edit_button.Enabled
            click_button(mw.edit_button)
            nud = await NewRootUrlDialog.wait_for()
            
            click_button(nud.options_button)
            assert (False, True) == (
                nud.set_as_default_domain_checkbox.Value,
                nud.set_as_default_directory_checkbox.Value
            )
            click_checkbox(nud.set_as_default_directory_checkbox)
            assert (False, False) == (
                nud.set_as_default_domain_checkbox.Value,
                nud.set_as_default_directory_checkbox.Value
            )
            await nud.ok()
        assert None == project.default_url_prefix
        
        # Case 4: Non-HTTP URL
        rr2 = RootResource(project, '', Resource(project, 'mailto:me@example.com'))
        rrn2 = root_ti.find_child(rr2.resource.url, project.default_url_prefix)
        rrn2.SelectItem()
        if True:
            assert mw.edit_button.Enabled
            click_button(mw.edit_button)
            nud = await NewRootUrlDialog.wait_for()
            
            click_button(nud.options_button)
            assert (False, False) == (
                nud.set_as_default_domain_checkbox.Enabled,
                nud.set_as_default_directory_checkbox.Enabled
            )
            assert (False, False) == (
                nud.set_as_default_domain_checkbox.Value,
                nud.set_as_default_directory_checkbox.Value
            )
            await nud.ok()
        assert None == project.default_url_prefix


# === Test: URL Input -> Candidate URLs ===

def test_given_empty_string_then_returns_empty_string() -> None:
    with _EXPAND_enabled():
        assertEqual([''], EXPAND(''))


@with_subtests
def test_given_any_valid_url_then_returns_that_url_as_only_candidate(subtests: SubtestsContext) -> None:
    VALID_URLS = [
        'https://xkcd.com/',
        'https://xkcd.com/1/',
        'https://www.apple.com/',
        'https://www.apple.com/mac/',
        'http://localhost:8000/',
        'http://localhost:8000/logout',
        'ftp://ftp.apple.com/',
        'mailto:me@example.com',
    ]
    with _EXPAND_enabled():
        for url in VALID_URLS:
            with subtests.test(url=url):
                assertEqual([url], EXPAND(url))


@with_subtests
def test_given_a_url_that_would_be_valid_with_appended_slash_then_returns_that_modified_url_as_only_candidate(subtests: SubtestsContext) -> None:
    VALID_WITH_SLASH_URLS = [
        'https://xkcd.com',
        'https://www.apple.com',
        'http://localhost:8000',
    ]
    with _EXPAND_enabled():
        for url in VALID_WITH_SLASH_URLS:
            with subtests.test(url=url):
                assertEqual([url + '/'], EXPAND(url))


@with_subtests
def test_given_schemaless_url_without_www_prefix_then_returns_that_url_plus_that_url_with_www_as_candidates(subtests: SubtestsContext) -> None:
    CASES = [
        ('xkcd.com/', ['https://xkcd.com/', 'https://www.xkcd.com/']),
        ('apple.com/', ['https://apple.com/', 'https://www.apple.com/']),
    ]
    with _EXPAND_enabled():
        for (input, output) in CASES:
            with subtests.test(input=input):
                _assert_contains_sublist(EXPAND(input), output)


@with_subtests
def test_given_schemaless_url_with_www_prefix_then_returns_that_url_plus_that_url_without_www_as_candidates(subtests: SubtestsContext) -> None:
    CASES = [
        ('www.xkcd.com/', ['https://www.xkcd.com/', 'https://xkcd.com/']),
        ('www.apple.com/', ['https://www.apple.com/', 'https://apple.com/']),
    ]
    with _EXPAND_enabled():
        for (input, output) in CASES:
            with subtests.test(input=input):
                _assert_contains_sublist(EXPAND(input), output)


@with_subtests
def test_given_schemaless_url_then_returns_https_and_http_candidate_variations_of_url(subtests: SubtestsContext) -> None:
    CASES = [
        ('xkcd.com/', ['https://xkcd.com/', 'http://xkcd.com/']),
        ('www.apple.com/', ['https://www.apple.com/', 'http://www.apple.com/']),
        
        ('xkcd.com/1/', ['https://xkcd.com/1/', 'http://xkcd.com/1/']),
        ('www.apple.com/mac/', ['https://www.apple.com/mac/', 'http://www.apple.com/mac/']),
        
        ('xkcd.com', ['https://xkcd.com/', 'http://xkcd.com/']),
        ('www.apple.com', ['https://www.apple.com/', 'http://www.apple.com/']),
    ]
    with _EXPAND_enabled():
        for (input, output) in CASES:
            with subtests.test(input=input):
                _assert_contains_sublist(EXPAND(input), output)


def test_given_schemaless_url_without_www_prefix_then_returns_ellipsis() -> None:
    (input, output) = ('xkcd.com', ['https://xkcd.com/', 'https://www.xkcd.com/', 'http://xkcd.com/', 'http://www.xkcd.com/'])
    with _EXPAND_enabled():
        _assert_contains_sublist(EXPAND(input), output)


def test_given_schemaless_url_with_www_prefix_then_returns_ellipsis() -> None:
    (input, output) = ('www.apple.com', ['https://www.apple.com/', 'https://apple.com/', 'http://www.apple.com/', 'http://apple.com/'])
    with _EXPAND_enabled():
        _assert_contains_sublist(EXPAND(input), output)


# === Test: Validate URL upon Blur ===

async def test_given_url_input_is_empty_and_focused_when_tab_pressed_then_url_input_unfocused_and_url_input_empty_and_no_spinner_visible() -> None:
    async with _new_root_url_dialog_open() as (nud, project):
        if fields_hide_hint_when_focused():
            SetFocus(nud.url_field, None)
        else:
            assertEqual(True, nud.url_field_focused)
        assertEqual(False, nud.url_cleaner_spinner.IsShown())
        assertEqual('', nud.url_field.Value)
        
        SetFocus(nud.name_field, nud.url_field)  # simulate press tab
        assertEqual(False, nud.url_field_focused)
        assertEqual(False, nud.url_cleaner_spinner.IsShown())
        assertEqual('', nud.url_field.Value)


@awith_subtests
async def test_given_url_input_is_nonempty_and_focused_when_tab_pressed_then_url_input_unfocused_and_spinner_appears(subtests: SubtestsContext) -> None:
    URLS = [
        'xkcd.com',
        'www.apple.com',
    ]
    async with _new_root_url_dialog_open() as (nud, project):
        with _urlopen_responding_with(_UrlOpenHttpResponse(code=404, url=ANY)):
            for url in URLS:
                with subtests.test(url=url):
                    if fields_hide_hint_when_focused():
                        SetFocus(nud.url_field, None)
                    nud.url_field.Value = url
                    
                    SetFocus(nud.name_field, nud.url_field)  # simulate press tab
                    assertEqual(False, nud.url_field_focused)
                    assertEqual(True, nud.url_cleaner_spinner.IsShown())
                    
                    SetFocus(nud.url_field, nud.name_field)  # simulate press shift-tab
                    assertEqual(True, nud.url_field_focused)
                    await wait_for(lambda: (False == nud.url_cleaner_spinner.IsShown()) or None)


# === Test: Resolve URL ===

@awith_subtests
async def test_given_url_input_is_nonempty_and_did_press_tab_and_spinner_is_visible_when_url_responds_with_http_200_then_spinner_disappears(subtests: SubtestsContext) -> None:
    CASES = [
        ('xkcd.com', 'https://xkcd.com/'),
        ('www.apple.com', 'https://www.apple.com/'),
    ]
    async with _new_root_url_dialog_open() as (nud, project):
        last_focused = None  # type: Optional[wx.Window]
        for (url, normalized_url) in CASES:
            with subtests.test(url=url):
                # NOTE: Fail if requests any URL beyond the original one
                with _urlopen_responding_with({url: _UrlOpenHttpResponse(code=200, url=url)}):
                    last_focused = SetFocus(nud.url_field, last_focused)
                    nud.url_field.Value = url
                    
                    last_focused = SetFocus(nud.name_field, last_focused)  # simulate press tab
                    assertEqual(False, nud.url_field_focused)
                    assertEqual(True, nud.url_cleaner_spinner.IsShown())
                    await wait_for(lambda: (False == nud.url_cleaner_spinner.IsShown()) or None)
                    assertEqual(normalized_url, nud.url_field.Value)


@awith_subtests
async def test_given_url_input_is_nonempty_without_www_and_did_press_tab_and_spinner_is_visible_when_url_responds_with_http_3xx_to_url_with_www_and_url_with_www_url_responds_with_http_200_then_url_input_replaced_with_url_with_www_and_spinner_disappears(subtests: SubtestsContext) -> None:
    CASES = [
        ('apple.com/mac/', 'https://apple.com/mac/', 'https://www.apple.com/mac/'),
        ('apple.com/', 'https://apple.com/', 'https://www.apple.com/'),
        ('apple.com', 'https://apple.com/', 'https://www.apple.com/'),
    ]
    async with _new_root_url_dialog_open() as (nud, project):
        last_focused = None  # type: Optional[wx.Window]
        for (url_input, without_www_url, with_www_url) in CASES:
            with subtests.test(url_input=url_input):
                with _urlopen_responding_with({
                        without_www_url: _UrlOpenHttpResponse(code=200, url=with_www_url)}):
                    last_focused = SetFocus(nud.url_field, last_focused)
                    nud.url_field.Value = url_input
                    
                    last_focused = SetFocus(nud.name_field, last_focused)  # simulate press tab
                    assertEqual(False, nud.url_field_focused)
                    assertEqual(True, nud.url_cleaner_spinner.IsShown())
                    await wait_for(lambda: (False == nud.url_cleaner_spinner.IsShown()) or None)
                    assertEqual(with_www_url, nud.url_field.Value)


@awith_subtests
async def test_given_url_input_is_nonempty_with_www_and_did_press_tab_and_spinner_is_visible_when_url_responds_with_http_3xx_to_url_without_www_and_url_without_www_responds_with_http_200_then_url_input_replaced_with_url_without_www_and_spinner_disappears(subtests: SubtestsContext) -> None:
    CASES = [
        ('www.xkcd.com/1/', 'https://www.xkcd.com/1/', 'https://xkcd.com/1/'),
        ('www.xkcd.com/', 'https://www.xkcd.com/', 'https://xkcd.com/'),
        ('www.xkcd.com', 'https://www.xkcd.com/', 'https://xkcd.com/'),
    ]
    async with _new_root_url_dialog_open() as (nud, project):
        last_focused = None  # type: Optional[wx.Window]
        for (url_input, with_www_url, without_www_url) in CASES:
            with subtests.test(url_input=url_input):
                with _urlopen_responding_with({
                        with_www_url: _UrlOpenHttpResponse(code=200, url=without_www_url)}):
                    last_focused = SetFocus(nud.url_field, last_focused)
                    nud.url_field.Value = url_input
                    
                    last_focused = SetFocus(nud.name_field, last_focused)  # simulate press tab
                    assertEqual(False, nud.url_field_focused)
                    assertEqual(True, nud.url_cleaner_spinner.IsShown())
                    await wait_for(lambda: (False == nud.url_cleaner_spinner.IsShown()) or None)
                    assertEqual(without_www_url, nud.url_field.Value)


@awith_subtests
async def test_given_url_input_is_nonempty_and_did_press_tab_and_spinner_is_visible_when_url_responds_with_http_3xx_to_unrelated_url_then_spinner_disappears(subtests: SubtestsContext) -> None:
    CASES = [
        ('contoso.com/', 'https://contoso.com/', 'https://www.microsoft.com/'),
    ]
    async with _new_root_url_dialog_open() as (nud, project):
        last_focused = None  # type: Optional[wx.Window]
        for (start_url, normalized_start_url, target_url) in CASES:
            with subtests.test(url_input=start_url):
                with _urlopen_responding_with({
                        start_url: _UrlOpenHttpResponse(code=200, url=target_url)}):
                    last_focused = SetFocus(nud.url_field, last_focused)
                    nud.url_field.Value = start_url
                    
                    last_focused = SetFocus(nud.name_field, last_focused)  # simulate press tab
                    assertEqual(False, nud.url_field_focused)
                    assertEqual(True, nud.url_cleaner_spinner.IsShown())
                    await wait_for(lambda: (False == nud.url_cleaner_spinner.IsShown()) or None)
                    assertEqual(normalized_start_url, nud.url_field.Value)


# === Test: Concurrent Actions While Resolving URL & Allow Create Root URL ===

async def test_given_url_input_is_unfocused_and_spinner_is_visible_when_focus_url_input_then_spinner_disappears() -> None:
    # TODO: Respond with "unreachable error" to be more realistic
    with _urlopen_responding_with(_UrlOpenHttpResponse(code=500, url=ANY)):
        with _urlopen_paused():
            async with _new_root_url_dialog_open() as (nud, project):
                last_focused = None  # type: Optional[wx.Window]
                
                last_focused = SetFocus(nud.url_field, last_focused)
                nud.url_field.Value = '1.99.1.99'  # arbitrary IP
                
                last_focused = SetFocus(nud.name_field, last_focused)  # simulate press tab
                assertEqual(False, nud.url_field_focused)
                assertEqual(True, nud.url_cleaner_spinner.IsShown())
                
                last_focused = SetFocus(nud.url_field, last_focused)  # simulate press shift-tab
                assertEqual(True, nud.url_field_focused)
                await wait_for(lambda: (False == nud.url_cleaner_spinner.IsShown()) or None)
                
                nud.url_field.Value = '2.99.2.99'  # arbitrary different IP
                
                last_focused = SetFocus(nud.name_field, last_focused)  # simulate press tab
                assertEqual(False, nud.url_field_focused)
                assertEqual(True, nud.url_cleaner_spinner.IsShown())


async def test_given_url_input_is_nonempty_and_did_press_tab_and_spinner_is_visible_when_press_ok_then_disables_all_controls_except_cancel() -> None:
    with _urlopen_responding_with(_UrlOpenHttpResponse(code=200, url=ANY)):
        async with _new_root_url_dialog_open() as (nud, project):
            last_focused = None  # type: Optional[wx.Window]
            
            with _urlopen_paused():
                last_focused = SetFocus(nud.url_field, last_focused)
                nud.url_field.Value = '1.99.1.99'  # arbitrary IP
                
                last_focused = SetFocus(nud.name_field, last_focused)  # simulate press tab
                assertEqual(False, nud.url_field_focused)
                assertEqual(True, nud.url_cleaner_spinner.IsShown())
                
                nud.name_field.Value = 'Home'
                
                click_button(nud.ok_button)
                assertEqual(False, nud.url_field.Enabled)
                assertEqual(False, nud.name_field.Enabled)
                assertEqual(False, nud.ok_button.Enabled)
                assertEqual(True, nud.cancel_button.Enabled)
            
            await wait_for(lambda: (False == nud.shown) or None)
            
            r = project.get_resource('https://1.99.1.99/')
            assert r is not None
            rr = project.get_root_resource(r)
            assert rr is not None
            assertEqual('Home', rr.name)


@skip('covered by: test_given_url_input_is_nonempty_and_did_press_tab_and_spinner_is_visible_when_press_ok_then_disables_all_controls_except_cancel')
async def test_given_url_input_is_nonempty_and_did_press_tab_and_spinner_is_visible_and_did_press_ok_when_spinner_disappears_then_dialog_disappears_and_root_url_is_created() -> None:
    pass


async def test_given_url_input_is_nonempty_and_did_press_tab_and_spinner_is_visible_and_did_press_ok_when_press_cancel_then_dialog_disappears() -> None:
    with _urlopen_responding_with(_UrlOpenHttpResponse(code=200, url=ANY)):
        async with _new_root_url_dialog_open() as (nud, project):
            last_focused = None  # type: Optional[wx.Window]
            
            with _urlopen_paused():
                last_focused = SetFocus(nud.url_field, last_focused)
                nud.url_field.Value = '1.99.1.99'  # arbitrary IP
                
                last_focused = SetFocus(nud.name_field, last_focused)  # simulate press tab
                assertEqual(False, nud.url_field_focused)
                assertEqual(True, nud.url_cleaner_spinner.IsShown())
                
                click_button(nud.ok_button)
                assertEqual(False, nud.url_field.Enabled)
                assertEqual(False, nud.name_field.Enabled)
                assertEqual(False, nud.ok_button.Enabled)
                assertEqual(True, nud.cancel_button.Enabled)
                
                click_button(nud.cancel_button)
            
            await wait_for(lambda: (False == nud.shown) or None)
            
            r = project.get_resource('https://1.99.1.99/')
            assert r is None


async def test_given_url_input_is_unfocused_and_spinner_is_not_visible_when_press_ok_then_dialog_disappears_and_root_url_is_created() -> None:
    with _urlopen_responding_with(_UrlOpenHttpResponse(code=200, url=ANY)):
        async with _new_root_url_dialog_open() as (nud, project):
            last_focused = None  # type: Optional[wx.Window]
            
            last_focused = SetFocus(nud.url_field, last_focused)
            nud.url_field.Value = 'xkcd.com'
            
            last_focused = SetFocus(nud.name_field, last_focused)  # simulate press tab
            assertEqual(False, nud.url_field_focused)
            assertEqual(True, nud.url_cleaner_spinner.IsShown())
            
            nud.name_field.Value = 'Home'
            
            await wait_for(lambda: (False == nud.url_cleaner_spinner.IsShown()) or None)
            
            click_button(nud.ok_button)
            assertEqual(False, nud.shown)
            
            r = project.get_resource('https://xkcd.com/')
            assert r is not None
            rr = project.get_root_resource(r)
            assert rr is not None
            assertEqual('Home', rr.name)


async def test_given_url_input_is_focused_and_spinner_is_not_visible_when_press_ok_then_dialog_disappears_and_root_url_is_created() -> None:
    with _urlopen_responding_with(_UrlOpenHttpResponse(code=200, url=ANY)):
        async with _new_root_url_dialog_open() as (nud, project):
            last_focused = None  # type: Optional[wx.Window]
            
            last_focused = SetFocus(nud.url_field, last_focused)
            nud.url_field.Value = 'xkcd.com'
            
            click_button(nud.ok_button)
            await wait_for(lambda: (False == nud.shown) or None)
            
            r = project.get_resource('https://xkcd.com/')
            assert r is not None
            rr = project.get_root_resource(r)
            assert rr is not None


async def test_given_url_input_is_focused_and_spinner_is_not_visible_when_press_cancel_then_dialog_disappears() -> None:
    with _urlopen_responding_with(_UrlOpenHttpResponse(code=200, url=ANY)):
        async with _new_root_url_dialog_open() as (nud, project):
            last_focused = None  # type: Optional[wx.Window]
            
            last_focused = SetFocus(nud.url_field, last_focused)
            nud.url_field.Value = 'xkcd.com'
            
            click_button(nud.cancel_button)
            await wait_for(lambda: (False == nud.shown) or None)
            
            r = project.get_resource('https://xkcd.com/')
            assert r is None


async def test_given_url_input_is_unfocused_when_is_focused_and_is_unfocused_then_spinner_does_not_appear() -> None:
    with _urlopen_responding_with(_UrlOpenHttpResponse(code=200, url=ANY)):
        async with _new_root_url_dialog_open() as (nud, project):
            last_focused = None  # type: Optional[wx.Window]
            
            last_focused = SetFocus(nud.url_field, last_focused)
            nud.url_field.Value = 'xkcd.com'
            
            last_focused = SetFocus(nud.name_field, last_focused)  # simulate press tab
            assertEqual(False, nud.url_field_focused)
            assertEqual(True, nud.url_cleaner_spinner.IsShown())
            
            nud.name_field.Value = 'Home'
            
            await wait_for(lambda: (False == nud.url_cleaner_spinner.IsShown()) or None)
            assertEqual('https://xkcd.com/', nud.url_field.Value)
            
            last_focused = SetFocus(nud.url_field, last_focused)  # simulate press shift-tab
            
            last_focused = SetFocus(nud.name_field, last_focused)  # simulate press tab
            assertEqual(False, nud.url_field_focused)
            assertEqual(False, nud.url_cleaner_spinner.IsShown())


# === Test: Disallow Create Empty Root URL ===

async def test_given_url_input_is_empty_then_ok_button_is_disabled() -> None:
    async with _new_root_url_dialog_open() as (nud, project):
        assertEqual('', nud.url_field.Value)
        assertEqual(False, nud.ok_button.Enabled)
        
        last_focused = None  # type: Optional[wx.Window]
        
        last_focused = SetFocus(nud.url_field, last_focused)
        nud.url_field.Value = 'xkcd.com'
        assertEqual(True, nud.ok_button.Enabled)
        
        last_focused = SetFocus(nud.name_field, last_focused)  # simulate press tab
        assertEqual(True, nud.ok_button.Enabled)
        
        last_focused = SetFocus(nud.url_field, last_focused)  # simulate press shift-tab
        assertEqual(True, nud.ok_button.Enabled)
        
        nud.url_field.Value = ''
        assertEqual(False, nud.ok_button.Enabled)


@skip('covered by: test_given_url_input_is_empty_then_ok_button_is_disabled')
async def test_given_url_input_is_empty_when_url_input_becomes_nonempty_then_ok_button_is_enabled() -> None:
    pass


@skip('covered by: test_given_url_input_is_empty_then_ok_button_is_disabled')
async def test_given_url_input_is_nonempty_when_url_input_becomes_empty_then_ok_button_is_disabled() -> None:
    pass


# === Test: Disallow Create Duplicate Root URL ===

@awith_subtests
async def test_given_url_input_matches_existing_root_url_when_press_ok_then_displays_error_dialog_and_enables_all_controls(subtests: SubtestsContext) -> None:
    with _urlopen_responding_with(_UrlOpenHttpResponse(code=200, url=ANY)):
        with subtests.test(case='given url input is focused'):
            async with _new_root_url_dialog_open() as (nud, project):
                r = Resource(project, 'https://xkcd.com/')
                RootResource(project, '', r)
                
                last_focused = None  # type: Optional[wx.Window]
                
                last_focused = SetFocus(nud.url_field, last_focused)
                nud.url_field.Value = 'xkcd.com/'
                
                with patch(
                        'crystal.browser.new_root_url.ShowModal',
                        mocked_show_modal('cr-root-url-exists', wx.ID_OK)
                        ) as show_modal_method:
                    click_button(nud.ok_button)
                    await wait_for(lambda: (1 == show_modal_method.call_count) or None)
                    await wait_for(lambda: (True == nud.url_field.Enabled) or None)
                assertEqual(True, nud.url_field.Enabled)
                assertEqual(True, nud.name_field.Enabled)
                assertEqual(True, nud.ok_button.Enabled)
                assertEqual(True, nud.cancel_button.Enabled)
        
        with subtests.test(case='given url input is unfocused and spinner is visible'):
            async with _new_root_url_dialog_open() as (nud, project):
                r = Resource(project, 'https://xkcd.com/')
                RootResource(project, '', r)
                
                last_focused = None
                
                last_focused = SetFocus(nud.url_field, last_focused)
                nud.url_field.Value = 'xkcd.com/'
                
                last_focused = SetFocus(nud.name_field, last_focused)  # simulate press tab
                assertEqual(False, nud.url_field_focused)
                assertEqual(True, nud.url_cleaner_spinner.IsShown())
                
                with patch(
                        'crystal.browser.new_root_url.ShowModal',
                        mocked_show_modal('cr-root-url-exists', wx.ID_OK)
                        ) as show_modal_method:
                    click_button(nud.ok_button)
                    await wait_for(lambda: (1 == show_modal_method.call_count) or None)
                    await wait_for(lambda: (True == nud.url_field.Enabled) or None)
                assertEqual(True, nud.url_field.Enabled)
                assertEqual(True, nud.name_field.Enabled)
                assertEqual(True, nud.ok_button.Enabled)
                assertEqual(True, nud.cancel_button.Enabled)
        
        with subtests.test(case='given url input is unfocused and spinner is not visible'):
            async with _new_root_url_dialog_open() as (nud, project):
                r = Resource(project, 'https://xkcd.com/')
                RootResource(project, '', r)
                
                last_focused = None
                
                last_focused = SetFocus(nud.url_field, last_focused)
                nud.url_field.Value = 'xkcd.com/'
                
                last_focused = SetFocus(nud.name_field, last_focused)  # simulate press tab
                assertEqual(False, nud.url_field_focused)
                assertEqual(True, nud.url_cleaner_spinner.IsShown())
                
                await wait_for(lambda: (False == nud.url_cleaner_spinner.IsShown()) or None)
                
                with patch(
                        'crystal.browser.new_root_url.ShowModal',
                        mocked_show_modal('cr-root-url-exists', wx.ID_OK)
                        ) as show_modal_method:
                    click_button(nud.ok_button)
                    await wait_for(lambda: (1 == show_modal_method.call_count) or None)
                    await wait_for(lambda: (True == nud.url_field.Enabled) or None)
                assertEqual(True, nud.url_field.Enabled)
                assertEqual(True, nud.name_field.Enabled)
                assertEqual(True, nud.ok_button.Enabled)
                assertEqual(True, nud.cancel_button.Enabled)


# === Utility ===

@contextmanager
def _EXPAND_enabled() -> Iterator[None]:
    old_value = os.environ.get('CRYSTAL_URLOPEN_MOCKED', 'False')
    os.environ['CRYSTAL_URLOPEN_MOCKED'] = 'True'
    try:
        yield
    finally:
        os.environ['CRYSTAL_URLOPEN_MOCKED'] = old_value


@asynccontextmanager
async def _new_root_url_dialog_open(*,
        autoclose: bool=True
        ) -> AsyncIterator[tuple[NewRootUrlDialog, Project]]:
    # Never allow automated tests to make real internet requests
    with _urlopen_responding_with(_UrlOpenHttpResponse(code=590, url=ANY)):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            click_button(mw.new_root_url_button)
            nud = await NewRootUrlDialog.wait_for()
            nud.do_not_download_immediately()
            
            try:
                yield (nud, project)
            finally:
                if autoclose and nud.shown:
                    await nud.cancel()


@contextmanager
def _urlopen_responding_with(responses: 'Union[_UrlOpenHttpResponse, Dict[str, _UrlOpenHttpResponse]]') -> Iterator[None]:
    with _EXPAND_enabled():
        def mock_urlopen(url: str, timeout: float=0):
            if isinstance(responses, _UrlOpenHttpResponse):
                return responses
            else:
                try:
                    return responses[url]
                except IndexError:
                    return _UrlOpenHttpResponse(code=591, url=url)
        
        with patch('crystal.url_input.urlopen', mock_urlopen):
            yield


class _UrlOpenHttpResponse:
    def __init__(self, code: int, url: str) -> None:
        self._code = code
        self._url = url
    
    def __enter__(self) -> Self:
        return self
    
    def __exit__(self, *args) -> None:
        pass
    
    def getcode(self) -> int:
        return self._code
    
    def geturl(self) -> str:
        return self._url


@contextmanager
def _urlopen_paused() -> Iterator[None]:
    paused = True
    waiting = False
    done = False
    
    original_func = crystal.url_input.urlopen  # capture
    
    def pausable_urlopen(url: str, timeout: float=0):
        nonlocal done
        
        waiting = True
        while paused:
            time.sleep(DEFAULT_WAIT_PERIOD)
        
        result = original_func(url, timeout=timeout)
        
        waiting = False
        done = True
        return result
    
    with patch('crystal.url_input.urlopen', pausable_urlopen):
        yield
        paused = False
        if waiting:
            while not done:
                time.sleep(DEFAULT_WAIT_PERIOD)


def _assert_contains_sublist(xs: list[str], ys: list[str]) -> None:
    last_index = -1
    for y in ys:
        try:
            last_index = xs.index(y, last_index + 1)
        except IndexError:
            raise AssertionError(f'Expected list {xs} to contain sublist {ys} but it does not')


# NOTE: Only for use with tree items in EntityTree
_assert_tree_item_icon_tooltip_contains = EntityTree.assert_tree_item_icon_tooltip_contains
