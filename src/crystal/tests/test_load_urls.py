from crystal.model import Project, Resource, ResourceGroup
from crystal.progress import CancelLoadUrls
# TODO: Consider extracting serve_and_fetch_xkcd_home_page() to utility module
from crystal.tests.test_server import serve_and_fetch_xkcd_home_page
from crystal.tests.util.controls import click_button, TreeItem
from crystal.tests.util.server import extracted_project, served_project
from crystal.tests.util.ssd import database_on_ssd
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util.tasks import wait_for_download_to_start_and_finish
from crystal.tests.util.wait import (
    first_child_of_tree_item_is_not_loading_condition,
    tree_has_no_children_condition, wait_for,
)
from crystal.tests.util.windows import NewGroupDialog, OpenOrCreateDialog
from unittest import skip
from unittest.mock import patch

# === Test: Database not on SSD ===

async def test_given_project_database_not_on_ssd_when_expanding_first_resource_group_node_in_entity_tree_then_loading_urls_progress_dialog_becomes_visible_and_shows_loading_node() -> None:
    with database_on_ssd(False):
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as (mw, project):
                comic_group = project.get_resource_group('Comics')
                assert comic_group is not None
                
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                
                (comic_group_ti,) = (
                    child for child in root_ti.Children
                    if child.Text.endswith(f'- {comic_group.name}')
                )
                
                # Prepare to press Cancel when LoadUrlsProgressDialog appears
                with patch.object(
                        project._load_urls_progress_listener,
                        'loading_resource',
                        side_effect=CancelLoadUrls) as progress_listener_method:
                    comic_group_ti.Expand()
                    
                    # Ensure shows loading node initially
                    assert True == comic_group_ti.IsExpanded()
                    child = comic_group_ti.GetFirstChild()
                    assert child is not None and child.Text == 'Loading...'
                    
                    # Ensure hides loading node after pressing Cancel
                    await wait_for(lambda: (progress_listener_method.call_count >= 1) or None)
                    await wait_for(lambda: True if not comic_group_ti.IsExpanded() else None)


@skip('covered by: test_given_project_database_not_on_ssd_when_expanding_first_resource_group_node_in_entity_tree_then_loading_urls_progress_dialog_becomes_visible_and_shows_loading_node')
async def test_given_project_database_not_on_ssd_given_expanding_first_resource_group_node_in_entity_tree_and_loading_urls_progress_dialog_is_visible_when_press_cancel_then_hides_dialog_and_hides_loading_node() -> None:
    pass


async def test_given_project_database_not_on_ssd_given_resource_group_node_selected_when_press_download_button_then_loading_urls_progress_dialog_becomes_visible() -> None:
    with database_on_ssd(False):
        with served_project('testdata_xkcd.crystalproj.zip') as sp:
            # Define URLs
            atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
            rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
            feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                # Create small resource group (with only 2 members)
                Resource(project, atom_feed_url)
                Resource(project, rss_feed_url)
                feed_group = ResourceGroup(project, 'Feed', feed_pattern)
                
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                
                (feed_group_ti,) = (
                    child for child in root_ti.Children
                    if child.Text.endswith(f'- {feed_group.name}')
                )
                
                # Prepare to press Cancel when LoadUrlsProgressDialog appears
                with patch.object(
                        project._load_urls_progress_listener,
                        'loading_resource',
                        side_effect=CancelLoadUrls) as progress_listener_method:
                    feed_group_ti.SelectItem()
                    click_button(mw.download_button)
                    
                    # Wait for progress dialog to show and for cancel to be pressed
                    await wait_for(lambda: (progress_listener_method.call_count >= 1) or None)
                    
                    # Ensure did not create a download task
                    assert tree_has_no_children_condition(mw.task_tree)() is not None


@skip('covered by: test_given_project_database_not_on_ssd_given_resource_group_node_selected_when_press_download_button_then_loading_urls_progress_dialog_becomes_visible')
async def test_given_project_database_not_on_ssd_given_resource_group_node_selected_and_did_press_download_button_and_loading_urls_progress_dialog_is_visible_when_press_cancel_then_hides_dialog() -> None:
    pass


async def test_given_project_database_not_on_ssd_when_press_new_group_button_then_loading_urls_progress_dialog_becomes_visible() -> None:
    with database_on_ssd(False):
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                # Prepare to press Cancel when LoadUrlsProgressDialog appears
                with patch.object(
                        project._load_urls_progress_listener,
                        'loading_resource',
                        side_effect=CancelLoadUrls) as progress_listener_method:
                    click_button(mw.new_group_button)
                    
                    # Wait for progress dialog to show and for cancel to be pressed
                    await wait_for(lambda: (progress_listener_method.call_count >= 1) or None)
                    
                    # Ensure did not show NewGroupDialog
                    assert NewGroupDialog.window_condition()() is None


