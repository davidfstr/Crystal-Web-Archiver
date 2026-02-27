"""
Tests for Pack16 revision storage format (major_version == 3).

All tests below implicitly include the condition:
* given_project_in_pack16_format

See doc/tech_designs/pack16.md for more information.
"""
from collections.abc import Iterator
from contextlib import closing, contextmanager, redirect_stderr
from unittest import skip
from crystal.model import Project, Resource, ResourceRevision as RR, NoRevisionBodyError, RevisionBodyMissingError
from crystal.model.project import MigrationType
from crystal.progress.interface import CancelOpenProject
from crystal.progress import interface as progress_interface
from crystal.tests.model.test_project_migrate import (
    progress_reported_at_maximum_resolution,
    project_opened_without_migrating,
    wait_for_project_to_upgrade,
)
from crystal.tests.util.asserts import assertEqual, assertIn, assertRaises
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util.tasks import scheduler_disabled, scheduler_thread_context
from crystal.tests.util.wait import wait_for, wait_for_future, wait_while
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.filesystem import fine_grained_mtimes_available, replace_and_flush
from crystal.util.wx_dialog import mocked_show_modal
from crystal.util.xos import is_windows
from crystal.util.xtyping import not_none
from io import BytesIO, StringIO
import os
import shutil
import tempfile
from unittest.mock import patch
import wx
import zipfile


# === Create ===

@awith_subtests
async def test_given_when_create_multiple_of_16_resource_revisions_then_creates_pack_file_if_at_least_one_revision_body_exists(subtests: SubtestsContext) -> None:
    # Case 1: 15th + 31st revision has a body; verify 2 packs created
    # (Packing triggers when IDs 15 and 31 are created)
    with subtests.test(case='15th_and_31st_have_bodies'):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            project._set_major_version_for_test(3)

            # Create 32 revisions, only IDs 15 and 31 have bodies
            revisions_with_bodies = []
            with scheduler_thread_context():  # safe because no tasks running
                for i in range(1, 33):
                    resource = Resource(project, f'http://example.com/case1/{i}')
                    if i == 15 or i == 31:
                        # Create revision with body
                        revision = RR.create_from_response(
                            resource,
                            metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                            body_stream=BytesIO(b'test body'),
                        )
                        revisions_with_bodies.append(revision)
                    else:
                        # Create error-only revision (no body)
                        RR.create_from_error(
                            resource,
                            Exception('Test error'))

            # Verify pack files exist
            pack_00_path = os.path.join(
                project.path, 'revisions', '000', '000', '000', '000', '00_.zip')
            pack_01_path = os.path.join(
                project.path, 'revisions', '000', '000', '000', '000', '01_.zip')
            assert os.path.exists(pack_00_path)
            assert os.path.exists(pack_01_path)

            # Verify pack contents
            with zipfile.ZipFile(pack_00_path, 'r') as zf:
                assertEqual(['00f'], zf.namelist())
            with zipfile.ZipFile(pack_01_path, 'r') as zf:
                assertEqual(['01f'], zf.namelist())

            # Verify revisions can be read back from pack files
            assertEqual(2, len(revisions_with_bodies))
            for revision in revisions_with_bodies:
                with revision.open() as f:
                    assertEqual(b'test body', f.read())
                assertEqual(len(b'test body'), revision.size())

    # Case 2: 15th + 31st revision has no body, rest have bodies; verify 2 packs
    with subtests.test(case='15th_and_31st_have_no_bodies'):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            project._set_major_version_for_test(3)

            # Create 32 revisions, all except IDs 15 and 31 have bodies
            with scheduler_thread_context():  # safe because no tasks running
                for i in range(1, 33):
                    resource = Resource(project, f'http://example.com/case2/{i}')
                    if i == 15 or i == 31:
                        # Create error-only revision (no body)
                        RR.create_from_error(
                            resource,
                            Exception('Test error'))
                    else:
                        # Create revision with body
                        RR.create_from_response(
                            resource,
                            metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                            body_stream=BytesIO(b'test body'),
                        )

            # Verify pack files exist
            revisions_dir = os.path.join(project.path, 'revisions')
            pack_files = []
            for (root, dirs, files) in os.walk(revisions_dir):
                for cur_file in files:
                    if cur_file.endswith('_.zip'):
                        pack_files.append(os.path.join(root, cur_file))
            assertEqual(2, len(pack_files))

    # Case 3: first 16 revisions have no body, next 16 have body; verify 1 pack (second group)
    with subtests.test(case='first_16_no_body_next_16_have_body'):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            project._set_major_version_for_test(3)

            # Create 32 revisions, first 16 have no body, next 16 have body
            with scheduler_thread_context():  # safe because no tasks running
                for i in range(1, 33):
                    resource = Resource(project, f'http://example.com/case3/{i}')
                    if i <= 16:
                        # Create error-only revision (no body)
                        RR.create_from_error(
                            resource,
                            Exception('Test error'))
                    else:
                        # Create revision with body
                        RR.create_from_response(
                            resource,
                            metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                            body_stream=BytesIO(b'test body'),
                        )

            # Verify only one pack file exists (for second group)
            revisions_dir = os.path.join(project.path, 'revisions')
            pack_files = []
            for (root, dirs, files) in os.walk(revisions_dir):
                for cur_file in files:
                    if cur_file.endswith('_.zip'):
                        pack_files.append(os.path.join(root, cur_file))
            assertEqual(1, len(pack_files))

    # Case 4: first 15 revisions have body, next 17 have no body; verify 1 pack (first group)
    # (Only IDs 1-15 get packed; ID 16 remains as individual file; IDs 17-32 trigger empty pack which is skipped)
    with subtests.test(case='first_15_have_body_rest_no_body'):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            project._set_major_version_for_test(3)

            # Create 32 revisions, first 15 have body, rest have no body
            with scheduler_thread_context():  # safe because no tasks running
                for i in range(1, 33):
                    resource = Resource(project, f'http://example.com/case4/{i}')
                    if i <= 15:
                        # Create revision with body
                        RR.create_from_response(
                            resource,
                            metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                            body_stream=BytesIO(b'test body'),
                        )
                    else:
                        # Create error-only revision (no body)
                        RR.create_from_error(
                            resource,
                            Exception('Test error'))

            # Verify only one pack file exists (for first group)
            revisions_dir = os.path.join(project.path, 'revisions')
            pack_files = []
            for (root, dirs, files) in os.walk(revisions_dir):
                for cur_file in files:
                    if cur_file.endswith('_.zip'):
                        pack_files.append(os.path.join(root, cur_file))
            assertEqual(1, len(pack_files))


async def test_given_project_when_create_non_multiple_of_16_resource_revisions_then_creates_individual_files() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Set project to major version 3 (Pack16 format)
        project._set_major_version_for_test(3)
        assertEqual(3, project.major_version)

        # Create 18 resources with bodies
        revisions = []
        with scheduler_thread_context():  # safe because no tasks running
            for i in range(1, 19):
                resource = Resource(project, f'http://example.com/{i}')
                revision = RR.create_from_response(
                    resource,
                    metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                    body_stream=BytesIO(b'test body'),
                )
                revisions.append(revision)

        # Verify pack file exists for first 16 revisions
        pack_00_path = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '00_.zip')
        assert os.path.exists(pack_00_path)

        # Verify individual files remain for revisions 17-18 (IDs 0x010-0x011)
        revision_010_path = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '010')
        revision_011_path = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '011')
        assert os.path.exists(revision_010_path)
        assert os.path.exists(revision_011_path)

        # Verify no pack file exists for second group
        pack_01_path = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '01_.zip')
        assert not os.path.exists(pack_01_path)

        # Verify all revisions can be read back.
        # First 16 should be read from pack, last 2 from individual files.
        for revision in revisions:
            with revision.open() as f:
                assertEqual(b'test body', f.read())
            assertEqual(len(b'test body'), revision.size())


async def test_when_create_revision_and_packs_revisions_given_all_bodyful_revisions_for_pack_have_bad_blocks_then_does_not_write_pack_file() -> None:
    # ...rather than writing an empty pack file
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        (pack_filepath, loose_filepath_a, revision_a) = \
            _create_almost_complete_pack_with_one_bodyful_revision(project)

        # Precondition: Loose revision A (ID 14) exists, pack does not
        assert os.path.exists(loose_filepath_a), 'Loose revision A should exist'
        assert not os.path.exists(pack_filepath), 'Pack file should not exist yet'

        # Loose file path for revision B (ID 15)
        loose_filepath_b = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '00f')

        # Simulate bad blocks for ALL bodyful revision files during packing.
        # Patch open() so that reading revision 14 or 15's files raises OSError.
        real_open = open  # capture
        bad_block_filepaths = {
            os.path.abspath(loose_filepath_a),
            os.path.abspath(loose_filepath_b),
        }
        def mock_open_func(filepath, *args, **kwargs):
            if isinstance(filepath, str):
                abs_filepath = os.path.abspath(filepath)
                if abs_filepath in bad_block_filepaths:
                    raise OSError(5, 'Input/output error')
            return real_open(filepath, *args, **kwargs)

        # Create bodyful revision B with ID 15. Completes a pack.
        with scheduler_thread_context():  # safe because no tasks running
            with patch('builtins.open', mock_open_func), \
                    redirect_stderr(StringIO()):
                resource_b = Resource(project, 'http://example.com/loose-pack-test/15')
                revision_b = RR.create_from_response(
                    resource_b,
                    metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                    body_stream=BytesIO(_LARGE_BODY_B),
                )

        # Verify pack file 00_.zip NOT created, because it would be empty
        assert not os.path.exists(pack_filepath), \
            'Pack file should not be created when all bodyful revisions have bad blocks'

        # Verify loose files for revisions 14 and 15 still exist
        assert os.path.exists(loose_filepath_a), \
            'Loose revision A (ID 14) should still exist (bad block, not packed)'
        assert os.path.exists(loose_filepath_b), \
            'Loose revision B (ID 15) should still exist (bad block, not packed)'


# === Read ===

@skip('covered by: test_given_when_create_multiple_of_16_resource_revisions_then_creates_pack_file_if_at_least_one_revision_body_exists')
async def test_given_resource_revision_in_pack_file_then_can_read_resource_revision() -> None:
    pass


@skip('covered by: test_given_project_when_create_non_multiple_of_16_resource_revisions_then_creates_individual_files')
async def test_given_resource_revision_in_individual_file_then_can_read_resource_revision() -> None:
    pass


async def test_given_given_pack_file_missing_when_read_resource_revision_then_falls_back_to_hierarchical_file() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        project._set_major_version_for_test(3)

        # Create 16 revisions with bodies (creates pack 00_)
        revisions = []
        with scheduler_thread_context():  # safe because no tasks running
            for i in range(1, 17):
                resource = Resource(project, f'http://example.com/{i}')
                revision = RR.create_from_response(
                    resource,
                    metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                    body_stream=BytesIO(b'test body'),
                )
                revisions.append(revision)

        # Verify pack file exists
        pack_00_path = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '00_.zip')
        assert os.path.exists(pack_00_path)

        # Extract pack file contents to restore individual hierarchical files
        with zipfile.ZipFile(pack_00_path, 'r') as zf:
            zf.extractall(os.path.dirname(pack_00_path))
        os.remove(pack_00_path)

        # Verify open() still works by reading hierarchical files
        for revision in revisions:
            with revision.open() as f:
                assertEqual(b'test body', f.read())
            assertEqual(len(b'test body'), revision.size())


