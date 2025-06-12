from crystal import progress
import crystal.main
from crystal.model import Project, Resource
from crystal.progress import CancelOpenProject
from crystal.tests.util.controls import TreeItem
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import extracted_project
from crystal.tests.util.skip import skipTest
from crystal.tests.util.ssd import database_on_ssd
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util.wait import (
    first_child_of_tree_item_is_not_loading_condition, wait_for,
)
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.xos import is_linux, is_mac_os, is_windows
import os.path
import tempfile
from unittest import skip
from unittest.mock import call, patch
import wx

# === Test: Create Project ===

async def test_when_create_project_then_shows_dialog_saying_opening_project_but_no_other_messages() -> None:
    ocd = await OpenOrCreateDialog.wait_for()
    
    progress_listener = progress._active_progress_listener
    assert progress_listener is not None
    
    with patch('crystal.progress._DELAY_UNTIL_PROGRESS_DIALOG_SHOWS', 0), \
            patch('crystal.progress.wx.ProgressDialog', autospec=True) as MockProgressDialog:
        pd = MockProgressDialog.return_value
        pd.Pulse.return_value = (True, False)
        pd.Update.return_value = (True, False)
        
        async with ocd.create() as (mw, _):
            pass
        
        assert (
            [call('Opening project...')],
            []
        ) == (
            pd.Pulse.call_args_list,
            pd.Update.call_args_list
        )


async def test_can_create_project_with_url_unsafe_characters() -> None:
    with tempfile.TemporaryDirectory(prefix='original#2', suffix='.crystalproj') as project_dirpath:
        assert '#' in project_dirpath
        
        ocd = await OpenOrCreateDialog.wait_for()
        async with ocd.create(project_dirpath) as (mw, _):
            assert os.path.exists(os.path.join(project_dirpath, Project._DB_FILENAME))


# === Test: Start Open Project ===

@skip('not yet automated: hard to automate')
async def test_given_macos_when_double_click_crystalproj_package_in_finder_then_opens_project() -> None:
    pass


async def test_given_macos_when_open_crystalproj_package_in_open_dialog_then_opens_project() -> None:
    if not is_mac_os():
        skipTest('only supported on macOS')
    
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        ocd = await OpenOrCreateDialog.wait_for()
        async with ocd.open(project_dirpath, using_crystalopen=False) as (mw, project):
            pass


@skip('not yet automated: hard to automate')
async def test_given_windows_when_double_click_crystalproj_directory_in_explorer_then_opens_project() -> None:
    pass


@skip('not yet automated: hard to automate')
async def test_given_windows_when_open_crystalproj_directory_and_double_click_crystalopen_file_in_explorer_then_opens_project() -> None:
    pass


async def test_given_windows_when_open_crystalproj_directory_and_double_click_crystalopen_file_in_open_dialog_then_opens_project() -> None:
    if not is_windows():
        skipTest('only supported on Windows')
    
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        with Project(project_dirpath):
            pass
        assert os.path.exists(os.path.join(project_dirpath, Project._OPENER_DEFAULT_FILENAME))
        
        ocd = await OpenOrCreateDialog.wait_for()
        async with ocd.open(project_dirpath, using_crystalopen=True) as (mw, project):
            pass


@skip('not yet automated: hard to automate')
async def test_given_linux_when_open_crystalproj_directory_and_double_click_crystalopen_file_in_file_explorer_then_opens_project() -> None:
    pass


async def test_given_linux_when_open_crystalproj_directory_in_open_dialog_then_opens_project() -> None:
    if not is_linux():
        skipTest('only supported on Linux')
    
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        assert not os.path.exists(os.path.join(project_dirpath, Project._OPENER_DEFAULT_FILENAME))
        
        # Simulate effect of:
        # 1. Press "Open" button to open the "Choose a project" dialog
        # 2. Select a .crystalproj directory. "Open Directory" button undims.
        # 3. Press "Open Directory" button
        ocd = await OpenOrCreateDialog.wait_for()
        async with ocd.open(project_dirpath, using_crystalopen=False) as (mw, project):
            pass


async def test_given_linux_when_open_crystalproj_directory_and_double_click_crystalopen_file_in_open_dialog_then_opens_project() -> None:
    if not is_linux():
        skipTest('only supported on Linux')
    
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        with Project(project_dirpath):
            pass
        assert os.path.exists(os.path.join(project_dirpath, Project._OPENER_DEFAULT_FILENAME))
        
        ocd = await OpenOrCreateDialog.wait_for()
        async with ocd.open(project_dirpath, using_crystalopen=True) as (mw, project):
            pass


# === Test: While Opening Project ===

@awith_subtests
async def test_given_project_opening_when_click_cancel_then_returns_to_prompt_dialog(
        subtests: SubtestsContext) -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        for method_name in [
                # Case 1: Cancel while creating Project object
                'loading_root_resources',
                # Case 2: Cancel while creating MainWindow object
                'creating_entity_tree_nodes',
                ]:
            with subtests.test(method_name=method_name):
                ocd = await OpenOrCreateDialog.wait_for()
                
                progress_listener = progress._active_progress_listener
                assert progress_listener is not None
                
                with patch.object(progress_listener, method_name, side_effect=CancelOpenProject):
                    await ocd.start_opening(project_dirpath, next_window_name='cr-open-or-create-project')
                    
                    # HACK: Wait minimum duration to allow open to finish
                    await bg_sleep(0.5)
                    
                    ocd = await OpenOrCreateDialog.wait_for()


