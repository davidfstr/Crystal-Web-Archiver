"""
*Direct* tests of the model layer.

The majority of the model layer's test coverage is *indirect*,
through higher level tests that operate at the UI layer.

Unless otherwise documented/specified, all model operations are expected to be:
- Atomic
    - Each write operation either fully completes or fully fails.
- Durable
    - Each write operation that completed successfully STAYS complete
      even after the project is closed through exceptional circumstances like
      disk disconnection, disk full, disk I/O error (bad blocks), or
      sudden process termination.

Related audit documentation:
- doc/model_durability_and_atomicity.md
"""

from crystal.model import Project, Resource, ResourceRevision, RootResource, ResourceGroup
from crystal.tests.task.test_download_body import (
    database_cursor_mocked_to_raise_database_io_error_on_write,
    downloads_mocked_to_raise_disk_io_error,
)
from crystal.tests.util.asserts import assertEqual
from crystal.tests.util.server import served_project
from crystal.tests.util.skip import skipTest
from crystal.tests.util.subtests import SubtestsContext, with_subtests
from crystal.tests.util.wait import wait_for_future
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.filesystem import flush_renames_in_directory, rename_and_flush
from crystal.util.xos import is_linux, is_mac_os, is_windows
import crystal.tests.util.xtempfile as xtempfile
import contextlib
import ctypes
import errno
import os
import sqlite3
import threading
from typing import assert_never, Callable, Literal, Optional
from unittest import skip
from unittest.mock import ANY, Mock, patch


# ------------------------------------------------------------------------------
# Test: Project

# === Test: Project: Migrate v1 -> v2: _migrate_v1_to_v2 ===

@skip('not yet automated')
async def test_given_migration_v1_to_v2_in_progress_when_processing_revisions_then_flushes_occur_whenever_leaving_a_directory_containing_renamed_files() -> None:
    # Verify that during migration, flush_rename_of_file is called periodically
    # (when revision filepath ends in 'fff') to ensure progress is durable
    pass


@skip('not yet automated')
async def test_given_migration_v1_to_v2_completes_when_last_revision_processed_then_last_directory_containing_renamed_files_is_flushed() -> None:
    # Verify that after all revisions are migrated, a final flush occurs for
    # the last revision's parent directory
    pass


# === Test: Project: Migrate v1 -> v2: _commit_migrate_v1_to_v2 atomicity ===

# Notes:
# - The commit is made atomic by:
#       (1) setting major_version to 2 first,
#       (2) performing directory renames,
#       (3) flushing the final rename.
#   If a crash occurs anywhere in this sequence, reopening the project will 
#   detect the incomplete commit and resume it.
# - The in-progress revisions directory serves as a marker that the commit
#   is incomplete.

@skip('not yet automated')
async def test_given_migration_v1_to_v2_ready_to_commit_when_commit_and_crash_occurs_after_major_version_update_but_before_directory_renames_then_reopening_resumes_commit() -> None:
    # Verify that if crash occurs after major_version is set to 2 but before
    # directory renames complete, reopening the project detects the incomplete
    # commit (via existence of in-progress revisions directory) and resumes it
    pass


@skip('not yet automated')
async def test_given_migration_v1_to_v2_ready_to_commit_when_commit_and_crash_occurs_after_directory_renames_but_before_final_flush_then_reopening_resumes_commit() -> None:
    # Verify that if crash occurs after directory renames but before final flush,
    # reopening the project detects the incomplete commit and resumes it
    pass


@skip('not yet automated')
async def test_given_migration_v1_to_v2_ready_to_commit_when_commit_completes_successfully_then_old_revisions_directory_moved_aside_and_new_directory_in_place() -> None:
    # Verify that after successful commit, old revisions directory is in .tmp/,
    # new revisions directory is at revisions/, and final flush has occurred
    pass


@skip('covered by: ' + ','.join([
    'test_given_migration_v1_to_v2_ready_to_commit_when_commit_and_crash_occurs_after_major_version_update_but_before_directory_renames_then_reopening_resumes_commit',
    'test_given_migration_v1_to_v2_ready_to_commit_when_commit_and_crash_occurs_after_directory_renames_but_before_final_flush_then_reopening_resumes_commit',
]))
async def test_given_project_at_major_version_2_with_incomplete_commit_when_open_then_commit_is_resumed_automatically() -> None:
    pass


# ------------------------------------------------------------------------------
# Test: Resource

# === Test: Resource: Create ===

@skip('not yet automated')
async def test_create_resource_is_atomic_and_durable() -> None:
    # ...because it is entirely performed within a single database transaction
    pass


# === Test: Resource: Delete ===

@skip('not yet automated')
async def test_given_resource_with_multiple_revisions_when_delete_and_first_revision_delete_fails_then_remaining_revisions_are_left_intact() -> None:
    # Verify that if any revision deletion fails, the remaining revisions (especially the most recent)
    # are preserved, as documented in the code comment
    pass


