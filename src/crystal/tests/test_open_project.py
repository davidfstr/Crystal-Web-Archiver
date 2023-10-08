from crystal import progress
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
