from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from crystal import resources
from crystal.model import (
    Project, Resource, ResourceGroup, ResourceRevision, RootResource,
)
from crystal.server import ProjectServer
from crystal.tests.util.controls import click_button, TreeItem
from crystal.tests.util.runner import bg_fetch_url
from crystal.tests.util.server import (
    assert_does_open_webbrowser_to, extracted_project,
    served_project_from_filepath,
)
from crystal.tests.util.tasks import wait_for_download_to_start_and_finish
from crystal.tests.util.wait import (
    first_child_of_tree_item_is_not_loading_condition, wait_for,
)
from crystal.tests.util.windows import (
    EntityTree, MainWindow, OpenOrCreateDialog,
)
import os
import tempfile
from unittest import skip
from unittest.mock import ANY

# All of the following tests have the implicit prefix:
# - test_given_html_page_links_to_embedded_resource_in_a_do_not_download_group...


async def test_when_download_html_page_then_does_not_download_embedded_resource_automatically() -> None:
    async with _project_with_do_not_download_group_open() as (
            mw, project, home_url, comic_image_rg_pattern, comic_image_r_url):
        # Download HTML page
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        home_ti = root_ti.GetFirstChild()
        assert home_ti is not None
        home_ti.Expand()
        await wait_for_download_to_start_and_finish(mw.task_tree)
        assert first_child_of_tree_item_is_not_loading_condition(home_ti)()
        
        # Expand HTML page children in entity tree
        comic_image_rg_ti = home_ti.find_child(comic_image_rg_pattern)
        comic_image_rg_ti.Expand()
        await wait_for(first_child_of_tree_item_is_not_loading_condition(comic_image_rg_ti))
        comic_image_rg_ti.find_child(comic_image_r_url)
        
        home_r = project.get_resource(home_url)
        assert home_r is not None
        assert home_r.has_any_revisions()
        
        comic_image_r = project.get_resource(comic_image_r_url)
        assert comic_image_r is not None
        assert not comic_image_r.has_any_revisions()


async def test_then_embedded_resource_does_not_appear_in_a_hidden_embedded_cluster_in_entity_tree() -> None:
    async with _project_with_do_not_download_group_open() as (
            mw, project, home_url, comic_image_rg_pattern, comic_image_r_url):
        # Download HTML page
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        home_ti = root_ti.GetFirstChild()
        assert home_ti is not None
        home_ti.Expand()
        await wait_for_download_to_start_and_finish(mw.task_tree)
        assert first_child_of_tree_item_is_not_loading_condition(home_ti)()
        
        # Expand HTML page children in entity tree
        (hidden_embedded_ti,) = (
            child for child in home_ti.Children
            if child.Text == '(Hidden: Embedded)'
        )
        hidden_embedded_ti.Expand()
        await wait_for(first_child_of_tree_item_is_not_loading_condition(hidden_embedded_ti))
        
        assert None == hidden_embedded_ti.try_find_child(comic_image_r_url)


async def test_when_browse_to_html_page_and_browser_requests_embedded_resource_then_do_not_dynamically_download_embedded_resource_and_instead_return_http_404() -> None:
    async with _project_with_do_not_download_group_open() as (
            mw, project, home_url, comic_image_rg_pattern, comic_image_r_url):
        # Download HTML page
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        home_ti = root_ti.GetFirstChild()
        assert home_ti is not None
        home_ti.SelectItem()
        await mw.click_download_button()
        await wait_for_download_to_start_and_finish(mw.task_tree)
        
        # Start server
        home_ti.SelectItem()
        with assert_does_open_webbrowser_to(ANY):
            click_button(mw.view_button)
        server = ProjectServer._last_created
        assert server is not None
        
        response = await bg_fetch_url(server.get_request_url(comic_image_r_url))
        assert 404 == response.status