async def test_given_both_pack_and_hierarchical_missing_when_read_resource_revision_then_raises_revision_body_missing_error() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Set project to major version 3 (Pack16 format)
        project._set_major_version_for_test(3)

        # Create a revision with body
        resource = Resource(project, 'http://example.com/test')
        with scheduler_thread_context():  # safe because no tasks running
            revision = RR.create_from_response(
                resource,
                metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                body_stream=BytesIO(b'test body'),
            )

        # Verify revision file exists (as individual file, not in pack yet)
        revision_001_path = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '001')
        assert os.path.exists(revision_001_path)

        # Delete the hierarchical file
        os.remove(revision_001_path)
        assert not os.path.exists(revision_001_path)

        # Verify pack file doesn't exist
        pack_00_path = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '00_.zip')
        assert not os.path.exists(pack_00_path)

        # Verify open() raises RevisionBodyMissingError
        with assertRaises(RevisionBodyMissingError):
            with revision.open() as f:
                f.read()

        # Verify size() also raises RevisionBodyMissingError
        with assertRaises(RevisionBodyMissingError):
            revision.size()


# === Recovery ===

async def test_given_individual_files_exist_for_last_missing_complete_pack_file_when_project_opened_then_pack_file_created_and_individual_files_deleted() -> None:
    """
    Test recovery mechanism: If a complete pack (16 revisions) was never created
    due to crash/disk-full, it should be created when the project is reopened.
    """
    async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
        project_dirpath = project.path
        project._set_major_version_for_test(3)

        # Create 31 revisions with bodies (should create packs 00_ and 01_)
        # Pack 00_ contains IDs 1-15 (0x001-0x00f), created when ID 15 is written
        # Pack 01_ contains IDs 16-31 (0x010-0x01f), created when ID 31 is written
        # NOTE: Stop at 31, not 32, because creating revision 32 would imply
        #       that pack 01_ was successfully and durably written. A crash during
        #       pack creation would occur before revision 32 could be created.
        with scheduler_thread_context():  # safe because no tasks running
            for i in range(1, 32):
                resource = Resource(project, f'http://example.com/{i}')
                RR.create_from_response(
                    resource,
                    metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                    body_stream=BytesIO(b'test body'),
                )

        # Verify both pack files were created
        pack_00_path = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '00_.zip')
        pack_01_path = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '01_.zip')
        assert os.path.exists(pack_00_path)
        assert os.path.exists(pack_01_path)

    # Simulate a crash before the pack was created, by undoing the pack operation
    with zipfile.ZipFile(pack_01_path, 'r') as zf:
        zf.extractall(os.path.dirname(pack_01_path))
    os.remove(pack_01_path)
    for hex_id in ['010', '011', '012', '013', '014', '015', '016', '017',
                   '018', '019', '01a', '01b', '01c', '01d', '01e', '01f']:
        individual_path = os.path.join(
            project_dirpath, 'revisions', '000', '000', '000', '000', hex_id)
        assert os.path.exists(individual_path), f'Expected {hex_id} to exist'

    # Reopen project. Recovery should detect missing pack and recreate it.
    async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
        # Verify pack 01_.zip was recreated
        pack_01_path_reopened = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '01_.zip')
        assert os.path.exists(pack_01_path_reopened), \
            f'Pack file should be recreated on project open. Checked: {pack_01_path_reopened}'

        # Verify individual files 010-01f were deleted
        for hex_id in ['010', '011', '012', '013', '014', '015', '016', '017',
                       '018', '019', '01a', '01b', '01c', '01d', '01e', '01f']:
            individual_path = os.path.join(
                project.path, 'revisions', '000', '000', '000', '000', hex_id)
            assert not os.path.exists(individual_path), f'Expected {hex_id} to be deleted'

        # Verify all revisions can still be read
        for i in range(1, 32):
            resource = not_none(project.get_resource(url=f'http://example.com/{i}'))
            revision = resource.default_revision()
            assert revision is not None
            with revision.open() as f:
                assertEqual(b'test body', f.read())


async def test_given_individual_files_exist_for_last_missing_incomplete_pack_file_when_project_opened_then_pack_file_not_created_and_individual_files_retained() -> None:
    """
    Test recovery mechanism: If the last pack is incomplete (fewer than 16 revisions),
    no pack should be created and individual files should remain.
    """
    async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
        project_dirpath = project.path
        project._set_major_version_for_test(3)

        # Create 18 revisions with bodies (pack 00_, then files 010-011)
        with scheduler_thread_context():  # safe because no tasks running
            for i in range(1, 19):
                resource = Resource(project, f'http://example.com/{i}')
                RR.create_from_response(
                    resource,
                    metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                    body_stream=BytesIO(b'test body'),
                )

        # Verify pack file exists for first 16 revisions
        pack_00_path = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '00_.zip')
        assert os.path.exists(pack_00_path)

        # Verify individual files remain for revisions 17-18 (IDs 0x010-0x011)
        revision_010_path = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '010')
        revision_011_path = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '011')
        assert os.path.exists(revision_010_path)
        assert os.path.exists(revision_011_path)

        # Verify no pack file exists for second group
        pack_01_path = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '01_.zip')
        assert not os.path.exists(pack_01_path)

    # Reopen project. Recovery should NOT create a pack for incomplete group.
    async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
        # Verify pack file still doesn't exist for incomplete group
        assert not os.path.exists(pack_01_path), 'Incomplete pack should not be created'

        # Verify individual files 010-011 remain as individual files
        assert os.path.exists(revision_010_path), 'Individual file 010 should remain'
        assert os.path.exists(revision_011_path), 'Individual file 011 should remain'

        # Verify all revisions can still be read
        for i in range(1, 19):
            resource = not_none(project.get_resource(url=f'http://example.com/{i}'))
            revision = resource.default_revision()
            assert revision is not None
            with revision.open() as f:
                assertEqual(b'test body', f.read())


# === Delete (major_version == 2) ===

# TODO: Move these tests to a more-appropriate location,
#       outside the Pack16 (major_version == 3) tests

async def test_given_resource_revision_with_body_when_deleted_then_revision_no_longer_exists_and_body_file_removed() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        assertEqual(2, project.major_version)

        # Create a resource with a revision
        resource = Resource(project, 'http://example.com/delete-test')
        revision = RR.create_from_response(
            resource,
            metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
            body_stream=BytesIO(b'delete me'),
        )

        # Capture the body file path before deletion
        body_filepath = revision._body_filepath  # capture
        assert os.path.exists(body_filepath)
        assert not_none(resource.default_revision())._id == revision._id

        # Delete the revision
        await wait_for_future(revision.delete())

        # Verify the revision no longer exists
        assert resource.default_revision() is None

        # Verify the body file has been removed
        assert not os.path.exists(body_filepath)


async def test_given_resource_with_revisions_when_deleted_then_resource_and_all_revisions_no_longer_exist() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        assertEqual(2, project.major_version)

        # Create a resource with multiple revisions
        resource = Resource(project, 'http://example.com/multi-delete')
        revision1 = RR.create_from_response(
            resource,
            metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
            body_stream=BytesIO(b'revision 1'),
        )
        revision2 = RR.create_from_response(
            resource,
            metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
            body_stream=BytesIO(b'revision 2'),
        )

        # Capture body file paths before deletion
        body_filepath1 = revision1._body_filepath  # capture
        body_filepath2 = revision2._body_filepath  # capture
        assert os.path.exists(body_filepath1)
        assert os.path.exists(body_filepath2)
        assert len(list(resource.revisions())) == 2

        # Delete the resource (and all its revisions)
        await wait_for_future(resource.delete())

        # Verify the resource no longer exists
        assert project.get_resource(resource.url) is None

        # Verify all body files have been removed
        assert not os.path.exists(body_filepath1)
        assert not os.path.exists(body_filepath2)


# === Delete (major_version == 3) ===

async def test_given_nonlast_resource_revision_in_pack_file_when_deleted_then_pack_file_rewritten_without_it() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        project._set_major_version_for_test(3)

        # Create 15 revisions to trigger pack file creation
        # (Revisions 1-15 go into pack 00_.zip)
        revisions = []
        with scheduler_thread_context():  # safe because no tasks running
            for i in range(1, 16):
                resource = Resource(project, f'http://example.com/pack-delete/{i}')
                revision = RR.create_from_response(
                    resource,
                    metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                    body_stream=BytesIO(f'body {i}'.encode()),
                )
                revisions.append(revision)

        # Verify pack file exists
        pack_path = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '00_.zip')
        assert os.path.exists(pack_path), 'Pack file should exist after 15 revisions'

        # Verify all 15 revisions are in the pack
        with zipfile.ZipFile(pack_path, 'r') as zf:
            initial_entries = set(zf.namelist())
            assert len(initial_entries) == 15, f'Expected 15 entries, got {len(initial_entries)}: {initial_entries}'

        # Delete a middle revision (revision 8, which is ID 8)
        deleted_revision = revisions[7]
        deleted_entry_name = f'{8:03x}'
        assert deleted_entry_name == '008'
        await wait_for_future(deleted_revision.delete())

        # Verify pack file still exists
        assert os.path.exists(pack_path), 'Pack file should still exist after deleting one entry'

        # Verify pack now has 14 entries (one removed)
        with zipfile.ZipFile(pack_path, 'r') as zf:
            remaining_entries = set(zf.namelist())
            assert len(remaining_entries) == 14
            assert deleted_entry_name not in remaining_entries

        # Verify other revisions in the pack are still readable
        for (i, revision) in enumerate(revisions, start=1):
            if i != 8:  # Skip the deleted revision
                with revision.open() as f:
                    content = f.read()
                    assert content == f'body {i}'.encode(), f'Revision {i} content should be readable'


async def test_given_last_resource_revision_in_pack_file_when_deleted_then_pack_file_deleted() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        project._set_major_version_for_test(3)

        # Create 15 revisions to trigger pack file creation
        # (Revisions 1-15 go into pack 00_.zip)
        revisions = []
        with scheduler_thread_context():  # safe because no tasks running
            for i in range(1, 16):
                resource = Resource(project, f'http://example.com/pack-delete-last/{i}')
                revision = RR.create_from_response(
                    resource,
                    metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                    body_stream=BytesIO(f'body {i}'.encode()),
                )
                revisions.append(revision)

        # Verify pack file exists
        pack_path = os.path.join(
            project.path, 'revisions', '000', '000', '000', '000', '00_.zip')
        assert os.path.exists(pack_path), 'Pack file should exist after 15 revisions'

        # Delete all revisions except the last one
        for i in range(0, 14):
            await wait_for_future(revisions[i].delete())

        # Pack should still exist with 1 entry
        assert os.path.exists(pack_path)
        with zipfile.ZipFile(pack_path, 'r') as zf:
            entries = set(zf.namelist())
            assert len(entries) == 1

        # Delete the last revision
        await wait_for_future(revisions[14].delete())

        # Pack file should now be deleted (empty pack is not stored)
        assert not os.path.exists(pack_path), 'Pack file should be deleted when it becomes empty'


# === Delete Backward Compatibility ===

async def test_when_resource_revision_deleted_but_result_of_returned_future_ignored_then_prints_warning_to_stderr() -> None:
    """
    Test that code typical of Crystal <=2.2.0 which called ResourceRevision.delete()
    but ignored its result - because it had no result at the time - will now print
    a warning now that delete() returns a Future that expects its result to be read from.
    """
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        project._set_major_version_for_test(3)
        
        # Create a resource with a revision
        resource = Resource(project, 'http://example.com/test')
        with scheduler_thread_context():  # safe because no tasks running
            revision = RR.create_from_response(
                resource,
                metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                body_stream=BytesIO(b'test body'),
            )
        
        # NOTE: Do NOT call the real warn_if_result_not_read() to avoid printing
        #       warnings to stderr after this test finishes 
        with patch('crystal.model.resource_revision.warn_if_result_not_read') as mock_warn, \
                patch.object(project, 'add_task', wraps=project.add_task) as mock_add_task:
            # Delete revision WITHOUT saving the returned Future (Crystal <=2.2.0 style)
            revision.delete()
        
        # Verify that warn_if_result_not_read() was called on delete_task.future,
        # so that "WARNING: Future's result was never read:" will eventually be
        # printed when task completes and its future finalizes without its result
        # having been read
        (delete_task,) = mock_add_task.call_args.args
        (future_warn_called_on, _) = mock_warn.call_args.args
        assert future_warn_called_on is delete_task.future


