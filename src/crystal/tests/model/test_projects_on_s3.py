"""
Tests whether can open and use projects on S3, currently only in a readonly fashion.

Especially exercises code in:
- Project.__init__
- ResourceRevision.{size, open}
- S3Filesystem
"""

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from crystal.browser import MainWindow as RealMainWindow
from crystal.browser.open_project_from_s3 import OpenProjectFromS3Dialog
from crystal.filesystem import FilesystemPath, LocalFilesystem, RENAME_SUFFIX, S3Filesystem
from crystal.model import Project, ProjectFormatError
from crystal.model.pack16 import open_pack_entry, rewrite_pack_without_entry
from crystal.model.project import MigrationType, NonLocalFilesystemNotSupported, NonLocalFilesystemReadOnlyError
from crystal.model.resource_revision import ResourceRevision
from crystal.progress.interface import CancelOpenProject, OpenProjectProgressListener
from crystal.server import get_request_url
from crystal.tests.util.asserts import assertEqual, assertIn, assertRegex
from crystal.tests.util.cli import (
    crystal_running,
    drain,
    ReadUntilTimedOut,
    read_until,
)
from crystal.tests.util.fake_boto3 import install as install_fake_boto3
from crystal.tests.util.fake_boto3.boto3 import HttpRequestToS3
from crystal.tests.util.mark import should_check_focused_windows
from crystal.tests.util.save_as import save_as_with_ui, save_as_without_ui
from crystal.tests.util.server import (
    assert_does_open_webbrowser_to,
    extracted_project,
    fetch_archive_url,
)
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util import xtempfile
from crystal.tests.util.wait import wait_for, wait_for_and_return
from crystal.tests.util.windows import MainWindow, OpenOrCreateDialog
from crystal.tests.util.wx_keyboard_actions import press_tab_in_window_to_navigate_focus
from crystal.util.controls import click_button, TreeItem
from crystal.util.wx_dialog import mocked_show_modal
from crystal.util.wx_window import SetFocus
from crystal.util.xos import is_windows
from io import TextIOBase
import os
import re
import subprocess
import tempfile
from typing import assert_never
import wx
from unittest import skip
from unittest.mock import patch
import urllib.request


# === Test: Happy Path Cases ===

@skip('covered by: test_given_open_project_from_s3_dialog_and_profile_credentials_is_selected_and_valid_credentials_provided_when_press_open_button_then_can_serve_a_resource_revision')
async def test_can_open_project_with_credentialless_s3_url_and_profile_credentials_as_readonly_and_serve_a_resource_revision() -> None:
    pass


@skip('covered by: test_given_open_project_from_s3_dialog_and_manual_credentials_is_selected_and_valid_credentials_provided_when_press_open_button_then_can_serve_a_resource_revision')
async def test_can_open_project_with_credentialless_s3_url_and_manual_credentials_as_readonly_and_serve_a_resource_revision() -> None:
    pass


@awith_subtests
async def test_can_open_project_with_credentialless_s3_url_and_env_var_credentials_as_readonly_and_serve_a_resource_revision(subtests: SubtestsContext) -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'
    
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:
        
        with subtests.test(layer='model'):
            with _crystal_running_with_fake_s3(
                    s3_url, fake_s3_root,
                    extra_args=['--readonly'],
                    ) as crystal:
                server_url = _wait_for_server_url(crystal)

                # Fetch the xkcd home page from the ProjectServer
                archive_url_path = '/_/https/xkcd.com/'
                request_url = f'{server_url}{archive_url_path}'
                with urllib.request.urlopen(request_url, timeout=10.0) as response:
                    assert response.status == 200
                    content = response.read().decode('utf-8')

                # Ensure it has the expected page title
                title_match = re.search(r'<title>([^<]*)</title>', content)
                assert title_match is not None, 'Page has no <title> tag'
                assertIn('xkcd', title_match.group(1))

                # Ensure it links to the expected comic image
                assertRegex(content, r'imgs\.xkcd\.com')
        
        with subtests.test(layer='ui'):
            # (UI does not support using env var credentials)
            pass


@awith_subtests
async def test_can_open_project_with_credentialful_s3_url_as_readonly_and_serve_a_resource_revision(subtests: SubtestsContext) -> None:
    s3_url = 's3://fake-access-key:fake-secret-key@test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:

        with subtests.test(layer='model'):
            with _crystal_running_with_fake_s3(
                    s3_url, fake_s3_root,
                    extra_args=['--readonly'],
                    # Verify credentials in s3:// URL are used
                    omit_env_var_credentials=True,
                    ) as crystal:
                server_url = _wait_for_server_url(crystal)

                # Fetch the xkcd home page from the ProjectServer
                archive_url_path = '/_/https/xkcd.com/'
                request_url = f'{server_url}{archive_url_path}'
                with urllib.request.urlopen(request_url, timeout=10.0) as response:
                    assert response.status == 200
                    content = response.read().decode('utf-8')

                # Ensure it has the expected page title
                title_match = re.search(r'<title>([^<]*)</title>', content)
                assert title_match is not None, 'Page has no <title> tag'
                assertIn('xkcd', title_match.group(1))

                # Ensure it links to the expected comic image
                assertRegex(content, r'imgs\.xkcd\.com')

        with subtests.test(layer='ui'):
            with _fake_s3(fake_s3_root, omit_env_var_credentials=True):
                def verify_credential_controls_disabled(dialog: OpenProjectFromS3Dialog) -> None:
                    # Verify credential controls are disabled (credentials detected in URL)
                    assert not dialog._use_profile_radio.Enabled
                    assert not dialog._use_manual_radio.Enabled

                (mw, project) = await _open_project_from_s3_in_ui(
                    s3_url,
                    fill_more_options=verify_credential_controls_disabled)
                await _ensure_can_serve_a_resource_revision(mw, project)


# === Test: Database Download Progress ===

async def test_given_project_on_s3_when_open_then_downloading_database_progress_is_reported() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root, \
            _fake_s3(fake_s3_root):
        progress_calls = []  # type: list[tuple[int, int, float]]

        class RecordingProgressListener(OpenProjectProgressListener):
            def downloading_database_progress(
                    self,
                    bytes_downloaded: int,
                    total_bytes: int,
                    bytes_per_second: float,
                    ) -> None:
                progress_calls.append((bytes_downloaded, total_bytes, bytes_per_second))

        with Project(s3_url, readonly=True, progress_listener=RecordingProgressListener()):
            pass

        assert len(progress_calls) >= 1, 'Expected at least one downloading_database_progress call'
        (final_bytes_downloaded, final_total_bytes, _) = progress_calls[-1]
        assert final_bytes_downloaded == final_total_bytes, (
            f'Expected final progress call to report 100% completion '
            f'({final_bytes_downloaded} != {final_total_bytes})')
        for (bytes_downloaded, total_bytes, _) in progress_calls:
            assert 0 <= bytes_downloaded <= total_bytes


async def test_given_project_on_s3_when_cancel_during_database_download_then_CancelOpenProject_is_raised() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root, \
            _fake_s3(fake_s3_root):

        class CancelOnFirstProgressListener(OpenProjectProgressListener):
            def downloading_database_progress(
                    self,
                    bytes_downloaded: int,
                    total_bytes: int,
                    bytes_per_second: float,
                    ) -> None:
                raise CancelOpenProject()

        try:
            with Project(s3_url, readonly=True, progress_listener=CancelOnFirstProgressListener()):
                pass
        except CancelOpenProject:
            pass  # Expected
        else:
            raise AssertionError('Expected CancelOpenProject to be raised but project opened successfully')


