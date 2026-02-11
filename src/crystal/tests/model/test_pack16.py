"""
Tests for Pack16 revision storage format (major_version == 3).

All tests below implicitly include the condition:
* given_project_in_pack16_format
"""
from unittest import skip
from crystal.model import Resource, ResourceRevision as RR, RevisionBodyMissingError
from crystal.tests.util.asserts import assertEqual, assertRaises
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util.tasks import scheduler_disabled, scheduler_thread_context
from crystal.tests.util.wait import wait_for, wait_for_future
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.xtyping import not_none
from io import BytesIO
import os
from unittest.mock import patch
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

        # Initiate migration: set markers then close (project reopens automatically at end of context)
        project._set_major_version_old_for_test(2)
        project._set_major_version_for_test(3)
        # (Close project)

    # Reopen project — migration runs automatically in _apply_migrations()
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
        project._set_major_version_old_for_test(2)
        project._set_major_version_for_test(3)
        # (Close project)

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
        project._set_major_version_old_for_test(2)
        project._set_major_version_for_test(3)
        # (Close project)

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