async def test_when_resource_deleted_but_result_of_returned_future_ignored_then_prints_warning_to_stderr() -> None:
    """
    Test that code typical of Crystal <=2.2.0 which called Resource.delete()
    but ignored its result - because it had no result at the time - will now print
    a warning now that delete() returns a Future that expects its result to be read from.
    """
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        project._set_major_version_for_test(3)
        
        # Create a resource with a revision
        resource = Resource(project, 'http://example.com/test')
        with scheduler_thread_context():  # safe because no tasks running
            RR.create_from_response(
                resource,
                metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                body_stream=BytesIO(b'test body'),
            )
        
        # NOTE: Do NOT call the real warn_if_result_not_read() to avoid printing
        #       warnings to stderr after this test finishes 
        with patch('crystal.model.resource.warn_if_result_not_read') as mock_warn, \
                patch.object(project, 'add_task', wraps=project.add_task) as mock_add_task:
            # Delete resource WITHOUT saving the returned Future (Crystal <=2.2.0 style)
            resource.delete()
        
        # Verify that warn_if_result_not_read() was called on delete_task.future,
        # so that "WARNING: Future's result was never read:" will eventually be
        # printed when task completes and its future finalizes without its result
        # having been read
        (delete_task,) = mock_add_task.call_args.args
        (future_warn_called_on, _) = mock_warn.call_args.args
        assert future_warn_called_on is delete_task.future


async def test_given_older_flat_or_hierarchical_project_when_resource_revision_deleted_then_performs_delete_synchronously() -> None:
    # NOTE: Prevent any improperly-created DeleteResourceRevisionTask from running and completing
    with scheduler_disabled():
        async with (await OpenOrCreateDialog.wait_for()).create() as (_, project):
            assertEqual(2, project.major_version)

            # Create a resource with a revision
            resource = Resource(project, 'http://example.com/sync-delete-test')
            revision = RR.create_from_response(
                resource,
                metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                body_stream=BytesIO(b'delete me'),
            )

            # Verify _delete_now() is called synchronously (before delete() returns)
            with patch.object(RR, '_delete_now', wraps=revision._delete_now) as spy_delete_now:
                future = revision.delete()
            # _delete_now() must have been called synchronously
            assertEqual(1, spy_delete_now.call_count)
            # 1. Ensure no error
            # 2. Avoid the "result was never read" warning
            await wait_for_future(future)

            # Try deleting the same revision again, which should raise an exception
            second_future = revision.delete()
            # Verify that delete() returned a Future with the exception,
            # rather than raising the exception directly
            with assertRaises(AssertionError):
                await wait_for_future(second_future)


async def test_given_older_flat_or_hierarchical_project_when_resource_deleted_then_performs_delete_synchronously() -> None:
    # NOTE: Prevent any improperly-created DeleteResourceTask from running and completing
    with scheduler_disabled():
        async with (await OpenOrCreateDialog.wait_for()).create() as (_, project):
            assertEqual(2, project.major_version)

            # Create a resource with a revision
            resource = Resource(project, 'http://example.com/sync-delete-resource-test')
            RR.create_from_response(
                resource,
                metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                body_stream=BytesIO(b'test body'),
            )

            # Verify _delete_now() is called synchronously (before delete() returns)
            with patch.object(Resource, '_delete_now', wraps=resource._delete_now) as spy_delete_now:
                future = resource.delete()
            # _delete_now() must have been called synchronously
            assertEqual(1, spy_delete_now.call_count)
            # 1. Ensure no error
            # 2. Avoid the "result was never read" warning
            await wait_for_future(future)

            # Try deleting the same resource again, which should raise an exception
            second_future = resource.delete()
            # Verify that delete() returned a Future with the exception,
            # rather than raising the exception directly
            with assertRaises(KeyError):
                await wait_for_future(second_future)


# === Migrate (major_version 2 -> 3) ===

async def test_given_project_with_major_version_2_when_migrate_to_pack16_then_creates_all_packs_and_upgrades_to_major_version_3() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
        project_dirpath = project.path
        assertEqual(2, project.major_version)

        # Create 50 revisions with bodies (v2 format: written as individual hierarchical files)
        # Expected packs after migration:
        #   00_.zip: IDs 0x001-0x00f (1-15)
        #   01_.zip: IDs 0x010-0x01f (16-31)
        #   02_.zip: IDs 0x020-0x02f (32-47)
        # Remaining individual files: IDs 0x030-0x032 (48-50)
        for i in range(1, 51):
            resource = Resource(project, f'http://example.com/migrate/{i}')
            RR.create_from_response(
                resource,
                metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                body_stream=BytesIO(f'body {i}'.encode()),
            )

        # Verify that revisions were written as individual hierarchical files (v2 format)
        revision_001_path = os.path.join(
            project_dirpath, 'revisions', '000', '000', '000', '000', '001')
        assert os.path.exists(revision_001_path), \
            'v2 project should have individual revision files before migration'

        # Initiate migration
        project._queue_migration_after_reopen(MigrationType.HIERARCHICAL_TO_PACK16)

    # Reopen project. Migration runs automatically.
    async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
        # Verify major version upgraded and migration marker removed
        assertEqual(3, project.major_version)
        assert project._get_property('major_version_old', None) is None, \
            'major_version_old should be removed after migration completes'

        # Verify pack files were created
        revisions_dir = os.path.join(project_dirpath, 'revisions', '000', '000', '000', '000')
        for pack_name in ['00_.zip', '01_.zip', '02_.zip']:
            pack_path = os.path.join(revisions_dir, pack_name)
            assert os.path.exists(pack_path), f'Pack file {pack_name} should exist after migration'

        # Verify pack contents (each should have 15 entries for IDs 1-15, 16-31, 32-47)
        with zipfile.ZipFile(os.path.join(revisions_dir, '00_.zip'), 'r') as zf:
            assertEqual(15, len(zf.namelist()))
        with zipfile.ZipFile(os.path.join(revisions_dir, '01_.zip'), 'r') as zf:
            assertEqual(16, len(zf.namelist()))
        with zipfile.ZipFile(os.path.join(revisions_dir, '02_.zip'), 'r') as zf:
            assertEqual(16, len(zf.namelist()))

        # Verify individual files for first pack group are gone
        assert not os.path.exists(revision_001_path), \
            'Individual files should be deleted after migration creates pack'

        # Verify incomplete last group remains as individual files
        for hex_id in ['030', '031', '032']:
            individual_path = os.path.join(revisions_dir, hex_id)
            assert os.path.exists(individual_path), \
                f'Individual file {hex_id} should remain (incomplete last group)'

        # Verify all revisions are still readable
        for i in range(1, 51):
            resource = not_none(project.get_resource(url=f'http://example.com/migrate/{i}'))
            revision = resource.default_revision()
            assert revision is not None
            with revision.open() as f:
                assertEqual(f'body {i}'.encode(), f.read())


async def test_given_empty_project_when_migrate_to_pack16_then_migration_completes_immediately() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
        project_dirpath = project.path
        assertEqual(2, project.major_version)

        # (No revisions. Project is empty.)

        # Initiate migration
        project._queue_migration_after_reopen(MigrationType.HIERARCHICAL_TO_PACK16)

    # Reopen project. Migration should complete immediately because no revisions to process.
    async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
        # Verify major version upgraded and migration marker removed
        assertEqual(3, project.major_version)
        assert project._get_property('major_version_old', None) is None, \
            'major_version_old should be removed after migration completes'

        # Verify no pack files were created. No revisions to pack.
        revisions_dir = os.path.join(project_dirpath, 'revisions')
        pack_count = sum(
            1
            for (root, dirs, files) in os.walk(revisions_dir)
            for f in files
            if f.endswith('.zip')
        )
        assertEqual(0, pack_count)


async def test_given_project_with_only_error_revisions_when_migrate_to_pack16_then_creates_no_pack_files() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
        project_dirpath = project.path
        assertEqual(2, project.major_version)

        # Create 32 error-only revisions (no body files)
        for i in range(1, 33):
            resource = Resource(project, f'http://example.com/error-migrate/{i}')
            RR.create_from_error(resource, Exception(f'Error {i}'))
        
        # Initiate migration
        project._queue_migration_after_reopen(MigrationType.HIERARCHICAL_TO_PACK16)

    # Reopen project. Migration runs but finds no body files to pack.
    async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
        # Verify major version upgraded and migration marker removed
        assertEqual(3, project.major_version)
        assert project._get_property('major_version_old', None) is None, \
            'major_version_old should be removed after migration completes'

        # Verify no pack files were created. All revisions were error-only, no body files.
        revisions_dir = os.path.join(project_dirpath, 'revisions')
        pack_count = sum(
            1
            for (root, dirs, files) in os.walk(revisions_dir)
            for f in files
            if f.endswith('.zip')
        )
        assertEqual(0, pack_count)


# === Migrate Robustness (major_version 2 -> 3) ===

async def test_given_migration_in_progress_when_cancel_and_reopen_project_then_migration_resumes_and_completes() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
        project_dirpath = project.path
        assertEqual(2, project.major_version)

        # Create 50 revisions with bodies (v2 format)
        for i in range(1, 51):
            resource = Resource(project, f'http://example.com/cancel-migrate/{i}')
            RR.create_from_response(
                resource,
                metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                body_stream=BytesIO(f'body {i}'.encode()),
            )

        # Initiate migration
        project._queue_migration_after_reopen(MigrationType.HIERARCHICAL_TO_PACK16)

    # Open project, but cancel the migration after the first pack is processed
    if True:
        ocd = await OpenOrCreateDialog.wait_for()

        progress_listener = progress_interface._active_progress_listener
        assert progress_listener is not None

        # Prepare to: Cancel migration in the middle
        did_cancel_migration_in_middle = False
        def upgrading_revision(index: int, revisions_per_second: float) -> None:
            nonlocal did_cancel_migration_in_middle
            if index >= 16:
                # Cancel after processing the first pack
                did_cancel_migration_in_middle = True
                raise CancelOpenProject()

        with patch.object(progress_listener, 'upgrading_revision', upgrading_revision), \
                progress_reported_at_maximum_resolution():
            await ocd.start_opening(project_dirpath, next_window_name='cr-open-or-create-project')

            # HACK: Wait minimum duration to allow open to finish
            await bg_sleep(0.5)

            # Wait for migration to start, get cancelled, and return to initial dialog
            ocd = await OpenOrCreateDialog.wait_for()
            assert did_cancel_migration_in_middle

    # Verify partial migration state:
    # At least the first pack should exist (migration got past index >= 16)
    revisions_dir = os.path.join(project_dirpath, 'revisions', '000', '000', '000', '000')
    pack_00_path = os.path.join(revisions_dir, '00_.zip')
    assert os.path.exists(pack_00_path), \
        'First pack should exist after partial migration'

    # Resume migration by reopening — allow to finish this time
    async with (await OpenOrCreateDialog.wait_for()).open(
            project_dirpath, wait_func=wait_for_project_to_upgrade) as (mw, project):
        # Verify migration completed
        assertEqual(3, project.major_version)
        assert project._get_property('major_version_old', None) is None, \
            'major_version_old should be removed after migration completes'

        # Verify all expected packs were created
        for pack_name in ['00_.zip', '01_.zip', '02_.zip']:
            pack_path = os.path.join(revisions_dir, pack_name)
            assert os.path.exists(pack_path), \
                f'Pack file {pack_name} should exist after migration completes'

        # Verify all revisions are still readable
        for i in range(1, 51):
            resource = not_none(project.get_resource(url=f'http://example.com/cancel-migrate/{i}'))
            revision = resource.default_revision()
            assert revision is not None
            with revision.open() as f:
                assertEqual(f'body {i}'.encode(), f.read())