# === Test: Bucket Region Resolve Efficiency ===

# NOTE: Also covers the "correct region" case
@awith_subtests
async def test_given_s3_operation_when_region_incorrect_or_missing_then_first_operation_makes_4_http_requests_and_subsequent_operations_make_1(subtests: SubtestsContext) -> None:
    CORRECT_REGION = 'us-east-2'
    INCORRECT_REGION = 'us-east-1'
    BUCKET = 'test-bucket'
    KEY_PREFIX = 'Archive/TestProject.crystalproj'

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region=CORRECT_REGION,
                bucket=BUCKET,
                key_prefix=KEY_PREFIX,
                ) as fake_s3_root, \
            _fake_s3(fake_s3_root):
        
        # Operation 2 & 3, shared across following subtests
        def _operation_2_and_3(
                s3_url: str,
                fs: S3Filesystem,
                http_requests: list[HttpRequestToS3]) -> None:
            # Operation 2, with cached correct region
            # - Expect 1 HTTP request
            fs.getsize(s3_url)
            assertEqual([
                (CORRECT_REGION, 'HEAD', f's3://{BUCKET}/{KEY_PREFIX}/database.sqlite'),
            ], http_requests)
            http_requests[:] = []
            
            # Operation 3, with cached correct region
            # - Expect 1 HTTP request
            fs.getsize(s3_url)
            assertEqual([
                (CORRECT_REGION, 'HEAD', f's3://{BUCKET}/{KEY_PREFIX}/database.sqlite'),
            ], http_requests)
            http_requests[:] = []
        
        with subtests.test(case='correct_region'):
            s3_url = f's3://{BUCKET}/{KEY_PREFIX}/database.sqlite?region={CORRECT_REGION}'

            with _s3_http_requests_monitored(BUCKET, CORRECT_REGION) as http_requests:
                fs = S3Filesystem()

                # Operation 1, with correct region
                # - Expect 1 HTTP request
                fs.getsize(s3_url)
                assertEqual([
                    (CORRECT_REGION, 'HEAD', f's3://{BUCKET}/{KEY_PREFIX}/database.sqlite'),
                ], http_requests)
                http_requests[:] = []
                
                _operation_2_and_3(s3_url, fs, http_requests)
        
        with subtests.test(case='missing_region'):
            DEFAULT_REGION = 'us-east-1'  # parse_s3_url() defaults to us-east-1 when no region in URL
            s3_url = f's3://{BUCKET}/{KEY_PREFIX}/database.sqlite'

            with _s3_http_requests_monitored(BUCKET, CORRECT_REGION) as http_requests:
                fs = S3Filesystem()

                # Operation 1, with missing (defaulted) region
                # - Expect 4 HTTP requests for the region-discovery pattern
                fs.getsize(s3_url)
                assertEqual([
                    (DEFAULT_REGION, 'HEAD', f's3://{BUCKET}/{KEY_PREFIX}/database.sqlite'),
                    (DEFAULT_REGION, 'HEAD', f's3://{BUCKET}/'),
                    (CORRECT_REGION, 'HEAD', f's3://{BUCKET}/'),
                    (CORRECT_REGION, 'HEAD', f's3://{BUCKET}/{KEY_PREFIX}/database.sqlite'),
                ], http_requests)
                http_requests[:] = []
                
                _operation_2_and_3(s3_url, fs, http_requests)

        with subtests.test(case='incorrect_region'):
            s3_url = f's3://{BUCKET}/{KEY_PREFIX}/database.sqlite?region={INCORRECT_REGION}'

            with _s3_http_requests_monitored(BUCKET, CORRECT_REGION) as http_requests:
                fs = S3Filesystem()

                # Operation 1, with incorrect region
                # - Expect 4 HTTP requests for the region-discovery pattern
                fs.getsize(s3_url)
                assertEqual([
                    (INCORRECT_REGION, 'HEAD', f's3://{BUCKET}/{KEY_PREFIX}/database.sqlite'),
                    (INCORRECT_REGION, 'HEAD', f's3://{BUCKET}/'),
                    (CORRECT_REGION, 'HEAD', f's3://{BUCKET}/'),
                    (CORRECT_REGION, 'HEAD', f's3://{BUCKET}/{KEY_PREFIX}/database.sqlite'),
                ], http_requests)
                http_requests[:] = []
                
                _operation_2_and_3(s3_url, fs, http_requests)


@skip('covered by: test_given_s3_operation_when_region_incorrect_or_missing_then_first_operation_makes_4_http_requests_and_subsequent_operations_make_1: Operations 2+')
async def test_given_missing_or_incorrect_bucket_region_when_non_first_s3_operation_on_bucket_then_makes_1_http_request_with_correct_region() -> None:
    pass


@skip('covered by: test_given_s3_operation_when_region_incorrect_or_missing_then_first_operation_makes_4_http_requests_and_subsequent_operations_make_1: case="correct_region"')
async def test_given_correct_bucket_region_when_operation_on_bucket_then_makes_1_http_request() -> None:
    pass


@contextmanager
def _s3_http_requests_monitored(bucket: str, correct_region: str) -> Iterator[list[HttpRequestToS3]]:
    from crystal.tests.util.fake_boto3.boto3 import _FakeS3Client

    _FakeS3Client.CORRECT_REGION_FOR_BUCKET = {bucket: correct_region}
    _FakeS3Client.http_requests = []
    try:
        yield _FakeS3Client.http_requests
    finally:
        _FakeS3Client.CORRECT_REGION_FOR_BUCKET = {}
        _FakeS3Client.http_requests[:] = []


# === Test: Credential Problem Cases ===

@awith_subtests
async def test_when_open_project_with_no_credentials_then_raises_PermissionError_with_instructions_to_fix(subtests: SubtestsContext) -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with subtests.test(layer='model'):
        # Credentialless s3 url with no env var credentials, a common case
        with xtempfile.TemporaryDirectory() as fake_s3_root, \
                _fake_s3(fake_s3_root, omit_env_var_credentials=True):
            try:
                with Project(s3_url, readonly=True):
                    pass
            except PermissionError as e:
                error_message = str(e)
            else:
                raise AssertionError('Expected PermissionError but Project opened successfully')

        # Ensure instructions mention AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY environment variables
        assertIn('AWS_ACCESS_KEY_ID', error_message)
        assertIn('AWS_SECRET_ACCESS_KEY', error_message)
        
        # Ensure instructions mention "aws configure" and the "default" profile
        assertIn('aws configure', error_message)
        assertIn('"default"', error_message)
        
        # Ensure instructions mention "aws configure --profile CUSTOM" and a CUSTOM profile
        assertIn('aws configure --profile', error_message)
        
        # Ensure instructions mention path to credentials file set by "aws configure"
        # Windows uses %USERPROFILE%\.aws\credentials, POSIX uses ~/.aws/credentials
        if is_windows():
            assertIn(r'.aws\credentials', error_message)
        else:
            assertIn('.aws/credentials', error_message)
        
        # Ensure instructions mention credentials in an s3:// URL
        assertIn('s3://', error_message)
    
    with subtests.test(layer='ui'):
        # Selects "Enter credentials manually" radio button
        # but enter no credentials before pressing "Open" button
        with xtempfile.TemporaryDirectory() as fake_s3_root, \
                _fake_s3(fake_s3_root, omit_env_var_credentials=True):
            captured_message = await _open_project_from_s3_in_ui_expecting_error(
                s3_url,
                error_dialog_name='cr-access-denied',
                # credentials=None: leave empty (don't fill in access key or secret)
                fill_more_options=lambda d: (
                    # No profiles available -> manual credentials is pre-selected
                    assertEqual(True, d._use_manual_radio.Value)))

        # Ensure shows appropriate informative error dialog
        assertIn('AWS_ACCESS_KEY_ID', captured_message)
        assertIn('AWS_SECRET_ACCESS_KEY', captured_message)
        assertIn('aws configure', captured_message)
        assertIn('"default"', captured_message)
        if is_windows():
            assertIn(r'.aws\credentials', captured_message)
        else:
            assertIn('.aws/credentials', captured_message)
        assertIn('s3://', captured_message)


