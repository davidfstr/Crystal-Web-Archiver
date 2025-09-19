from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from crystal.browser import MainWindow as RealMainWindow
from crystal.model import (
    Project, ProjectReadOnlyError, Resource, ResourceGroup, RootResource,
)
from crystal.progress import CancelSaveAs, SaveAsProgressDialog
from crystal.task import DownloadResourceGroupTask, DownloadResourceTask
from crystal.tests.util import xtempfile
from crystal.tests.util.cli import (
    PROJECT_PROXY_REPR_STR, close_main_window, close_open_or_create_dialog, create_new_empty_project, crystal_shell, py_eval, py_eval_literal, wait_for_main_window, _OK_THREAD_STOP_SUFFIX,
)
from crystal.tests.util.controls import (
    TreeItem, file_dialog_returning,
)
from crystal.tests.util.hdiutil import hdiutil_disk_image_mounted
from crystal.tests.util.save_as import (
    save_as_with_ui,
    save_as_without_ui,
    start_save_as_with_ui,
    wait_for_save_as_to_complete,
)
from crystal.tests.util.server import served_project
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util.tasks import (
    append_deferred_top_level_tasks, scheduler_disabled, step_scheduler,
    step_scheduler_until_done,
)
from crystal.tests.util.windows import MainWindow, OpenOrCreateDialog
from crystal.util.db import DatabaseCursor
from crystal.app_preferences import app_prefs
from crystal.util.wx_dialog import mocked_show_modal
from crystal.util.xappdirs import user_untitled_projects_dir
from crystal.util.xos import is_ci, is_linux, is_mac_os, is_windows
from dataclasses import dataclass
import errno
from functools import cache, wraps
import os
import send2trash
import sqlite3
import subprocess
import tempfile
import textwrap
import shutil
from typing import Callable, ContextManager, Never
from unittest import skip, SkipTest
from unittest.mock import MagicMock, patch
import warnings
import wx


# TODO: Reorder the test "===" sections in this file to be in a more logical order,
#       with similar sections grouped together.

# === Decorators ===

def reopen_projects_enabled(test_func):
    """
    Decorator for tests that specifically test auto-reopen functionality.
    
    Temporarily disables the CRYSTAL_NO_REOPEN_PROJECTS environment variable
    and ensures state is cleaned up before and after the test.
    """
    @wraps(test_func)
    async def wrapper(*args, **kwargs):
        # Save original environment state
        original_env_value = os.environ.get('CRYSTAL_NO_REOPEN_PROJECTS')
        
        try:
            # Enable auto-reopen functionality for this test
            if 'CRYSTAL_NO_REOPEN_PROJECTS' in os.environ:
                del os.environ['CRYSTAL_NO_REOPEN_PROJECTS']
            
            # Clean up state before test
            del app_prefs.unsaved_untitled_project_path
            _cleanup_untitled_projects()
            
            # Run the test
            return await test_func(*args, **kwargs)
        finally:
            # Restore original environment state
            if original_env_value is not None:
                os.environ['CRYSTAL_NO_REOPEN_PROJECTS'] = original_env_value
            elif 'CRYSTAL_NO_REOPEN_PROJECTS' in os.environ:
                del os.environ['CRYSTAL_NO_REOPEN_PROJECTS']
            
            # Clean up state after test
            del app_prefs.unsaved_untitled_project_path
            _cleanup_untitled_projects()
    
    return wrapper


# === Untitled Project: Clean/Dirty State Tests ===

async def test_when_untitled_project_created_then_is_clean() -> None:
    with _untitled_project() as project:
        assert False == project.is_dirty


async def test_when_root_resource_created_then_untitled_project_becomes_dirty() -> None:
    with _untitled_project() as project:
        assert False == project.is_dirty
        r = Resource(project, 'https://xkcd.com/')
        assert True == project.is_dirty
        RootResource(project, 'Home', r)
        assert True == project.is_dirty


async def test_when_resource_group_created_then_untitled_project_becomes_dirty() -> None:
    with _untitled_project() as project:
        assert False == project.is_dirty
        ResourceGroup(project, 'Comic', url_pattern='https://xkcd.com/#/')
        assert True == project.is_dirty


async def test_when_resource_revision_downloaded_then_untitled_project_becomes_dirty() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
    
        with _untitled_project() as project:
            assert False == project.is_dirty
            Resource(project, atom_feed_url)
            assert True == project.is_dirty


async def test_when_project_properties_changed_then_untitled_project_becomes_dirty() -> None:
    with _untitled_project() as project:
        assert False == project.is_dirty
        # Change a property
        project.html_parser_type = 'html_parser' if project.html_parser_type != 'html_parser' else 'lxml'
        assert True == project.is_dirty


# === Untitled Project: Save Tests ===

