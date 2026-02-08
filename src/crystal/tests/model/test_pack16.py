"""
Tests for Pack16 revision storage format (major_version == 3).

All tests below implicitly include the condition:
* given_project_in_pack16_format
"""
from unittest import skip
from crystal.model import Resource, ResourceRevision as RR, RevisionBodyMissingError
from crystal.tests.util.asserts import assertEqual, assertRaises
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.xtyping import not_none
from io import BytesIO
import os
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