@awith_subtests
async def test_given_corrupt_revision_file_when_migrate_to_pack16_then_skips_file_and_warns(subtests: SubtestsContext) -> None:
    for io_error_location in ['open', 'read']:
        with subtests.test(io_error_location=io_error_location):
            async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
                project_dirpath = project.path
                assertEqual(2, project.major_version)

                # Create 16 revisions with bodies (enough for one complete pack)
                for i in range(1, 17):
                    resource = Resource(project, f'http://example.com/corrupt-migrate/{i}')
                    RR.create_from_response(
                        resource,
                        metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                        body_stream=BytesIO(f'body {i}'.encode()),
                    )

                # Identify the revision file for ID 8 (to simulate corruption)
                corrupt_revision_filepath = os.path.join(
                    project_dirpath, 'revisions', '000', '000', '000', '000', '008')
                assert os.path.exists(corrupt_revision_filepath)

                # Initiate migration
                project._queue_migration_after_reopen(MigrationType.HIERARCHICAL_TO_PACK16)

            # Mock builtins.open to simulate I/O error at the specified location
            real_open = open  # capture
            def mock_open_func(filepath, *args, **kwargs):
                if io_error_location == 'open':
                    if os.path.abspath(filepath) == os.path.abspath(corrupt_revision_filepath):
                        raise OSError(5, 'Input/output error')
                    return real_open(filepath, *args, **kwargs)
                elif io_error_location == 'read':
                    result = real_open(filepath, *args, **kwargs)
                    if os.path.abspath(filepath) == os.path.abspath(corrupt_revision_filepath):
                        return _ErrorOnReadFile(result)
                    return result
                else:
                    raise AssertionError()

            # Reopen project with the mock. Migration runs automatically.
            with patch('builtins.open', mock_open_func), \
                    redirect_stderr(StringIO()) as captured_stderr:
                async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                    # Verify migration completed
                    assertEqual(3, project.major_version)
                    assert project._get_property('major_version_old', None) is None, \
                        'major_version_old should be removed after migration completes'

                    # Verify pack file was created but WITHOUT the corrupt entry
                    pack_00_path = os.path.join(
                        project_dirpath, 'revisions', '000', '000', '000', '000', '00_.zip')
                    assert os.path.exists(pack_00_path), 'Pack file should exist'
                    with zipfile.ZipFile(pack_00_path, 'r') as zf:
                        entries = set(zf.namelist())
                        assert '008' not in entries, \
                            'Corrupt entry should be excluded from pack'
                        # Other entries should be present (IDs 1-7, 9-15)
                        assertEqual(14, len(entries))

                    # Verify corrupt file is still on disk (not deleted)
                    assert os.path.exists(corrupt_revision_filepath), \
                        'Corrupt file should be left in place'

                    # Verify non-corrupt revisions in the pack are readable
                    for i in range(1, 16):
                        if i == 8:
                            continue  # skip the corrupt one
                        resource = not_none(project.get_resource(url=f'http://example.com/corrupt-migrate/{i}'))
                        revision = resource.default_revision()
                        assert revision is not None
                        with revision.open() as f:
                            assertEqual(f'body {i}'.encode(), f.read())

            # Verify warning was printed to stderr about the corrupt file
            stderr_output = captured_stderr.getvalue()
            assertIn('WARNING: Could not read revision file', stderr_output)
            assertIn(corrupt_revision_filepath, stderr_output)


@awith_subtests
async def test_given_cannot_write_pack_file_when_migrate_to_pack16_then_skips_file_and_warns(subtests: SubtestsContext) -> None:
    for io_error_location in ['open', 'write']:
        with subtests.test(io_error_location=io_error_location):
            async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
                project_dirpath = project.path
                assertEqual(2, project.major_version)

                # Create 32 revisions (two complete packs worth: IDs 1-15 and 16-31,
                # plus individual file for ID 32)
                for i in range(1, 33):
                    resource = Resource(project, f'http://example.com/write-fail-migrate/{i}')
                    RR.create_from_response(
                        resource,
                        metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                        body_stream=BytesIO(f'body {i}'.encode()),
                    )

                # Initiate migration
                project._queue_migration_after_reopen(MigrationType.HIERARCHICAL_TO_PACK16)

            revisions_dir = os.path.join(project_dirpath, 'revisions', '000', '000', '000', '000')
            pack_00_path = os.path.join(revisions_dir, '00_.zip')
            pack_01_path = os.path.join(revisions_dir, '01_.zip')

            if io_error_location == 'open':
                # Mock tempfile.NamedTemporaryFile to raise OSError for the first pack
                real_named_temp_file = tempfile.NamedTemporaryFile
                open_fail_count = 0
                def mock_named_temp_file(*args, **kwargs):
                    nonlocal open_fail_count
                    open_fail_count += 1
                    if open_fail_count == 1:
                        raise OSError(28, 'No space left on device')
                    return real_named_temp_file(*args, **kwargs)
                mock_cm = patch('tempfile.NamedTemporaryFile', mock_named_temp_file)
            elif io_error_location == 'write':
                # Mock ZipFile.open to wrap the first write-mode entry in _ErrorOnWriteFile,
                # simulating a write failure when creating the first pack
                real_zf_open = zipfile.ZipFile.open
                write_fail_count = 0
                def mock_zf_open(self, *args, **kwargs):
                    nonlocal write_fail_count
                    result = real_zf_open(self, *args, **kwargs)
                    mode = args[1] if len(args) > 1 else kwargs.get('mode', 'r')
                    if mode == 'w':
                        write_fail_count += 1
                        if write_fail_count == 1:
                            return _ErrorOnWriteFile(result)
                    return result
                mock_cm = patch.object(zipfile.ZipFile, 'open', mock_zf_open)
            else:
                raise AssertionError()

            # Reopen project with the mock. Migration runs automatically.
            with mock_cm, redirect_stderr(StringIO()) as captured_stderr:
                async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                    # Verify migration completed (even though first pack write failed)
                    assertEqual(3, project.major_version)
                    assert project._get_property('major_version_old', None) is None, \
                        'major_version_old should be removed after migration completes'

                    # Verify second pack was created successfully
                    assert os.path.exists(pack_01_path), \
                        'Second pack file should exist after migration'

                    # Verify first pack was NOT created (write failed)
                    assert not os.path.exists(pack_00_path), \
                        'First pack file should not exist (write failed)'

                    # Verify individual files for first pack remain on disk
                    # (not deleted because packing failed)
                    for rid in range(1, 16):  # IDs 1-15 = hex 001-00f
                        body_filepath = os.path.join(revisions_dir, f'{rid:03x}')
                        assert os.path.exists(body_filepath), \
                            f'Individual file {rid:03x} should remain (packing failed)'

                    # Verify all revisions are still readable
                    # (first pack's revisions fall back to individual files; second pack reads from zip)
                    for i in range(1, 33):
                        resource = not_none(project.get_resource(url=f'http://example.com/write-fail-migrate/{i}'))
                        revision = resource.default_revision()
                        assert revision is not None
                        with revision.open() as f:
                            assertEqual(f'body {i}'.encode(), f.read())

            # Verify warning was printed to stderr about the failed pack write
            stderr_output = captured_stderr.getvalue()
            assertIn('WARNING: Could not write pack file', stderr_output)
            assertIn(pack_00_path, stderr_output)


async def test_given_bad_blocks_observed_in_some_bodyful_revisions_for_a_pack_when_cancel_and_restart_migration_then_does_not_attempt_to_reread_bad_block_revisions() -> None:
    # ...because revision ranges corresponding to created pack files are skipped when restarting a migration
    
    # Create project fixture. Queue v2->v3 migration to start.
    async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
        project_dirpath = project.path
        assertEqual(2, project.major_version)

        # Create revisions in v2 format:
        # - IDs 1-13: bodyless (error revisions)
        # - IDs 14-15: bodyful
        # - IDs 16-29: bodyless (error revisions)
        # - IDs 30-32: bodyful
        # - ID 33: bodyful (max ID; exists so that
        #     _repair_incomplete_rollback_of_resource_revision_create opens
        #     this revision instead of one we're tracking)
        # 
        # After migration these map to:
        # - Pack 00_ (IDs 1-15): 2 bodyful entries (14, 15)
        # - Pack 01_ (IDs 16-31): 2 bodyful entries (30, 31)
        # - IDs 32-33: individual files (incomplete group)
        for i in range(1, 34):
            resource = Resource(project, f'http://example.com/bad-block-migrate/{i}')
            if i in (14, 15, 30, 31, 32, 33):
                RR.create_from_response(
                    resource,
                    metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                    body_stream=BytesIO(f'body {i}'.encode()),
                )
            else:
                RR.create_from_error(resource, Exception(f'Error {i}'))

        revisions_dir = os.path.join(project_dirpath, 'revisions', '000', '000', '000', '000')

        # Identify bodyful revision file paths (v2 hierarchical format)
        bodyful_filepaths = {}
        for rid in (14, 15, 30, 31, 32, 33):
            bodyful_filepaths[rid] = os.path.join(revisions_dir, f'{rid:03x}')
            assert os.path.exists(bodyful_filepaths[rid])

        # Initiate migration
        project._queue_migration_after_reopen(MigrationType.HIERARCHICAL_TO_PACK16)

    # First migration attempt. Cancel after first pack.
    if True:
        ocd = await OpenOrCreateDialog.wait_for()

        progress_listener = progress_interface._active_progress_listener
        assert progress_listener is not None

        # Prepare to:
        # 1. Simulate bad blocks for bodyful revision 15 (not 14)
        # 2. Cancel migration at revision 16
        did_cancel_migration_in_middle = False
        def upgrading_revision(index: int, revisions_per_second: float) -> None:
            nonlocal did_cancel_migration_in_middle
            if index >= 16:
                did_cancel_migration_in_middle = True
                raise CancelOpenProject()

        # Track which revision body files are opened during migration
        opened_revision_ids = set()  # type: set[int]
        real_open = open  # capture
        bad_block_filepath = bodyful_filepaths[15]
        def mock_open_func(filepath, *args, **kwargs):
            if isinstance(filepath, str):
                # Track opens of revision body files
                abs_filepath = os.path.abspath(filepath)
                for (rid, rid_path) in bodyful_filepaths.items():
                    if abs_filepath == os.path.abspath(rid_path):
                        opened_revision_ids.add(rid)
                        break
                
                # Simulate bad block for revision 15
                if abs_filepath == os.path.abspath(bad_block_filepath):
                    raise OSError(5, 'Input/output error')
            return real_open(filepath, *args, **kwargs)

        with patch.object(progress_listener, 'upgrading_revision', upgrading_revision), \
                progress_reported_at_maximum_resolution(), \
                patch('builtins.open', mock_open_func), \
                redirect_stderr(StringIO()):
            await ocd.start_opening(project_dirpath, next_window_name='cr-open-or-create-project')

            # HACK: Wait minimum duration to allow open to finish
            await bg_sleep(0.5)

            # Wait for migration to start, get cancelled, and return to initial dialog
            ocd = await OpenOrCreateDialog.wait_for()
            assert did_cancel_migration_in_middle

    # Verify partial migration state after first attempt
    if True:
        # Only pack 00_.zip should be created; not 01_.zip
        pack_00_path = os.path.join(revisions_dir, '00_.zip')
        pack_01_path = os.path.join(revisions_dir, '01_.zip')
        assert os.path.exists(pack_00_path), \
            'First pack should exist after partial migration'
        assert not os.path.exists(pack_01_path), \
            'Second pack should not exist (migration cancelled before processing it)'

        # Verify loose files: {15, 30, 31, 32, 33} should exist
        # (15 was left because of bad block; 30-33 not yet migrated)
        assert os.path.exists(bodyful_filepaths[15]), \
            'Revision 15 should remain as loose file (bad block)'
        for rid in (30, 31, 32, 33):
            assert os.path.exists(bodyful_filepaths[rid]), \
                f'Revision {rid} should remain as loose file (not yet migrated)'
        # Revision 14 should have been packed and deleted
        assert not os.path.exists(bodyful_filepaths[14]), \
            'Revision 14 should have been packed into 00_.zip and deleted'

        # Verify reads attempted for only bodyful revisions {14, 15}
        # NOTE: Revision 14 may be opened twice because create_pack_file does a
        #       second pass to rewrite the zip with only good entries after encountering
        #       bad blocks. Using a set here because we care about *which* revisions
        #       were read, not the exact open count.
        assertEqual({14, 15}, opened_revision_ids)

    # Second migration attempt. Resume and complete.
    if True:
        # Track which revision body files are opened during migration
        opened_revision_ids_2 = set()  # type: set[int]
        real_open_2 = open  # capture
        def spy_open_func(filepath, *args, **kwargs):
            if isinstance(filepath, str):
                # Track opens of revision body files
                abs_filepath = os.path.abspath(filepath)
                for (rid, rid_path) in bodyful_filepaths.items():
                    # Exclude max-ID revision 33 from tracking. It may be opened by
                    # _repair_incomplete_rollback_of_resource_revision_create during Project.__init__
                    if rid == 33:
                        continue
                    if abs_filepath == os.path.abspath(rid_path):
                        opened_revision_ids_2.add(rid)
                        break
            return real_open_2(filepath, *args, **kwargs)

        with patch('builtins.open', spy_open_func):
            async with (await OpenOrCreateDialog.wait_for()).open(
                    project_dirpath, wait_func=wait_for_project_to_upgrade) as (mw, project):
                # Verify migration completed
                assertEqual(3, project.major_version)
                assert project._get_property('major_version_old', None) is None, \
                    'major_version_old should be removed after migration completes'
    
    # Verify full migration state after second attempt
    if True:
        # Verify pack files 00_.zip and 01_.zip exist; not 02_.zip
        assert os.path.exists(pack_00_path), \
            'First pack should still exist'
        assert os.path.exists(pack_01_path), \
            'Second pack should exist after resumed migration'
        pack_02_path = os.path.join(revisions_dir, '02_.zip')
        assert not os.path.exists(pack_02_path), \
            'Third pack should not exist (incomplete group)'

        # Verify only loose files {15, 32, 33} remain
        assert os.path.exists(bodyful_filepaths[15]), \
            'Revision 15 should remain as loose file (bad block, never successfully read)'
        for rid in (32, 33):
            assert os.path.exists(bodyful_filepaths[rid]), \
                f'Revision {rid} should remain as loose file (incomplete group)'
        assert not os.path.exists(bodyful_filepaths[30]), \
            'Revision 30 should have been packed into 01_.zip and deleted'
        assert not os.path.exists(bodyful_filepaths[31]), \
            'Revision 31 should have been packed into 01_.zip and deleted'

        # Verify reads attempted for bodyful revisions {30, 31} only
        # (32 is not read because it's in an incomplete group that stays as individual files)
        # Notably, read NOT attempted for 15 (bad block observed earlier, pack 00_ already exists)
        assertEqual({30, 31}, opened_revision_ids_2)