@awith_subtests
async def test_when_untitled_project_saved_then_becomes_clean_and_titled(subtests: SubtestsContext) -> None:
    with scheduler_disabled() as disabled_scheduler, \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        home_url = sp.get_request_url('https://xkcd.com/')
        comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        comic50_url = sp.get_request_url('https://xkcd.com/50/')
        
        assert 1 == disabled_scheduler.start_count
        assert 0 == disabled_scheduler.stop_count
        
        # Test saving an untitled project to a new location on the same filesystem
        with subtests.test(filesystem='same'), \
                _untitled_project() as project, \
                xtempfile.TemporaryDirectory() as new_container_dirpath:
            assert False == project.is_dirty
            assert True == project.is_untitled
            assert 2 == disabled_scheduler.start_count
            
            # Download a resource revision, so that we can test whether it is moved later
            r = Resource(project, atom_feed_url)
            rr_future = r.download()
            await step_scheduler_until_done(project)
            
            assert True == project.is_dirty
            assert True == project.is_untitled
            rr = rr_future.result()
            old_rr_body_filepath = rr._body_filepath  # capture
            assert os.path.exists(old_rr_body_filepath)
            
            # Save untitled project to somewhere on the same filesystem
            old_project_dirpath = project.path  # capture
            old_project_fs = os.stat(old_project_dirpath).st_dev  # capture
            new_project_dirpath = os.path.join(
                new_container_dirpath,
                os.path.basename(old_project_dirpath))
            new_project_fs = os.stat(new_container_dirpath).st_dev
            assert old_project_fs == new_project_fs, (
                'Expected old_project_dirpath and new_project_dirpath to be on the same filesystem: '
                f'{old_project_dirpath=}, {new_container_dirpath=}'
            )
            await save_as_without_ui(project, new_project_dirpath)
            
            assert False == project.is_dirty
            assert False == project.is_untitled
            assert 1 == disabled_scheduler.stop_count
            assert 3 == disabled_scheduler.start_count
            
            # Ensure project was moved to new location
            assert new_project_dirpath != old_project_dirpath
            assert os.path.exists(new_project_dirpath)
            assert not os.path.exists(old_project_dirpath)
            
            # Ensure resource revision was moved to new location
            new_rr_body_filepath = rr._body_filepath
            assert new_rr_body_filepath != old_rr_body_filepath, \
                'Resource revision filepath should have changed after saving untitled project'
            assert os.path.exists(new_rr_body_filepath)
            
            # Ensure can download a new resource revision after moving the project
            r = Resource(project, rss_feed_url)
            rr_future = r.download()
            await step_scheduler_until_done(project)
            
            # Ensure titled projects don't become dirty even when modified
            assert False == project.is_untitled
            assert False == project.is_dirty
        
        # Test saving an untitled project to a new location on a different filesystem
        with subtests.test(filesystem='different'), \
                _untitled_project() as project, \
                _temporary_directory_on_new_filesystem() as new_container_dirpath:
            # Download a resource revision, so that we can test whether it is moved later
            r = Resource(project, atom_feed_url)
            rr_future = r.download()
            await step_scheduler_until_done(project)
            
            rr = rr_future.result()
            old_rr_body_filepath = rr._body_filepath  # capture
            assert os.path.exists(old_rr_body_filepath)
            
            # Save untitled project to somewhere on a different filesystem
            old_project_dirpath = project.path  # capture
            old_project_fs = os.stat(old_project_dirpath).st_dev  # capture
            new_project_dirpath = os.path.join(
                new_container_dirpath,
                os.path.basename(old_project_dirpath))
            new_project_fs = os.stat(new_container_dirpath).st_dev
            assert old_project_fs != new_project_fs, (
                'Expected old_project_dirpath and new_project_dirpath to be on different filesystems. '
                f'{old_project_dirpath=}, {new_container_dirpath=}'
            )
            try:
                # TODO: Consider adding way to force the old project to
                #       be deleted immediately so that this test can
                #       run in a more-deterministic fashion
                force_immediate_old_project_delete = False
                await save_as_without_ui(project, new_project_dirpath)
            except ProjectReadOnlyError as e:
                raise SkipTest(
                    'cannot create a temporary directory on a new filesystem '
                    'that is writable: ' + str(e)
                )
            
            # Ensure project was moved to new location
            assert new_project_dirpath != old_project_dirpath
            assert os.path.exists(new_project_dirpath)
            if force_immediate_old_project_delete:
                assert not os.path.exists(old_project_dirpath)
            
            # Ensure resource revision was moved to new location
            new_rr_body_filepath = rr._body_filepath
            assert new_rr_body_filepath != old_rr_body_filepath, \
                'Resource revision filepath should have changed after saving untitled project'
            assert os.path.exists(new_rr_body_filepath)
        
        # Test saving an untitled project while downloads are in progress
        # AKA: test_when_save_as_project_with_active_tasks_then_hibernates_and_restores_tasks
        with subtests.test(tasks_running=True), \
                _untitled_project() as project, \
                xtempfile.TemporaryDirectory() as new_container_dirpath:
            # Download a resource revision, so that comic URLs are discovered
            r = Resource(project, home_url)
            rr_future = r.download()
            await step_scheduler_until_done(project)
            
            # Start downloading a group and an individual resource
            g = ResourceGroup(project, 'Comic', comic_pattern)
            g.download()
            await step_scheduler(project)
            root_r = RootResource(project, '', Resource(project, comic50_url))
            root_r.download()
            await step_scheduler(project)
            (old_drg_task, old_dr_task) = project.root_task.children
            assert isinstance(old_drg_task, DownloadResourceGroupTask)
            assert isinstance(old_dr_task, DownloadResourceTask)
            
            # Save untitled project to somewhere else
            new_project_dirpath = os.path.join(
                new_container_dirpath,
                os.path.basename(old_project_dirpath))
            await save_as_without_ui(project, new_project_dirpath)
            append_deferred_top_level_tasks(project)
            
            # Ensure tasks are restored
            (new_drg_task, new_dr_task) = project.root_task.children
            assert isinstance(new_drg_task, DownloadResourceGroupTask)
            assert isinstance(new_dr_task, DownloadResourceTask)
            assert new_drg_task is not old_drg_task
            assert new_dr_task is not old_dr_task
            
            # Ensure tasks can still be stepped without error
            await step_scheduler(project)


# === Untitled Project: Create Tests ===

async def test_given_prompt_to_create_or_save_project_dialog_visible_when_create_button_pressed_then_untitled_project_created() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create(autoclose=True) as (mw, project):
        assert project.is_untitled
        assert not project.is_dirty

        # Verify window title indicates untitled project
        assert 'Untitled' in mw.main_window.GetTitle()
        save_item = mw.main_window.MenuBar.FindItemById(wx.ID_SAVE)
        assert save_item is not None
        assert save_item.IsEnabled()


# === Untitled Project: Close Tests ===

async def test_when_dirty_untitled_project_closed_then_prompts_to_save() -> None:
    with xtempfile.TemporaryDirectory() as tmp_dir:
        save_path = os.path.join(tmp_dir, 'TestProject.crystalproj')
        
        async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw, project):
            assert project.is_untitled
            assert not project.is_dirty

            # Make the project dirty by creating a resource
            r = Resource(project, 'https://example.com/')
            assert project.is_dirty
            if is_mac_os():
                # Verify dot in close box on macOS
                assert mw.main_window.OSXIsModified()

            # Close the project, expect a prompt to save, and save to the specified path
            with patch('crystal.browser.ShowModal', mocked_show_modal('cr-save-changes-dialog', wx.ID_YES)), \
                    file_dialog_returning(save_path):
                await mw.close()
                assert os.path.exists(save_path)

async def test_when_clean_untitled_project_closed_then_does_not_prompt_to_save() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw, project):
        assert project.is_untitled
        assert not project.is_dirty

        # Close project. Ensure no prompt to save.
        with patch('crystal.browser.ShowModal') as mock_show_modal:
            await mw.close()
            mock_show_modal.assert_not_called()


# === Titled Project: Clean/Dirty State Tests ===

async def test_when_titled_project_modified_then_remains_clean() -> None:
    with xtempfile.TemporaryDirectory() as tmp_dir:
        project_path = os.path.join(tmp_dir, 'TestProject.crystalproj')
        with Project(project_path) as project:
            assert not project.is_untitled
            assert not project.is_dirty
            
            # Modify the project
            r = Resource(project, 'https://example.com/')
            RootResource(project, 'Example', r)
            
            # Verify project remains clean even after modification
            assert not project.is_dirty


# === Titled Project: Save Tests ===

async def test_when_titled_project_explicitly_saved_then_does_nothing() -> None:
    with xtempfile.TemporaryDirectory() as tmp_dir:
        project_path = os.path.join(tmp_dir, 'TestProject.crystalproj')
        with Project(project_path) as project:
            main_window = RealMainWindow(project)
            
            # Verify Save... menu item is disabled
            save_item = main_window._frame.MenuBar.FindItemById(wx.ID_SAVE)
            assert save_item is not None
            assert not save_item.IsEnabled()
            
            # Try to save. Ensure no save dialog appears.
            with patch('wx.FileDialog.ShowModal') as mock_show_modal:
                save_event = wx.CommandEvent(wx.EVT_MENU.typeId, wx.ID_SAVE)
                main_window._frame.ProcessEvent(save_event)
                
                # Verify no save dialog was shown
                mock_show_modal.assert_not_called()
            
            main_window.close()


# === Untitled Project: Logout Tests ===

async def test_given_os_logout_with_dirty_untitled_project_and_prompts_to_save_when_save_pressed_then_saves_and_closes_project() -> None:
    with xtempfile.TemporaryDirectory() as tmp_dir:
        save_path = os.path.join(tmp_dir, 'TestProject.crystalproj')
        
        async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw, project):
            assert project.is_untitled
            assert not project.is_dirty

            # Make the project dirty
            r = Resource(project, 'https://example.com/')
            assert project.is_dirty

            def _ensure_logout_vetoed_and_return_yes(dialog: wx.Dialog) -> int:
                assert logout_event.GetVeto(), \
                    'Logout should be vetoed before showing any user prompts'
                return wx.ID_YES

            # Start logout. Expect a prompt to save. Save.
            with patch('crystal.browser.ShowModal', mocked_show_modal(
                        'cr-save-changes-dialog',
                        _ensure_logout_vetoed_and_return_yes)), \
                    file_dialog_returning(save_path):
                
                # Simulate OS logout
                with _simulate_os_logout_on_exit() as logout_event:
                    pass
                
                # Verify the project was saved
                assert os.path.exists(save_path)