@awith_subtests
async def test_when_open_project_with_invalid_credentials_then_raises_PermissionError_with_informative_message(subtests: SubtestsContext) -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with subtests.test(layer='model'):
        with xtempfile.TemporaryDirectory() as fake_s3_root, \
                _fake_s3(fake_s3_root, invalid_credentials=True):
            try:
                with Project(s3_url, readonly=True):
                    pass
            except PermissionError as e:
                error_message = str(e)
            else:
                raise AssertionError('Expected PermissionError but Project opened successfully')

        assertIn('InvalidClientTokenId', error_message)
    
    with subtests.test(layer='ui'):
        with xtempfile.TemporaryDirectory() as fake_s3_root, \
                _fake_s3(fake_s3_root, omit_env_var_credentials=True, invalid_credentials=True):
            captured_message = await _open_project_from_s3_in_ui_expecting_error(
                s3_url,
                error_dialog_name='cr-access-denied',
                credentials=S3Filesystem.Credentials('invalid-access-key', 'invalid-secret-key'),
                fill_more_options=lambda d: (
                    # No profiles available -> manual credentials is pre-selected
                    assertEqual(True, d._use_manual_radio.Value)))

        # Ensure shows appropriate informative error dialog
        assertIn('InvalidClientTokenId', captured_message)


# === Test: URL Format Cases ===

@awith_subtests
async def test_given_s3_url_ending_with_crystalproj_slash_then_can_open_project_at_that_s3_url(subtests: SubtestsContext) -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:

        with subtests.test(layer='model'):
            with _fake_s3(fake_s3_root), Project(s3_url, readonly=True):
                pass  # opened successfully

        with subtests.test(layer='ui'):
            with _fake_s3(fake_s3_root, omit_env_var_credentials=True):
                (mw, _) = await _open_project_from_s3_in_ui(
                    s3_url,
                    credentials=S3Filesystem.Credentials('fake-access-key', 'fake-secret-key'),
                    fill_more_options=lambda d: (
                        # No profiles available -> manual credentials is pre-selected
                        assertEqual(True, d._use_manual_radio.Value)))
                await mw.close()


@awith_subtests
async def test_given_s3_url_ending_with_crystalproj_then_can_open_project_at_that_s3_url(subtests: SubtestsContext) -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj?region=us-east-1'

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:

        with subtests.test(layer='model'):
            with _fake_s3(fake_s3_root), Project(s3_url, readonly=True):
                pass  # opened successfully

        with subtests.test(layer='ui'):
            with _fake_s3(fake_s3_root, omit_env_var_credentials=True):
                (mw, _) = await _open_project_from_s3_in_ui(
                    s3_url,
                    credentials=S3Filesystem.Credentials('fake-access-key', 'fake-secret-key'),
                    fill_more_options=lambda d: (
                        # No profiles available -> manual credentials is pre-selected
                        assertEqual(True, d._use_manual_radio.Value)))
                await mw.close()


@awith_subtests
async def test_given_s3_url_ending_with_crystalopen_then_can_open_project_at_that_s3_url(subtests: SubtestsContext) -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/OPEN ME.crystalopen?region=us-east-1'

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:

        with subtests.test(layer='model'):
            with _fake_s3(fake_s3_root), Project(s3_url, readonly=True):
                pass  # opened successfully

        with subtests.test(layer='ui'):
            with _fake_s3(fake_s3_root, omit_env_var_credentials=True):
                (mw, _) = await _open_project_from_s3_in_ui(
                    s3_url,
                    credentials=S3Filesystem.Credentials('fake-access-key', 'fake-secret-key'),
                    fill_more_options=lambda d: (
                        # No profiles available -> manual credentials is pre-selected
                        assertEqual(True, d._use_manual_radio.Value)))
                await mw.close()


@awith_subtests
async def test_given_s3_url_not_pointing_to_a_project_when_open_project_then_raises_ProjectFormatError(subtests: SubtestsContext) -> None:
    s3_url = 's3://test-bucket/Archive/NotAProject/?region=us-east-1'

    with subtests.test(layer='model'):
        with xtempfile.TemporaryDirectory() as fake_s3_root, \
                _fake_s3(fake_s3_root):
            try:
                with Project(s3_url, readonly=True):
                    pass
            except ProjectFormatError:
                pass  # expected
            else:
                raise AssertionError('Expected ProjectFormatError but Project opened successfully')

    with subtests.test(layer='ui'):
        with xtempfile.TemporaryDirectory() as fake_s3_root, \
                _fake_s3(fake_s3_root, omit_env_var_credentials=True):
            captured_message = await _open_project_from_s3_in_ui_expecting_error(
                s3_url,
                error_dialog_name='cr-invalid-project',
                credentials=S3Filesystem.Credentials('fake-access-key', 'fake-secret-key'),
                fill_more_options=lambda d: (
                    # No profiles available -> manual credentials is pre-selected
                    assertEqual(True, d._use_manual_radio.Value)))

        # Ensure shows appropriate informative error dialog
        assertEqual(
            'The selected file or directory is not a valid project.',
            captured_message)


# === Test: Writable vs Readonly Case ===

@awith_subtests
async def test_when_open_project_as_writable_given_s3_url_then_raises_NonLocalFilesystemReadOnlyError(subtests: SubtestsContext) -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with subtests.test(layer='model'):
        with xtempfile.TemporaryDirectory() as fake_s3_root, \
                _fake_s3(fake_s3_root):
            try:
                with Project(s3_url):  # readonly=False by default
                    pass
            except NonLocalFilesystemReadOnlyError:
                pass  # expected
            else:
                raise AssertionError('Expected NonLocalFilesystemReadOnlyError but Project opened successfully')

    with subtests.test(layer='ui'):
        # (No way to attempt to open project from S3 as writable from the UI)
        pass


# === Test: Security Cases ===

@awith_subtests
async def test_project_path_is_s3_url_with_credentials_removed_given_project_opened_with_credentialful_s3_url(subtests: SubtestsContext) -> None:
    s3_url = 's3://fake-access-key:fake-secret-key@test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'
    expected_path = 's3://test-bucket/Archive/TestProject.crystalproj?region=us-east-1'

    with subtests.test(layer='model'):
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
                _fake_s3_root(
                    project_dirpath,
                    region='us-east-1',
                    bucket='test-bucket',
                    key_prefix='Archive/TestProject.crystalproj',
                    ) as fake_s3_root:
            with _fake_s3(fake_s3_root, omit_env_var_credentials=True), \
                    Project(s3_url, readonly=True) as project:
                assert project.path == expected_path

    with subtests.test(layer='ui'):
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
                _fake_s3_root(
                    project_dirpath,
                    region='us-east-1',
                    bucket='test-bucket',
                    key_prefix='Archive/TestProject.crystalproj',
                    ) as fake_s3_root:
            with _fake_s3(fake_s3_root, omit_env_var_credentials=True):
                (mw, project) = await _open_project_from_s3_in_ui(s3_url)
                try:
                    assert project.path == expected_path
                finally:
                    await mw.close()