async def test_given_bad_blocks_observed_in_all_bodyful_revisions_for_a_pack_when_cancel_and_restart_migration_then_does_not_attempt_to_reread_bad_block_revisions() -> None:
    # ...because empty marker zip file retained for pack

    # Create project fixture. Queue v2->v3 migration to start.
    # Same fixture as preceding test.
    async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
        project_dirpath = project.path
        assertEqual(2, project.major_version)

        # Create revisions in v2 format:
        # - IDs 1-13: bodyless (error revisions)
        # - IDs 14-15: bodyful
        # - IDs 16-29: bodyless (error revisions)
        # - IDs 30-32: bodyful
        # - ID 33: bodyful (max ID; exists so that
        #     _repair_incomplete_rollback_of_resource_revision_create opens
        #     this revision instead of one we're tracking)
        #
        # After migration these map to:
        # - Pack 00_ (IDs 1-15): 2 bodyful entries (14, 15)
        # - Pack 01_ (IDs 16-31): 2 bodyful entries (30, 31)
        # - IDs 32-33: individual files (incomplete group)
        for i in range(1, 34):
            resource = Resource(project, f'http://example.com/all-bad-block-migrate/{i}')
            if i in (14, 15, 30, 31, 32, 33):
                RR.create_from_response(
                    resource,
                    metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                    body_stream=BytesIO(f'body {i}'.encode()),
                )
            else:
                RR.create_from_error(resource, Exception(f'Error {i}'))

        revisions_dir = os.path.join(project_dirpath, 'revisions', '000', '000', '000', '000')

        # Identify bodyful revision file paths (v2 hierarchical format)
        bodyful_filepaths = {}
        for rid in (14, 15, 30, 31, 32, 33):
            bodyful_filepaths[rid] = os.path.join(revisions_dir, f'{rid:03x}')
            assert os.path.exists(bodyful_filepaths[rid])

        # Initiate migration
        project._queue_migration_after_reopen(MigrationType.HIERARCHICAL_TO_PACK16)

    # First migration attempt. Cancel after first pack.
    if True:
        ocd = await OpenOrCreateDialog.wait_for()

        progress_listener = progress_interface._active_progress_listener
        assert progress_listener is not None

        # Prepare to:
        # 1. Simulate bad blocks for bodyful revisions 14 AND 15
        # 2. Cancel migration at revision 16
        did_cancel_migration_in_middle = False
        def upgrading_revision(index: int, revisions_per_second: float) -> None:
            nonlocal did_cancel_migration_in_middle
            if index >= 16:
                did_cancel_migration_in_middle = True
                raise CancelOpenProject()

        # Track which revision body files are opened during migration
        opened_revision_ids = set()  # type: set[int]
        real_open = open  # capture
        bad_block_filepaths = {bodyful_filepaths[14], bodyful_filepaths[15]}
        def mock_open_func(filepath, *args, **kwargs):
            if isinstance(filepath, str):
                # Track opens of revision body files
                abs_filepath = os.path.abspath(filepath)
                for (rid, rid_path) in bodyful_filepaths.items():
                    if abs_filepath == os.path.abspath(rid_path):
                        opened_revision_ids.add(rid)
                        break

                # Simulate bad blocks for revisions 14 and 15
                if any(abs_filepath == os.path.abspath(p) for p in bad_block_filepaths):
                    raise OSError(5, 'Input/output error')
            return real_open(filepath, *args, **kwargs)

        with patch.object(progress_listener, 'upgrading_revision', upgrading_revision), \
                progress_reported_at_maximum_resolution(), \
                patch('builtins.open', mock_open_func), \
                redirect_stderr(StringIO()):
            await ocd.start_opening(project_dirpath, next_window_name='cr-open-or-create-project')

            # HACK: Wait minimum duration to allow open to finish
            await bg_sleep(0.5)

            # Wait for migration to start, get cancelled, and return to initial dialog
            ocd = await OpenOrCreateDialog.wait_for()
            assert did_cancel_migration_in_middle

    # Verify partial migration state after first attempt
    if True:
        # Only pack 00_.zip should be created; not 01_.zip
        # Notably, pack file 00_.zip IS created even though it is empty,
        # to mark that revisions 1-15 were (attempted to be) migrated
        pack_00_path = os.path.join(revisions_dir, '00_.zip')
        pack_01_path = os.path.join(revisions_dir, '01_.zip')
        assert os.path.exists(pack_00_path), \
            'First pack should exist after partial migration (empty marker)'
        assert not os.path.exists(pack_01_path), \
            'Second pack should not exist (migration cancelled before processing it)'

        # Verify the empty marker pack has no entries
        with zipfile.ZipFile(pack_00_path, 'r') as zf:
            assertEqual([], zf.namelist())

        # Verify loose files: {14, 15, 30, 31, 32, 33} should exist
        # (14-15 were left because of bad blocks; 30-33 not yet migrated)
        for rid in (14, 15, 30, 31, 32, 33):
            assert os.path.exists(bodyful_filepaths[rid]), \
                f'Revision {rid} should remain as loose file'

        # Verify reads attempted for only bodyful revisions {14, 15}
        assertEqual({14, 15}, opened_revision_ids)

    # Second migration attempt. Resume and complete.
    if True:
        # Track which revision body files are opened during migration
        opened_revision_ids_2 = set()  # type: set[int]
        real_open_2 = open  # capture
        def spy_open_func(filepath, *args, **kwargs):
            if isinstance(filepath, str):
                # Track opens of revision body files
                abs_filepath = os.path.abspath(filepath)
                for (rid, rid_path) in bodyful_filepaths.items():
                    # Exclude max-ID revision 33 from tracking. It may be opened by
                    # _repair_incomplete_rollback_of_resource_revision_create during Project.__init__
                    if rid == 33:
                        continue
                    if abs_filepath == os.path.abspath(rid_path):
                        opened_revision_ids_2.add(rid)
                        break
            return real_open_2(filepath, *args, **kwargs)

        with patch('builtins.open', spy_open_func):
            async with (await OpenOrCreateDialog.wait_for()).open(
                    project_dirpath, wait_func=wait_for_project_to_upgrade) as (mw, project):
                # Verify migration completed
                assertEqual(3, project.major_version)
                assert project._get_property('major_version_old', None) is None, \
                    'major_version_old should be removed after migration completes'

    # Verify full migration state after second attempt
    if True:
        # Verify pack files 00_.zip and 01_.zip exist; not 02_.zip
        assert os.path.exists(pack_00_path), \
            'First pack should still exist (empty marker)'
        assert os.path.exists(pack_01_path), \
            'Second pack should exist after resumed migration'
        pack_02_path = os.path.join(revisions_dir, '02_.zip')
        assert not os.path.exists(pack_02_path), \
            'Third pack should not exist (incomplete group)'

        # Verify only loose files {14, 15, 32, 33} remain
        for rid in (14, 15):
            assert os.path.exists(bodyful_filepaths[rid]), \
                f'Revision {rid} should remain as loose file (bad block, never successfully read)'
        for rid in (32, 33):
            assert os.path.exists(bodyful_filepaths[rid]), \
                f'Revision {rid} should remain as loose file (incomplete group)'
        assert not os.path.exists(bodyful_filepaths[30]), \
            'Revision 30 should have been packed into 01_.zip and deleted'
        assert not os.path.exists(bodyful_filepaths[31]), \
            'Revision 31 should have been packed into 01_.zip and deleted'

        # Verify reads attempted for bodyful revisions {30, 31} only
        # (32 is not read because it's in an incomplete group that stays as individual files)
        # Notably, read NOT attempted for {14, 15} (bad blocks observed earlier, pack 00_ already exists)
        assertEqual({30, 31}, opened_revision_ids_2)