@skip('not yet automated')
async def test_given_resource_with_multiple_revisions_when_delete_and_all_revision_deletes_succeed_then_delete_fully_succeeds() -> None:
    pass


# ------------------------------------------------------------------------------
# Test: RootResource

# === Test: RootResource: Create ===

@skip('not yet automated')
async def test_create_root_resource_is_atomic_and_durable() -> None:
    # ...because it is entirely performed within a single database transaction
    pass


# === Test: RootResource: Delete ===

async def test_given_root_resource_referenced_by_groups_when_delete_and_database_error_occurs_then_delete_fully_fails_and_all_sources_remain_intact() -> None:
    """
    Verify that when database deletion fails, the entire delete operation fails atomically,
    and all other groups that had this group as a source still reference it.
    """
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Create a RootResource
        home_url = 'https://example.com/'
        home_r = Resource(project, home_url)
        home_rr = RootResource(project, 'Home', home_r)
        
        # Create 2 ResourceGroups that use the RootResource as their source
        group1_pattern = r'^https://example\.com/group1/.*'
        group2_pattern = r'^https://example\.com/group2/.*'
        group1 = ResourceGroup(project, 'Group1', group1_pattern, source=home_rr)
        group2 = ResourceGroup(project, 'Group2', group2_pattern, source=home_rr)
        assert group1.source == home_rr, 'Group1 source should be home_rr'
        assert group2.source == home_rr, 'Group2 source should be home_rr'
        
        # Allow "update resource_group ..." command but not "delete from root_resource ..."
        def should_raise_on_delete_from_root_resource(command: str) -> bool:
            return 'delete from root_resource' in command
        with database_cursor_mocked_to_raise_database_io_error_on_write(
                project,
                should_raise=should_raise_on_delete_from_root_resource,
                ) as is_db_io_error:
            
            # Attempt to delete the RootResource
            try:
                home_rr.delete()
            except Exception as e:
                assert is_db_io_error(e), f'Expected database I/O error, got {type(e).__name__}: {e}'
            else:
                raise AssertionError('Expected delete() to raise database error')
        
        # Verify atomicity
        # 1. Sources should still reference the RootResource
        assert group1.source == home_rr, 'Group1 source should still be home_rr after failed delete'
        assert group2.source == home_rr, 'Group2 source should still be home_rr after failed delete'
        # 2. The RootResource should still exist
        assert home_rr in project.root_resources, 'RootResource should still exist in project after failed delete'


async def test_given_root_resource_referenced_by_groups_when_delete_fully_succeeds_then_all_referencing_groups_have_source_set_to_none() -> None:
    """
    Verify that when deletion succeeds, all other groups that had this group as a source
    now have source=None.
    """
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Create a RootResource
        home_url = 'https://example.com/'
        home_r = Resource(project, home_url)
        home_rr = RootResource(project, 'Home', home_r)
        
        # Create 2 ResourceGroups that use the RootResource as their source
        group1_pattern = r'^https://example\.com/group1/.*'
        group2_pattern = r'^https://example\.com/group2/.*'
        group1 = ResourceGroup(project, 'Group1', group1_pattern, source=home_rr)
        group2 = ResourceGroup(project, 'Group2', group2_pattern, source=home_rr)
        assert group1.source == home_rr, 'Group1 source should be home_rr'
        assert group2.source == home_rr, 'Group2 source should be home_rr'
        
        # Delete the RootResource
        home_rr.delete()
        
        # Verify deleted
        # 1. Sources should be cleared
        assert group1.source == None
        assert group2.source == None
        # 2. The RootResource should NOT still exist
        assert home_rr not in project.root_resources


@skip('not yet automated')
async def test_given_root_resource_not_referenced_by_groups_when_delete_then_fully_succeeds() -> None:
    # ...because it is entirely performed within a single database transaction
    pass


# ------------------------------------------------------------------------------
# Test: ResourceRevision

# === Test: ResourceRevision: Create: _create_from_stream ===

# Notes:
# - All factory methods of ResourceRevision delegate to _create_from_stream
#   to do the actual work. Factory methods are:
#     - create_from_revision
#     - create_from_error
#     - create_from_response

@skip('not yet automated')
async def test_create_resource_revision_is_durable() -> None:
    # ...because it is performed within a single database transaction
    #    plus a filesystem write that is flushed to disk explicitly
    pass


