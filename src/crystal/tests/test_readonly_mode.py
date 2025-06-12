from collections.abc import Iterator
from contextlib import contextmanager
from crystal.model import Project
from crystal.tests.util.skip import skipTest
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.xos import is_mac_os, is_windows
import os
import stat
import subprocess
import tempfile
from unittest import skip

# ------------------------------------------------------------------------------
# Tests

async def test_project_opens_as_readonly_when_user_requests_it_in_ui() -> None:
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        # Create empty project
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
            pass
        
        # Ensure project opens as writable by default
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
            assert False == mw.readonly
        
        # Ensure project opens as readonly when requested
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as (mw, project):
            assert True == mw.readonly


@skip('not yet automated')
async def test_project_opens_as_readonly_when_user_requests_it_in_cli() -> None:
    pass


async def test_project_opens_as_readonly_when_project_is_on_readonly_filesystem() -> None:
    if not is_mac_os():
        skipTest('only supported on macOS')
    
    with tempfile.TemporaryDirectory() as working_dirpath:
        volume_src_dirpath = os.path.join(working_dirpath, 'Project')
        os.mkdir(volume_src_dirpath)
        
        # Create empty project
        project_dirpath = os.path.join(volume_src_dirpath, 'Project.crystalproj')
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
            pass
        
        # Create disk image with project on it
        dmg_filepath = os.path.join(working_dirpath, 'Project.dmg')
        subprocess.run([
            'hdiutil',
            'create',
            '-srcfolder', volume_src_dirpath,
            dmg_filepath,
        ], check=True, stdout=subprocess.DEVNULL)
        
        # Mount disk image as readonly
        subprocess.run([
            'hdiutil',
            'attach',
            dmg_filepath,
            '-readonly',
        ], check=True, stdout=subprocess.DEVNULL)
        volume_dirpath = '/Volumes/Project'
        assert os.path.exists(volume_dirpath)
        try:
            mounted_project_dirpath = os.path.join(volume_dirpath, 'Project.crystalproj')
            async with (await OpenOrCreateDialog.wait_for()).open(mounted_project_dirpath) as (mw, project):
                assert True == mw.readonly
        finally:
            subprocess.run([
                'umount',
                volume_dirpath,
            ], check=True)


@awith_subtests
async def test_project_opens_as_readonly_when_project_directory_or_database_is_locked(subtests: SubtestsContext) -> None:
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        # Create empty project
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
            pass
        
        # Ensure project opens as writable by default, when no files are locked
        with subtests.test(locked='nothing'):
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                assert False == mw.readonly
        
        # Ensure project opens as readonly when project directory is locked
        if is_windows():
            # Can't lock directory on Windows
            pass
        else:
            with subtests.test(locked='project_directory'):
                with _file_set_to_readonly(project_dirpath):
                    async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                        assert True == mw.readonly
        
        # Ensure project opens as readonly when project database is locked
        with subtests.test(locked='project_database'):
            with _file_set_to_readonly(os.path.join(project_dirpath, Project._DB_FILENAME)):
                async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):
                    assert True == mw.readonly


# ------------------------------------------------------------------------------
# Utility

@contextmanager
def _file_set_to_readonly(filepath: str) -> Iterator[None]:
    _set_file_readonly(filepath, True)
    try:
        yield
    finally:
        _set_file_readonly(filepath, False)


def _set_file_readonly(filepath: str, readonly: bool) -> None:
    if is_mac_os():
        # Set the "Locked" attribute
        flags = os.stat(filepath).st_flags  # type: ignore[attr-defined]  # available on macOS
        if readonly:
            os.chflags(filepath, flags | stat.UF_IMMUTABLE)  # type: ignore[attr-defined]  # available on macOS
        else:
            os.chflags(filepath, flags & ~stat.UF_IMMUTABLE)  # type: ignore[attr-defined]  # available on macOS
    else:
        # Set the "Read Only" attribute on Windows,
        # or set the presence of "owner writer" permissions on Linux
        mode = os.stat(filepath).st_mode
        if readonly:
            os.chmod(filepath, mode & ~stat.S_IWRITE)
        else:
            os.chmod(filepath, mode | stat.S_IWRITE)


# ------------------------------------------------------------------------------