async def test_given_disk_disconnects_before_migration_reaches_intermediate_checkpoint_when_checkpoint_hit_then_aborts_migration_early_and_displays_error_dialog_and_closes_project() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
        project_dirpath = project.path
        assertEqual(2, project.major_version)

        # Create 64 revisions with bodies (4 complete packs worth)
        for i in range(1, 65):
            resource = Resource(project, f'http://example.com/disk-disconnect-mid/{i}')
            RR.create_from_response(
                resource,
                metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                body_stream=BytesIO(f'body {i}'.encode()),
            )

        # Initiate migration
        project._queue_migration_after_reopen(MigrationType.HIERARCHICAL_TO_PACK16)

    revisions_dir = os.path.join(project_dirpath, 'revisions')
    leaf_revisions_dir = os.path.join(revisions_dir, '000', '000', '000', '000')

    # Simulate disk disconnect after some packs are written
    real_listdir = os.listdir
    disk_disconnected = False
    def mock_listdir(path):
        if disk_disconnected and os.path.normpath(path) == os.path.normpath(revisions_dir):
            raise OSError(5, 'Input/output error')
        return real_listdir(path)

    # Disconnect disk after the first pack is written (before the intermediate checkpoint)
    from crystal.model.pack16 import create_pack_file as _real_create_pack_file
    packs_written = 0
    def mock_create_pack_file(revision_files, dest_filepath, *args, **kwargs):
        nonlocal packs_written, disk_disconnected
        result = _real_create_pack_file(revision_files, dest_filepath, *args, **kwargs)
        packs_written += 1
        if packs_written >= 1:
            disk_disconnected = True
        return result

    # Reopen project. Migration should detect disk disconnect and abort.
    with patch('os.listdir', mock_listdir), \
            patch('crystal.model.pack16.create_pack_file', mock_create_pack_file), \
            patch('crystal.progress.ui.ShowModal',
                mocked_show_modal('cr-disk-error', wx.ID_OK)) as show_modal_method, \
            _revision_count_between_disk_health_checks_set_to(32):
        ocd = await OpenOrCreateDialog.wait_for()
        await ocd.start_opening(project_dirpath, next_window_name='cr-open-or-create-project')

        # HACK: Wait minimum duration to allow open to finish
        await bg_sleep(0.5)

        # Wait for migration to abort and return to initial dialog
        ocd = await OpenOrCreateDialog.wait_for()
        assertEqual(1, show_modal_method.call_count)

    # Verify partial migration state: at least one pack was created before abort
    pack_00_path = os.path.join(leaf_revisions_dir, '00_.zip')
    assert os.path.exists(pack_00_path), \
        'First pack should exist (written before disk disconnect)'

    # Verify migration marker still present (migration was not completed)
    async with project_opened_without_migrating(project_dirpath) as (_, project):
        assertEqual(3, project.major_version)
        assertEqual(2, project._get_major_version_old(project._db))

    # Verify migration can resume successfully after disk reconnects
    async with (await OpenOrCreateDialog.wait_for()).open(
            project_dirpath, wait_func=wait_for_project_to_upgrade) as (mw, project):
        assertEqual(3, project.major_version)
        assertEqual(None, project._get_major_version_old(project._db))

        # Verify all revisions are readable
        for i in range(1, 65):
            resource = not_none(project.get_resource(url=f'http://example.com/disk-disconnect-mid/{i}'))
            revision = resource.default_revision()
            assert revision is not None
            with revision.open() as f:
                assertEqual(f'body {i}'.encode(), f.read())


async def test_given_disk_disconnects_before_migration_reaches_final_checkpoint_when_checkpoint_hit_then_aborts_migration_early_and_displays_error_dialog_and_closes_project() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
        project_dirpath = project.path
        assertEqual(2, project.major_version)

        # Create 32 revisions with bodies (2 complete packs worth)
        for i in range(1, 33):
            resource = Resource(project, f'http://example.com/disk-disconnect-final/{i}')
            RR.create_from_response(
                resource,
                metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                body_stream=BytesIO(f'body {i}'.encode()),
            )

        # Initiate migration
        project._queue_migration_after_reopen(MigrationType.HIERARCHICAL_TO_PACK16)

    revisions_dir = os.path.join(project_dirpath, 'revisions')
    leaf_revisions_dir = os.path.join(revisions_dir, '000', '000', '000', '000')

    # Simulate disk disconnect after all packs are written
    real_listdir = os.listdir
    disk_disconnected = False
    def mock_listdir(path):
        if disk_disconnected and os.path.normpath(path) == os.path.normpath(revisions_dir):
            raise OSError(5, 'Input/output error')
        return real_listdir(path)

    # Disconnect disk after the last pack is written (before the final checkpoint)
    from crystal.model.pack16 import create_pack_file as _real_create_pack_file
    packs_written = 0
    def mock_create_pack_file(revision_files, dest_filepath, *args, **kwargs):
        nonlocal packs_written, disk_disconnected
        result = _real_create_pack_file(revision_files, dest_filepath, *args, **kwargs)
        packs_written += 1
        if packs_written >= 2:  # disconnect after both packs are written
            disk_disconnected = True
        return result

    # Reopen project. Migration should detect disk disconnect at final checkpoint.
    # NOTE: Uses a large checkpoint interval (e.g. 256) so no intermediate checkpoint fires;
    #       only the final checkpoint should catch the disconnect
    with patch('os.listdir', mock_listdir), \
            patch('crystal.model.pack16.create_pack_file', mock_create_pack_file), \
            patch('crystal.progress.ui.ShowModal',
                mocked_show_modal('cr-disk-error', wx.ID_OK)) as show_modal_method:
        ocd = await OpenOrCreateDialog.wait_for()
        await ocd.start_opening(project_dirpath, next_window_name='cr-open-or-create-project')

        # HACK: Wait minimum duration to allow open to finish
        await bg_sleep(0.5)

        # Wait for migration to abort and return to initial dialog
        ocd = await OpenOrCreateDialog.wait_for()
        assertEqual(1, show_modal_method.call_count)
    
    # Verify both packs were created before the disconnect was detected
    pack_00_path = os.path.join(leaf_revisions_dir, '00_.zip')
    pack_01_path = os.path.join(leaf_revisions_dir, '01_.zip')
    assert os.path.exists(pack_00_path), 'First pack should exist'
    assert os.path.exists(pack_01_path), 'Second pack should exist'

    # Verify migration marker still present (migration was not completed)
    async with project_opened_without_migrating(project_dirpath) as (_, project):
        assertEqual(3, project.major_version)
        assertEqual(2, project._get_major_version_old(project._db))

    # Verify migration can resume successfully after disk reconnects
    async with (await OpenOrCreateDialog.wait_for()).open(
            project_dirpath, wait_func=wait_for_project_to_upgrade) as (mw, project):
        assertEqual(3, project.major_version)
        assertEqual(None, project._get_major_version_old(project._db))

        # Verify all revisions are readable
        for i in range(1, 33):
            resource = not_none(project.get_resource(url=f'http://example.com/disk-disconnect-final/{i}'))
            revision = resource.default_revision()
            assert revision is not None
            with revision.open() as f:
                assertEqual(f'body {i}'.encode(), f.read())


@skip('covered by: test_when_create_resource_revision_and_disk_disconnects_or_disk_full_or_process_terminates_before_filesystem_flush_then_will_rollback_when_project_reopened')
async def test_given_interrupted_migration_when_reopen_then_cleans_up_temp_pack_files() -> None:
    pass


# === Concurrent Operations ===

# At most 1 WRITE to resource revision data can be active within a project,
# as enforced by the _revision_bodies_writable() context.
#
# An unlimited number of READS from revision revisiomn data can be concurrent
# with each other and with up to 1 WRITE within a project.
# 
# Note that a READ can sometimes perform a READ-REPAIR which is a special
# kind of write that can be performed concurrently with other READ-REPAIRS
# and other WRITES. A READ-REPAIR uses replace_destination_locked() to 
# ensure that only one repair (or conflicting WRITE) can happen at a time.