async def test_when_create_resource_revision_and_io_error_before_filesystem_flush_then_will_rollback_immediately() -> None:
    """
    Verify that when an I/O error occurs during revision body download
    (before the filesystem flush completes), the database row is rolled back
    immediately and the error is propagated to the caller.
    
    The expected behavior is:
    1. Database row is inserted for the revision
    2. I/O error occurs during body file write
    3. Database row is deleted (rollback)
    4. A new error revision is created (without body)
    """
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Track database operations
            db_revision_inserts = []
            db_revision_deletes = []
            
            real_cursor_func = project._db.cursor  # capture
            def spy_cursor():
                real_cursor = real_cursor_func()
                
                def spy_execute(command: str, *args, **kwargs):
                    # Track insert and delete operations on resource_revision table specifically
                    if command.strip().startswith('insert into resource_revision'):
                        db_revision_inserts.append((command, args))
                    elif command.strip().startswith('delete from resource_revision'):
                        db_revision_deletes.append((command, args))
                    return real_cursor.execute(command, *args, **kwargs)
                
                spy_cursor_obj = Mock(wraps=real_cursor)
                spy_cursor_obj.execute = spy_execute
                type(spy_cursor_obj).lastrowid = property(lambda self: real_cursor.lastrowid)
                return spy_cursor_obj
            
            # Raise I/O error during body download
            with patch.object(project._db, 'cursor', spy_cursor):
                with downloads_mocked_to_raise_disk_io_error() as is_io_error:
                    r = Resource(project, home_url)
                    revision_future = r.download_body()
                    
                    # Ensure I/O error is reported as an error revision
                    revision = await wait_for_future(revision_future)
                    assert revision.error is not None
                    assert is_io_error(revision.error)
            
            # Verify database operations occurred as expected:
            # 1. Two revision inserts: first attempt with metadata, then error revision
            # 2. One rollback delete should occur for the first revision that failed
            assert len(db_revision_inserts) == 2, \
                f'Expected 2 revision inserts (initial attempt + error revision), got {len(db_revision_inserts)}'
            assert len(db_revision_deletes) == 1, \
                f'Expected 1 revision delete (rollback of first attempt), got {len(db_revision_deletes)}'
            
            # Verify database and filesystem is in expected state
            assert 1 == project._revision_count(), 'Only error revision should remain in database'
            assert not revision.has_body, 'Body file should not exist for error revision'
            assert [] == os.listdir(os.path.join(
                project.path, Project._TEMPORARY_DIRNAME)), 'Temporary files should be cleaned up'


async def test_when_create_resource_revision_and_disk_disconnects_or_disk_full_or_process_terminates_before_filesystem_flush_then_will_rollback_when_project_reopened() -> None:
    """
    Verify that when a disk disconnection (or other permanent I/O error) occurs
    during revision body download, preventing the rollback from completing,
    the orphaned revision is automatically cleaned up when the project is reopened.
    
    The expected behavior is:
    1. Download 3 revisions successfully (so rollback logic considers it safe to rollback later)
    2. For the 4th revision:
       - Database row is inserted
       - Disk disconnection occurs during body file write
       - Rollback is attempted but fails due to disk disconnection
       - Project becomes unusable
    3. Project is closed (simulating app crash or user forcibly closing)
    4. "Disk is reconnected"
    5. Project is reopened
    6. Repair logic detects orphaned 4th revision and deletes it
    7. Only 3 revisions remain
    """
    await _test_orphaned_revision_repair()


