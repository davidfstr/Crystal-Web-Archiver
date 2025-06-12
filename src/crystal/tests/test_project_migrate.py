"""
Tests that projects in older on-disk formats are upgraded to the latest
format properly.

In particular this module tests the Project._apply_migrations() method.

All tests below implicitly include the condition:
* given_project_opened_as_writable
"""
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from crystal import progress
import crystal.main
from crystal.model import Project, Resource
from crystal.model import ResourceRevision as RR
from crystal.model import ResourceRevisionMetadata
from crystal.progress import CancelOpenProject, OpenProjectProgressDialog
from crystal.tests.test_server import serve_and_fetch_xkcd_home_page
from crystal.tests.util.controls import click_button
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import extracted_project
from crystal.tests.util.wait import wait_for, wait_while, window_condition
from crystal.tests.util.windows import MainWindow, OpenOrCreateDialog
from crystal.util.db import DatabaseCursor
from crystal.util.wx_dialog import mocked_show_modal
import os.path
from typing_extensions import override
from unittest import skip
from unittest.mock import patch
import wx

# === .crystalopen & README ===

@skip('not yet automated')
def test_given_project_lacks_crystalopen_and_lacks_readme_when_project_opened_then_crystalopen_and_readme_created() -> None:
    pass


@skip('not yet automated')
def test_given_project_lacks_crystalopen_and_has_maybe_modified_readme_when_project_opened_then_readme_content_preserved() -> None:
    pass


@skip('not yet automated')
def test_given_project_has_crystalopen_with_nondefault_name_when_project_opened_then_crystalopen_name_preserved() -> None:
    pass


@skip('not yet automated')
def test_given_project_has_crystalopen_and_has_maybe_modified_readme_when_project_opened_then_readme_content_preserved() -> None:
    pass


@skip('not yet automated')
def test_given_project_has_crystalopen_and_readme_was_deleted_when_project_opened_then_readme_stays_deleted() -> None:
    pass


# === Windows desktop.ini ===

@skip('not yet automated')
def test_given_project_lacks_desktop_ini_file_then_desktop_ini_and_icons_directory_created() -> None:
    pass


@skip('not yet automated')
def test_given_project_has_desktop_ini_file_then_desktop_ini_content_preserved() -> None:
    pass


# === Linux .directory ===

@skip('not yet automated')
def test_given_project_lacks_dot_directory_file_then_dot_directory_file_created() -> None:
    pass


@skip('not yet automated')
def test_given_project_has_dot_directory_file_then_dot_directory_file_content_preserved() -> None:
    pass


# === Hide special files on Windows ===

@skip('not yet automated')
def test_given_windows_then_desktop_ini_file_and_dot_directory_file_marked_as_hidden() -> None:
    pass


# === Major Version Migrations ===

# --- Unknown Major Versions ---

async def test_refuses_to_open_project_with_unknown_high_major_version() -> None:
    UNKNOWN_HIGH_MAJOR_VERSION = Project._LATEST_SUPPORTED_MAJOR_VERSION + 1
    
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        # Create project with unknown high major version
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            project._set_property('major_version', str(UNKNOWN_HIGH_MAJOR_VERSION))
            assert UNKNOWN_HIGH_MAJOR_VERSION == project.major_version
        
        # Try to open that project
        if True:
            # Prepare to: OK
            did_respond_to_project_too_new_modal = False
            def click_ok_in_project_too_new_modal(dialog: wx.Dialog) -> int:
                assert 'cr-project-too-new' == dialog.Name
                
                nonlocal did_respond_to_project_too_new_modal
                did_respond_to_project_too_new_modal = True
                
                return wx.ID_OK
            
            load_project = crystal.main._load_project  # capture
            def patched_load_project(*args, **kwargs) -> Project:
                return load_project(
                    *args,
                    _show_modal_func=click_ok_in_project_too_new_modal,  # type: ignore[misc]
                    **kwargs)
            
            with patch(f'crystal.main._load_project', patched_load_project):
                ocd = await OpenOrCreateDialog.wait_for()
                await ocd.start_opening(project_dirpath, next_window_name='cr-open-or-create-project')
                
                # HACK: Wait minimum duration to allow open to finish
                await bg_sleep(0.5)
                
                # Wait for cancel and return to initial dialog
                ocd = await OpenOrCreateDialog.wait_for()
                
                assert did_respond_to_project_too_new_modal