# === Test: Database Management ===

@awith_subtests
async def test_when_close_project_given_project_opened_from_s3_url_then_deletes_local_copy_of_project_database(subtests: SubtestsContext) -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with subtests.test(layer='model'):
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
                _fake_s3_root(
                    project_dirpath,
                    region='us-east-1',
                    bucket='test-bucket',
                    key_prefix='Archive/TestProject.crystalproj',
                    ) as fake_s3_root:

            captured_db_paths = []  # type: list[str]
            original_ntf = tempfile.NamedTemporaryFile
            def capture_db_path(*args, **kwargs):
                f = original_ntf(*args, **kwargs)
                captured_db_paths.append(f.name)
                return f

            with _fake_s3(fake_s3_root), \
                    patch('crystal.model.project.tempfile.NamedTemporaryFile',
                          side_effect=capture_db_path):
                with Project(s3_url, readonly=True):
                    (local_db_path,) = captured_db_paths
                    assert os.path.exists(local_db_path), \
                        f'Expected local DB copy to exist while project is open: {local_db_path}'

            assert not os.path.exists(local_db_path), \
                f'Expected local DB copy to be deleted after project closed: {local_db_path}'

    with subtests.test(layer='ui'):
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
                _fake_s3_root(
                    project_dirpath,
                    region='us-east-1',
                    bucket='test-bucket',
                    key_prefix='Archive/TestProject.crystalproj',
                    ) as fake_s3_root:

            captured_db_paths = []
            original_ntf = tempfile.NamedTemporaryFile
            def capture_db_path(*args, **kwargs):
                f = original_ntf(*args, **kwargs)
                captured_db_paths.append(f.name)
                return f

            with _fake_s3(fake_s3_root, omit_env_var_credentials=True), \
                    patch('crystal.model.project.tempfile.NamedTemporaryFile',
                          side_effect=capture_db_path):
                (mw, _) = await _open_project_from_s3_in_ui(
                    s3_url,
                    credentials=S3Filesystem.Credentials('fake-access-key', 'fake-secret-key'))
                try:
                    (local_db_path,) = captured_db_paths
                    assert os.path.exists(local_db_path), \
                        f'Expected local DB copy to exist while project is open: {local_db_path}'
                finally:
                    await mw.close()

            assert not os.path.exists(local_db_path), \
                f'Expected local DB copy to be deleted after project closed: {local_db_path}'


# === Test: Read ===

@skip('covered by: test_can_read_resource_revision_given_project_opened_from_s3_url')
async def test_can_size_resource_revision_given_project_opened_from_s3_url() -> None:
    pass


@awith_subtests
async def test_can_read_resource_revision_given_project_opened_from_s3_url(subtests: SubtestsContext) -> None:
    XKCD_HOME_URL = 'https://xkcd.com/'
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'
    s3_url_with_creds = 's3://fake-access-key:fake-secret-key@test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    def _open_and_read_home_revision(project: Project) -> tuple[str, int]:
        home_r = project.get_resource(XKCD_HOME_URL)
        assert home_r is not None, f'Resource {XKCD_HOME_URL} not found'
        home_rr = home_r.default_revision()
        assert home_rr is not None, f'No revision for {XKCD_HOME_URL}'
        assert home_rr.has_body
        with home_rr.open(readonly=True) as f:
            content = f.read().decode('utf-8')
        size = home_rr.size()
        return (content, size)

    def _assert_matches_xkcd_home_content(content: str, size: int) -> None:
        assertIn('xkcd', content)
        assertRegex(content, r'imgs\.xkcd\.com')
        assertEqual(len(content.encode('utf-8')), size)

    with subtests.test(layer='model'):
        # Case: major_version=1 (Flat)
        with subtests.test(major_version=1):
            with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
                    _fake_s3_root(
                        project_dirpath,
                        region='us-east-1',
                        bucket='test-bucket',
                        key_prefix='Archive/TestProject.crystalproj',
                        ) as fake_s3_root:
                with _fake_s3(fake_s3_root), \
                        Project(s3_url, readonly=True) as project:
                    assertEqual(1, project.major_version)
                    (content, size) = _open_and_read_home_revision(project)
                    _assert_matches_xkcd_home_content(content, size)

        # Case: major_version=2 (Hierarchical)
        with subtests.test(major_version=2):
            with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
                # Upgrade v1 -> v2 by opening writable
                with Project(project_dirpath) as project:
                    assertEqual(2, project.major_version)

                with _fake_s3_root(
                        project_dirpath,
                        region='us-east-1',
                        bucket='test-bucket',
                        key_prefix='Archive/TestProject.crystalproj',
                        ) as fake_s3_root:
                    with _fake_s3(fake_s3_root), \
                            Project(s3_url, readonly=True) as project:
                        assertEqual(2, project.major_version)
                        (content, size) = _open_and_read_home_revision(project)
                        _assert_matches_xkcd_home_content(content, size)

        # Case: major_version=3 (Pack16)
        if True:
            # Case: Pack16 where revision is inside pack file (at pack_filepath)
            with subtests.test(major_version=3, case='revision inside pack file'):
                with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
                    _upgrade_project_to_v3(project_dirpath)

                    with _fake_s3_root(
                            project_dirpath,
                            region='us-east-1',
                            bucket='test-bucket',
                            key_prefix='Archive/TestProject.crystalproj',
                            ) as fake_s3_root:
                        with _fake_s3(fake_s3_root), \
                                Project(s3_url, readonly=True) as project:
                            assertEqual(3, project.major_version)
                            # Home page is revision ID 1, inside pack 00f_.zip
                            (content, size) = _open_and_read_home_revision(project)
                            _assert_matches_xkcd_home_content(content, size)

            # Case: Pack16 where revision is inside unrepaired pack file (at movedaside_pack_filepath)
            with subtests.test(major_version=3, case='revision inside unrepaired pack file'):
                with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
                    _upgrade_project_to_v3(project_dirpath)

                    # Move pack file to .replacing to simulate unrepaired state
                    pack_filepath = _pack_filepath_for_revision(project_dirpath, revision_id=1)
                    replacing_filepath = pack_filepath + RENAME_SUFFIX
                    os.rename(pack_filepath, replacing_filepath)
                    assert not os.path.exists(pack_filepath)
                    assert os.path.exists(replacing_filepath)

                    with _fake_s3_root(
                            project_dirpath,
                            region='us-east-1',
                            bucket='test-bucket',
                            key_prefix='Archive/TestProject.crystalproj',
                            ) as fake_s3_root:
                        with _fake_s3(fake_s3_root), \
                                Project(s3_url, readonly=True) as project:
                            assertEqual(3, project.major_version)
                            (content, size) = _open_and_read_home_revision(project)
                            _assert_matches_xkcd_home_content(content, size)

            # Case: Pack16 where revision is individual file
            with subtests.test(major_version=3, case='revision as individual file'):
                with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
                    _upgrade_project_to_v3(project_dirpath)

                    # Extract revision from pack to individual file, then remove from pack
                    _extract_revision_from_pack_to_individual_file(
                        project_dirpath, revision_id=1)

                    with _fake_s3_root(
                            project_dirpath,
                            region='us-east-1',
                            bucket='test-bucket',
                            key_prefix='Archive/TestProject.crystalproj',
                            ) as fake_s3_root:
                        with _fake_s3(fake_s3_root), \
                                Project(s3_url, readonly=True) as project:
                            assertEqual(3, project.major_version)
                            (content, size) = _open_and_read_home_revision(project)
                            _assert_matches_xkcd_home_content(content, size)

    # NOTE: Only check the major_version=1 case.
    #       Sufficient coverage for other cases exists in layer='model' above.
    with subtests.test(layer='ui', major_version=1):
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
                _fake_s3_root(
                    project_dirpath,
                    region='us-east-1',
                    bucket='test-bucket',
                    key_prefix='Archive/TestProject.crystalproj',
                    ) as fake_s3_root:
            with _fake_s3(fake_s3_root, omit_env_var_credentials=True):
                (mw, project) = await _open_project_from_s3_in_ui(s3_url_with_creds)
                try:
                    assertEqual(1, project.major_version)
                    (content, size) = _open_and_read_home_revision(project)
                    _assert_matches_xkcd_home_content(content, size)
                finally:
                    await mw.close()