@skip('covered by: test_given_os_logout_with_dirty_untitled_project_and_prompts_to_save_when_save_pressed_then_saves_and_closes_project')
async def test_given_os_logout_with_dirty_untitled_project_then_vetoes_logout_before_prompting_to_save() -> None:
    pass


async def test_given_os_logout_with_dirty_untitled_project_and_prompts_to_save_when_cancel_pressed_then_does_not_close_project() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw, project):
        assert project.is_untitled
        assert not project.is_dirty

        # Make the project dirty
        r = Resource(project, 'https://example.com/')
        assert project.is_dirty
        
        # Start logout. Expect a prompt to save. Cancel.
        with patch('crystal.browser.ShowModal', mocked_show_modal('cr-save-changes-dialog', wx.ID_CANCEL)):
            logout_event = _simulate_os_logout()

            # Verify the logout was vetoed
            assert logout_event.GetVeto()
            
            # Verify the project is still dirty and untitled
            assert project.is_dirty
            assert project.is_untitled
        
        # Now close the project without saving
        with patch('crystal.browser.ShowModal', mocked_show_modal('cr-save-changes-dialog', wx.ID_NO)):
            await mw.close()


async def test_given_os_logout_with_dirty_untitled_project_and_prompts_to_save_when_do_not_save_pressed_then_closes_project_without_saving() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw, project):
        assert project.is_untitled
        assert not project.is_dirty

        # Make the project dirty
        r = Resource(project, 'https://example.com/')
        assert project.is_dirty
        
        # Start logout. Expect a prompt to save. Do not save.
        with patch('crystal.browser.ShowModal', mocked_show_modal('cr-save-changes-dialog', wx.ID_NO)):
            _simulate_os_logout()
            
            # Ensure project was closed
            await mw.wait_for_dispose()


# === Untitled Project: Cleanup Tests ===

async def test_when_close_untitled_prompt_and_user_does_not_save_then_project_moved_to_trash_so_that_user_can_easily_recover_later_if_desired() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create(autoclose=False) as (mw, project):
        assert project.is_untitled
        old_project_dirpath = project.path  # capture

        with patch('crystal.model.send2trash', wraps=send2trash.send2trash) as send2trash_spy, \
                patch(
                    'crystal.browser.ShowModal',
                    mocked_show_modal('cr-save-changes-dialog', wx.ID_NO)):
            await mw.close()
        
        assert send2trash_spy.call_count == 1
        assert not os.path.exists(old_project_dirpath)


async def test_when_close_untitled_prompt_and_user_does_save_to_different_filesystem_then_old_project_deleted_in_background() -> None:
    with _temporary_directory_on_new_filesystem() as new_container_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            rmw = RealMainWindow._last_created
            assert rmw is not None
            
            # Save to different filesystem (using UI)
            old_project_dirpath = project.path  # capture
            new_project_dirpath = os.path.join(
                new_container_dirpath,
                os.path.basename(old_project_dirpath))
            with patch(
                    'crystal.model.Project._delete_in_background',
                    wraps=Project._delete_in_background
                    ) as delete_spy:
                await save_as_with_ui(rmw, new_project_dirpath)
            assert delete_spy.call_count == 1


# === Save As Tests + Progress Dialog Tests ===

# TODO: For every situation where a save error dialog is shown ('cr-save-error-dialog'),
#       verify that the error message is easy to understand and actionable.

@awith_subtests
async def test_when_save_as_menu_item_selected_for_titled_or_untitled_project_then_shows_save_as_dialog(subtests: SubtestsContext) -> None:
    with xtempfile.TemporaryDirectory() as tmp_dir:
        save_as_path = os.path.join(tmp_dir, 'SavedProject.crystalproj')
        titled_project_path = os.path.join(tmp_dir, 'TitledProject.crystalproj')
        save_as_path2 = os.path.join(tmp_dir, 'SavedProject2.crystalproj')
        
        async def run_save_as_case(
                project_context_factory: Callable[[], ContextManager[Project]],
                target_path: str
                ) -> None:
            with project_context_factory() as project, \
                    RealMainWindow(project) as rmw:
                await save_as_with_ui(rmw, target_path)

        # Test with untitled project
        with subtests.test(project_type='untitled'):
            await run_save_as_case(lambda: _untitled_project(), save_as_path)

        # Test with titled project
        with subtests.test(project_type='titled'):
            await run_save_as_case(lambda: Project(titled_project_path), save_as_path2)


async def test_when_save_as_project_then_new_tasks_started_continue_to_show_in_task_tree_ui() -> None:
    """
    During a Save As operation the RootTask of the Project is replaced
    and the TaskTree UI needs to specially update itself to reflect this change.
    In particular the root TaskTreeNode must be updated/replaced to point
    to the new RootTask after Save As.
    """
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            xtempfile.TemporaryDirectory() as tmp_dir, \
            _untitled_project() as project, \
            RealMainWindow(project) as rmw:
        mw = await MainWindow.wait_for()
        
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        save_path = os.path.join(tmp_dir, 'SavedProject.crystalproj')
        
        # Create initial project content
        r = Resource(project, atom_feed_url)
        rr_future = r.download()
        append_deferred_top_level_tasks(project)
        assert len(project.root_task.children) > 0
        
        # Get initial task tree state
        task_root_ti = TreeItem.GetRootItem(mw.task_tree)
        initial_task_count = len(task_root_ti.Children)
        assert initial_task_count > 0
        
        # Perform Save As
        await save_as_with_ui(rmw, save_path)
        
        # Verify project path changed
        assert project.path == save_path
        
        # Add a new task after Save As
        r2 = Resource(project, sp.get_request_url('https://xkcd.com/1/'))
        r2_future = r2.download()
        append_deferred_top_level_tasks(project)
        
        # Verify TaskTree shows the new task (this would fail without our fix)
        task_root_ti = TreeItem.GetRootItem(mw.task_tree)
        final_task_count = len(task_root_ti.Children)
        assert final_task_count > initial_task_count, \
            f"TaskTree should show new task after Save As. " \
            f"Initial: {initial_task_count}, Final: {final_task_count}"


async def test_when_save_as_untitled_project_to_different_filesystem_then_copies_project_and_shows_progress_dialog() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            _temporary_directory_on_new_filesystem() as new_container_dirpath, \
            _untitled_project() as project, \
            RealMainWindow(project) as rmw:
        
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        # Download a resource revision to make the project have some data
        r = Resource(project, atom_feed_url)
        rr_future = r.download()
        await step_scheduler_until_done(project)
        rr = rr_future.result(timeout=0)
        
        # Save to different filesystem (using UI)
        old_project_dirpath = project.path  # capture
        new_project_dirpath = os.path.join(
            new_container_dirpath,
            os.path.basename(old_project_dirpath))
        await save_as_with_ui(rmw, new_project_dirpath)
        
        # Verify project was copied
        if True:
            assert os.path.exists(new_project_dirpath)
            
            new_rr_body_filepath = rr._body_filepath
            assert os.path.exists(new_rr_body_filepath)