# --- 1 -> 2: Prompt to upgrade ---

@skip('covered by: test_can_upgrade_project_from_major_version_1_to_2')
async def test_given_project_is_major_version_1_and_would_be_fast_to_upgrade_to_major_version_2_when_open_project_then_updates_project_without_prompting_for_confirmation() -> None:
    pass


async def test_when_prompted_to_upgrade_project_from_major_version_1_to_2_then_can_continue_upgrade() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        # Create project with major version = 1 and at least one revision
        async with _project_opened_without_migrating(project_dirpath) as (_, project):
            assert 1 == project.major_version, (
                'Expected project to not be upgraded'
            )  # not > 1
        
        def continue_button_id(dialog: wx.Dialog) -> int:
            style = dialog.GetMessageDialogStyle()
            if style & wx.YES_NO != 0:
                return wx.ID_YES  # Continue
            elif style & wx.OK != 0:
                return wx.ID_OK  # Continue
            else:
                raise AssertionError()
        
        with _upgrade_required_modal_always_shown(), \
                patch(
                    'crystal.progress.ShowModal',
                    # Prepare to: Accept upgrade
                    mocked_show_modal('cr-upgrade-required', continue_button_id)
                    ) as show_modal_method:
            async with (await OpenOrCreateDialog.wait_for()).open(
                    project_dirpath, wait_func=_wait_for_project_to_upgrade) as (mw, project):
                assert 1 == show_modal_method.call_count
                
                assert project.major_version >= 2, (
                    'Expected project to be upgraded'
                )  # not == 1


async def test_when_prompted_to_upgrade_project_from_major_version_1_to_2_then_can_defer_upgrade_to_later() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        # Create project with major version = 1 and at least one revision
        async with _project_opened_without_migrating(project_dirpath) as (_, project):
            assert 1 == project.major_version, (
                'Expected project to not be upgraded'
            )  # not > 1
        
        def later_button_id(dialog: wx.Dialog) -> int:
            style = dialog.GetMessageDialogStyle()
            if style & wx.YES_NO != 0:
                return wx.ID_NO  # Later
            elif style & wx.OK != 0:
                raise AssertionError('"Later" button in dialog is not visible')
            else:
                raise AssertionError()
        
        with _upgrade_required_modal_always_shown(), \
                patch(
                    'crystal.progress.ShowModal',
                    # Prepare to: Defer upgrade
                    mocked_show_modal('cr-upgrade-required', later_button_id)
                    ) as show_modal_method:
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                assert 1 == show_modal_method.call_count
                
                assert 1 == project.major_version, (
                    'Expected project to not be upgraded'
                )  # not > 1


async def test_when_prompted_to_upgrade_project_from_major_version_1_to_2_then_can_cancel_open_project() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        # Create project with major version = 1 and at least one revision
        async with _project_opened_without_migrating(project_dirpath) as (_, project):
            assert 1 == project.major_version, (
                'Expected project to not be upgraded'
            )  # not > 1
        
        with _upgrade_required_modal_always_shown(), \
                patch(
                    'crystal.progress.ShowModal',
                    # Prepare to: Cancel
                    mocked_show_modal('cr-upgrade-required', wx.ID_CANCEL)
                    ) as show_modal_method:
            ocd = await OpenOrCreateDialog.wait_for()
            await ocd.start_opening(project_dirpath, next_window_name='cr-open-or-create-project')
            
            # HACK: Wait minimum duration to allow open to finish
            await bg_sleep(0.5)
            
            # Wait for cancel and return to initial dialog
            ocd = await OpenOrCreateDialog.wait_for()
            assert 1 == show_modal_method.call_count


async def test_given_project_is_major_version_1_and_has_more_than_MAX_REVISION_ID_revisions_when_open_project_then_defers_upgrade_to_later() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        async with _project_opened_without_migrating(project_dirpath) as (_, project):
            assert 1 == project.major_version, (
                'Expected project to not be upgraded'
            )  # not > 1
        
        # Open project, simulating an estimated revision count > Project._MAX_REVISION_ID.
        # Ensure is not upgraded to major version 2.
        if True:
            super_process_table_rows = Project._process_table_rows
            @staticmethod  # type: ignore[misc]
            def process_table_rows(
                    c: DatabaseCursor,
                    approx_row_count_query: str,
                    *args, **kwargs,
                    ) -> None:
                return super_process_table_rows(
                    c,
                    f'select {Project._MAX_REVISION_ID + 1}'
                        if approx_row_count_query.startswith('select id from resource_revision ')
                        else approx_row_count_query,
                    *args, **kwargs)
        
        with patch.object(Project, '_process_table_rows', process_table_rows):
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                assert 1 == project.major_version, (
                    'Expected project to not be upgraded'
                )  # not > 1


