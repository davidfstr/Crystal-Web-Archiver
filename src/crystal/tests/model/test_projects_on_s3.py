"""
Tests whether can open and use projects on S3, currently only in a readonly fashion.

Especially exercises code in:
- Project.__init__
- ResourceRevision.{size, open}
- S3Filesystem
"""

from collections.abc import Iterator
from contextlib import contextmanager
from crystal.filesystem import FilesystemPath, LocalFilesystem, RENAME_SUFFIX
from crystal.browser import MainWindow as RealMainWindow
from crystal.model import Project, ProjectFormatError
from crystal.model.pack16 import open_pack_entry, rewrite_pack_without_entry
from crystal.model.project import MigrationType, NonLocalFilesystemNotSupported, NonLocalFilesystemReadOnlyError
from crystal.model.resource_revision import ResourceRevision
from crystal.tests.util.asserts import assertEqual, assertIn, assertRegex
from crystal.tests.util.cli import (
    crystal_running,
    drain,
    ReadUntilTimedOut,
    read_until,
)
from crystal.tests.util.fake_boto3 import install as install_fake_boto3
from crystal.tests.util.save_as import save_as_with_ui, save_as_without_ui
from crystal.tests.util.server import extracted_project
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util import xtempfile
from crystal.util.wx_dialog import mocked_show_modal
from crystal.util.xos import is_windows
from io import TextIOBase
import os
import re
import tempfile
import wx
from unittest import skip
from unittest.mock import patch
import urllib.request


# === Test: Happy Path Cases ===

def test_can_open_project_with_credentialless_s3_url_and_env_var_credentials_as_readonly_and_serve_a_resource_revision() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'
    
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:
        
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


def test_can_open_project_with_credentialful_s3_url_as_readonly_and_serve_a_resource_revision() -> None:
    s3_url = 's3://fake-access-key:fake-secret-key@test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'
    
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:

        # Intentionally do NOT set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY,
        # to verify that the credentials embedded in the s3:// URL are used.
        with _crystal_running_with_fake_s3(
                s3_url, fake_s3_root,
                extra_args=['--readonly'],
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


# === Test: Credential Problem Cases ===

# Usual case, to test: credentialless s3 url and no env var credentials
async def test_when_open_project_with_no_credentials_then_raises_PermissionError_with_instructions_to_fix() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

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


async def test_when_open_project_with_invalid_credentials_then_raises_PermissionError_with_informative_message() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

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


# === Test: URL Format Cases ===

async def test_given_s3_url_ending_with_crystalproj_slash_then_can_open_project_at_that_s3_url() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'
    
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:
        with _fake_s3(fake_s3_root), Project(s3_url, readonly=True):
            pass  # opened successfully


async def test_given_s3_url_ending_with_crystalproj_then_can_open_project_at_that_s3_url() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj?region=us-east-1'
    
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region='us-east-1',
                bucket='test-bucket',
                key_prefix='Archive/TestProject.crystalproj',
                ) as fake_s3_root:
        with _fake_s3(fake_s3_root), Project(s3_url, readonly=True):
            pass  # opened successfully


@skip('fails: not yet implemented')
async def test_given_s3_url_ending_with_crystalopen_then_can_open_project_at_that_s3_url() -> None:
    # TODO: Call _normalize_project_path here, after adapting it to
    #       use the Filesystem interface to manipulate paths
    pass


async def test_given_s3_url_not_pointing_to_a_project_when_open_project_then_raises_ProjectFormatError() -> None:
    s3_url = 's3://test-bucket/Archive/NotAProject/?region=us-east-1'

    with xtempfile.TemporaryDirectory() as fake_s3_root, \
            _fake_s3(fake_s3_root):
        try:
            with Project(s3_url, readonly=True):
                pass
        except ProjectFormatError:
            pass  # expected
        else:
            raise AssertionError('Expected ProjectFormatError but Project opened successfully')


# === Test: Writable vs Readonly Case ===

async def test_when_open_project_as_writable_given_s3_url_then_raises_NonLocalFilesystemReadOnlyError() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

    with xtempfile.TemporaryDirectory() as fake_s3_root, \
            _fake_s3(fake_s3_root):
        try:
            with Project(s3_url):  # readonly=False by default
                pass
        except NonLocalFilesystemReadOnlyError:
            pass  # expected
        else:
            raise AssertionError('Expected NonLocalFilesystemReadOnlyError but Project opened successfully')


# === Test: Security Cases ===

async def test_project_path_is_s3_url_with_credentials_removed_given_project_opened_with_credentialful_s3_url() -> None:
    s3_url = 's3://fake-access-key:fake-secret-key@test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'
    expected_path = 's3://test-bucket/Archive/TestProject.crystalproj?region=us-east-1'

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


# === Test: Database Management ===

async def test_when_close_project_given_project_opened_from_s3_url_then_deletes_local_copy_of_project_database() -> None:
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

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


# === Test: Read ===

@skip('covered by: test_can_read_resource_revision_given_project_opened_from_s3_url')
async def test_can_size_resource_revision_given_project_opened_from_s3_url() -> None:
    pass


@awith_subtests
async def test_can_read_resource_revision_given_project_opened_from_s3_url(subtests: SubtestsContext) -> None:
    XKCD_HOME_URL = 'https://xkcd.com/'
    s3_url = 's3://test-bucket/Archive/TestProject.crystalproj/?region=us-east-1'

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
        
        symlink_path = os.path.join(fake_s3_root, region, bucket, key_prefix)
        os.symlink(project_dirpath, symlink_path)
        
        yield fake_s3_root


@contextmanager
def _fake_s3(
        fake_s3_root: str,
        *,
        omit_env_var_credentials: bool = False,
        invalid_credentials: bool = False,
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
