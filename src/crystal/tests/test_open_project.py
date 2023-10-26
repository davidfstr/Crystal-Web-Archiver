from crystal import progress
import crystal.main
from crystal.model import Project
from crystal.progress import CancelOpenProject
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import extracted_project
from crystal.tests.util.skip import skipTest
from crystal.tests.util.subtests import SubtestsContext, awith_subtests
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.xos import is_linux, is_mac_os, is_windows
import os.path
from unittest import skip
from unittest.mock import patch
import wx


@skip('not yet automated: hard to automate')
async def test_given_macos_when_double_click_crystalproj_package_in_finder_then_opens_projects() -> None:
    pass


async def test_given_macos_when_open_crystalproj_package_in_open_dialog_then_opens_project() -> None:
    if not is_mac_os():
        skipTest('only supported on macOS')
    
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        ocd = await OpenOrCreateDialog.wait_for()
        async with ocd.open(project_dirpath, using_crystalopen=False) as mw:
            pass


@skip('not yet automated: hard to automate')
async def test_given_windows_when_double_click_crystalproj_directory_in_explorer_then_opens_projects() -> None:
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
        assert os.path.exists(os.path.join(project_dirpath, Project._LAUNCHER_DEFAULT_FILENAME))
        
        ocd = await OpenOrCreateDialog.wait_for()
        async with ocd.open(project_dirpath, using_crystalopen=True) as mw:
            pass


@skip('not yet automated: hard to automate')
async def test_given_linux_when_open_crystalproj_directory_and_double_click_crystalopen_file_in_file_explorer_then_opens_project() -> None:
    pass


async def test_given_linux_when_open_crystalproj_directory_in_open_dialog_then_opens_project() -> None:
    if not is_linux():
        skipTest('only supported on Linux')
    
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        assert not os.path.exists(os.path.join(project_dirpath, Project._LAUNCHER_DEFAULT_FILENAME))
        
        # Simulate effect of:
        # 1. Press "Open" button to open the "Choose a project" dialog
        # 2. Select a .crystalproj directory. "Open Directory" button undims.
        # 3. Press "Open Directory" button
        ocd = await OpenOrCreateDialog.wait_for()
        async with ocd.open(project_dirpath, using_crystalopen=False) as mw:
            pass


async def test_given_linux_when_open_crystalproj_directory_and_double_click_crystalopen_file_in_open_dialog_then_opens_project() -> None:
    if not is_linux():
        skipTest('only supported on Linux')
    
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        with Project(project_dirpath):
            pass
        assert os.path.exists(os.path.join(project_dirpath, Project._LAUNCHER_DEFAULT_FILENAME))
        
        ocd = await OpenOrCreateDialog.wait_for()
        async with ocd.open(project_dirpath, using_crystalopen=True) as mw:
            pass


@awith_subtests
async def test_given_project_opening_when_click_cancel_then_returns_to_prompt_dialog(
        subtests: SubtestsContext) -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        for method_name in [
                # Case 1: Cancel while creating Project object
                'loading_resource',
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
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as mw:
            project = Project._last_opened_project
            assert project is not None
            
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