async def test_when_save_as_untitled_project_to_same_filesystem_then_moves_project_and_does_not_show_progress_dialog() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            _untitled_project() as project, \
            xtempfile.TemporaryDirectory() as new_container_dirpath, \
            RealMainWindow(project) as rmw:
        
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        # Download a resource revision to make the project have some data
        r = Resource(project, atom_feed_url)
        rr_future = r.download()
        await step_scheduler_until_done(project)
        rr = rr_future.result()
        old_rr_body_filepath = rr._body_filepath  # capture
        
        # Save to same filesystem
        old_project_dirpath = project.path  # capture
        new_project_dirpath = os.path.join(
            new_container_dirpath,
            os.path.basename(old_project_dirpath))
        old_project_fs = os.stat(old_project_dirpath).st_dev
        new_project_fs = os.stat(new_container_dirpath).st_dev
        assert old_project_fs == new_project_fs, (
            'Expected old and new paths to be on same filesystem'
        )
        
        async with _assert_save_as_dialog_not_shown_during_save_as(project):
            start_save_as_with_ui(rmw, new_project_dirpath)
        
        # Verify project was moved (original no longer exists)
        if True:
            assert not os.path.exists(old_project_dirpath)
            assert os.path.exists(new_project_dirpath)
            
            new_rr_body_filepath = rr._body_filepath
            assert new_rr_body_filepath != old_rr_body_filepath
            assert os.path.exists(new_rr_body_filepath)


async def test_when_save_as_titled_project_then_copies_project_and_shows_progress_dialog() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            xtempfile.TemporaryDirectory() as tmp_dir:
        
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        # Create a titled project with some data
        original_project_path = os.path.join(tmp_dir, 'OriginalProject.crystalproj')
        with Project(original_project_path) as project:
            assert not project.is_untitled
            
            # Download a resource revision
            r = Resource(project, atom_feed_url)
            rr_future = r.download()
            await step_scheduler_until_done(project)
            rr = rr_future.result()
            original_rr_body_filepath = rr._body_filepath  # capture
        
        # Reopen the project and perform Save As
        with Project(original_project_path) as project, \
                RealMainWindow(project) as rmw:
            copy_project_path = os.path.join(tmp_dir, 'CopiedProject.crystalproj')
            # NOTE: Verifies progress dialog is shown internally
            await save_as_with_ui(rmw, copy_project_path)
        
        # Verify project was copied, and original still exists
        if True:
            assert os.path.exists(original_project_path)
            assert os.path.exists(copy_project_path)
            
            assert os.path.exists(original_rr_body_filepath)
            copied_rr_body_filepath = rr._body_filepath
            assert os.path.exists(copied_rr_body_filepath)


async def test_when_save_as_large_project_then_progress_updates_incrementally() -> None:
    # HACK: Duplicates Project._copytree_of_project_with_progress.TARGET_MAX_DELAY_BETWEEN_REPORTS
    COPYTREE_TARGET_MAX_DELAY_BETWEEN_REPORTS = 0.5
    
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            _temporary_directory_on_new_filesystem() as save_dir, \
            _untitled_project() as project, \
            RealMainWindow(project) as rmw:
        
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        # Add a resource with downloaded content to create a project with some data
        r = Resource(project, atom_feed_url)
        rr_future = r.download()
        await step_scheduler_until_done(project)
        rr = rr_future.result()
        
        new_project_dirpath = os.path.join(save_dir, 'copy.crystalproj')
        
        # Use an infinite generator for time.monotonic to handle many progress updates
        def time_generator():
            t = 0.0
            while True:
                yield t
                # Increment slightly above threshold to always trigger progress reports
                t += COPYTREE_TARGET_MAX_DELAY_BETWEEN_REPORTS + 0.1
        
        # Patch COPY_BUFSIZE to a small value to force many progress updates
        # even for our relatively small test project
        with patch('crystal.model.COPY_BUFSIZE', 5000), \
                patch('time.monotonic', side_effect=time_generator()):
            
            # Save to different filesystem (using UI)
            async with _wait_for_save_as_dialog_to_complete(project) as spies:
                start_save_as_with_ui(rmw, new_project_dirpath)
            spy_copying = spies.copying
            
            # Verify the project copy operation started successfully
            assert os.path.exists(new_project_dirpath)
            
            # Verify that copying() was called multiple times to show incremental progress
            assert spy_copying is not None, 'Expected SaveAsProgressDialog to be created'
            assert spy_copying.call_count >= 2, (
                f'Expected copying() to be called at least 2 times for incremental progress, '
                f'but it was called {spy_copying.call_count} times'
            )
            if spy_copying.call_count > 100:
                warnings.warn(
                    'SaveAsProgressDialog.copying() was called very many times '
                    f'({spy_copying.call_count}), which may slow down this test. '
                    'Consider increasing COPY_BUFSIZE or adjusting the test project size.'
                )
            
            # Verify that progress increases monotonically
            call_args_list = spy_copying.call_args_list
            bytes_copied_values = [call.args[2] for call in call_args_list]  # 3rd argument is bytes_copied
            for i in range(1, len(bytes_copied_values)):
                assert bytes_copied_values[i] >= bytes_copied_values[i-1], (
                    f'Expected bytes_copied to increase monotonically, '
                    f'but got {bytes_copied_values[i]} after {bytes_copied_values[i-1]}'
                )
            
            # Verify the final call shows completion
            final_call = call_args_list[-1]
            final_bytes_copied = final_call.args[2]
            assert final_bytes_copied > 0, 'Expected final bytes_copied to be > 0'


async def test_when_save_as_project_and_user_cancels_then_operation_stops_and_cleans_up() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            _untitled_project() as project, \
            RealMainWindow(project) as rmw, \
            _temporary_directory_on_new_filesystem() as save_dir:
        
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        # Add some data to the project to ensure there's something to copy
        r = Resource(project, atom_feed_url)
        rr_future = r.download()
        await step_scheduler_until_done(project)
        
        save_path = os.path.join(save_dir, 'CanceledProject.crystalproj')
        with _assert_project_not_copied(project, save_path), \
                _rmtree_fallback_for_send2trash('crystal.model.send2trash'):
            # Run the save operation
            with patch.object(SaveAsProgressDialog, 'copying', side_effect=CancelSaveAs) as mock_copying:
                await save_as_with_ui(rmw, save_path)
            
            # Ensure cancellation was triggered properly
            assert mock_copying.call_count > 0, f'copying() was never called. Call count: {mock_copying.call_count}'


@skip('unimplementable: save dialog does not allow overwriting existing projects')
async def test_when_save_as_project_and_destination_project_exists_then_replaces_destination() -> None:
    pass


@skip('unimplementable: save dialog does not allow saving to read-only locations')
async def test_when_save_as_project_and_destination_filesystem_readonly_then_fails_with_error() -> None:
    pass


async def test_when_save_as_project_and_destination_filesystem_writable_generally_but_not_writable_by_sqlite_then_reopens_as_readonly() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            _untitled_project() as project, \
            RealMainWindow(project) as rmw, \
            _temporary_directory_on_new_filesystem() as save_dir:
        mw = await MainWindow.wait_for(timeout=1)
        
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        # Add some data to the project to ensure there's something to copy
        r = Resource(project, atom_feed_url)
        rr_future = r.download()
        await step_scheduler_until_done(project)
        
        save_path = os.path.join(save_dir, 'SqliteUnwritableProject.crystalproj')
        
        assert not project.readonly
        assert not mw.readonly
        
        # Mock DatabaseCursor.execute to fail on the specific SQLite pragma
        # that checks database writability
        original_execute = DatabaseCursor.execute
        def spy_execute(self, command: str, *args, **kwargs):
            if command == 'pragma user_version = user_version':
                raise sqlite3.OperationalError('attempt to write a readonly database')
            return original_execute(self, command, *args, **kwargs)
        
        # Run the save operation
        with patch.object(DatabaseCursor, 'execute', spy_execute), \
                patch('crystal.browser.ShowModal', mocked_show_modal(
                    'cr-save-error-dialog', wx.ID_OK)):
            await save_as_with_ui(rmw, save_path)
        
        assert project.readonly, \
            'Expected project to be reopened as read-only after SQLite error'
        assert mw.readonly, \
            'Expected UI to show that project was reopened as read-only'