async def _test_orphaned_revision_repair(
        *, last_revision_error_type: Literal['disk_disconnect', 'bad_block'] = 'disk_disconnect',
        before_reopen: Optional[Callable[[str, Project], None]] = None,
        expect_repair_success: bool = True,
        database_partially_corrupt_after_disk_reconnect: bool = False,
        ) -> None:
    """
    Tests orphaned revision repair logic.
    
    Arguments:
    * last_revision_error_type --
        Type of error to simulate for the last (4th) revision.
        - 'disk_disconnect': Simulates full disk disconnect, causing both body write
          and rollback to fail. Creates orphaned revision with missing body.
        - 'bad_block': Simulates bad block during body write only. Creates error
          revision (has_body=False) without attempting rollback.
    * before_reopen --
        Optional callable(project_dirpath, project) to run after project
        is closed but before it is reopened. Can be used to modify the project state.
    * database_partially_corrupt_after_disk_reconnect --
        Whether to simulate database corruption at the specific ResourceRevision row
        when attempting to delete the orphaned revision during repair.
        If True, the delete() call will raise sqlite3.OperationalError.
    * expect_repair_success --
        Whether to expect the repair to succeed.
        If True, expects revision 4 to be deleted and only 3 revisions to remain.
        If False, expects revision 4 to remain and 4 revisions total.
    """
    if database_partially_corrupt_after_disk_reconnect:
        assert last_revision_error_type == 'disk_disconnect'
    
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
        comic1_url = sp.get_request_url('https://xkcd.com/1/')
        comic2_url = sp.get_request_url('https://xkcd.com/2/')
        comic3_url = sp.get_request_url('https://xkcd.com/3/')
        
        with xtempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            # Create project and download 3 revisions successfully
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, project):
                # Download 3 revisions
                for url in [home_url, comic1_url, comic2_url]:
                    r = Resource(project, url)
                    revision_future = r.download_body()
                    revision = await wait_for_future(revision_future)
                    assert revision.error is None, f'Expected successful download for {url}'
                    assert revision.has_body, f'Expected body for {url}'
                assertEqual(3, project._revision_count())
                
                # Simulate error while downloading a 4th revision.
                # Behavior depends on last_revision_error_type.
                if last_revision_error_type == 'disk_disconnect':
                    # Simulate disk disconnection while downloading a 4th revision.
                    # After the disk disconnects, all I/O operations fail.
                    r4 = Resource(project, comic3_url)
                    
                    revision_row_written = threading.Event()
                    disk_disconnected = threading.Event()
                    
                    # 1. Simulate disk disconnection during body write
                    #    after database row successfully written.
                    # 2. Mock downloads to raise I/O error after disk disconnect
                    #
                    # This will cause:
                    # 1. Revision row to be created in database (before disconnect)
                    # 2. Body file write to fail with I/O error (after disconnect)
                    # 3. Rollback attempt (DELETE) to fail with database I/O error
                    # 4. Error revision creation to fail with database I/O error
                    def disk_will_raise() -> None:
                        if not revision_row_written.wait(timeout=5.0):
                            raise TimeoutError('Timed out waiting for revision_row_written')
                        disk_disconnected.set()
                    with downloads_mocked_to_raise_disk_io_error(
                            will_raise=disk_will_raise) as is_download_io_error:
                        
                        # Mock database to raise I/O error after disk disconnect
                        def db_should_raise(command: str) -> bool:
                            result = disk_disconnected.is_set()  # capture
                            revision_row_written.set()
                            return result
                        with database_cursor_mocked_to_raise_database_io_error_on_write(
                                project,
                                should_raise=db_should_raise) as is_db_io_error:
                            
                            # Start downloading 4th revision
                            revision_future = r4.download_body()
                            
                            # Wait for download to complete with error.
                            # The error will propagate because even creating an error revision fails.
                            try:
                                revision4 = await wait_for_future(revision_future)
                            except Exception as e:
                                # Verify it's an I/O error
                                assert is_download_io_error(e) or is_db_io_error(e), \
                                    f'Expected I/O error, got {e}'
                            else:
                                raise AssertionError('Expected download to fail with unhandled I/O error')
                    
                    # After disk disconnect, orphaned revision 4 should exist in database
                    # (created before disconnect) but its body file should not exist (write failed)
                    assertEqual(4, project._revision_count(), 
                        'Orphaned revision should exist in database after failed rollback')
                    assert False == os.path.exists(ResourceRevision._body_filepath_with(
                        project.path, project.major_version, revision_id=4,
                    ))
                
                elif last_revision_error_type == 'bad_block':
                    # Simulate bad block during body write only.
                    # This causes body write to fail but allows rollback and error revision creation to succeed.
                    r4 = Resource(project, comic3_url)
                    
                    # Mock downloads to raise I/O error immediately
                    with downloads_mocked_to_raise_disk_io_error() as is_download_io_error:
                        # Start downloading 4th revision
                        revision_future = r4.download_body()
                        
                        # Wait for download to complete.
                        # An error revision (has_body=False) should be created successfully.
                        revision4 = await wait_for_future(revision_future)
                        assert revision4.error is not None, \
                            'Expected error revision to be created'
                        assert is_download_io_error(revision4.error), \
                            f'Expected I/O error, got {revision4.error}'
                        assert not revision4.has_body, \
                            'Error revision should not have body'
                    
                    # After bad block, error revision 4 should exist in database
                    # with has_body=False (no body expected)
                    assertEqual(4, project._revision_count(), 
                        'Error revision should exist in database')
                
                else:
                    assert_never(last_revision_error_type)
            
            if 'last_revision_error_type' == 'disk_disconnect':
                # Reconnect disk.
                # NOTE: No observable effects yet.
                pass
            
            # Run before_reopen hook if provided
            if before_reopen is not None:
                before_reopen(project_dirpath, project)
            
            # Reopen project. The repair logic may detect and clean up the orphaned revision.
            # 
            # If database_partially_corrupt_after_disk_reconnect is True, simulate corruption
            # during the deletion attempt.
            if database_partially_corrupt_after_disk_reconnect:
                # Patch ResourceRevision.delete() to raise I/O error
                mock_delete_raised_error = False
                def mock_delete_with_error(self):
                    nonlocal mock_delete_raised_error
                    mock_delete_raised_error = True
                    raise sqlite3.OperationalError('disk I/O error')  # SQLITE_IOERR
                corruption_context = patch.object(
                    ResourceRevision, 'delete', mock_delete_with_error
                )  # type: contextlib.AbstractContextManager
            else:
                # No corruption simulation needed
                corruption_context = contextlib.nullcontext()
            with corruption_context:
                with patch('builtins.print', wraps=print) as spy_print:
                    async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                        if expect_repair_success:
                            # Verify repair message was printed
                            spy_print.assert_any_call(
                                '*** Cleaning up likely-orphaned revision 4. '
                                    'Missing body file. Probable rollback failure.',
                                file=ANY)
                            
                            # Verify only 3 revisions remain (4th was rolled back)
                            assertEqual(3, project._revision_count())
                        else:
                            if database_partially_corrupt_after_disk_reconnect:
                                # Special case: Repair was ATTEMPTED but failed during deletion
                                
                                # Verify repair message was printed
                                spy_print.assert_any_call(
                                    '*** Cleaning up likely-orphaned revision 4. '
                                        'Missing body file. Probable rollback failure.',
                                    file=ANY)
                                
                                # Verify 4 revisions remain (4th was NOT successfully rolled back)
                                assertEqual(4, project._revision_count())
                                
                                # Verify delete was called and raised an error
                                assert mock_delete_raised_error
                            else:
                                # Verify no repair message was printed
                                for call in spy_print.call_args_list:
                                    (args, kwargs) = call
                                    if len(args) > 0 and 'Cleaning up likely-orphaned revision' in str(args[0]):
                                        raise AssertionError('Repair message should not have been printed')
                                
                                # Verify 4 revisions remain (4th was NOT rolled back)
                                assertEqual(4, project._revision_count())