async def test_given_embedded_resource_selected_in_entity_tree_when_press_download_button_explicitly_then_downloads_embedded_resource() -> None:
    async with _project_with_do_not_download_group_open() as (
            mw, project, home_url, comic_image_rg_pattern, comic_image_r_url):
        # Download HTML page
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        home_ti = root_ti.GetFirstChild()
        assert home_ti is not None
        home_ti.Expand()
        await wait_for_download_to_start_and_finish(mw.task_tree)
        assert first_child_of_tree_item_is_not_loading_condition(home_ti)()
        
        # Expand HTML page children in entity tree
        comic_image_rg_ti = home_ti.find_child(comic_image_rg_pattern)
        comic_image_rg_ti.Expand()
        await wait_for(first_child_of_tree_item_is_not_loading_condition(comic_image_rg_ti))
        comic_image_r_ti = comic_image_rg_ti.find_child(comic_image_r_url)
        
        comic_image_r = project.get_resource(comic_image_r_url)
        assert comic_image_r is not None
        assert not comic_image_r.has_any_revisions()
        
        comic_image_r_ti.SelectItem()
        await mw.click_download_button(
            # NOTE: May "finish immediately" because has no embedded subresources
            immediate_finish_ok=True)
        await wait_for_download_to_start_and_finish(
            mw.task_tree,
            # NOTE: May "finish immediately" because has no embedded subresources
            immediate_finish_ok=True)
        assert comic_image_r.has_any_revisions()


async def test_given_do_not_download_group_selected_in_entity_tree_when_press_download_button_explicitly_then_downloads_group() -> None:
    async with _project_with_do_not_download_group_open() as (
            mw, project, home_url, comic_image_rg_pattern, comic_image_r_url):
        # Download HTML page
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        home_ti = root_ti.GetFirstChild()
        assert home_ti is not None
        home_ti.SelectItem()
        await mw.click_download_button()
        await wait_for_download_to_start_and_finish(mw.task_tree)
        
        # Expand group children in entity tree
        comic_image_rg_ti = root_ti.find_child(comic_image_rg_pattern)
        comic_image_rg_ti.Expand()
        await wait_for(first_child_of_tree_item_is_not_loading_condition(comic_image_rg_ti))
        comic_image_rg_ti.find_child(comic_image_r_url)
        
        comic_image_r = project.get_resource(comic_image_r_url)
        assert comic_image_r is not None
        assert not comic_image_r.has_any_revisions()
        
        comic_image_rg_ti.SelectItem()
        await mw.click_download_button()
        await wait_for_download_to_start_and_finish(mw.task_tree)
        assert comic_image_r.has_any_revisions()


async def test_then_embedded_resource_in_entity_tree_appears_with_do_not_download_badge() -> None:
    async with _project_with_do_not_download_group_open() as (
            mw, project, home_url, comic_image_rg_pattern, comic_image_r_url):
        # Download HTML page
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        home_ti = root_ti.GetFirstChild()
        assert home_ti is not None
        home_ti.Expand()
        await wait_for_download_to_start_and_finish(mw.task_tree)
        assert first_child_of_tree_item_is_not_loading_condition(home_ti)()
        
        # Expand HTML page children in entity tree
        comic_image_rg_ti = home_ti.find_child(comic_image_rg_pattern)
        comic_image_rg_ti.Expand()
        await wait_for(first_child_of_tree_item_is_not_loading_condition(comic_image_rg_ti))
        comic_image_r_ti = comic_image_rg_ti.find_child(comic_image_r_url)
        
        await _assert_tree_item_icon_tooltip_contains(comic_image_rg_ti, 'Ignored')
        await _assert_tree_item_icon_tooltip_contains(comic_image_r_ti, 'Ignored')
        
        # Expand group children in entity tree
        comic_image_rg_ti = root_ti.find_child(comic_image_rg_pattern)
        comic_image_rg_ti.Expand()
        await wait_for(first_child_of_tree_item_is_not_loading_condition(comic_image_rg_ti))
        comic_image_r_ti = comic_image_rg_ti.find_child(comic_image_r_url)
        
        await _assert_tree_item_icon_tooltip_contains(comic_image_rg_ti, 'Ignored')
        await _assert_tree_item_icon_tooltip_contains(comic_image_r_ti, 'Ignored')
        
        # Test: test_given_embedded_resource_also_in_a_non_do_not_download_group_then_embedded_resource_in_entity_tree_does_not_appear_with_do_not_download_badge
        if True:
            specific_comic_image_rg = ResourceGroup(
                project, 'air_gap_2x.png', comic_image_r_url)
            await _assert_tree_item_icon_tooltip_contains(comic_image_r_ti, 'Undownloaded')
            
            specific_comic_image_rg.delete()
            await _assert_tree_item_icon_tooltip_contains(comic_image_r_ti, 'Ignored')