@skip('covered by: test_given_project_database_not_on_ssd_when_press_new_group_button_then_loading_urls_progress_dialog_becomes_visible')
async def test_given_project_database_not_on_ssd_given_did_press_new_group_button_and_loading_urls_progress_dialog_is_visible_when_press_cancel_then_hides_dialog_and_add_group_dialog_does_not_appear() -> None:
    pass


# === Test: Database on SSD ===

async def test_given_project_database_on_ssd_when_expanding_any_resource_group_node_in_entity_tree_then_shows_loading_node() -> None:
    with database_on_ssd(True):
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as (mw, project):
                comic_group = project.get_resource_group('Comics')
                assert comic_group is not None
                
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                
                (comic_group_ti,) = (
                    child for child in root_ti.Children
                    if child.Text.endswith(f'- {comic_group.name}')
                )
                
                # Prepare to spy on whether LoadUrlsProgressDialog appears
                with patch.object(
                        project._load_urls_progress_listener,
                        'loading_resource',
                        wraps=project._load_urls_progress_listener.loading_resource) as progress_listener_method:
                    comic_group_ti.Expand()
                    
                    # Ensure shows loading node initially
                    assert True == comic_group_ti.IsExpanded()
                    child = comic_group_ti.GetFirstChild()
                    assert child is not None and child.Text == 'Loading...'
                    
                    # Wait for expand to complete
                    await wait_for(first_child_of_tree_item_is_not_loading_condition(comic_group_ti))
                    
                    # Ensure did not show LoadUrlsProgressDialog
                    assert 0 == progress_listener_method.call_count


async def test_given_project_database_on_ssd_given_resource_group_node_selected_when_press_download_button_then_download_task_has_subtitle_loading() -> None:
    with database_on_ssd(True):
        with served_project('testdata_xkcd.crystalproj.zip') as sp:
            # Define URLs
            atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
            rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
            feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                # Create small resource group (with only 2 members)
                Resource(project, atom_feed_url)
                Resource(project, rss_feed_url)
                feed_group = ResourceGroup(project, 'Feed', feed_pattern)
                
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                
                (feed_group_ti,) = (
                    child for child in root_ti.Children
                    if child.Text.endswith(f'- {feed_group.name}')
                )
                
                # Prepare to spy on whether LoadUrlsProgressDialog appears
                with patch.object(
                        project._load_urls_progress_listener,
                        'loading_resource',
                        wraps=project._load_urls_progress_listener.loading_resource) as progress_listener_method:
                    feed_group_ti.SelectItem()
                    
                    # Wait for download to start and complete
                    await mw.click_download_button()
                    await wait_for_download_to_start_and_finish(mw.task_tree)
                    
                    # Ensure did not show LoadUrlsProgressDialog
                    assert 0 == progress_listener_method.call_count


async def test_given_project_database_on_ssd_when_press_new_group_button_then_add_group_dialog_does_appear() -> None:
    with database_on_ssd(True):
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                # Prepare to spy on whether LoadUrlsProgressDialog appears
                with patch.object(
                        project._load_urls_progress_listener,
                        'loading_resource',
                        wraps=project._load_urls_progress_listener.loading_resource) as progress_listener_method:
                    click_button(mw.new_group_button)
                    
                    # Wait for NewGroupDialog to appear
                    ngd = await NewGroupDialog.wait_for()
                    
                    # Ensure did not show LoadUrlsProgressDialog
                    assert 0 == progress_listener_method.call_count
                    
                    click_button(ngd.cancel_button)


# === Test: No Load Required ===

@awith_subtests
async def test_serve_url_never_requires_loading_urls(subtests: SubtestsContext) -> None:
    for is_ssd in [False, True]:
        with subtests.test(is_ssd=is_ssd), database_on_ssd(is_ssd):
            with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
                # Define URLs
                home_url = 'https://xkcd.com/'
                
                async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as (mw, project):
                    root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                    
                    (home_ti,) = (
                        child for child in root_ti.Children
                        if child.Text.endswith(f'- Home')
                    )
                    
                    # Prepare to spy on whether LoadUrlsProgressDialog appears
                    with patch.object(
                            project._load_urls_progress_listener,
                            'loading_resource',
                            wraps=project._load_urls_progress_listener.loading_resource) as progress_listener_method:
                        # 1. Start server
                        # 2. Fetch page
                        (server_page, _) = await serve_and_fetch_xkcd_home_page(mw)
                        assert 200 == server_page.status
                        
                        # Ensure did not show LoadUrlsProgressDialog
                        assert 0 == progress_listener_method.call_count