# === Test: ResourceRevision: Create: _repair_incomplete_rollback_of_resource_revision_create ===

# Notes:
# - This repair logic runs automatically when opening a project as writable.
# - The repair uses heuristics to detect likely-orphaned revisions from 
#   failed rollbacks, being conservative to avoid false positives.
# - The logic specifically checks only the last revision because that's where 
#   a permanent I/O failure (like disk disconnection) would have occurred 
#   during the most recent write operation.

@skip('covered by: any test that creates a new empty project')
async def test_given_no_revisions_exist_when_repair_then_no_action_taken() -> None:
    # Verify that repair logic handles empty projects gracefully
    pass


@skip('not yet automated')
async def test_given_last_revision_has_body_when_repair_then_no_deletion_occurs() -> None:
    # Verify that if last revision's body exists, it's not considered orphaned
    pass


async def test_given_last_revision_has_no_body_expected_when_repair_then_no_deletion_occurs() -> None:
    """
    Verify that if last revision is an error (has_body=False), it's not considered orphaned.
    
    This test simulates a scenario where:
    1. Revisions 1-3 are downloaded successfully
    2. Revision 4 fails with a bad block error during body write
    3. An error revision (has_body=False) is created successfully
    4. When project is reopened, repair logic should NOT delete revision 4
       because it's a valid error revision with no body expected
    """
    await _test_orphaned_revision_repair(
        last_revision_error_type='bad_block',
        expect_repair_success=False,
    )


@skip('not yet automated')
async def test_given_last_revision_body_missing_but_fewer_than_3_other_revisions_when_repair_then_no_deletion_occurs() -> None:
    # Verify that repair is conservative and doesn't delete the last revision
    # if there aren't enough other revisions to confirm filesystem accessibility
    pass


async def test_given_last_revision_body_missing_and_other_revision_bodies_also_missing_or_unreadable_when_repair_then_no_deletion_occurs() -> None:
    """
    Verify that if multiple revision bodies are missing (suggesting unmounted
    filesystem or intermittent availability), repair doesn't delete anything.
    
    This test simulates a scenario where:
    1. Revisions 1-3 are downloaded successfully
    2. Revision 4 fails with disk disconnect (orphaned revision)
    3. Before reopening, revision 3's body is deleted (simulating filesystem issues)
    4. When project is reopened, repair logic should NOT delete revision 4
       because multiple revisions are missing bodies, suggesting a broader problem
    """
    def before_reopen(project_dirpath: str, project: Project) -> None:
        # Delete revision 3's body file to simulate filesystem issues
        revision3_filepath = ResourceRevision._body_filepath_with(
            project_dirpath, project.major_version, revision_id=3)
        if os.path.exists(revision3_filepath):
            os.remove(revision3_filepath)
    
    await _test_orphaned_revision_repair(
        before_reopen=before_reopen,
        expect_repair_success=False,
    )


@skip('covered by: test_when_create_resource_revision_and_disk_disconnects_or_disk_full_or_process_terminates_before_filesystem_flush_then_will_rollback_when_project_reopened')
async def test_given_last_revision_body_missing_and_at_least_3_other_revision_bodies_readable_when_repair_then_last_revision_deleted() -> None:
    # Verify that if last revision's body is missing but at least 3 other
    # revisions have readable bodies (confirming filesystem is accessible),
    # the last revision is deleted to complete the failed rollback
    pass


@skip('not yet automated')
async def test_given_database_error_while_loading_last_revision_when_repair_then_project_continues_opening() -> None:
    # Verify that if database is corrupt, repair aborts gracefully & the project continues opening
    pass


@skip('not yet automated')
async def test_given_io_error_while_checking_revision_bodies_when_repair_then_project_continues_opening() -> None:
    # Verify that if I/O errors occur while checking revision bodies, repair aborts gracefully & the project continues opening
    pass