# === Test: UI: Open Project from S3 Dialog ===

@awith_subtests
async def test_can_open_s3_dialog_from_file_menu(subtests: SubtestsContext) -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'
    credentials = S3Filesystem.Credentials('fake-access-key', 'fake-secret-key')

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:

        with subtests.test(when='before_project_opened'):
            # Trigger from minimal menubar (no project open yet)
            with _fake_s3(fake_s3_root, omit_env_var_credentials=True):
                (mw, _) = await _open_project_from_s3_in_ui(
                    s3_url, credentials=credentials)
                await mw.close()

        with subtests.test(when='after_project_opened'):
            # Trigger from regular menubar (project already open in MainWindow)
            with _fake_s3(fake_s3_root, omit_env_var_credentials=True):
                (mw1, _) = await _open_project_from_s3_in_ui(
                    s3_url, credentials=credentials)

                async def start_open_from_main_window() -> None:
                    # Open S3 dialog from regular menubar, then wait for the current
                    # MainWindow to be disposed before waiting for the next
                    # MainWindow to appear, via MainWindow.wait_for()
                    await mw1.start_open_project_from_s3_with_menuitem()
                    await mw1.wait_for_dispose()

                (mw2, _) = await _open_project_from_s3_in_ui(
                    s3_url, credentials=credentials,
                    start_open_func=start_open_from_main_window)
                await mw2.close()


async def test_given_open_project_from_s3_dialog_and_url_is_valid_when_blur_url_field_then_open_button_is_enabled() -> None:
    with xtempfile.TemporaryDirectory() as fake_s3_root, \
            _fake_s3(fake_s3_root):
        dialog = OpenProjectFromS3Dialog(None)
        try:
            # Set URL to valid s3:// URL
            dialog._url_field.Value = 's3://test-bucket/Archive/Test.crystalproj/'

            # Simulate URL field blur
            dialog._validate_url_and_update_controls()

            # Verify Open button is enabled
            assert dialog._open_button.Enabled

            # Verify no URL error is shown
            assert not dialog._url_error_label.IsShown()
        finally:
            dialog.Destroy()


async def test_given_open_project_from_s3_dialog_and_url_is_invalid_when_blur_url_field_then_inline_error_is_shown_and_open_button_is_disabled() -> None:
    with xtempfile.TemporaryDirectory() as fake_s3_root, \
            _fake_s3(fake_s3_root):
        dialog = OpenProjectFromS3Dialog(None)
        try:
            # Set URL to invalid (not an s3:// URL)
            dialog._url_field.Value = 'http://not-an-s3-url.com/foo'

            # Simulate URL field blur
            dialog._validate_url_and_update_controls()

            # Verify inline error is shown
            assert dialog._url_error_label.IsShown()
            assertIn('Not a valid S3 URL', dialog._url_error_label.Label)

            # Verify Open button is disabled
            assert not dialog._open_button.Enabled
        finally:
            dialog.Destroy()


async def test_given_open_project_from_s3_dialog_and_url_contains_embedded_credentials_when_blur_url_field_then_credential_fields_are_disabled() -> None:
    s3_url_with_creds = 's3://fake-key:fake-secret@test-bucket/Archive/Test.crystalproj/'
    check_focused = should_check_focused_windows()

    with xtempfile.TemporaryDirectory() as fake_s3_root, \
            _fake_s3(fake_s3_root, omit_env_var_credentials=True):
        dialog = OpenProjectFromS3Dialog(None)
        try:
            initial_height = dialog.Size.Height  # capture
            
            # Set URL with embedded credentials
            dialog._url_field.Value = s3_url_with_creds

            if check_focused:
                # Simulate Tab navigation away from URL field,
                # which triggers _on_url_blur -> _validate_url_and_update_controls.
                # This exercises the tricky interaction where:
                # 1. URL blur disables credential controls (including radio buttons)
                # 2. Focus moves to _use_profile_radio (now disabled)
                # 3. _on_radio_focused_while_disabled navigates past disabled radios
                dialog.Show()
                SetFocus(dialog._url_field)
                press_tab_in_window_to_navigate_focus(dialog)
            else:
                # Directly trigger what blur would trigger
                dialog._validate_url_and_update_controls()

            # Verify credential controls are disabled (credentials come from URL)
            assert not dialog._use_profile_radio.Enabled
            assert not dialog._use_manual_radio.Enabled
            assert not dialog._access_key_id_field.Enabled
            assert not dialog._secret_access_key_field.Enabled
            assert not dialog._profile_choice.Enabled

            # Verify "Credentials provided in URL" label is shown
            assert dialog._embedded_creds_label.IsShown()

            # Verify dialog height resized to accommodate the label
            assert dialog.Size.Height > initial_height, \
                f'Expected dialog height to increase after showing embedded creds label'

            # Verify Open button is enabled (URL is valid)
            assert dialog._open_button.Enabled

            if check_focused:
                # Verify focus landed on an enabled control
                # (not trapped on a disabled radio button)
                focused = dialog.FindFocus()
                assert focused is not None
                assert focused.Enabled, \
                    f'Focus landed on disabled control: {focused.Name}'
                assert not isinstance(focused, wx.RadioButton), \
                    f'Focus should not be trapped on a radio button: {focused.Name}'
        finally:
            dialog.Destroy()


async def test_given_open_project_from_s3_dialog_and_no_aws_profiles_exist_then_profile_option_is_disabled_and_manual_credentials_is_selected() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:
        with _fake_s3(fake_s3_root, profiles=[]):
            def verify_no_profiles(dialog: OpenProjectFromS3Dialog) -> None:
                # Profile radio is disabled (no profiles available)
                assert not dialog._use_profile_radio.Enabled
                
                # Manual credentials radio is selected
                assert dialog._use_manual_radio.Value
                
                # Profile dropdown is disabled
                assert not dialog._profile_choice.Enabled

            (mw, _) = await _open_project_from_s3_in_ui(
                s3_url,
                credentials=S3Filesystem.Credentials('fake-access-key', 'fake-secret-key'),
                fill_more_options=verify_no_profiles)
            await mw.close()