async def test_when_save_as_project_and_disk_full_then_fails_with_error_and_cleans_up() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            _untitled_project() as project, \
            RealMainWindow(project) as rmw, \
            _temporary_directory_on_new_filesystem() as save_dir, \
            _rmtree_fallback_for_send2trash('crystal.model.send2trash'):
        
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        # Add some data to the project to ensure there's something to copy
        r = Resource(project, atom_feed_url)
        rr_future = r.download()
        await step_scheduler_until_done(project)
        
        save_path = os.path.join(save_dir, 'DiskFullProject.crystalproj')
        with _assert_project_not_copied(project, save_path):
            def raise_disk_full_error() -> Never:
                if is_windows():
                    raise OSError(errno.ENOSPC, 'There is not enough space on the disk')
                elif is_linux() or is_mac_os():
                    raise OSError(errno.ENOSPC, 'No space left on device')
                else:
                    raise AssertionError('Unsupported OS for disk full simulation')
            
            # Run the save operation
            with _file_object_write_mocked_to(raise_disk_full_error), \
                    patch('crystal.browser.ShowModal', mocked_show_modal(
                        'cr-save-error-dialog', wx.ID_OK)):
                await save_as_with_ui(rmw, save_path)


@awith_subtests
async def test_when_save_as_project_and_destination_filesystem_unmounts_unexpectedly_then_fails_with_error_and_cleans_up(subtests: SubtestsContext) -> None:
    if is_windows():
        fs_gone_errors = [
            OSError(errno.ENOENT, 'No such file or directory'),  # mount point disappears
            OSError(errno.EIO, 'Input/output error'),  # device is suddenly unavailable
            OSError(55, 'The specified network resource or device is no longer available'),
            OSError(15, 'The system cannot find the drive specified'),
        ]
    elif is_linux() or is_mac_os():
        fs_gone_errors = [
            OSError(errno.ENOENT, 'No such file or directory'),  # mount point disappears
            OSError(errno.EIO, 'Input/output error'),  # device is suddenly unavailable
            OSError(errno.ENODEV, 'No such device'),  # device removal
            OSError(errno.ESTALE, 'Stale file handle'),  # NFS or network filesystems
        ]
    else:
        raise AssertionError('Unsupported OS for filesystem unmount simulation')
    
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            _temporary_directory_on_new_filesystem() as save_dir, \
            _rmtree_fallback_for_send2trash('crystal.model.send2trash'):
        for error in fs_gone_errors:
            with subtests.test(error=error), \
                    _untitled_project() as project, \
                    RealMainWindow(project) as rmw:
                
                atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
                
                # Add some data to the project to ensure there's something to copy
                r = Resource(project, atom_feed_url)
                rr_future = r.download()
                await step_scheduler_until_done(project)
                
                save_path = os.path.join(save_dir, 'DiskFullProject.crystalproj')
                with _assert_project_not_copied(project, save_path):
                    def raise_destination_filesystem_gone_error() -> Never:
                        raise error
                    
                    # Run the save operation
                    with _file_object_write_mocked_to(raise_destination_filesystem_gone_error), \
                            patch('crystal.browser.ShowModal', mocked_show_modal(
                                'cr-save-error-dialog', wx.ID_OK)):
                        await save_as_with_ui(rmw, save_path)


async def test_when_save_as_readonly_project_then_creates_writable_copy_and_opens_as_writable() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            xtempfile.TemporaryDirectory() as tmp_dir:
        
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        # Create a titled project with some data, initially writable
        original_project_path = os.path.join(tmp_dir, 'OriginalProject.crystalproj')
        with Project(original_project_path) as project:
            assert not project.readonly, 'Original project should be writable'
            
            # Download a resource revision
            r = Resource(project, atom_feed_url)
            rr_future = r.download()
            await step_scheduler_until_done(project)
            rr = rr_future.result()
        
        # Reopen the project as readonly
        with Project(original_project_path, readonly=True) as readonly_project, \
                RealMainWindow(readonly_project) as rmw:
            assert readonly_project.readonly, 'Project should be opened as readonly'
            
            # Perform Save As
            copy_project_path = os.path.join(tmp_dir, 'CopiedProject.crystalproj')
            await save_as_with_ui(rmw, copy_project_path)
            
            # Verify project was copied to new location
            assert os.path.exists(copy_project_path)
            assert os.path.exists(original_project_path)  # original still exists
            
            # Verify the copied project is writable on disk (file permissions)
            db_filepath = os.path.join(copy_project_path, Project._DB_FILENAME)
            assert os.access(copy_project_path, os.W_OK), 'Copied project directory should be writable'
            assert os.access(db_filepath, os.W_OK), 'Copied database file should be writable'
            
            # And the project object should now be writable
            assert not readonly_project.readonly, \
                'Project should be writable after save_as'
            assert readonly_project.path == copy_project_path, 'Project should be at new path'


@skip('covered by: test_when_untitled_project_saved_then_becomes_clean_and_titled')
async def test_when_save_as_project_with_active_tasks_then_hibernates_and_restores_tasks() -> None:
    pass


# NOTE: This can happen if a very large resource revision is being downloaded
#       and Project._stop_scheduler() times out waiting for the scheduler thread to stop.
async def test_when_save_as_project_and_old_project_fails_to_close_then_handles_gracefully() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            scheduler_disabled(simulate_thread_never_dies=True), \
            _untitled_project() as project, \
            RealMainWindow(project) as rmw, \
            _temporary_directory_on_new_filesystem() as save_dir:
        
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        # Add some data to the project to ensure there's something to save
        r = Resource(project, atom_feed_url)
        rr_future = r.download()
        await step_scheduler_until_done(project)
        rr = rr_future.result()
        
        save_path = os.path.join(save_dir, 'FailedSaveProject.crystalproj')
        old_path = project.path  # capture original path
        
        with _assert_project_not_copied(project, save_path):
            # Patch the scheduler join timeout to 0 to force immediate timeout
            with patch.object(Project, '_SCHEDULER_JOIN_TIMEOUT', 0):
                # Mock error dialog to acknowledge the timeout error
                with patch('crystal.browser.ShowModal', mocked_show_modal(
                        'cr-save-error-dialog', wx.ID_OK)):
                    await save_as_with_ui(rmw, save_path)
        
        # Verify project is still at original path and remains functional
        assert project.path == old_path
        assert project._is_untitled
        assert os.path.exists(old_path)
        
        # Verify the resource and data are still accessible
        assert rr._body_filepath
        assert os.path.exists(rr._body_filepath)