async def test_given_deletion_fails_during_repair_when_repair_then_project_continues_opening() -> None:
    """
    Verify that if deletion fails during repair, repair aborts gracefully & the project continues opening.
    
    This test simulates a scenario where:
    1. Revisions 1-3 are downloaded successfully
    2. Revision 4 fails with disk disconnect (orphaned revision with missing body)
    3. Disk is reconnected
    4. When project is reopened, repair logic attempts to delete revision 4
    5. Deletion fails with database I/O error (simulating partial corruption)
    6. Repair aborts gracefully and project continues opening with revision 4 still present
    """
    await _test_orphaned_revision_repair(
        database_partially_corrupt_after_disk_reconnect=True,
        expect_repair_success=False,
    )


# === Test: ResourceRevision: Delete ===

@skip('not yet automated')
async def test_given_resource_revision_exists_when_delete_and_database_error_occurs_then_delete_fully_fails_and_revision_remains_intact() -> None:
    # Verify that when database deletion fails, both the database row and body file remain
    pass


@skip('not yet automated')
async def test_given_resource_revision_exists_when_delete_and_database_succeeds_but_body_file_deletion_fails_then_delete_partially_succeeds_leaving_dangling_body_file() -> None:
    # Verify that when database deletion succeeds but file deletion fails (e.g., permission error),
    # the revision is removed from database but body file remains
    pass


@skip('not yet automated')
async def test_given_resource_revision_exists_when_delete_and_body_file_already_missing_then_delete_succeeds_without_error() -> None:
    # Verify that FileNotFoundError during body file deletion is handled gracefully
    pass


@skip('not yet automated')
async def test_given_resource_revision_exists_when_delete_and_database_succeeds_and_body_file_deletion_succeeds_then_delete_fully_succeeds() -> None:
    pass


# === Test: filesystem: rename_and_flush ===

def test_given_macos_or_linux_when_rename_and_flush_then_calls_fsync_on_parent_directory() -> None:
    """
    Verify that rename_and_flush calls fsync on the parent directory (via flush_renames_in_directory)
    to ensure the rename is flushed to disk on macOS and Linux.
    """
    if not (is_mac_os() or is_linux()):
        skipTest('only supported on macOS and Linux')
    
    with xtempfile.TemporaryDirectory() as temp_dir:
        src_path = os.path.join(temp_dir, 'source.txt')
        dst_path = os.path.join(temp_dir, 'dest.txt')
        
        # Create source file
        with open(src_path, 'w') as f:
            f.write('test content')
        
        # Capture the fd that's opened for the parent directory
        temp_dir_fd = None
        original_open = os.open
        def spy_open(path, *args, **kwargs):
            fd = original_open(path, *args, **kwargs)
            if path == temp_dir:
                nonlocal temp_dir_fd
                temp_dir_fd = fd
            return fd
        
        # Spy on os.open and os.fsync
        with patch('os.open', side_effect=spy_open), \
                patch('os.fsync', wraps=os.fsync) as spy_fsync:
            rename_and_flush(src_path, dst_path)
            
            # Verify os.open was called to open the parent directory
            assert temp_dir_fd is not None, (
                f'Expected os.open to be called with parent directory {temp_dir}, '
                f'but it was not opened'
            )
            
            # Verify fsync was called with the same fd that was opened
            assert spy_fsync.call_count >= 1
            fsync_called_with_correct_fd = False
            for call in spy_fsync.call_args_list:
                fd = call[0][0]
                assert isinstance(fd, int)
                if fd == temp_dir_fd:
                    fsync_called_with_correct_fd = True
                    break
            assert fsync_called_with_correct_fd, (
                f'Expected os.fsync to be called with fd {temp_dir_fd}, '
                f'but it was called with: {[call[0][0] for call in spy_fsync.call_args_list]}'
            )
        
        # Verify the rename succeeded
        assert not os.path.exists(src_path), 'Source file should no longer exist'
        assert os.path.exists(dst_path), 'Destination file should exist'