async def test_given_project_is_corrupt_when_open_project_then_displays_error_dialog() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        # Introduce corruption to the project
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            group = list(project.resource_groups)[0]  # arbitrary
            
            c = project._db.cursor()
            c.execute(
                'update resource_group set source_type = ? where id = ?',
                ('bogus', group._id))
            project._db.commit()
        
        # Try to open that project
        if True:
            # Prepare to: OK
            did_respond_to_invalid_project_dialog = False
            def click_ok_in_invalid_project_dialog(dialog: wx.Dialog) -> int:
                assert 'cr-invalid-project' == dialog.Name
                assert 'may be corrupted' in dialog.Message
                
                nonlocal did_respond_to_invalid_project_dialog
                did_respond_to_invalid_project_dialog = True
                
                return wx.ID_OK
            
            load_project = crystal.main._load_project  # capture
            def patched_load_project(*args, **kwargs) -> Project:
                return load_project(
                    *args,
                    _show_modal_func=click_ok_in_invalid_project_dialog,  # type: ignore[misc]
                    **kwargs)
            
            with patch(f'crystal.main._load_project', patched_load_project):
                ocd = await OpenOrCreateDialog.wait_for()
                await ocd.start_opening(project_dirpath, next_window_name='cr-open-or-create-project')
                
                # HACK: Wait minimum duration to allow open to finish
                await bg_sleep(0.5)
                
                # Wait for cancel and return to initial dialog
                ocd = await OpenOrCreateDialog.wait_for()
                
                assert did_respond_to_invalid_project_dialog


# === Test: After Opening Project ===

async def test_given_project_was_just_opened_then_first_entity_selected() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        home_url = 'https://xkcd.com/'
        
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            home_ti = root_ti.find_child(home_url)
            assert home_ti.IsSelected()
            
            # Ensure can view the downloaded site with 1 click
            assert mw.view_button.Enabled


@awith_subtests
async def test_given_project_was_just_opened_then_no_resources_loaded_except_root_resources(subtests: SubtestsContext) -> None:
    for is_ssd in [False, True]:
        with subtests.test(is_ssd=is_ssd), database_on_ssd(is_ssd):
            with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
                async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                    # Ensure project opens with only root resources loaded
                    assert len(list(project.root_resources)) >= 1
                    resources_that_are_loaded = _sort_resources(
                        _loaded_resources(project))  # capture
                    resources_that_are_root = _sort_resources(
                        [rr.resource for rr in project.root_resources])
                    assert resources_that_are_root == resources_that_are_loaded


async def test_given_on_ssd_when_resource_group_node_expanded_then_only_new_resources_loaded_are_group_members() -> None:
    with database_on_ssd(True):
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                # Ensure when group expanded, only that group's members become loaded
                if True:
                    comic_group = project.get_resource_group('Comics')
                    assert comic_group is not None
                    
                    root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                    
                    (comic_group_ti,) = (
                        child for child in root_ti.Children
                        if child.Text.endswith(f'- {comic_group.name}')
                    )
                    
                    comic_group_ti.Expand()
                    await wait_for(first_child_of_tree_item_is_not_loading_condition(comic_group_ti))
                    
                    assert len(list(comic_group.members)) >= 1
                    resources_that_are_loaded = _sort_resources(
                        _loaded_resources(project))  # capture
                    resources_that_are_root_or_group_members = _sort_resources(
                        [rr.resource for rr in project.root_resources] + list(comic_group.members))
                    assert resources_that_are_root_or_group_members == resources_that_are_loaded, (
                        f'{resources_that_are_root_or_group_members=} but {resources_that_are_loaded=}'
                    )


async def test_given_not_on_ssd_when_resource_group_node_expanded_then_all_project_resources_are_loaded() -> None:
    with database_on_ssd(False):
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                # Ensure when group expanded, all project resources become loaded
                if True:
                    comic_group = project.get_resource_group('Comics')
                    assert comic_group is not None
                    
                    root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                    
                    (comic_group_ti,) = (
                        child for child in root_ti.Children
                        if child.Text.endswith(f'- {comic_group.name}')
                    )
                    
                    comic_group_ti.Expand()
                    await wait_for(first_child_of_tree_item_is_not_loading_condition(comic_group_ti))
                    
                    assert len(list(comic_group.members)) >= 1
                    resources_that_are_loaded = _sort_resources(
                        _loaded_resources(project))  # capture
                    resources_in_project = _sort_resources(
                        list(project.resources))
                    
                    assert resources_in_project == resources_that_are_loaded, (
                        f'{resources_in_project=} but {resources_that_are_loaded=}'
                    )


def _loaded_resources(project: Project) -> list[Resource]:
    # HACK: Use private API
    resource_for_url = project._resource_for_url
    resource_for_id = project._resource_for_id
    assert len(resource_for_url) == len(resource_for_id)
    return list(resource_for_url.values())


def _sort_resources(resources: list[Resource]) -> list[Resource]:
    return sorted(resources, key=lambda r: r._id)