# --- 1 -> 2: Move revisions from flat structure to hierarchy ---

async def test_can_upgrade_project_from_major_version_1_to_2() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        # Create project with >=4,096 revisions, which is just over the number of
        # revisions that fit into a single subdirectory of the new hierarchy
        async with _project_opened_without_migrating(project_dirpath) as (_, project):
            assert 1 == project.major_version, (
                'Expected project to not be upgraded'
            )  # not > 1
            
            # Create many resources
            max_id = max([r._id for r in project.resources])
            resources = Resource.bulk_create(project, [
                f'https://example.com/{id}'
                for id in range(max_id + 1, 4096 + 1)
            ], 'https://example.com/')
            max_id = max([r._id for r in project.resources])
            assert 4096 == max_id
            
            # Create many revisions
            if True:
                # Create revision rows in database
                c = project._db.cursor()
                encoded_null_error = RR._encode_error(None)
                encoded_404_error = RR._encode_metadata(ResourceRevisionMetadata(
                    http_version=10,
                    status_code=404,
                    reason_phrase='Not Found',
                    headers=[],
                ))
                c.executemany(
                    'insert into resource_revision '
                        '(id, resource_id, request_cookie, error, metadata) values (?, ?, ?, ?, ?)', 
                    [
                        (r._id, r._id, None, encoded_null_error, encoded_404_error)
                        for r in resources
                    ])
                project._db.commit()
                
                # Create revision files in filesystem
                for id in [r._id for r in resources]:
                    with open(os.path.join(project.path, Project._REVISIONS_DIRNAME, str(id)), 'w') as tf:
                        tf.write(str(id))  # arbitrary content
        
        # Upgrade the project to major version >= 2.
        # Ensure revisions appear to be migrated correctly.
        async with (await OpenOrCreateDialog.wait_for()).open(
                project_dirpath, wait_func=_wait_for_project_to_upgrade) as (mw, project):
            assert project.major_version >= 2, (
                'Expected project to be upgraded'
            )  # not == 1
            
            assert os.path.isdir(os.path.join(
                project.path, Project._REVISIONS_DIRNAME, '000', '000', '000', '000'))
            assert os.path.isfile(os.path.join(
                project.path, Project._REVISIONS_DIRNAME, '000', '000', '000', '000', '001'))
            
            assert os.path.isdir(os.path.join(
                project.path, Project._REVISIONS_DIRNAME, '000', '000', '000', '001'))
            assert os.path.isfile(os.path.join(
                project.path, Project._REVISIONS_DIRNAME, '000', '000', '000', '001', '000'))
            assert not os.path.exists(os.path.join(
                project.path, Project._REVISIONS_DIRNAME, '000', '000', '000', '001', '001'))
            
            assert not os.path.exists(os.path.join(
                project.path, Project._REVISIONS_DIRNAME, '000', '000', '000', '002'))