def test_given_windows_when_rename_and_flush_then_calls_movefile_with_writethrough() -> None:
    """
    Verify that rename_and_flush calls MoveFileExW with MOVEFILE_WRITE_THROUGH flag
    to ensure the rename is flushed to disk on Windows.
    """
    if not is_windows():
        skipTest('only supported on Windows')
    
    with xtempfile.TemporaryDirectory() as temp_dir:
        src_path = os.path.join(temp_dir, 'source.txt')
        dst_path = os.path.join(temp_dir, 'dest.txt')
        
        # Create source file
        with open(src_path, 'w') as f:
            f.write('test content')
        
        # Track MoveFileExW calls by patching ctypes.WinDLL
        move_calls = []
        original_WinDLL = ctypes.WinDLL  # type: ignore[attr-defined]
        class SpyWinDLL:
            def __init__(self, name, **kwargs):
                self._dll = original_WinDLL(name, **kwargs)
            
            def __getattr__(self, name):
                attr = getattr(self._dll, name)
                if name == 'MoveFileExW':
                    # Wrap MoveFileExW to track calls,
                    # copying some important attributes
                    original_func = attr  # capture
                    def spy_MoveFileExW(src, dst, flags):
                        move_calls.append({
                            'src': src,
                            'dst': dst,
                            'flags': flags,
                        })
                        return original_func(src, dst, flags)
                    spy_MoveFileExW.argtypes = getattr(original_func, 'argtypes', None)
                    spy_MoveFileExW.restype = getattr(original_func, 'restype', None)
                    return spy_MoveFileExW
                return attr
        with patch('ctypes.WinDLL', SpyWinDLL):
            rename_and_flush(src_path, dst_path)
        
        # Verify MoveFileExW was called
        (call,) = move_calls
        assertEqual(src_path, call['src'])
        assertEqual(dst_path, call['dst'])
        
        # Verify MOVEFILE_WRITE_THROUGH flag (0x8) is set
        MOVEFILE_WRITE_THROUGH = 0x8
        assert (call['flags'] & MOVEFILE_WRITE_THROUGH) != 0, (
            f'Expected MoveFileExW to be called with MOVEFILE_WRITE_THROUGH flag (0x8), '
            f'but got flags={call["flags"]:#x}'
        )
        
        # Verify the rename succeeded
        assert not os.path.exists(src_path), 'Source file should no longer exist'
        assert os.path.exists(dst_path), 'Destination file should exist'


# === Test: filesystem: flush_renames_in_directory ===

@with_subtests
def test_given_macos_or_linux_when_flush_renames_in_directory_then_calls_fsync(subtests: SubtestsContext) -> None:
    """
    Verify that flush_renames_in_directory calls fsync on the directory file descriptor.
    """
    if not (is_mac_os() or is_linux()):
        skipTest('only supported on macOS and Linux')
    
    # Case 1: fsync supported by filesystem; does not raise
    with subtests.test(fsync_support=True, fsync_io_error=False):
        with xtempfile.TemporaryDirectory() as temp_dir:
            # Capture the fd that's opened for the directory
            temp_dir_fd = None
            original_open = os.open
            def spy_open(path, *args, **kwargs):
                fd = original_open(path, *args, **kwargs)
                if path == temp_dir:
                    nonlocal temp_dir_fd
                    temp_dir_fd = fd
                return fd
            
            with patch('os.open', side_effect=spy_open), \
                    patch('os.fsync', wraps=os.fsync) as spy_fsync:
                flush_renames_in_directory(temp_dir)
                
                # Verify os.open was called to open the directory
                assert temp_dir_fd is not None, (
                    f'Expected os.open to be called with directory {temp_dir}, '
                    f'but it was not opened'
                )
                
                # Verify fsync was called with the same fd that was opened
                assert spy_fsync.call_count == 1
                fd = spy_fsync.call_args[0][0]
                assert isinstance(fd, int)
                assert fd == temp_dir_fd, (
                    f'Expected os.fsync to be called with fd {temp_dir_fd}, '
                    f'but it was called with fd {fd}'
                )
    
    # Case 2: fsync unsupported by filesystem; does not raise
    with subtests.test(fsync_support=False):
        for unsupported_errno in (errno.EINVAL, errno.ENOTSUP, getattr(errno, 'ENOSYS', None)):
            if unsupported_errno is None:
                continue  # ENOSYS may not exist on all platforms
            
            with xtempfile.TemporaryDirectory() as temp_dir:
                def mock_fsync_unsupported(fd):
                    # Simulate filesystem that doesn't support fsync
                    raise OSError(unsupported_errno, os.strerror(unsupported_errno))
                
                with patch('os.fsync', side_effect=mock_fsync_unsupported) as spy_fsync:
                    # Should not raise even though fsync fails with unsupported error
                    flush_renames_in_directory(temp_dir)
                    
                    # Verify fsync was called
                    assert spy_fsync.call_count == 1
    
    # Case 3: fsync I/O error; raises
    with subtests.test(fsync_support=True, fsync_io_error=True):
        with xtempfile.TemporaryDirectory() as temp_dir:
            def mock_fsync_io_error(fd):
                # Simulate an actual I/O error (not an unsupported operation)
                raise OSError(errno.EIO, 'Input/output error')
            
            with patch('os.fsync', side_effect=mock_fsync_io_error):
                # Should raise the I/O error
                try:
                    flush_renames_in_directory(temp_dir)
                except OSError as e:
                    assert e.errno == errno.EIO, (
                        f'Expected errno.EIO ({errno.EIO}), but got {e.errno}'
                    )
                else:
                    raise AssertionError('Expected OSError to be raised for I/O error')