async def test_when_save_as_project_and_new_project_fails_to_open_then_handles_gracefully() -> None:
    """
    Test that when saving an untitled project and the new project fails to open 
    (e.g., due to database corruption), the operation fails gracefully with an error dialog
    and the original untitled project remains open and functional.
    """
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            _untitled_project() as project, \
            RealMainWindow(project) as rmw, \
            _temporary_directory_on_new_filesystem() as save_dir:
        
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        # Add some data to the project to ensure there's something to save
        r = Resource(project, atom_feed_url)
        rr_future = r.download()
        await step_scheduler_until_done(project)
        rr = rr_future.result()
        
        save_path = os.path.join(save_dir, 'CorruptedProject.crystalproj')
        old_path = project.path  # capture original path
        
        with _assert_project_not_copied(project, save_path):
            def raise_database_corruption_error(*args, **kwargs):
                # Simulate a corrupted database file by raising a DatabaseError
                # when trying to open the copied project's database
                if 'CorruptedProject.crystalproj' in str(args[0]):
                    raise sqlite3.DatabaseError('database disk image is malformed')
                # Allow the original database connection to succeed
                return sqlite3.connect(*args, **kwargs)
            
            # Run the save operation
            with patch('sqlite3.connect', side_effect=raise_database_corruption_error), \
                    patch('crystal.browser.ShowModal', mocked_show_modal(
                        'cr-save-error-dialog', wx.ID_OK)):
                await save_as_with_ui(rmw, save_path)
        
        # Verify project is still at original path and remains functional
        assert project.path == old_path
        assert project._is_untitled
        assert os.path.exists(old_path)
        
        # Verify the resource and data are still accessible
        assert rr._body_filepath
        assert os.path.exists(rr._body_filepath)


