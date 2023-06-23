from contextlib import contextmanager
from crystal.model import Project
from crystal.tests.util.subtests import SubtestsContext, awith_subtests
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.tests.util.xos import skip_if_not_linux
from crystal.util.xos import is_mac_os, is_windows
import os
import shutil
import stat
import subprocess
import tempfile
from typing import Iterator
from unittest import skip


# ------------------------------------------------------------------------------
# Tests

async def test_project_opens_as_readonly_when_user_requests_it_in_ui() -> None:
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        # Create empty project
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
            pass
        
        # Ensure project opens as writable by default
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as mw:
            assert False == mw.readonly
        
        # Ensure project opens as readonly when requested
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as mw:
            assert True == mw.readonly


@skip('not yet automated')
async def test_project_opens_as_readonly_when_user_requests_it_in_cli() -> None:
    pass


@skip_if_not_linux
async def test_project_opens_as_readonly_when_project_is_on_readonly_filesystem() -> None:
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        # Create empty project
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
            pass
        
        with tempfile.NamedTemporaryFile() as disk_image_file:
            # Create empty disk image
            subprocess.run([
                'dd',
                'if=/dev/zero',
                f'of={disk_image_file.name}',
                'bs=1024', 'count=1024',  # 1 MiB
            ], check=True)
            subprocess.run([
                'mke2fs',
                disk_image_file.name
            ], check=True)
            
            with tempfile.TemporaryDirectory() as mountpoint_dirpath:
                # 1. Mount disk image and copy empty project to it
                # 2. Try to open project on it. Ensure it is opened as writable.
                project_filename = os.path.basename(project_dirpath)
                mounted_project_dirpath = os.path.join(mountpoint_dirpath, project_filename)
                subprocess.run([
                    'mount',
                    '-o', 'loop',
                    disk_image_file.name,
                    mountpoint_dirpath,
                ], check=True)
                try:
                    shutil.copytree(project_dirpath, mounted_project_dirpath)
                    
                    async with (await OpenOrCreateDialog.wait_for()).open(mounted_project_dirpath) as mw:
                        assert False == mw.readonly
                finally:
                    subprocess.run([
                        'umount',
                        mountpoint_dirpath,
                    ], check=True)
                
                # 1. Remount disk image as read-only
                # 2. Try to open project on it. Ensure it is opened as read-only.
                subprocess.run([
                    'mount',
                    '-o', 'loop,ro',
                    disk_image_file.name,
                    mountpoint_dirpath,
                ], check=True)
                try:
                    async with (await OpenOrCreateDialog.wait_for()).open(mounted_project_dirpath) as mw:
                        assert True == mw.readonly
                finally:
                    subprocess.run([
                        'umount',
                        mountpoint_dirpath,
                    ], check=True)


@awith_subtests
async def test_project_opens_as_readonly_when_project_directory_or_database_is_locked(subtests: SubtestsContext) -> None:
    with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        # Create empty project
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
            pass
        
        # Ensure project opens as writable by default, when no files are locked
        with subtests.test(locked='nothing'):
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as mw:
                assert False == mw.readonly
        
        # Ensure project opens as readonly when project directory is locked
        if is_windows():
            # Can't lock directory on Windows
            pass
        else:
            with subtests.test(locked='project_directory'):
                with _file_set_to_readonly(project_dirpath):
                    async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as mw:
                        assert True == mw.readonly
        
        # Ensure project opens as readonly when project database is locked
        with subtests.test(locked='project_database'):
            with _file_set_to_readonly(os.path.join(project_dirpath, Project._DB_FILENAME)):
                async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as mw:
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
        flags = os.stat(filepath).st_flags
        if readonly:
            os.chflags(filepath, flags | stat.UF_IMMUTABLE)
        else:
            os.chflags(filepath, flags & ~stat.UF_IMMUTABLE)
    else:
        # Set the "Read Only" attribute on Windows,
        # or set the presence of "owner writer" permissions on Linux
        mode = os.stat(filepath).st_mode
        if readonly:
            os.chmod(filepath, mode & ~stat.S_IWRITE)
        else:
            os.chmod(filepath, mode | stat.S_IWRITE)


# ------------------------------------------------------------------------------