def test_given_windows_when_flush_renames_in_directory_then_does_nothing() -> None:
    """
    Verify that flush_renames_in_directory does nothing on Windows
    (since Windows doesn't provide an API to bulk-flush renames in a directory).
    """
    if not is_windows():
        skipTest('only supported on Windows')
    
    with xtempfile.TemporaryDirectory() as temp_dir:
        # Call flush_renames_in_directory and verify it doesn't raise an error
        flush_renames_in_directory(temp_dir)
        
        # (Success if we get here without any exceptions.
        #  The function should be a no-op on Windows.)


# ------------------------------------------------------------------------------
# Test: ResourceGroup

# === Test: ResourceGroup: Create ===

@skip('not yet automated')
async def test_given_new_resource_group_when_init_and_database_error_occurs_during_source_update_then_no_partial_resource_group_is_created() -> None:
    # Verify that if database error occurs while setting the source field,
    # the entire ResourceGroup creation is rolled back atomically,
    # leaving no partial ResourceGroup in the database
    pass


@skip('not yet automated')
async def test_given_new_resource_group_when_init_completes_successfully_then_both_group_and_source_are_committed_atomically() -> None:
    # Verify that ResourceGroup creation and source setting happen in a single transaction
    pass


# === Test: ResourceGroup: Delete ===

async def test_given_resource_group_referenced_by_other_groups_when_delete_and_database_error_occurs_then_delete_fully_fails_and_all_sources_remain_intact() -> None:
    """
    Verify that when database deletion fails, the entire delete operation fails atomically,
    and all other groups that had this group as a source still reference it.
    """
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Create a source ResourceGroup
        source_pattern = r'^https://example\.com/source/.*'
        source_group = ResourceGroup(project, 'Source', source_pattern, source=None)
        
        # Create 2 ResourceGroups that use the source group as their source
        group1_pattern = r'^https://example\.com/group1/.*'
        group2_pattern = r'^https://example\.com/group2/.*'
        group1 = ResourceGroup(project, 'Group1', group1_pattern, source=source_group)
        group2 = ResourceGroup(project, 'Group2', group2_pattern, source=source_group)
        assert group1.source == source_group, 'Group1 source should be source_group'
        assert group2.source == source_group, 'Group2 source should be source_group'
        
        # Allow "update resource_group ..." command but not "delete from resource_group ..." for source_group
        def should_raise_on_delete_from_resource_group(command: str) -> bool:
            # Only raise on the delete for the source group, not on updates
            return 'delete from resource_group' in command
        with database_cursor_mocked_to_raise_database_io_error_on_write(
                project,
                should_raise=should_raise_on_delete_from_resource_group,
                ) as is_db_io_error:
            
            # Attempt to delete the source ResourceGroup
            try:
                source_group.delete()
            except Exception as e:
                assert is_db_io_error(e), f'Expected database I/O error, got {type(e).__name__}: {e}'
            else:
                raise AssertionError('Expected delete() to raise database error')
        
        # Verify atomicity
        # 1. Sources should still reference the source group
        assert group1.source == source_group, 'Group1 source should still be source_group after failed delete'
        assert group2.source == source_group, 'Group2 source should still be source_group after failed delete'
        # 2. The source ResourceGroup should still exist
        assert source_group in project.resource_groups, 'ResourceGroup should still exist in project after failed delete'


async def test_given_resource_group_referenced_by_other_groups_when_delete_fully_succeeds_then_all_referencing_groups_have_source_set_to_none() -> None:
    """
    Verify that when deletion succeeds, all other groups that had this group as a source
    now have source=None.
    """
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Create a source ResourceGroup
        source_pattern = r'^https://example\.com/source/.*'
        source_group = ResourceGroup(project, 'Source', source_pattern, source=None)
        
        # Create 2 ResourceGroups that use the source group as their source
        group1_pattern = r'^https://example\.com/group1/.*'
        group2_pattern = r'^https://example\.com/group2/.*'
        group1 = ResourceGroup(project, 'Group1', group1_pattern, source=source_group)
        group2 = ResourceGroup(project, 'Group2', group2_pattern, source=source_group)
        assert group1.source == source_group, 'Group1 source should be source_group'
        assert group2.source == source_group, 'Group2 source should be source_group'
        
        # Delete the source ResourceGroup
        source_group.delete()
        
        # Verify deleted
        # 1. Sources should be cleared
        assert group1.source == None
        assert group2.source == None
        # 2. The source ResourceGroup should NOT still exist
        assert source_group not in project.resource_groups


@skip('not yet automated')
async def test_given_resource_group_not_referenced_by_other_groups_when_delete_then_fully_succeeds() -> None:
    # ...because it is entirely performed within a single database transaction
    pass


# ------------------------------------------------------------------------------
# Test: Alias

# === Test: Alias: Create ===

@skip('not yet automated')
async def test_create_alias_is_atomic_and_durable() -> None:
    # ...because it is entirely performed within a single database transaction
    pass


# === Test: Alias: Delete ===

@skip('not yet automated')
async def test_delete_alias_is_atomic_and_durable() -> None:
    # ...because it is entirely performed within a single database transaction
    pass


# ------------------------------------------------------------------------------