async def test_when_read_packed_revision_and_concurrently_read_another_revision_from_same_pack_then_both_reads_succeed() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        (pack_filepath, revision_a, revision_b) = \
            _create_pack_with_two_bodyful_revisions(project)
        
        # Precondition: Pack file exists with mtime T1
        mtime_t1 = os.path.getmtime(pack_filepath)
        
        # Precondition: Pack file contains A and B
        with zipfile.ZipFile(pack_filepath, 'r') as zf:
            assertEqual({'00e', '00f'}, set(zf.namelist()))
        
        # Open revision body A. Read half of it.
        file_a = revision_a.open()
        body_a_half = file_a.read(len(_LARGE_BODY_A) // 2)
        assertEqual(_LARGE_BODY_A[:len(_LARGE_BODY_A) // 2], body_a_half)
        
        # Open revision body B. Read half of it.
        file_b = revision_b.open()
        body_b_half = file_b.read(len(_LARGE_BODY_B) // 2)
        assertEqual(_LARGE_BODY_B[:len(_LARGE_BODY_B) // 2], body_b_half)
        
        # Read remainder of revision body A. Close it.
        body_a_remainder = file_a.read()
        assertEqual(_LARGE_BODY_A[len(_LARGE_BODY_A) // 2:], body_a_remainder)
        file_a.close()
        
        # Read remainder of revision body B. Close it.
        body_b_remainder = file_b.read()
        assertEqual(_LARGE_BODY_B[len(_LARGE_BODY_B) // 2:], body_b_remainder)
        file_b.close()
        
        # Postcondition: Pack file exists with mtime T1 (unchanged)
        if fine_grained_mtimes_available():
            mtime_t1_after = os.path.getmtime(pack_filepath)
            assertEqual(mtime_t1, mtime_t1_after)
        
        # Postcondition: Pack file contains A and B
        with zipfile.ZipFile(pack_filepath, 'r') as zf:
            assertEqual({'00e', '00f'}, set(zf.namelist()))


async def test_when_read_packed_revision_and_concurrently_delete_another_revision_from_same_pack_then_both_operations_succeed() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        (pack_filepath, revision_a, revision_b) = \
            _create_pack_with_two_bodyful_revisions(project)
        
        # Precondition: Pack file exists with mtime T1
        mtime_t1 = os.path.getmtime(pack_filepath)
        
        # Precondition: Pack file contains A and B
        with zipfile.ZipFile(pack_filepath, 'r') as zf:
            assertEqual({'00e', '00f'}, set(zf.namelist()))
        
        # Open revision body A. Read half of it.
        file_a = revision_a.open()
        body_a_half = file_a.read(len(_LARGE_BODY_A) // 2)
        assertEqual(_LARGE_BODY_A[:len(_LARGE_BODY_A) // 2], body_a_half)
        
        # Delete revision B.
        await wait_for_future(revision_b.delete())
        
        # Read remainder of revision body A. Close it.
        body_a_remainder = file_a.read()
        assertEqual(_LARGE_BODY_A[len(_LARGE_BODY_A) // 2:], body_a_remainder)
        file_a.close()
        
        # Postcondition: Pack file exists with mtime T2 (changed due to delete)
        if fine_grained_mtimes_available():
            mtime_t2 = os.path.getmtime(pack_filepath)
            assert mtime_t2 != mtime_t1, 'Pack file mtime should have changed after delete'
        
        # Postcondition: Pack file contains A but not B
        with zipfile.ZipFile(pack_filepath, 'r') as zf:
            assertEqual({'00e'}, set(zf.namelist()))


async def test_when_read_packed_revision_and_concurrently_delete_same_revision_then_both_operations_succeed() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        (pack_filepath, revision_a, revision_b) = \
            _create_pack_with_two_bodyful_revisions(project)
        
        # Precondition: Pack file exists with mtime T1
        mtime_t1 = os.path.getmtime(pack_filepath)
        
        # Precondition: Pack file contains A and B
        with zipfile.ZipFile(pack_filepath, 'r') as zf:
            assertEqual({'00e', '00f'}, set(zf.namelist()))
        
        # Open revision body A. Read half of it.
        file_a = revision_a.open()
        body_a_half = file_a.read(len(_LARGE_BODY_A) // 2)
        assertEqual(_LARGE_BODY_A[:len(_LARGE_BODY_A) // 2], body_a_half)
        
        # Delete revision A (the same one being read).
        await wait_for_future(revision_a.delete())
        
        # Read remainder of revision body A. Close it.
        # (Should succeed because the file handle was opened before the delete)
        body_a_remainder = file_a.read()
        assertEqual(_LARGE_BODY_A[len(_LARGE_BODY_A) // 2:], body_a_remainder)
        file_a.close()
        
        # Postcondition: Pack file exists with mtime T2 (changed due to delete)
        if fine_grained_mtimes_available():
            mtime_t2 = os.path.getmtime(pack_filepath)
            assert mtime_t2 != mtime_t1, 'Pack file mtime should have changed after delete'
        
        # Postcondition: Pack file contains B but not A
        with zipfile.ZipFile(pack_filepath, 'r') as zf:
            assertEqual({'00f'}, set(zf.namelist()))


async def test_when_read_packed_revision_and_pack_file_needs_repair_then_repair_performed_and_read_succeeds() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        (pack_filepath, revision_a, revision_b) = \
            _create_pack_with_two_bodyful_revisions(project)
        
        # Precondition: Pack file exists
        assert os.path.exists(pack_filepath), 'Pack file should exist'
        
        # Simulate crash during delete by renaming pack file to .replacing
        replacing_filepath = pack_filepath + replace_and_flush.RENAME_SUFFIX  # type: ignore[attr-defined]
        os.rename(pack_filepath, replacing_filepath)
        
        # Precondition: Pack file does NOT exist, .replacing file exists
        assert not os.path.exists(pack_filepath), 'Pack file should not exist'
        assert os.path.exists(replacing_filepath), '.replacing file should exist'
        
        # Read revision A. Should trigger repair and succeed.
        with revision_a.open() as f:
            body = f.read()
        assertEqual(_LARGE_BODY_A, body)
        
        # Postcondition: Pack file exists (repaired)
        assert os.path.exists(pack_filepath), 'Pack file should be repaired'
        
        # Postcondition: .replacing file does NOT exist (cleaned up)
        assert not os.path.exists(replacing_filepath), '.replacing file should be cleaned up'
        
        # Verify both revisions are still readable
        with revision_a.open() as f:
            assertEqual(_LARGE_BODY_A, f.read())
        with revision_b.open() as f:
            assertEqual(_LARGE_BODY_B, f.read())


async def test_when_concurrent_reads_of_packed_revision_and_pack_file_needs_repair_then_one_repair_performed_and_both_reads_succeed() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        (pack_filepath, revision_a, revision_b) = \
            _create_pack_with_two_bodyful_revisions(project)
        
        # Precondition: Pack file exists
        assert os.path.exists(pack_filepath), 'Pack file should exist'
        
        # Simulate crash during delete by renaming pack file to .replacing
        replacing_filepath = pack_filepath + replace_and_flush.RENAME_SUFFIX  # type: ignore[attr-defined]
        os.rename(pack_filepath, replacing_filepath)
        
        # Precondition: Pack file does NOT exist, .replacing file exists
        assert not os.path.exists(pack_filepath), 'Pack file should not exist'
        assert os.path.exists(replacing_filepath), '.replacing file should exist'
        
        # Track how many times replace_and_flush is called (indicating repair)
        repair_count = 0
        real_replace_and_flush = replace_and_flush
        def mock_replace_and_flush(src, dst):
            nonlocal repair_count
            repair_count += 1
            return real_replace_and_flush(src, dst)
        # Copy the RENAME_SUFFIX attribute so the patched function behaves correctly
        mock_replace_and_flush.RENAME_SUFFIX = replace_and_flush.RENAME_SUFFIX  # type: ignore[attr-defined]
        
        # Read both revisions concurrently. Only one should trigger repair.
        with patch('crystal.model.resource_revision.replace_and_flush', mock_replace_and_flush):
            # Open revision A (will trigger repair)
            file_a = revision_a.open()
            body_a_half = file_a.read(len(_LARGE_BODY_A) // 2)
            assertEqual(_LARGE_BODY_A[:len(_LARGE_BODY_A) // 2], body_a_half)
            
            # Open revision B (should NOT trigger repair since pack is now repaired)
            file_b = revision_b.open()
            body_b_half = file_b.read(len(_LARGE_BODY_B) // 2)
            assertEqual(_LARGE_BODY_B[:len(_LARGE_BODY_B) // 2], body_b_half)
            
            # Finish reading both
            body_a_remainder = file_a.read()
            assertEqual(_LARGE_BODY_A[len(_LARGE_BODY_A) // 2:], body_a_remainder)
            file_a.close()
            
            body_b_remainder = file_b.read()
            assertEqual(_LARGE_BODY_B[len(_LARGE_BODY_B) // 2:], body_b_remainder)
            file_b.close()
        
        # Postcondition: Only one repair was performed
        assertEqual(1, repair_count)
        
        # Postcondition: Pack file exists (repaired)
        assert os.path.exists(pack_filepath), 'Pack file should be repaired'
        
        # Postcondition: .replacing file does NOT exist (cleaned up)
        assert not os.path.exists(replacing_filepath), '.replacing file should be cleaned up'


async def test_when_read_packed_revision_and_stale_replacing_file_exists_then_read_on_newer_pack_succeeds_and_old_replacing_file_ignored() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        (pack_filepath, revision_a, revision_b) = \
            _create_pack_with_two_bodyful_revisions(project)
        
        # Precondition: Pack file exists with mtime T1
        mtime_t1 = os.path.getmtime(pack_filepath)
        
        # Create a stale .replacing file (simulating incomplete cleanup after a
        # successful replacement that didn't finish deleting the old file)
        replacing_filepath = pack_filepath + replace_and_flush.RENAME_SUFFIX  # type: ignore[attr-defined]
        with open(replacing_filepath, 'wb') as f:
            # Write stale/different content to the .replacing file
            f.write(b'stale pack content that should be ignored')
        
        # Precondition: Both pack file and .replacing file exist
        assert os.path.exists(pack_filepath), 'Pack file should exist'
        assert os.path.exists(replacing_filepath), '.replacing file should exist'
        
        # Read revision A. Should read from pack file, ignoring stale .replacing.
        with revision_a.open() as f:
            body = f.read()
        assertEqual(_LARGE_BODY_A, body)
        
        # Postcondition: Pack file still exists with same mtime (not touched)
        if fine_grained_mtimes_available():
            mtime_t2 = os.path.getmtime(pack_filepath)
            assertEqual(mtime_t1, mtime_t2)
        
        # Postcondition: .replacing file still exists (not cleaned up by read)
        # NOTE: .replacing cleanup happens during delete operations, not reads
        assert os.path.exists(replacing_filepath), '.replacing file should still exist'
        
        # Verify both revisions are readable from the pack file
        with revision_a.open() as f:
            assertEqual(_LARGE_BODY_A, f.read())
        with revision_b.open() as f:
            assertEqual(_LARGE_BODY_B, f.read())


async def test_when_read_loose_revision_and_concurrently_pack_same_revision_then_both_operations_succeed() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        (pack_filepath, loose_filepath_a, revision_a) = \
            _create_almost_complete_pack_with_one_bodyful_revision(project)
        
        # Precondition: Loose revision A exists
        assert os.path.exists(loose_filepath_a), 'Loose revision A should exist'
        
        # Precondition: Pack file does not exist
        assert not os.path.exists(pack_filepath), 'Pack file should not exist yet'
        
        # Open revision body A. Read half of it.
        file_a = revision_a.open()
        body_a_half = file_a.read(len(_LARGE_BODY_A) // 2)
        assertEqual(_LARGE_BODY_A[:len(_LARGE_BODY_A) // 2], body_a_half)
        
        # Create bodyful revision B with ID 15. Completes a pack including revision A.
        with scheduler_thread_context():  # safe because no tasks running
            resource_b = Resource(project, 'http://example.com/loose-pack-test/15')
            revision_b = RR.create_from_response(
                resource_b,
                metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                body_stream=BytesIO(_LARGE_BODY_B),
            )
        
        # Read remainder of revision body A. Close it.
        # (Should succeed because the file handle was opened before the pack operation)
        body_a_remainder = file_a.read()
        assertEqual(_LARGE_BODY_A[len(_LARGE_BODY_A) // 2:], body_a_remainder)
        file_a.close()
        
        # Postcondition: Loose revision A does NOT exist
        assert not os.path.exists(loose_filepath_a), 'Loose revision A should be packed'
        
        # Postcondition: Pack file exists, containing A and B
        assert os.path.exists(pack_filepath), 'Pack file should exist after completing pack'
        with zipfile.ZipFile(pack_filepath, 'r') as zf:
            assertEqual({'00e', '00f'}, set(zf.namelist()))


async def test_when_read_loose_revision_and_concurrently_delete_same_revision_then_both_operations_succeed() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        (pack_filepath, loose_filepath_a, revision_a) = \
            _create_almost_complete_pack_with_one_bodyful_revision(project)
        
        # Precondition: Loose revision A exists
        assert os.path.exists(loose_filepath_a), 'Loose revision A should exist'
        
        # Open revision body A. Read half of it.
        file_a = revision_a.open()
        body_a_half = file_a.read(len(_LARGE_BODY_A) // 2)
        assertEqual(_LARGE_BODY_A[:len(_LARGE_BODY_A) // 2], body_a_half)
        
        # Delete revision A.
        await wait_for_future(revision_a.delete())
        
        # Read remainder of revision body A. Close it.
        # (Should succeed because the file handle was opened before the delete)
        body_a_remainder = file_a.read()
        assertEqual(_LARGE_BODY_A[len(_LARGE_BODY_A) // 2:], body_a_remainder)
        file_a.close()
        
        # Postcondition: Loose revision A does NOT exist
        assert not os.path.exists(loose_filepath_a), 'Loose revision A should be deleted'


async def test_when_delete_packed_revision_during_concurrent_read_and_stale_replacing_file_exists_then_replacing_file_deleted_and_delete_succeeds() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        (pack_filepath, revision_a, revision_b) = \
            _create_pack_with_two_bodyful_revisions(project)
        
        # Precondition: Pack file exists with mtime T1
        mtime_t1 = os.path.getmtime(pack_filepath)
        
        # Create a stale .replacing file (simulating incomplete cleanup after a
        # successful replacement that didn't finish deleting the old file)
        replacing_filepath = pack_filepath + replace_and_flush.RENAME_SUFFIX  # type: ignore[attr-defined]
        with open(replacing_filepath, 'wb') as f:
            # Write stale/different content to the .replacing file
            f.write(b'stale pack content that should be cleaned up during delete')
        
        # Precondition: Both pack file and .replacing file exist
        assert os.path.exists(pack_filepath), 'Pack file should exist'
        assert os.path.exists(replacing_filepath), '.replacing file should exist'
        
        # Open revision body A. Read half of it.
        # (This simulates a concurrent read, triggering cleanup logic in replace_and_flush())
        file_a = revision_a.open()
        body_a_half = file_a.read(len(_LARGE_BODY_A) // 2)
        assertEqual(_LARGE_BODY_A[:len(_LARGE_BODY_A) // 2], body_a_half)
        
        # Delete revision B. Should clean up stale .replacing file during replace.
        await wait_for_future(revision_b.delete())
        
        # Read remainder of revision body A. Close it.
        # (Should succeed because the file handle was opened before the delete)
        body_a_remainder = file_a.read()
        assertEqual(_LARGE_BODY_A[len(_LARGE_BODY_A) // 2:], body_a_remainder)
        file_a.close()
        
        # Postcondition: Pack file exists (rewritten without revision B)
        assert os.path.exists(pack_filepath), 'Pack file should exist after delete'
        
        # Postcondition: Pack file has changed (new mtime)
        if fine_grained_mtimes_available():
            mtime_t2 = os.path.getmtime(pack_filepath)
            assert mtime_t2 != mtime_t1, 'Pack file mtime should have changed'
        
        if is_windows():
            # Postcondition: .replacing file was cleaned up during delete operation
            assert not os.path.exists(replacing_filepath), \
                '.replacing file should be cleaned up during delete'
        else:
            # Postcondition: Currently, non-Windows platform will not clean up
            # a .replacing file during the delete operation. This behavior may
            # be changed to match the Windows behavior in the future.
            assert os.path.exists(replacing_filepath), \
                '.replacing file expected to still exist on non-Windows platforms'
        
        # Postcondition: Pack file contains A but not B
        with zipfile.ZipFile(pack_filepath, 'r') as zf:
            assertEqual({'00e'}, set(zf.namelist()))
        
        # Verify revision A is still readable
        with revision_a.open() as f:
            assertEqual(_LARGE_BODY_A, f.read())


async def test_when_size_packed_or_loose_revision_then_correct_size_is_returned() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        with scheduler_thread_context():  # safe because will not create any running tasks
            project._set_major_version_for_test(3)

            # Create revisions
            # - ID 13 (packed): "body missing" case
            # - ID 14 (packed): "no body" case
            # - ID 15 (packed): "has body" case
            # - ID 16 (unpacked): "body missing" case
            # - ID 17 (unpacked): "no body" case
            # - ID 18 (unpacked): "has body" case
            _PACKED_HAS_BODY_CONTENT = b'packed body'
            _LOOSE_HAS_BODY_CONTENT = b'loose body'
            if True:
                # Create packed revisions (IDs 1-15)
                if True:
                    # Create 12 filler error revisions (IDs 1-12)
                    for i in range(1, 13):
                        resource = Resource(project, f'http://example.com/size-test/{i}')
                        RR.create_from_error(resource, Exception('Test error'))

                    # ID 13: bodyful (body will be deleted from pack later, for "body missing" case)
                    resource_packed_missing = Resource(
                        project, 'http://example.com/size-test/packed-body-missing')
                    packed_body_missing_revision = RR.create_from_response(
                        resource_packed_missing,
                        metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                        body_stream=BytesIO(b'will be deleted from pack'),
                    )

                    # ID 14: error revision (no body) - "packed, no body" case
                    resource_packed_no_body = Resource(
                        project, 'http://example.com/size-test/packed-no-body')
                    packed_no_body_revision = RR.create_from_error(
                        resource_packed_no_body, Exception('Test error'))

                    # ID 15: bodyful - "packed, has body" case. Triggers pack creation.
                    resource_packed_has_body = Resource(
                        project, 'http://example.com/size-test/packed-has-body')
                    packed_has_body_revision = RR.create_from_response(
                        resource_packed_has_body,
                        metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                        body_stream=BytesIO(_PACKED_HAS_BODY_CONTENT),
                    )

                    # Verify pack was created (triggered by ID 15)
                    pack_filepath = os.path.join(
                        project.path, 'revisions', '000', '000', '000', '000', '00_.zip')
                    assert os.path.exists(pack_filepath), 'Pack file should exist after 15 revisions'

                    # Delete body of ID 13 from pack, leaving its DB row
                    # (simulates "body missing" for a packed revision)
                    with scheduler_thread_context():  # safe because no tasks running
                        packed_body_missing_revision._delete_body_now(
                            not_none(packed_body_missing_revision._id),
                            packed_body_missing_revision._body_filepath)

                # Create loose revisions (IDs 16-18; second pack not yet triggered)
                if True:
                    # ID 16: bodyful (body will be deleted later, for "body missing" loose case)
                    resource_loose_missing = Resource(
                        project, 'http://example.com/size-test/loose-body-missing')
                    loose_body_missing_revision = RR.create_from_response(
                        resource_loose_missing,
                        metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                        body_stream=BytesIO(b'will be deleted loose'),
                    )

                    # ID 17: error revision (no body) - "loose, no body" case
                    resource_loose_no_body = Resource(
                        project, 'http://example.com/size-test/loose-no-body')
                    loose_no_body_revision = RR.create_from_error(
                        resource_loose_no_body, Exception('Test error'))

                    # ID 18: bodyful - "loose, has body" case
                    resource_loose_has_body = Resource(
                        project, 'http://example.com/size-test/loose-has-body')
                    loose_has_body_revision = RR.create_from_response(
                        resource_loose_has_body,
                        metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
                        body_stream=BytesIO(_LOOSE_HAS_BODY_CONTENT),
                    )

                # Delete body of ID 16 (individual loose file), leaving its DB row
                # (simulates "body missing" for a loose revision)
                with scheduler_thread_context():  # safe because no tasks running
                    loose_body_missing_revision._delete_body_now(
                        not_none(loose_body_missing_revision._id),
                        loose_body_missing_revision._body_filepath)

            # Verify size() for packed revisions (IDs 13-15)
            with assertRaises(NoRevisionBodyError):
                packed_no_body_revision.size()
            with assertRaises(RevisionBodyMissingError):
                packed_body_missing_revision.size()
            assertEqual(len(_PACKED_HAS_BODY_CONTENT), packed_has_body_revision.size())

            # Verify size() for loose revisions (IDs 16-18)
            with assertRaises(NoRevisionBodyError):
                loose_no_body_revision.size()
            with assertRaises(RevisionBodyMissingError):
                loose_body_missing_revision.size()
            assertEqual(len(_LOOSE_HAS_BODY_CONTENT), loose_has_body_revision.size())


async def test_when_size_packed_revision_and_pack_file_needs_repair_then_repair_performed_and_size_succeeds() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        (pack_filepath, revision_a, revision_b) = \
            _create_pack_with_two_bodyful_revisions(project)

        # Precondition: Pack file exists
        assert os.path.exists(pack_filepath), 'Pack file should exist'

        # Simulate crash during delete by renaming pack file to .replacing
        replacing_filepath = pack_filepath + replace_and_flush.RENAME_SUFFIX  # type: ignore[attr-defined]
        os.rename(pack_filepath, replacing_filepath)

        # Precondition: Pack file does NOT exist, .replacing file exists
        assert not os.path.exists(pack_filepath), 'Pack file should not exist'
        assert os.path.exists(replacing_filepath), '.replacing file should exist'

        # Size revision A. Should trigger repair and succeed.
        size_a = revision_a.size()
        assertEqual(len(_LARGE_BODY_A), size_a)

        # Postcondition: Pack file exists (repaired)
        assert os.path.exists(pack_filepath), 'Pack file should be repaired'

        # Postcondition: .replacing file does NOT exist (cleaned up)
        assert not os.path.exists(replacing_filepath), '.replacing file should be cleaned up'

        # Verify both revisions are still size-able
        assertEqual(len(_LARGE_BODY_A), revision_a.size())
        assertEqual(len(_LARGE_BODY_B), revision_b.size())


# === Misc ===

# NOTE: See also: test_refuses_to_open_project_with_unknown_high_major_version
async def test_given_project_with_major_version_3_when_opened_by_older_crystal_then_raises_project_too_new_error() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
        project_dirpath = project.path
        project._set_major_version_for_test(3)
        assert 3 == project.major_version

    # Try to open the v3 project as if we are an older Crystal that only supports up to v2
    show_modal = mocked_show_modal('cr-project-too-new', wx.ID_OK)
    with patch('crystal.util.wx_dialog.ShowModal', show_modal), \
            patch.object(Project, '_LATEST_SUPPORTED_MAJOR_VERSION', 2):
        ocd = await OpenOrCreateDialog.wait_for()
        await ocd.start_opening(project_dirpath, next_window_name='cr-open-or-create-project')

        # HACK: Wait minimum duration to allow open to finish
        await bg_sleep(0.5)

        # Wait for cancel and return to initial dialog
        ocd = await OpenOrCreateDialog.wait_for()

        assert 1 == show_modal.call_count


# === Utility ===

# Large body content used in concurrent tests (must be large enough to read in halves)
_LARGE_BODY_A = b'A' * 1024 + b'Body content for revision A' + b'A' * 1024
_LARGE_BODY_B = b'B' * 1024 + b'Body content for revision B' + b'B' * 1024


def _create_pack_with_two_bodyful_revisions(
        project: Project
        ) -> tuple[str, RR, RR]:
    """
    Creates a project with 1 pack containing exactly 2 revision bodies.
    
    Creates:
    - Bodyless error revisions for IDs 1-13
    - Bodyful revisions for IDs 14-15, completing a pack with 2 revision bodies
    
    Returns:
    - pack_filepath: Path to the pack file (00_.zip)
    - revision_a: The revision with ID 14 (body: _LARGE_BODY_A)
    - revision_b: The revision with ID 15 (body: _LARGE_BODY_B)
    """
    project._set_major_version_for_test(3)
    
    with scheduler_thread_context():  # safe because no tasks running
        # Create 13 bodyless error revisions (IDs 1-13)
        for i in range(1, 14):
            resource = Resource(project, f'http://example.com/concurrent-test/{i}')
            RR.create_from_error(resource, Exception('Test error'))
        
        # Create 2 bodyful revisions (IDs 14-15), completing the pack
        resource_a = Resource(project, 'http://example.com/concurrent-test/14')
        revision_a = RR.create_from_response(
            resource_a,
            metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
            body_stream=BytesIO(_LARGE_BODY_A),
        )
        
        resource_b = Resource(project, 'http://example.com/concurrent-test/15')
        revision_b = RR.create_from_response(
            resource_b,
            metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
            body_stream=BytesIO(_LARGE_BODY_B),
        )
    
    pack_filepath = os.path.join(
        project.path, 'revisions', '000', '000', '000', '000', '00_.zip')
    
    # Verify pack was created with exactly 2 entries
    assert os.path.exists(pack_filepath), 'Pack file should exist after 15 revisions'
    with zipfile.ZipFile(pack_filepath, 'r') as zf:
        entries = zf.namelist()
        assert len(entries) == 2, f'Expected 2 entries, got {len(entries)}: {entries}'
    
    return (pack_filepath, revision_a, revision_b)


def _create_almost_complete_pack_with_one_bodyful_revision(
        project: Project
        ) -> tuple[str, str, RR]:
    """
    Creates a project with ALMOST 1 complete pack (missing 1 revision to complete).
    
    Creates:
    - Bodyless error revisions for IDs 1-13
    - Bodyful revision for ID 14 (as a loose/individual file, not yet packed)
    
    Returns:
    - pack_filepath: Path where the pack file would be created (does not exist yet)
    - loose_filepath_a: Path to the loose revision file for ID 14
    - revision_a: The revision with ID 14 (body: _LARGE_BODY_A)
    """
    project._set_major_version_for_test(3)
    
    with scheduler_thread_context():  # safe because no tasks running
        # Create 13 bodyless error revisions (IDs 1-13)
        for i in range(1, 14):
            resource = Resource(project, f'http://example.com/loose-pack-test/{i}')
            RR.create_from_error(resource, Exception('Test error'))
        
        # Create 1 bodyful revision (ID 14), NOT completing the pack
        resource_a = Resource(project, 'http://example.com/loose-pack-test/14')
        revision_a = RR.create_from_response(
            resource_a,
            metadata={'http_version': 11, 'status_code': 200, 'reason_phrase': 'OK', 'headers': []},
            body_stream=BytesIO(_LARGE_BODY_A),
        )
    
    pack_filepath = os.path.join(
        project.path, 'revisions', '000', '000', '000', '000', '00_.zip')
    loose_filepath_a = os.path.join(
        project.path, 'revisions', '000', '000', '000', '000', '00e')
    
    # Verify pack was NOT created yet
    assert not os.path.exists(pack_filepath), 'Pack file should not exist (incomplete pack)'
    
    # Verify loose revision A exists
    assert os.path.exists(loose_filepath_a), 'Loose revision A should exist'
    
    return (pack_filepath, loose_filepath_a, revision_a)


class _ErrorOnReadFile:
    """Wraps a file object, raising OSError on read() while delegating other methods."""
    def __init__(self, base):
        self._base = base

    def read(self, *args, **kwargs):
        raise OSError(5, 'Input/output error')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._base.close()

    def __getattr__(self, name):
        return getattr(self._base, name)


class _ErrorOnWriteFile:
    """Wraps a file object, raising OSError on write() while delegating other methods."""
    def __init__(self, base):
        self._base = base

    def write(self, *args, **kwargs):
        raise OSError(28, 'No space left on device')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._base.close()

    def __getattr__(self, name):
        return getattr(self._base, name)


@contextmanager
def _revision_count_between_disk_health_checks_set_to(count: int) -> Iterator[None]:
    was_count = Project._revision_count_between_disk_health_checks
    Project._revision_count_between_disk_health_checks = count
    try:
        yield
    finally:
        Project._revision_count_between_disk_health_checks = was_count