@skip('covered by: test_then_embedded_resource_in_entity_tree_appears_with_do_not_download_badge')
async def test_then_do_not_download_group_in_entity_tree_appears_with_do_not_download_badge() -> None:
    pass


@skip('covered by: test_then_embedded_resource_in_entity_tree_appears_with_do_not_download_badge')
async def test_given_embedded_resource_also_in_a_non_do_not_download_group_then_embedded_resource_in_entity_tree_does_not_appear_with_do_not_download_badge() -> None:
    pass


async def test_when_reopen_project_then_group_that_was_marked_as_do_not_download_is_still_marked_as_do_not_download() -> None:
    # Define URLs
    comic_image_rg_pattern = 'https://imgs.xkcd.com/comics/*'
    
    # Case 1: New group marked as do_not_download
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        os.rmdir(project_dirpath)
        
        # Create project with do_not_download group
        with Project(project_dirpath) as project:
            comic_image_rg1 = ResourceGroup(
                project, 'Comic Image', comic_image_rg_pattern,
                do_not_download=True)
            assert True == comic_image_rg1.do_not_download
        
        # Reopen project. Ensure group is still marked as do_not_download
        with Project(project_dirpath) as project:
            comic_image_rg2 = project.get_resource_group(name='Comic Image')
            assert comic_image_rg2 is not None
            assert True == comic_image_rg2.do_not_download
    
    # Case 2: Edited group marked as do_not_download
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        os.rmdir(project_dirpath)
        
        # Create project with group. Edit to mark as do_not_download.
        with Project(project_dirpath) as project:
            comic_image_rg1 = ResourceGroup(
                project, 'Comic Image', comic_image_rg_pattern,
                do_not_download=False)
            assert False == comic_image_rg1.do_not_download
            
            comic_image_rg1.do_not_download = True
            assert True == comic_image_rg1.do_not_download
        
        # Reopen project. Ensure group is still marked as do_not_download
        with Project(project_dirpath) as project:
            comic_image_rg2 = project.get_resource_group(name='Comic Image')
            assert comic_image_rg2 is not None
            assert True == comic_image_rg2.do_not_download


# ------------------------------------------------------------------------------
# Utility

@asynccontextmanager
async def _project_with_do_not_download_group_open(
        ) -> AsyncIterator[tuple[MainWindow, Project, str, str, str]]:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        # Add comic image to project,
        # since it's not part of the default project test data
        with Project(project_dirpath) as project1:
            r = Resource(project1, 'https://imgs.xkcd.com/comics/air_gap_2x.png')
            with resources.open_binary('testdata_air_gap_2x.png') as image_stream:
                rr = ResourceRevision.create_from_response(
                    r,
                    metadata=None,
                    body_stream=image_stream)
        
        with served_project_from_filepath(project_dirpath) as sp:
            # Define URLs
            home_url = sp.get_request_url('https://xkcd.com/')
            comic_image_rg_pattern = sp.get_request_url('https://imgs.xkcd.com/comics/*')
            comic_image_r_url = sp.get_request_url('https://imgs.xkcd.com/comics/air_gap_2x.png')
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                # Define entities
                RootResource(project, 'Home', Resource(project, home_url))
                comic_image_rg = ResourceGroup(
                    project, 'Comic Image', comic_image_rg_pattern,
                    do_not_download=True)
                
                yield (mw, project, home_url, comic_image_rg_pattern, comic_image_r_url)


# NOTE: Only for use with tree items in EntityTree
_assert_tree_item_icon_tooltip_contains = EntityTree.assert_tree_item_icon_tooltip_contains


# ------------------------------------------------------------------------------
