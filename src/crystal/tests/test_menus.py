from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from crystal.model import Project, Resource, RootResource
from crystal.tests.util.cli import (
    create_new_empty_project, py_eval, crystal_shell,
)
from crystal.tests.util.controls import file_dialog_returning
from crystal.tests.util.server import extracted_project
from crystal.tests.util.wait import wait_for
from crystal.tests.util.windows import MainWindow, OpenOrCreateDialog
import crystal.tests.util.xtempfile as xtempfile
from crystal.util.wx_dialog import mocked_show_modal
import os.path
import textwrap
from unittest import skip
from unittest.mock import patch
import wx


# === Test: New Project ===

async def test_can_create_project_with_menuitem_given_clean_untitled_project_visible() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw1, project1):
        await mw1.start_new_project_with_menuitem()
        
        # (OpenOrCreateDialog will briefly appear)
        
        await _wait_for_main_window_to_reopen_to_untitled_project(project1)


async def test_can_create_project_with_menuitem_given_dirty_untitled_project_visible() -> None:
    # Case 1: Don't Save the current project
    async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw1, project1):
        # Create a RootResource to make the project dirty
        RootResource(project1, '', Resource(project1, 'https://example.com/'))
        
        with patch('crystal.browser.ShowModal',
                mocked_show_modal('cr-save-changes-dialog', wx.ID_NO)):
            await mw1.start_new_project_with_menuitem()
            
            # (Save changes dialog will be shown and "Don't Save" will be clicked)
            # (OpenOrCreateDialog will briefly appear)
            
            await _wait_for_main_window_to_reopen_to_untitled_project(project1)
    
    # Case 2: Save the current project
    async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw1, project1):
        # Create a RootResource to make the project dirty
        RootResource(project1, '', Resource(project1, 'https://example.com/'))
        
        with xtempfile.TemporaryDirectory() as tmp_dir:
            save_path = os.path.join(tmp_dir, 'TestProject.crystalproj')
            with file_dialog_returning(save_path):
                with patch('crystal.browser.ShowModal',
                        mocked_show_modal('cr-save-changes-dialog', wx.ID_YES)):
                    await mw1.start_new_project_with_menuitem()
                    
                    # (Save changes dialog will be shown and "Save" will be clicked)
                    # (Save file dialog will be shown and populated)
                    # (OpenOrCreateDialog will briefly appear)
                    
                    await _wait_for_main_window_to_reopen_to_untitled_project(project1)

    # Case 3: Cancel close of the current project
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw1, project1):
        # Create a RootResource to make the project dirty
        RootResource(project1, '', Resource(project1, 'https://example.com/'))
        
        with patch('crystal.browser.ShowModal',
                mocked_show_modal('cr-save-changes-dialog', wx.ID_CANCEL)):
            await mw1.start_new_project_with_menuitem()
            
            # (Save changes dialog will be shown and "Cancel" will be clicked)
            # (Project 1 should remain open)
            
            # Verify that project 1 is still the active project
            assert Project._last_opened_project is project1
        
        # (Close project 1)


async def test_can_create_project_with_menuitem_given_titled_project_visible() -> None:
    with xtempfile.TemporaryDirectory() as tmp_dir:
        # Create a titled project
        project1_dirpath = os.path.join(tmp_dir, 'Project1.crystalproj')
        with Project(project1_dirpath) as project1:
            pass
        
        # Open the titled project
        async with (await OpenOrCreateDialog.wait_for()).open(project1_dirpath, autoclose=False) as (mw1, project1):
            await mw1.start_new_project_with_menuitem()
            
            # (OpenOrCreateDialog will briefly appear)
            
            await _wait_for_main_window_to_reopen_to_untitled_project(project1)


async def _wait_for_main_window_to_reopen_to_untitled_project(project1: Project) -> None:
    async with _wait_for_main_window_to_reopen(project1) as project2:
        # Ensure the 2nd project was actually opened
        assert project2.is_untitled


# === Test: Open Project ===

