"""
Tests for Pack16 revision storage format (major_version == 3).

All tests below implicitly include the condition:
* given_project_opened_as_writable
"""

from crystal.model import Resource
from crystal.model import ResourceRevision as RR
from crystal.tests.util.asserts import assertEqual
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util.windows import OpenOrCreateDialog
from io import BytesIO
import os
import zipfile


# === Create ===

@awith_subtests
async def test_given_project_in_pack16_format_when_create_multiple_of_16_resource_revisions_then_creates_pack_file_if_at_least_one_revision_body_exists(subtests: SubtestsContext) -> None:
    # Case 1: 15th + 31st revision has a body; verify 2 packs created
    # (Packing triggers when IDs 15 and 31 are created)
    with subtests.test(case='15th_and_31st_have_bodies'):
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            project._set_major_version_for_test(3)

            # Create 32 revisions, only IDs 15 and 31 have bodies
            for i in range(1, 33):
                resource = Resource(project, f'http://example.com/case1/{i}')
                if i == 15 or i == 31:
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
                for f in files:
                    if f.endswith('_.zip'):
                        pack_files.append(os.path.join(root, f))
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
                for f in files:
                    if f.endswith('_.zip'):
                        pack_files.append(os.path.join(root, f))
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
                for f in files:
                    if f.endswith('_.zip'):
                        pack_files.append(os.path.join(root, f))
            assertEqual(1, len(pack_files))


async def test_given_project_in_pack16_format_when_create_non_multiple_of_16_resource_revisions_then_creates_individual_files() -> None:
    async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
        # Set project to major version 3 (Pack16 format)
        project._set_major_version_for_test(3)
        assertEqual(3, project.major_version)

        # Create 18 resources with bodies
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