async def test_given_open_project_from_s3_dialog_and_default_aws_profile_exists_then_profile_option_is_enabled_and_dropdown_contains_all_aws_profiles_and_default_aws_profile_is_preselected_and_profile_credentials_is_selected() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:
        with _fake_s3(fake_s3_root, profiles=['default', 'staging', 'production']):
            def verify_default_profile(dialog: OpenProjectFromS3Dialog) -> None:
                # Profile radio is enabled and selected
                assert dialog._use_profile_radio.Enabled
                assert dialog._use_profile_radio.Value
                
                # Dropdown contains all profiles
                profile_items = [dialog._profile_choice.GetString(i)
                    for i in range(dialog._profile_choice.Count)]
                assertEqual(['default', 'staging', 'production'], profile_items)
                
                # "default" profile is preselected
                assertEqual('default', dialog._profile_choice.GetStringSelection())

            (mw, _) = await _open_project_from_s3_in_ui(
                s3_url,
                credentials=S3Filesystem.ProfileCredentials('default'),
                fill_more_options=verify_default_profile)
            await mw.close()


async def test_given_open_project_from_s3_dialog_and_aws_profile_exists_but_default_profile_does_not_exist_then_profile_option_is_enabled_and_dropdown_contains_all_aws_profiles_and_first_aws_profile_is_preselected_and_profile_credentials_is_selected() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:
        with _fake_s3(fake_s3_root, profiles=['staging', 'production']):
            def verify_first_profile(dialog: OpenProjectFromS3Dialog) -> None:
                # Profile radio is enabled and selected
                assert dialog._use_profile_radio.Enabled
                assert dialog._use_profile_radio.Value
                
                # Dropdown contains all profiles
                profile_items = [dialog._profile_choice.GetString(i)
                    for i in range(dialog._profile_choice.Count)]
                assertEqual(['staging', 'production'], profile_items)
                
                # First profile is preselected (no "default" exists)
                assertEqual('staging', dialog._profile_choice.GetStringSelection())

            (mw, _) = await _open_project_from_s3_in_ui(
                s3_url,
                credentials=S3Filesystem.ProfileCredentials('staging'),
                fill_more_options=verify_first_profile)
            await mw.close()


async def test_given_open_project_from_s3_dialog_and_profile_credentials_is_selected_and_valid_credentials_provided_when_press_open_button_then_can_serve_a_resource_revision() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:
        with _fake_s3(fake_s3_root, profiles=['default', 'other']):
            def verify_profile_radio_preselected(dialog: OpenProjectFromS3Dialog) -> None:
                # Verify profile radio is pre-selected (because profiles exist)
                assert dialog._use_profile_radio.Value
                assert dialog._profile_choice.GetStringSelection() == 'default'

            (mw, project) = await _open_project_from_s3_in_ui(
                s3_url,
                credentials=S3Filesystem.ProfileCredentials('default'),
                fill_more_options=verify_profile_radio_preselected)
            await _ensure_can_serve_a_resource_revision(mw, project)


@skip('covered by: test_when_open_project_with_no_credentials_then_raises_PermissionError_with_instructions_to_fix')
async def test_given_open_project_from_s3_dialog_and_manual_credentials_is_selected_and_no_credentials_provided_when_press_open_button_then_shows_permission_error_dialog() -> None:
    pass


async def test_given_open_project_from_s3_dialog_and_manual_credentials_is_selected_and_incomplete_credentials_provided_when_press_open_button_then_shows_error_dialog() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with xtempfile.TemporaryDirectory() as fake_s3_root, \
            _fake_s3(fake_s3_root, omit_env_var_credentials=True):
        captured_message = None  # type: str | None

        def show_modal_func(dialog: wx.Dialog) -> int:
            nonlocal captured_message
            if dialog.Name == 'cr-open-project-from-s3-dialog':
                assert isinstance(dialog, OpenProjectFromS3Dialog)

                dialog._url_field.Value = s3_url
                dialog._validate_url_and_update_controls()

                # Fill only Access Key ID (no Secret Access Key) — incomplete
                dialog._access_key_id_field.Value = 'fake-access-key'

                # Verify manual credentials radio is pre-selected (no profiles exist)
                assert dialog._use_manual_radio.Value

                # _validate_inputs() will detect incomplete creds
                # and show an error dialog (intercepted below)
                result = dialog._validate_inputs()
                assert result is None  # validation failed

                return wx.ID_CANCEL
            elif dialog.Name == 'cr-open-project-from-s3-dialog__incomplete-creds-error':
                assert isinstance(dialog, wx.MessageDialog)
                captured_message = dialog.Message
                return wx.ID_OK
            else:
                raise AssertionError(f'Unexpected dialog: {dialog.Name!r}')

        with patch('crystal.util.wx_dialog.ShowModal', show_modal_func), \
                patch('crystal.browser.open_project_from_s3.ShowModal', show_modal_func):
            ocd = await OpenOrCreateDialog.wait_for()
            await ocd.start_open_project_from_s3_with_menuitem()
            await wait_for(lambda: captured_message is not None)

        assert captured_message is not None
        assertEqual(
            'Please enter both Access Key ID and Secret Access Key, '
            'or leave both empty to use default AWS credentials.',
            captured_message)


@skip('covered by: test_when_open_project_with_invalid_credentials_then_raises_PermissionError_with_informative_message')
async def test_given_open_project_from_s3_dialog_and_manual_credentials_is_selected_and_invalid_credentials_provided_when_press_open_button_then_shows_permission_error_dialog() -> None:
    pass


async def test_given_open_project_from_s3_dialog_and_manual_credentials_is_selected_and_valid_credentials_provided_when_press_open_button_then_can_serve_a_resource_revision() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:
        with _fake_s3(fake_s3_root, omit_env_var_credentials=True):
            (mw, project) = await _open_project_from_s3_in_ui(
                s3_url,
                credentials=S3Filesystem.Credentials('fake-access-key', 'fake-secret-key'),
                fill_more_options=lambda d: (
                    # Verify manual radio is pre-selected (because no profiles exist)
                    assertEqual(True, d._use_manual_radio.Value)))
            await _ensure_can_serve_a_resource_revision(mw, project)


# === Test: UI: Main Window ===

async def test_main_window_title_does_not_show_file_extension_given_project_opened_from_s3_url() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:
        with _fake_s3(fake_s3_root):
            project = Project(s3_url, readonly=True)
            with RealMainWindow(project) as rmw:
                # RealMainWindow takes ownership of project and will close it
                title = rmw._frame.GetTitle()

    assert '.crystalproj' not in title, \
        f'Expected title to not show .crystalproj extension, but got: {title!r}'


# === Test: UI: Save As ===