async def test_can_open_project_with_menuitem_given_clean_untitled_project_visible() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project2_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw1, project1):
            with file_dialog_returning(project2_dirpath):
                await mw1.start_open_project_with_menuitem()
                
                # (OpenOrCreateDialog will briefly appear)
                # (Open file dialog will be shown and populated)
                
                await _wait_for_main_window_to_reopen_to_xkcd_project(project1)


async def test_can_open_project_with_menuitem_given_dirty_untitled_project_visible() -> None:
    # Extract a project 2, for use in the following cases
    with extracted_project('testdata_xkcd.crystalproj.zip') as project2_dirpath:
        
        # Case 1: Don't Save the current project
        async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw1, project1):
            # Create a RootResource to make the project dirty
            RootResource(project1, '', Resource(project1, 'https://example.com/'))
            
            with file_dialog_returning(project2_dirpath):
                with patch('crystal.browser.ShowModal',
                        mocked_show_modal('cr-save-changes-dialog', wx.ID_NO)):
                    await mw1.start_open_project_with_menuitem()
                    
                    # (Save changes dialog will be shown and "Don't Save" will be clicked)
                    # (OpenOrCreateDialog will briefly appear)
                    # (Open file dialog will be shown and populated)
                    
                    await _wait_for_main_window_to_reopen_to_xkcd_project(project1)
        
        # Case 2: Save the current project
        async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw1, project1):
            # Create a RootResource to make the project dirty
            RootResource(project1, '', Resource(project1, 'https://example.com/'))
            
            with xtempfile.TemporaryDirectory() as tmp_dir:
                save_path = os.path.join(tmp_dir, 'TestProject.crystalproj')
                with file_dialog_returning([save_path, project2_dirpath]):
                    with patch('crystal.browser.ShowModal',
                            mocked_show_modal('cr-save-changes-dialog', wx.ID_YES)):
                        await mw1.start_open_project_with_menuitem()
                        
                        # (Save changes dialog will be shown and "Save" will be clicked)
                        # (Save file dialog will be shown and populated)
                        # (OpenOrCreateDialog will briefly appear)
                        # (Open file dialog will be shown and populated)
                        
                        await _wait_for_main_window_to_reopen_to_xkcd_project(project1)

        # Case 3: Cancel close of the current project
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw1, project1):
            # Create a RootResource to make the project dirty
            RootResource(project1, '', Resource(project1, 'https://example.com/'))
            
            with patch('crystal.browser.ShowModal',
                    mocked_show_modal('cr-save-changes-dialog', wx.ID_CANCEL)):
                await mw1.start_open_project_with_menuitem()
                
                # (Save changes dialog will be shown and "Cancel" will be clicked)
                # (Project 1 should remain open)
                
                # Verify that project 1 is still the active project
                assert Project._last_opened_project is project1
            
            # (Close project 1)


async def test_can_open_project_with_menuitem_given_titled_project_visible() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project2_dirpath:
        with xtempfile.TemporaryDirectory() as tmp_dir:
            # Create a titled project
            project1_dirpath = os.path.join(tmp_dir, 'Project1.crystalproj')
            with Project(project1_dirpath) as project1:
                pass
            
            # Open the titled project
            async with (await OpenOrCreateDialog.wait_for()).open(project1_dirpath, autoclose=False) as (mw1, project1):
                with file_dialog_returning(project2_dirpath):
                    await mw1.start_open_project_with_menuitem()
                    
                    # (OpenOrCreateDialog will briefly appear)
                    # (Open file dialog will be shown and populated)
                    
                    await _wait_for_main_window_to_reopen_to_xkcd_project(project1)


async def _wait_for_main_window_to_reopen_to_xkcd_project(project1: Project) -> None:
    async with _wait_for_main_window_to_reopen(project1) as project2:
        # Ensure the 2nd project was actually opened
        assert project2.get_root_resource(url='https://xkcd.com/') is not None