async def test_can_cancel_and_resume_upgrade_of_project_from_major_version_1_to_2() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        # Create project with major version = 1 and at least one revision
        async with _project_opened_without_migrating(project_dirpath) as (_, project):
            assert 1 == project.major_version, (
                'Expected project to not be upgraded'
            )  # not > 1
        old_revision_count = _count_files_in(
            os.path.join(project.path, Project._REVISIONS_DIRNAME))  # capture
        assert old_revision_count >= 1
        
        # Start upgrading the project to major version >= 2,
        # but cancel the upgrade after the second revision
        if True:
            ocd = await OpenOrCreateDialog.wait_for()
            
            progress_listener = progress._active_progress_listener
            assert progress_listener is not None
            
            # Prepare to: Cancel upgrade in the middle
            did_cancel_migration_in_middle = False  # type: bool
            def upgrading_revision(index: int, revisions_per_second: float) -> None:
                nonlocal did_cancel_migration_in_middle
                if index >= 1:
                    # Cancel before migrating the second revision
                    did_cancel_migration_in_middle = True
                    raise CancelOpenProject()
            
            with patch.object(progress_listener, 'upgrading_revision', upgrading_revision), \
                    _progress_reported_at_maximum_resolution():
                await ocd.start_opening(project_dirpath, next_window_name='cr-open-or-create-project')
                
                # HACK: Wait minimum duration to allow open to finish
                await bg_sleep(0.5)
                
                # Wait for migration to start, get cancelled, and return to initial dialog
                ocd = await OpenOrCreateDialog.wait_for()
                assert did_cancel_migration_in_middle
        
        # Verify looks like migration was canceled in filesystem
        assert os.path.exists(os.path.join(project.path, Project._REVISIONS_DIRNAME))
        assert os.path.exists(os.path.join(project.path, Project._IN_PROGRESS_REVISIONS_DIRNAME))
        assert 1 == _count_files_in(
            os.path.join(project.path, Project._IN_PROGRESS_REVISIONS_DIRNAME))
        assert (old_revision_count - 1) == _count_files_in(
            os.path.join(project.path, Project._REVISIONS_DIRNAME))
        
        # Resume upgrading the project to major version >= 2. Allow to finish.
        if True:
            async with (await OpenOrCreateDialog.wait_for()).open(
                    project_dirpath, wait_func=_wait_for_project_to_upgrade) as (mw, project):
                assert project.major_version >= 2, (
                    'Expected project to be upgraded'
                )  # not == 1
            new_revision_count = _count_files_in(
                os.path.join(project.path, Project._REVISIONS_DIRNAME))
        
        # Ensure all revisions appear to be migrated
        assert os.path.exists(os.path.join(project.path, Project._REVISIONS_DIRNAME))
        assert not os.path.exists(os.path.join(project.path, Project._IN_PROGRESS_REVISIONS_DIRNAME))
        assert old_revision_count == new_revision_count
        assert not os.path.exists(os.path.join(project.path, Project._TEMPORARY_DIRNAME, Project._REVISIONS_DIRNAME))


# --- 1 -> 2: Smoke test operations on both project versions ---

async def test_can_serve_revisions_from_project_with_major_version_1() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        async with _project_opened_without_migrating(project_dirpath) as (mw, project):
            assert 1 == project.major_version
            
            (server_page, _) = await serve_and_fetch_xkcd_home_page(mw)
            assert 200 == server_page.status


async def test_can_serve_revisions_from_project_with_major_version_2() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            assert 2 == project.major_version
            
            (server_page, _) = await serve_and_fetch_xkcd_home_page(mw)
            assert 200 == server_page.status


# --- Utility ---

@asynccontextmanager
async def _project_opened_without_migrating(
        project_dirpath: str
        ) -> AsyncIterator[tuple[MainWindow, Project]]:
    class NonUpgradingProject(Project):
        @override
        def _apply_migrations(self, *args, **kwargs) -> None:
            pass
    
    # Project imported inside by _prompt_to_open_project()
    with patch('crystal.model.Project', NonUpgradingProject), \
            patch('crystal.tests.util.windows.Project', NonUpgradingProject):
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            yield (mw, project)


@contextmanager
def _upgrade_required_modal_always_shown() -> Iterator[None]:
    was_enabled = OpenProjectProgressDialog._always_show_upgrade_required_modal
    OpenProjectProgressDialog._always_show_upgrade_required_modal = True
    try:
        yield
    finally:
        OpenProjectProgressDialog._always_show_upgrade_required_modal = was_enabled


@contextmanager
def _progress_reported_at_maximum_resolution() -> Iterator[None]:
    was_enabled = Project._report_progress_at_maximum_resolution
    Project._report_progress_at_maximum_resolution = True
    try:
        yield
    finally:
        Project._report_progress_at_maximum_resolution = was_enabled


def _count_files_in(dirpath: str) -> int:
    file_count = 0
    for (_, _, filenames) in os.walk(dirpath):
        file_count += len(filenames)
    return file_count


async def _wait_for_project_to_upgrade() -> None:
    if OpenProjectProgressDialog._upgrading_revision_progress is None:
        OpenProjectProgressDialog._upgrading_revision_progress = 0
    
    def progression_func() -> int | None:
        return OpenProjectProgressDialog._upgrading_revision_progress
    await wait_while(progression_func)