# TODO: Add support for non-local filesystems to Save As
@awith_subtests
async def test_when_save_as_given_project_opened_from_s3_url_then_raises_NonLocalFilesystemNotSupported(subtests: SubtestsContext) -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with subtests.test(layer='model'):
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
                _fake_s3_root(
                    project_dirpath,
                    region='us-east-1',
                    bucket='test-bucket',
                    key_prefix='Archive/TestProject.crystalproj',
                    ) as fake_s3_root:
            with _fake_s3(fake_s3_root), \
                    Project(s3_url, readonly=True) as project, \
                    xtempfile.TemporaryDirectory() as tmp_dir:
                save_path = os.path.join(tmp_dir, 'SavedProject.crystalproj')
                try:
                    await save_as_without_ui(project, save_path)
                except NonLocalFilesystemNotSupported:
                    pass  # expected
                else:
                    raise AssertionError('Expected NonLocalFilesystemNotSupported from save_as()')

    with subtests.test(layer='ui'):
        with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
                _fake_s3_root(
                    project_dirpath,
                    region='us-east-1',
                    bucket='test-bucket',
                    key_prefix='Archive/TestProject.crystalproj',
                    ) as fake_s3_root:
            with _fake_s3(fake_s3_root), \
                    xtempfile.TemporaryDirectory() as tmp_dir:
                project = Project(s3_url, readonly=True)
                with RealMainWindow(project) as rmw:
                    save_path = os.path.join(tmp_dir, 'SavedProject.crystalproj')
                    
                    captured_message = None  # type: str | None
                    def capture_message_and_dismiss(dialog: wx.Dialog) -> int:
                        nonlocal captured_message
                        if dialog.Name == 'cr-save-error-dialog':
                            captured_message = dialog.Message
                        return wx.ID_OK
                    
                    with patch('crystal.browser.ShowModal',
                            mocked_show_modal('cr-save-error-dialog', capture_message_and_dismiss),
                            ) as mock_show_modal:
                        await save_as_with_ui(rmw, save_path)
                    assert mock_show_modal.call_count == 1, \
                        f'Expected save error dialog to appear exactly once, got {mock_show_modal.call_count}'
                    assertEqual(
                        'Error saving project: Save As does not support non-local filesystems yet',
                        captured_message)


# === Utility: Project Setup ===

def _upgrade_project_to_v3(project_dirpath: str) -> None:
    """Opens a v1 project, upgrades to v2, then to v3."""
    # Upgrade v1 -> v2
    with Project(project_dirpath) as project:
        assertEqual(2, project.major_version)
        project._queue_migration_after_reopen(
            MigrationType.HIERARCHICAL_TO_PACK16)
    # Run v2 -> v3 migration
    with Project(project_dirpath) as project:
        assertEqual(3, project.major_version)


def _pack_filepath_for_revision(project_dirpath: str, *, revision_id: int) -> str:
    """Returns the local filesystem path to the pack file containing a revision."""
    lfs = LocalFilesystem()
    fs_path = FilesystemPath(lfs, project_dirpath)
    return ResourceRevision._body_pack_filepath_with(fs_path, revision_id)


def _extract_revision_from_pack_to_individual_file(
        project_dirpath: str, *, revision_id: int) -> None:
    """
    Extracts a revision's body from its pack file to an individual file,
    then rewrites the pack without that entry.
    """
    lfs = LocalFilesystem()
    fs_path = FilesystemPath(lfs, project_dirpath)
    pack_filepath = ResourceRevision._body_pack_filepath_with(fs_path, revision_id)
    entry_name = ResourceRevision._entry_name_for_revision_id(revision_id)

    # Read entry bytes from the pack
    with open_pack_entry(pack_filepath, entry_name, lfs=lfs) as f:
        body_bytes = f.read()

    # Write to individual file path
    individual_filepath = ResourceRevision._body_filepath_with(fs_path, 3, revision_id)
    with open(individual_filepath, 'wb') as f:
        f.write(body_bytes)

    # Remove from pack
    tmp_dirpath = os.path.join(project_dirpath, 'tmp')
    rewrite_pack_without_entry(
        pack_filepath, entry_name, tmp_dirpath, lfs=lfs)


# === Utility: Fake S3: General ===

@contextmanager
def _fake_s3_root(project_dirpath: str, *, region: str, bucket: str, key_prefix: str) -> Iterator[str]:
    """
    Create a fake S3 root directory that maps region/bucket/key_prefix
    to the given project_dirpath via a symlink.

    Returns the fake S3 root path.
    """
    with xtempfile.TemporaryDirectory() as tmpdir:
        fake_s3_root = os.path.join(tmpdir, 'fake_s3_root')
        
        target_parent = os.path.join(fake_s3_root, region, bucket, os.path.dirname(key_prefix))
        os.makedirs(target_parent, exist_ok=True)
        
        symlink_path = os.path.normpath(os.path.join(fake_s3_root, region, bucket, key_prefix))
        try:
            os.symlink(project_dirpath, symlink_path)
        except OSError as e:
            if is_windows() and getattr(e, 'winerror', None) == 1314:
                # Fallback to a directory junction on Windows when the symlink
                # privilege (SeCreateSymbolicLinkPrivilege) is not held.
                # Junctions don't require any special privileges.
                subprocess.check_call(
                    ['cmd', '/c', 'mklink', '/J', symlink_path, project_dirpath],
                    stdout=subprocess.DEVNULL,
                )
            else:
                raise
        
        yield fake_s3_root


@contextmanager
def _fake_s3(
        fake_s3_root: str,
        *,
        omit_env_var_credentials: bool = False,
        invalid_credentials: bool = False,
        profiles: list[str] | None = None,
        ) -> Iterator[None]:
    """
    Context in which a fake S3 backend replaces "boto3" and "botocore".
    """
    env_add = {'CRYSTAL_FAKE_S3_ROOT': fake_s3_root}
    if not omit_env_var_credentials:
        env_add['AWS_ACCESS_KEY_ID'] = 'fake-access-key'
        env_add['AWS_SECRET_ACCESS_KEY'] = 'fake-secret-key'
    if invalid_credentials:
        env_add['CRYSTAL_FAKE_S3_INVALID_CREDENTIALS'] = '1'
    if profiles is not None:
        env_add['CRYSTAL_FAKE_S3_PROFILES'] = ','.join(profiles)
    env_remove = (
        ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY']
        if omit_env_var_credentials
        else []
    )

    # Save state
    saved_env = {k: os.environ.get(k) for k in list(env_add) + env_remove}

    os.environ.update(env_add)
    for k in env_remove:
        os.environ.pop(k, None)
    uninstall_fake_boto3 = install_fake_boto3()
    try:
        yield
    finally:
        uninstall_fake_boto3()
        for (k, old_v) in saved_env.items():
            if old_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_v


# === Utility: Fake S3: CLI ===

def _crystal_running_with_fake_s3(
        s3_url: str,
        fake_s3_root: str,
        *, extra_args: list[str] | None = None,
        env_extra: dict[str, str] | None = None,
        omit_env_var_credentials: bool = False,
        ):
    """
    Context which starts Crystal in --headless --serve mode
    using a fake S3 backend and returns (crystal_process, server_url).

    Arguments:
    * omit_env_var_credentials --
        if True, AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are not set,
        so credentials must come from the s3:// URL itself.
    """
    if extra_args is None:
        extra_args = []
    if env_extra is None:
        env_extra = {}

    base_env = {
        'CRYSTAL_FAKE_S3_ROOT': fake_s3_root,
    }
    if not omit_env_var_credentials:
        base_env['AWS_ACCESS_KEY_ID'] = 'fake-access-key'
        base_env['AWS_SECRET_ACCESS_KEY'] = 'fake-secret-key'

    return crystal_running(
        args=['--headless', '--serve', *extra_args, s3_url],
        env_extra={**base_env, **env_extra},
    )