@asynccontextmanager
async def _wait_for_main_window_to_reopen(project1: Project) -> AsyncIterator[Project]:
    # Wait for new MainWindow to appear
    def new_mw_is_visible() -> bool:
        new_project = Project._last_opened_project
        return new_project is not None and new_project is not project1
    await wait_for(
        lambda: new_mw_is_visible() or None,
        timeout=OpenOrCreateDialog._TIMEOUT_FOR_OPEN_MAIN_WINDOW)
    mw2 = await MainWindow.wait_for(timeout=OpenOrCreateDialog._TIMEOUT_FOR_OPEN_MAIN_WINDOW)
    try:
        project2 = Project._last_opened_project
        assert project2 is not None
        
        yield project2
    finally:
        await mw2.close()


# === Test: Close Project ===

async def test_can_close_project_with_menuitem_given_clean_untitled_project_visible() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw, _):
        await mw.start_close_project_with_menuitem()
    
    await OpenOrCreateDialog.wait_for()


async def test_can_close_project_with_menuitem_given_dirty_untitled_project_visible() -> None:
    # Case 1: Don't Save the current project
    async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw1, project1):
        # Create a RootResource to make the project dirty
        RootResource(project1, '', Resource(project1, 'https://example.com/'))
        
        with patch('crystal.browser.ShowModal',
                mocked_show_modal('cr-save-changes-dialog', wx.ID_NO)):
            await mw1.start_close_project_with_menuitem()
            
            # (Save changes dialog will be shown and "Don't Save" will be clicked)
            
            await OpenOrCreateDialog.wait_for()
    
    # Case 2: Save the current project
    async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw1, project1):
        # Create a RootResource to make the project dirty
        RootResource(project1, '', Resource(project1, 'https://example.com/'))
        
        with xtempfile.TemporaryDirectory() as tmp_dir:
            save_path = os.path.join(tmp_dir, 'TestProject.crystalproj')
            with file_dialog_returning(save_path):
                with patch('crystal.browser.ShowModal',
                        mocked_show_modal('cr-save-changes-dialog', wx.ID_YES)):
                    await mw1.start_close_project_with_menuitem()
                    
                    # (Save changes dialog will be shown and "Save" will be clicked)
                    # (Save file dialog will be shown and populated)
                    
                    await OpenOrCreateDialog.wait_for()

    # Case 3: Cancel close of the current project
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw1, project1):
        # Create a RootResource to make the project dirty
        RootResource(project1, '', Resource(project1, 'https://example.com/'))
        
        with patch('crystal.browser.ShowModal',
                mocked_show_modal('cr-save-changes-dialog', wx.ID_CANCEL)):
            await mw1.start_close_project_with_menuitem()
            
            # (Save changes dialog will be shown and "Cancel" will be clicked)
            # (Project 1 should remain open)
            
            # Verify that project 1 is still the active project
            assert Project._last_opened_project is project1
        
        # (Close project 1)


async def test_can_close_project_with_menuitem_given_titled_project_visible() -> None:
    with xtempfile.TemporaryDirectory() as tmp_dir:
        # Create a titled project
        project1_dirpath = os.path.join(tmp_dir, 'Project1.crystalproj')
        with Project(project1_dirpath) as project1:
            pass
        
        # Open the titled project
        async with (await OpenOrCreateDialog.wait_for()).open(project1_dirpath, autoclose=False) as (mw1, project1):
            await mw1.start_close_project_with_menuitem()
            
        await OpenOrCreateDialog.wait_for()

# === Test: Quit ===

async def test_can_quit_with_menuitem() -> None:
    with crystal_shell() as (crystal, _):
        create_new_empty_project(crystal)
        
        py_eval(crystal,
            textwrap.dedent(f'''\
                from crystal.tests.util.runner import run_test
                from crystal.tests.util.windows import MainWindow
                from threading import Thread
                import wx

                async def quit_with_menuitem():
                    mw = await MainWindow.wait_for()
                    #
                    await mw.quit_with_menuitem()
                    #
                    print('OK')

                t = Thread(target=lambda: run_test(quit_with_menuitem))
                t.start()
                '''
            ),
            stop_suffix=('crystal.util.xthreading.NoForegroundThreadError\n',),
            timeout=3.0)  # took 4.4s on macOS ASAN CI (after 2x multiplier)


# === Test: Preferences... ===

async def test_can_open_preferences_with_menuitem() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
        prefs_dialog = await mw.open_preferences_with_menuitem()
        await prefs_dialog.ok()