async def test_when_save_as_untitled_project_with_corrupted_database_then_fails_with_error_and_closes_project() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            _untitled_project() as project, \
            xtempfile.TemporaryDirectory() as tmp_dir:
        rmw = RealMainWindow(project)
        mw = await MainWindow.wait_for(timeout=1)
        
        # Download a resource revision to have some data
        url = sp.get_request_url('https://xkcd.com/atom.xml')
        r = Resource(project, url)
        rr_future = r.download()
        await step_scheduler_until_done(project)
        rr = rr_future.result(timeout=0)
        
        save_path = os.path.join(tmp_dir, 'CorruptedDBProject.crystalproj')
        
        # Patch reopen to corrupt the copied DB file before opening
        original_reopen = Project._reopen
        def fake_reopen(self):
            if self.path == save_path:
                # Corrupt the database file before allowing reopen to proceed
                db_file = os.path.join(self.path, Project._DB_FILENAME)
                size = os.path.getsize(db_file)
                with open(db_file, 'r+b') as f:
                    f.truncate(size // 2)
            return original_reopen(self)
        with patch.object(Project, '_reopen', fake_reopen), \
                patch('crystal.browser.ShowModal', mocked_show_modal(
                    'cr-save-error-dialog', wx.ID_OK)) as show_modal_method:
            await save_as_with_ui(rmw, save_path)
            assert 1 == show_modal_method.call_count, \
                'Expected error dialog to be shown due to database corruption'

        # Ensure project and its main window are closed
        assert project._closed
        await mw.wait_for_dispose()


async def test_when_save_as_titled_project_with_corrupted_database_then_fails_with_error_and_reopens_original_project() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            xtempfile.TemporaryDirectory() as tmp_dir:
        
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        # Create a titled project with some data
        original_project_path = os.path.join(tmp_dir, 'OriginalProject.crystalproj')
        with Project(original_project_path) as project:
            assert not project.is_untitled
            
            # Download a resource revision
            r = Resource(project, atom_feed_url)
            rr_future = r.download()
            await step_scheduler_until_done(project)
            rr = rr_future.result()
        
        # Reopen the project and perform Save As with corruption
        with Project(original_project_path) as project, \
                RealMainWindow(project) as rmw:
            mw = await MainWindow.wait_for(timeout=1)
            
            save_path = os.path.join(tmp_dir, 'CorruptedDBProject.crystalproj')
            
            # Patch reopen to corrupt the copied DB file before opening
            original_reopen = Project._reopen
            def fake_reopen(self):
                if self.path == save_path:
                    # Corrupt the database file before allowing reopen to proceed
                    db_file = os.path.join(self.path, Project._DB_FILENAME)
                    size = os.path.getsize(db_file)
                    with open(db_file, 'r+b') as f:
                        f.truncate(size // 2)
                return original_reopen(self)
            
            with patch.object(Project, '_reopen', fake_reopen), \
                    patch('crystal.browser.ShowModal', mocked_show_modal(
                        'cr-save-error-dialog', wx.ID_OK)) as show_modal_method:
                await save_as_with_ui(rmw, save_path)
                assert 1 == show_modal_method.call_count, \
                    'Expected error dialog to be shown due to database corruption'
            
            # Verify original project is reopened and functional
            assert project.path == original_project_path
            assert not project.is_untitled
            assert not project._closed
            
            # Verify the original resource and data are still accessible
            assert rr._body_filepath
            assert os.path.exists(rr._body_filepath)


async def test_when_save_as_project_with_missing_revision_files_then_ignores_missing_revision_files() -> None:
    """
    When saving a project that has resource revisions whose body files are missing on disk,
    the save operation should ignore missing files and complete successfully.
    """
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            _untitled_project() as project, \
            xtempfile.TemporaryDirectory() as tmp_dir:
        # Download a resource revision to generate a body file
        url = sp.get_request_url('https://xkcd.com/atom.xml')
        r = Resource(project, url)
        rr_future = r.download()
        await step_scheduler_until_done(project)
        rr = rr_future.result(timeout=0)
        
        # Simulate missing revision body file
        os.remove(rr._body_filepath)
        
        # Save project without UI - should ignore missing files and succeed
        new_path = os.path.join(tmp_dir, os.path.basename(project.path))
        await save_as_without_ui(project, new_path)
        
        # Verify new project exists and project updated
        assert os.path.exists(new_path)
        assert project.path == new_path
        
        # Should become titled and clean
        assert not project._is_untitled
        assert not project.is_dirty


# === Untitled Project: Auto-Reopen Tests ===
# TODO: Move this section after the "=== Untitled Project: Logout Tests ==="

@reopen_projects_enabled
@awith_subtests
async def test_given_untitled_project_created_when_crystal_unexpectedly_quits_then_untitled_project_reopened(subtests: SubtestsContext) -> None:
    with subtests.test('mark for reopen'):
        with _untitled_project(in_default_nonisolated_location=True) as project:
            # Should track this untitled project
            tracked_path = app_prefs.unsaved_untitled_project_path
            assert tracked_path is not None
            assert tracked_path == project.path
            
            # Should be in permanent directory, not temp
            untitled_dir = user_untitled_projects_dir()
            assert project.path.startswith(untitled_dir)
            
            # Verify directory structure exists
            assert os.path.exists(untitled_dir)
            assert os.path.exists(project.path)
        
        # After closing, state should be cleared
        assert app_prefs.unsaved_untitled_project_path is None
    
    with subtests.test('actually reopen'):
        # Create untitled project in subprocess to simulate unexpected quit
        with crystal_shell(reopen_projects_enabled=True) as (crystal, banner):
            # Create an untitled project through the UI
            create_new_empty_project(crystal)
            
            # Verify project is tracked for reopen
            tracked_path = py_eval_literal(crystal, textwrap.dedent('''\
                from crystal.app_preferences import app_prefs
                print(repr(app_prefs.unsaved_untitled_project_path))
                '''
            ))
            assert tracked_path and 'UntitledProjects' in tracked_path
            
            # Capture the project path for later verification
            project_path = py_eval_literal(crystal, 'project.path')
            
            # Simulate unexpected quit
            crystal.kill()
            crystal.wait()
        
        # Now start Crystal again and verify it reopens the untitled project
        with crystal_shell(reopen_projects_enabled=True) as (crystal, banner):
            # Ensure project was auto-opened
            # TODO: Eliminate race condition that requires this wait
            import time; time.sleep(0.5)
            project_available = _project_is_available(crystal)
            assert project_available, "Expected project to be auto-reopened but none was found"
            
            # Ensure we have a main window
            wait_for_main_window(crystal)
            
            # Verify the untitled project was automatically reopened
            reopened_path = py_eval_literal(crystal, 'project.path')
            assert reopened_path == project_path
            
            # Verify it's still untitled
            is_untitled = py_eval_literal(crystal, 'project.is_untitled')
            assert is_untitled == True
            
            # Verify it's considered immediately dirty
            is_dirty = py_eval_literal(crystal, 'project.is_dirty')
            assert is_dirty == True
            
            # Force quit, so that we don't have to respond to the "Save Changes?" dialog
            crystal.kill()
            crystal.wait()


@reopen_projects_enabled
@awith_subtests
async def test_given_untitled_project_saved_when_crystal_unexpectedly_quits_then_no_project_reopened(subtests: SubtestsContext) -> None:
    with subtests.test('mark for reopen'):
        with _untitled_project(in_default_nonisolated_location=True) as project, \
                xtempfile.TemporaryDirectory() as tmp_dir:
            # Should initially track this untitled project
            assert app_prefs.unsaved_untitled_project_path == project.path
            
            # Save the project (make it titled)
            new_project_path = os.path.join(tmp_dir, 'SavedProject.crystalproj')
            await save_as_without_ui(project, new_project_path)
            
            # State should be cleared since project is no longer untitled
            assert app_prefs.unsaved_untitled_project_path is None
            assert not project.is_untitled
    
    with subtests.test('actually reopen'):
        # Create untitled project in subprocess, save it, then simulate unexpected quit
        with crystal_shell(reopen_projects_enabled=True) as (crystal, banner):
            # Create an untitled project through the UI
            create_new_empty_project(crystal)
            
            # Prepare save location
            py_eval(crystal, textwrap.dedent('''\
                import tempfile
                import os
                tmp_dir = tempfile.mkdtemp()
                saved_path = os.path.join(tmp_dir, 'SavedProject.crystalproj')
                '''
            ))
            
            # Save the untitled project using the UI
            py_eval(crystal, textwrap.dedent('''\
                from crystal.tests.util.runner import run_test
                from crystal.tests.util.save_as import save_as_with_ui
                from threading import Thread

                async def perform_save():
                    # Use the window directly (it's a RealMainWindow)
                    await save_as_with_ui(window, saved_path)

                result_cell = [None]
                def get_result():
                    result_cell[0] = run_test(perform_save)
                    print("OK")

                t = Thread(target=get_result)
                t.start()
                '''
            ), stop_suffix=_OK_THREAD_STOP_SUFFIX, timeout=8.0)
            
            # Verify state is cleared after saving
            tracked_path = py_eval_literal(crystal, textwrap.dedent('''\
                from crystal.app_preferences import app_prefs
                print(repr(app_prefs.unsaved_untitled_project_path))
                '''
            ))
            assert tracked_path == None, f"Expected 'None' but got {repr(tracked_path)}"
            
            # Simulate unexpected quit
            crystal.kill()
            crystal.wait()
        
        # Now start Crystal again and verify no project is reopened
        with crystal_shell(reopen_projects_enabled=True) as (crystal, banner):
            # Should show open/create dialog, not auto-reopen any project
            close_open_or_create_dialog(crystal)
            
            # Verify no project is automatically available
            assert not _project_is_available(crystal)


@reopen_projects_enabled
@awith_subtests
async def test_given_crystal_quit_cleanly_when_crystal_launched_then_no_project_reopened(subtests: SubtestsContext) -> None:
    with subtests.test('mark for reopen'):
        with _untitled_project(in_default_nonisolated_location=True) as project:
            # Should be tracked
            assert app_prefs.unsaved_untitled_project_path == project.path
        
        # After closing, state should be cleared automatically
        assert app_prefs.unsaved_untitled_project_path is None
    
    with subtests.test('actually reopen'):
        # Create untitled project in subprocess and close it cleanly
        with crystal_shell(reopen_projects_enabled=True) as (crystal, banner):
            # Create an untitled project through the UI
            create_new_empty_project(crystal)
            
            # Verify project is tracked
            tracked_path = py_eval_literal(crystal, textwrap.dedent('''\
                from crystal.app_preferences import app_prefs
                print(repr(app_prefs.unsaved_untitled_project_path))
                '''
            ))
            assert 'UntitledProjects' in tracked_path
            
            # Close the project cleanly through the UI (this should clear the reopen state)
            close_main_window(crystal)

        # Ensure no longer tracking project
        assert app_prefs.unsaved_untitled_project_path is None

        # Now start Crystal again and verify no project is reopened
        with crystal_shell(reopen_projects_enabled=True) as (crystal, banner):
            # Should show open/create dialog, not auto-reopen any project
            close_open_or_create_dialog(crystal)
            
            # Verify no project is automatically available
            assert not _project_is_available(crystal)


# NOTE: Crystal isn't currently designed to handle multiple open projects gracefully.
#       So this behavior may be changed when prompt multiple projects support is
#       added, as part of: https://github.com/davidfstr/Crystal-Web-Archiver/issues/101
@reopen_projects_enabled
async def test_given_multiple_untitled_projects_when_crystal_unexpectedly_quits_then_only_reopen_last_untitled_project() -> None:
    project1 = None
    project2 = None
    try:
        # Create first untitled project
        project1 = Project()
        path1 = project1.path
        
        # Should track first project
        assert app_prefs.unsaved_untitled_project_path == path1
        
        # Create second untitled project
        project2 = Project()
        path2 = project2.path
        
        # Should now track second project (most recent)
        assert app_prefs.unsaved_untitled_project_path == path2
        
        # Close first project - state should be cleared because ANY untitled project close clears state
        # (This is the intended behavior: manual close indicates user intent to not auto-reopen)
        project1.close()
        project1 = None
        assert app_prefs.unsaved_untitled_project_path is None
        
        # Second project should still be open but no longer tracked
        assert not project2._closed
        
        # Close second project - state should remain cleared
        project2.close()
        project2 = None
        assert app_prefs.unsaved_untitled_project_path is None
    finally:
        if project1 is not None:
            project1.close()
        if project2 is not None:
            project2.close()


# === Utility ===

@contextmanager
def _untitled_project(in_default_nonisolated_location: bool=False) -> Iterator[Project]:
    """Creates an untitled project, by default in an isolated temporary directory."""
    if in_default_nonisolated_location:
        with Project() as project:
            yield project
    else:
        with xtempfile.TemporaryDirectory() as container_dirpath:
            untitled_project_dirpath = os.path.join(container_dirpath, 'Untitled.crystalproj')
            with Project(untitled_project_dirpath, is_untitled=True) as project:
                yield project


@contextmanager
def _temporary_directory_on_new_filesystem() -> Iterator[str]:
    """
    Context that creates a temporary directory on a new filesystem† on enter and
    cleans it up on exit.
    
    † A new filesystem is defined as a directory that is not on the same
    filesystem as the operating system's temporary directory (e.g. /tmp).
    
    Raises:
    * SkipTest -- if cannot create a temporary directory on a new filesystem on this OS
    """
    if is_mac_os():
        with hdiutil_disk_image_mounted() as mount_point:
            yield mount_point
    elif is_linux() and is_ci():
        # NOTE: It is not possible to mount a disk image in GitHub Actions CI runners
        #       because the runner user does not have mount permissions.
        #       Therefore we cannot create a temporary directory on a new
        #       filesystem in this environment.
        raise SkipTest(
            'Cannot create temp directory on a new filesystem '
            'on a Linux GitHub Actions CI runner'
        )
    else:
        # Fallback: Try to use a temp directory on the same filesystem
        if os.stat('.').st_dev == _filesystem_of_temporary_directory():
            raise SkipTest(
                'Cannot create temp directory on a new filesystem '
                'because the current directory is on the same filesystem '
                'as the system\'s temporary directory and no other methods '
                'for creating a new filesystem are available.'
            )
        
        with xtempfile.TemporaryDirectory(prefix='tmpdir_', dir='.') as tmp_dirpath:
            yield tmp_dirpath


@cache
def _filesystem_of_temporary_directory() -> int:
    """
    Returns the filesystem ID of the system's temporary directory.
    """
    return os.stat(tempfile.gettempdir()).st_dev


def _simulate_os_logout() -> wx.CloseEvent:
    with _simulate_os_logout_on_exit() as logout_event:
        return logout_event


@contextmanager
def _simulate_os_logout_on_exit() -> Iterator[wx.CloseEvent]:
    app = wx.GetApp()
    logout_event = wx.CloseEvent(wx.EVT_QUERY_END_SESSION.typeId)
    yield logout_event
    app.ProcessEvent(logout_event)


@dataclass
class SaveAsSpies:
    """Mutable container for spies on SaveAsProgressDialog methods."""
    copying: MagicMock | None = None

@asynccontextmanager
async def _wait_for_save_as_dialog_to_complete(project: Project) -> AsyncIterator[SaveAsSpies]:
    """
    Context that upon entry spies on SaveAsProgressDialog and Project.save_as,
    yields for the caller to start a Save As operation,
    and upon exit waits for the dialog to complete AND the save_as operation to fully complete.
    
    The yielded spies object will be filled out upon exiting the context.
    """
    spies_yielded = None
    
    patcher_copying = None
    spy_copying = None
    
    def SaveAsProgressDialogSpy(*args, **kwargs) -> SaveAsProgressDialog:  # wraps real constructor
        nonlocal patcher_copying
        nonlocal spy_copying
        nonlocal spies_yielded
        
        assert (
            spy_copying is None
        ), 'Expected SaveAsProgressDialog to be created only once'
        assert spies_yielded is not None, 'Expected SaveAsSpies to already be yielded'
        
        instance = SaveAsProgressDialog(*args, **kwargs)
        
        # Spy on calls to the returned SaveAsProgressDialog instance
        patcher_copying = patch.object(instance, 'copying', wraps=instance.copying)
        spy_copying = patcher_copying.start()
        
        # Update the yielded spies object with spy instances
        spies_yielded.copying = spy_copying
        
        return instance
    
    try:
        with patch('crystal.browser.SaveAsProgressDialog', SaveAsProgressDialogSpy):
            async with wait_for_save_as_to_complete(project):
                # 1. Tell caller to start a Save As operation
                # 2. Yield a placeholder for spies that will be updated when the dialog is created
                yield (spies_yielded := SaveAsSpies())
    finally:
        if patcher_copying is not None:
            patcher_copying.stop()


@asynccontextmanager
async def _assert_save_as_dialog_not_shown_during_save_as(project: Project) -> AsyncIterator[None]:
    """
    Context that upon entry spies on SaveAsProgressDialog,
    yields for the caller to start a Save As operation,
    and upon exit ensures the dialog was not shown.
    """
    patcher = None
    spy = None
    def SaveAsProgressDialogSpy(*args, **kwargs):  # wraps real constructor
        nonlocal patcher, spy
        assert spy is None, 'Expected SaveAsProgressDialog to be created only once'
        
        instance = SaveAsProgressDialog(*args, **kwargs)
        patcher = patch.object(instance, 'calculating_total_size', wraps=instance.calculating_total_size)
        spy = patcher.start()
        return instance
    
    try:
        old_project_dirpath = project.path  # capture
        assert os.path.exists(old_project_dirpath)
        with patch('crystal.browser.SaveAsProgressDialog', SaveAsProgressDialogSpy):
            async with wait_for_save_as_to_complete(project):
                yield
            
            assert not os.path.exists(old_project_dirpath)

            assert spy is not None, 'Expected SaveAsProgressDialog to be created'
            assert spy.call_count == 0, (
                'Expected SaveAsProgressDialog to not be shown, '
                f'but it was shown {spy.call_count} times'
            )
    finally:
        if patcher is not None:
            patcher.stop()


@contextmanager
def _assert_project_not_copied(project: Project, save_path: str) -> Iterator[None]:
    """Ensure that the project is not copied on exit."""
    partial_path = save_path.replace('.crystalproj', '.crystalproj-partial')
    
    assert project._is_untitled, 'Expected project to start as untitled'
    
    yield
    
    # Verify that the project is still at its original location (untitled)
    assert project._is_untitled, 'Project should still be untitled after cancellation'
    
    # Verify cleanup occurred - neither the final file nor partial file should exist
    assert not os.path.exists(save_path), f'Final save file should not exist: {save_path}'
    assert not os.path.exists(partial_path), f'Partial save file should not exist: {partial_path}'


@contextmanager
def _file_object_write_mocked_to(raise_func: Callable[[], Never]) -> Iterator[None]:
    """
    Context manager that mocks the file object write() method to raise an error.
    """
    real_open = open  # capture
    mock_write_call_count = 0
    def fake_open(file, mode='r', *args, **kwargs):
        file_obj = real_open(file, mode, *args, **kwargs)
        if 'w' in mode:
            def mock_write(*args, **kwargs) -> Never:
                nonlocal mock_write_call_count
                mock_write_call_count += 1
                raise_func()
            file_obj.write = mock_write
        return file_obj
    
    with patch('builtins.open', fake_open):
        yield
    
    # Ensure write() was actually called
    assert mock_write_call_count > 0, f'write() was never called. Call count: {mock_write_call_count}'


@contextmanager
def _rmtree_fallback_for_send2trash(send2trash_location: str, *, linux_only: bool=True) -> Iterator[None]:
    """
    Context manager that provides a fallback for send2trash() to use shutil.rmtree()
    if send2trash fails.
    
    Defaults to only applying this fallback on Linux systems because send2trash
    is less reliable on Linux and often requires additional permissions.
    
    Arguments:
    * send2trash_location -- the import path for send2trash, e.g. 'send2trash.send2trash'
    """
    if linux_only and not is_linux():
        yield
        return
    
    real_send2trash = send2trash.send2trash  # capture
    def wrapped_send2trash(path: str) -> None:
        try:
            real_send2trash(path)
        except (send2trash.TrashPermissionError, OSError, Exception):
            # If send2trash fails, fall back to shutil.rmtree
            shutil.rmtree(path, ignore_errors=False)
    with patch(send2trash_location, wrapped_send2trash):
        yield


def _cleanup_untitled_projects() -> None:
    """Clean up untitled projects directory."""
    untitled_dir = user_untitled_projects_dir()
    if os.path.exists(untitled_dir):
        shutil.rmtree(untitled_dir)


def _project_is_available(crystal: subprocess.Popen) -> bool:
    return py_eval(crystal, 'project') != PROJECT_PROXY_REPR_STR