def _wait_for_server_url(crystal) -> str:
    """
    Read Crystal's stdout until the "Server started at: ..." line appears
    and return the server URL.
    """
    assert isinstance(crystal.stdout, TextIOBase)

    banner = ''
    MAX_LINES = 15
    for _ in range(MAX_LINES):
        try:
            (line, _) = read_until(
                crystal.stdout,
                '\n',
                timeout=10.0,
                _drain_diagnostic=False,
            )
        except ReadUntilTimedOut:
            raise AssertionError(
                f'Never saw "Server started at:" in Crystal output. '
                f'Read so far: {banner!r} '
                f'Trailing output: {drain(crystal.stdout)!r}'
            )
        banner += line

        if 'Traceback ' in line:
            raise AssertionError(
                f'Crystal raised exception:\n\n{banner}{drain(crystal.stdout)}'
            )

        url_match = re.search(r'Server started at: (http://[\d.:]+)', banner)
        if url_match is not None:
            return url_match.group(1)

    raise AssertionError(
        f'Never saw "Server started at:" in first {MAX_LINES} lines. '
        f'Read so far: {banner!r}'
    )


# === Utility: Fake S3: UI ===

async def _open_project_from_s3_in_ui(
        s3_url: str,
        credentials: 'S3Filesystem.Credentials | S3Filesystem.ProfileCredentials | None' = None,
        fill_more_options: 'Callable[[OpenProjectFromS3Dialog], None] | None' = None,
        start_open_func: 'Callable[[], Awaitable[None]] | None' = None,
        ) -> 'tuple[MainWindow, Project]':
    """
    Opens a project from S3 via the UI dialog, returning (mw, project).

    Arguments:
    * s3_url -- the S3 URL to open (may include embedded credentials)
    * credentials -- optional credentials to fill into the dialog:
        - Credentials: fills in manual access key + secret access key fields
        - ProfileCredentials: selects the profile radio and chooses the named profile
        - None: leaves credential fields untouched (use when creds are embedded in URL)
    * fill_more_options -- optional callback to make extra assertions or interactions
        on the dialog after the URL and credentials are filled
    * start_open_func -- optional async function to open the S3 dialog.
        If None (default), waits for OpenOrCreateDialog and clicks its S3 menu item.
        If provided, calls start_open_func() instead (e.g. to open from a MainWindow).
    """
    def fill_and_accept_s3_dialog(dialog: wx.Dialog) -> int:
        assert isinstance(dialog, OpenProjectFromS3Dialog)

        dialog._url_field.Value = s3_url
        dialog._validate_url_and_update_controls()

        if isinstance(credentials, S3Filesystem.Credentials):
            dialog._access_key_id_field.Value = credentials.access_key_id
            dialog._secret_access_key_field.Value = credentials.secret_access_key
        elif isinstance(credentials, S3Filesystem.ProfileCredentials):
            dialog._use_profile_radio.Value = True
            dialog._profile_choice.SetStringSelection(credentials.profile_name)
        elif credentials is None:
            pass
        else:
            assert_never(credentials)

        if fill_more_options is not None:
            fill_more_options(dialog)

        result = dialog._validate_inputs()
        assert result is not None
        (dialog.plain_s3_url, dialog.credentials) = result

        return wx.ID_OK

    from crystal.main import _get_last_window
    old_main_last_window = _get_last_window()  # capture
    
    with patch('crystal.util.wx_dialog.ShowModal',
            mocked_show_modal('cr-open-project-from-s3-dialog', fill_and_accept_s3_dialog)):
        if start_open_func is not None:
            await start_open_func()
        else:
            ocd = await OpenOrCreateDialog.wait_for()
            await ocd.start_open_project_from_s3_with_menuitem()
        mw = await MainWindow.wait_for()
    
    # Wait for relaunch() to assign main.py's last_window
    await wait_for(lambda: _get_last_window() is not old_main_last_window)
    
    project = await wait_for_and_return(lambda: Project._last_opened_project)
    assert project.readonly
    return (mw, project)


async def _open_project_from_s3_in_ui_expecting_error(
        s3_url: str,
        error_dialog_name: str,
        credentials: 'S3Filesystem.Credentials | S3Filesystem.ProfileCredentials | None' = None,
        fill_more_options: 'Callable[[OpenProjectFromS3Dialog], None] | None' = None,
        ) -> str:
    """
    Opens a project from S3 via the UI dialog, expecting an error dialog.
    Returns the error dialog's message string.

    Arguments:
    * s3_url -- the S3 URL to open (may include embedded credentials)
    * error_dialog_name -- the Name of the expected error dialog
        (e.g. 'cr-access-denied', 'cr-invalid-project')
    * credentials -- optional credentials to fill into the dialog:
        - Credentials: fills in manual access key + secret access key fields
        - ProfileCredentials: selects the profile radio and chooses the named profile
        - None: leaves credential fields untouched (use when creds are embedded in URL)
    * fill_more_options -- optional callback to make extra assertions or interactions
        on the dialog after the URL and credentials are filled
    """
    captured_message = None  # type: str | None

    def show_modal_func(dialog: wx.Dialog) -> int:
        nonlocal captured_message
        if dialog.Name == 'cr-open-project-from-s3-dialog':
            assert isinstance(dialog, OpenProjectFromS3Dialog)

            dialog._url_field.Value = s3_url
            dialog._validate_url_and_update_controls()

            if isinstance(credentials, S3Filesystem.Credentials):
                dialog._access_key_id_field.Value = credentials.access_key_id
                dialog._secret_access_key_field.Value = credentials.secret_access_key
            elif isinstance(credentials, S3Filesystem.ProfileCredentials):
                dialog._use_profile_radio.Value = True
                dialog._profile_choice.SetStringSelection(credentials.profile_name)
            elif credentials is None:
                pass
            else:
                assert_never(credentials)

            if fill_more_options is not None:
                fill_more_options(dialog)

            result = dialog._validate_inputs()
            assert result is not None
            (dialog.plain_s3_url, dialog.credentials) = result

            return wx.ID_OK
        elif dialog.Name == error_dialog_name:
            assert isinstance(dialog, wx.MessageDialog)
            captured_message = dialog.Message
            return wx.ID_OK
        else:
            raise AssertionError(f'Unexpected dialog: {dialog.Name!r}')

    with patch('crystal.util.wx_dialog.ShowModal', show_modal_func):
        ocd = await OpenOrCreateDialog.wait_for()
        await ocd.start_open_project_from_s3_with_menuitem()
        await wait_for(lambda: captured_message is not None)

    assert captured_message is not None
    return captured_message


# === Utility: Happy Path Tests ===

async def _ensure_can_serve_a_resource_revision(mw: MainWindow, project: Project) -> None:
    """
    Verifies that the given xkcd project opened in mw can serve the home page.

    Selects the Home page root resource, clicks View, and asserts that an HTTP
    request to the started ProjectServer returns the expected HTML contents.

    Closes mw when done (or if an assertion fails).
    """
    try:
        # Select the Home page root resource in the entity tree
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        home_ti = root_ti.GetFirstChild()
        assert home_ti is not None
        home_ti.SelectItem()

        # Click View to start the ProjectServer and open a browser
        home_url = 'https://xkcd.com/'
        with assert_does_open_webbrowser_to(lambda: get_request_url(
                home_url,
                project_default_url_prefix=project.default_url_prefix)):
            click_button(mw.view_button)

        # Fetch the xkcd home page from the ProjectServer
        home_page = await fetch_archive_url(home_url)
        assert home_page.status == 200

        # Ensure it has the expected page title
        assertRegex(home_page.content, r'<title>[^<]*xkcd[^<]*</title>')

        # Ensure it links to the expected comic image
        assertRegex(home_page.content, r'imgs\.xkcd\.com')
    finally:
        await mw.close()
