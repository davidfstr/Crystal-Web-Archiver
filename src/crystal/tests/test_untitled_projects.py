from collections.abc import Iterator
from contextlib import contextmanager
from crystal.model import Project, ProjectReadOnlyError, Resource, ResourceGroup, RootResource
from crystal.task import DownloadResourceGroupTask, DownloadResourceTask
from crystal.tests.util.server import served_project
from crystal.tests.util.subtests import SubtestsContext, awith_subtests
from crystal.tests.util.tasks import (
    append_deferred_top_level_tasks, scheduler_disabled, step_scheduler, step_scheduler_until_done
)
from crystal.tests.util.wait import wait_for_future
from crystal.util.xos import is_ci, is_mac_os, is_linux
from functools import cache
import os
import subprocess
import tempfile
from typing import Iterator
from unittest import SkipTest, skip


# TODO: Reorder the "===" sections in this file to be in a more logical order,
#       with similar sections grouped together.

# === Untitled Project: Clean/Dirty State Tests ===

async def test_when_untitled_project_created_then_is_clean() -> None:
    with _untitled_project() as project:
        assert False == project.is_dirty


async def test_when_root_resource_created_then_untitled_project_becomes_dirty() -> None:
    with _untitled_project() as project:
        assert False == project.is_dirty
        r = Resource(project, 'https://xkcd.com/')
        assert True == project.is_dirty
        RootResource(project, 'Home', r)
        assert True == project.is_dirty


async def test_when_resource_group_created_then_untitled_project_becomes_dirty() -> None:
    with _untitled_project() as project:
        assert False == project.is_dirty
        ResourceGroup(project, 'Comic', url_pattern='https://xkcd.com/#/')
        assert True == project.is_dirty


async def test_when_resource_revision_downloaded_then_untitled_project_becomes_dirty() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
    
        with _untitled_project() as project:
            assert False == project.is_dirty
            Resource(project, atom_feed_url)
            assert True == project.is_dirty


async def test_when_project_properties_changed_then_untitled_project_becomes_dirty() -> None:
    with _untitled_project() as project:
        assert False == project.is_dirty
        # Change a property
        project.html_parser_type = 'html_parser' if project.html_parser_type != 'html_parser' else 'lxml'
        assert True == project.is_dirty


# === Untitled Project: Save Tests ===

@awith_subtests
async def test_when_untitled_project_saved_then_becomes_clean_and_titled(subtests: SubtestsContext) -> None:
    with scheduler_disabled() as disabled_scheduler, \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        home_url = sp.get_request_url('https://xkcd.com/')
        comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        comic50_url = sp.get_request_url('https://xkcd.com/50/')
        
        assert 1 == disabled_scheduler.start_count
        assert 0 == disabled_scheduler.stop_count
        
        # Test saving an untitled project to a new location on the same filesystem
        with subtests.test(filesystem='same'), \
                _untitled_project() as project, \
                _temporary_directory() as new_container_dirpath:
            assert False == project.is_dirty
            assert True == project.is_untitled
            assert 2 == disabled_scheduler.start_count
            
            # Download a resource revision, so that we can test whether it is moved later
            r = Resource(project, atom_feed_url)
            rr_future = r.download()
            await step_scheduler_until_done(project)
            
            assert True == project.is_dirty
            assert True == project.is_untitled
            rr = rr_future.result()
            old_rr_body_filepath = rr._body_filepath  # capture
            assert os.path.exists(old_rr_body_filepath)
            
            # Save untitled project to somewhere on the same filesystem
            old_project_dirpath = project.path  # capture
            old_project_fs = os.stat(old_project_dirpath).st_dev  # capture
            new_project_dirpath = os.path.join(
                new_container_dirpath,
                os.path.basename(old_project_dirpath))
            new_project_fs = os.stat(new_container_dirpath).st_dev
            assert old_project_fs == new_project_fs, (
                'Expected old_project_dirpath and new_project_dirpath to be on the same filesystem: '
                f'{old_project_dirpath=}, {new_container_dirpath=}'
            )
            await wait_for_future(project.save_as(new_project_dirpath))
            
            assert False == project.is_dirty
            assert False == project.is_untitled
            assert 1 == disabled_scheduler.stop_count
            assert 3 == disabled_scheduler.start_count
            
            # Ensure project was moved to new location
            assert new_project_dirpath != old_project_dirpath
            assert os.path.exists(new_project_dirpath)
            assert not os.path.exists(old_project_dirpath)
            
            # Ensure resource revision was moved to new location
            new_rr_body_filepath = rr._body_filepath
            assert new_rr_body_filepath != old_rr_body_filepath, \
                'Resource revision filepath should have changed after saving untitled project'
            assert os.path.exists(new_rr_body_filepath)
            
            # Ensure can download a new resource revision after moving the project
            r = Resource(project, rss_feed_url)
            rr_future = r.download()
            await step_scheduler_until_done(project)
            
            # Ensure titled projects don't become dirty even when modified
            assert False == project.is_untitled
            assert False == project.is_dirty
        
        # Test saving an untitled project to a new location on a different filesystem
        with subtests.test(filesystem='different'), \
                _untitled_project() as project, \
                _temporary_directory_on_new_filesystem() as new_container_dirpath:
            # Download a resource revision, so that we can test whether it is moved later
            r = Resource(project, atom_feed_url)
            rr_future = r.download()
            await step_scheduler_until_done(project)
            
            rr = rr_future.result()
            old_rr_body_filepath = rr._body_filepath  # capture
            assert os.path.exists(old_rr_body_filepath)
            
            # Save untitled project to somewhere on a different filesystem
            old_project_dirpath = project.path  # capture
            old_project_fs = os.stat(old_project_dirpath).st_dev  # capture
            new_project_dirpath = os.path.join(
                new_container_dirpath,
                os.path.basename(old_project_dirpath))
            new_project_fs = os.stat(new_container_dirpath).st_dev
            assert old_project_fs != new_project_fs, (
                'Expected old_project_dirpath and new_project_dirpath to be on different filesystems. '
                f'{old_project_dirpath=}, {new_container_dirpath=}'
            )
            try:
                await wait_for_future(project.save_as(new_project_dirpath))
            except ProjectReadOnlyError as e:
                raise SkipTest(
                    'cannot create a temporary directory on a new filesystem '
                    'that is writable: ' + str(e)
                )
            
            # Ensure project was moved to new location
            assert new_project_dirpath != old_project_dirpath
            assert os.path.exists(new_project_dirpath)
            assert not os.path.exists(old_project_dirpath)
            
            # Ensure resource revision was moved to new location
            new_rr_body_filepath = rr._body_filepath
            assert new_rr_body_filepath != old_rr_body_filepath, \
                'Resource revision filepath should have changed after saving untitled project'
            assert os.path.exists(new_rr_body_filepath)
        
        # Test saving an untitled project while downloads are in progress
        with subtests.test(tasks_running=True), \
                _untitled_project() as project, \
                _temporary_directory() as new_container_dirpath:
            # Download a resource revision, so that comic URLs are discovered
            r = Resource(project, home_url)
            rr_future = r.download()
            await step_scheduler_until_done(project)
            
            # Start downloading a group and an individual resource
            g = ResourceGroup(project, 'Comic', comic_pattern)
            g.download()
            await step_scheduler(project)
            root_r = RootResource(project, '', Resource(project, comic50_url))
            root_r.download()
            await step_scheduler(project)
            (old_drg_task, old_dr_task) = project.root_task.children
            assert isinstance(old_drg_task, DownloadResourceGroupTask)
            assert isinstance(old_dr_task, DownloadResourceTask)
            
            # Save untitled project to somewhere else
            new_project_dirpath = os.path.join(
                new_container_dirpath,
                os.path.basename(old_project_dirpath))
            await wait_for_future(project.save_as(new_project_dirpath))
            append_deferred_top_level_tasks(project)
            
            # Ensure tasks are restored
            (new_drg_task, new_dr_task) = project.root_task.children
            assert isinstance(new_drg_task, DownloadResourceGroupTask)
            assert isinstance(new_dr_task, DownloadResourceTask)
            assert new_drg_task is not old_drg_task
            assert new_dr_task is not old_dr_task
            
            # Ensure tasks can still be stepped without error
            await step_scheduler(project)


@skip('not yet implemented')
async def test_when_dirty_untitled_project_closed_then_prompts_to_save_and_becomes_clean_and_titled() -> None:
    pass


@skip('not yet implemented')
async def test_when_clean_untitled_project_closed_then_does_not_prompt_to_save() -> None:
    pass


@skip('not yet implemented')
async def test_when_titled_project_modified_then_remains_clean() -> None:
    pass


@skip('not yet implemented')
async def test_when_titled_project_explicitly_saved_then_does_nothing() -> None:
    pass


# === Utility ===

@contextmanager
def _untitled_project() -> Iterator[Project]:
    """Creates an untitled project in a temporary directory."""
    with _temporary_directory() as container_dirpath:
        untitled_project_dirpath = os.path.join(container_dirpath, 'Untitled.crystalproj')
        with Project(untitled_project_dirpath, is_untitled=True) as project:
            yield project


def _temporary_directory():
    return tempfile.TemporaryDirectory(
        # NOTE: If a file inside the temporary directory is still open,
        #       ignore_cleanup_errors=True will prevent Windows from raising,
        #       at the cost of leaving the temporary directory around
        ignore_cleanup_errors=True
    )


@contextmanager
def _temporary_directory_on_new_filesystem() -> Iterator[str]:
    """
    Context that creates a temporary directory on a new filesystem† on enter and
    cleans it up on exit.
    
    † A new filesystem is defined as a directory that is not on the same
    filesystem as the operating system's temporary directory (e.g. /tmp).
    
    Raises:
    * SkipTest -- if cannot create a temporary directory on a new filesystem on this OS
    """
    if is_mac_os():
        with tempfile.TemporaryDirectory(prefix='tmpfs_', ignore_cleanup_errors=True) as tmp_root:
            image_path = os.path.join(tmp_root, 'volume.sparseimage')
            mount_point = os.path.join(tmp_root, 'mnt')
            os.makedirs(mount_point, exist_ok=True)

            # Create the sparse image
            subprocess.run([
                'hdiutil', 'create',
                '-size', '16m',
                '-fs', 'HFS+',
                '-type', 'SPARSE',
                '-volname', 'TemporaryFS',
                image_path
            ], check=True, stdout=subprocess.DEVNULL)

            # Attach (mount) it without showing in Finder
            subprocess.run([
                'hdiutil', 'attach',
                '-mountpoint', mount_point,
                '-nobrowse',
                image_path
            ], check=True, stdout=subprocess.DEVNULL)

            try:
                yield mount_point
            finally:
                # Detach the volume (force if necessary)
                try:
                    subprocess.run([
                        'hdiutil', 'detach',
                        mount_point,
                        '-force'
                    ], check=True, stdout=subprocess.DEVNULL)
                except subprocess.CalledProcessError:
                    pass
    elif is_linux() and is_ci():
        # NOTE: It is not possible to mount a disk image in GitHub Actions CI runners
        #       because the runner user does not have mount permissions.
        #       Therefore we cannot create a temporary directory on a new
        #       filesystem in this environment.
        raise SkipTest(
            'cannot create temp directory on a new filesystem '
            'in GitHub Actions CI runner'
        )
    else:
        assert os.stat('.').st_dev != _filesystem_of_temporary_directory(), (
            'Expected the current directory to be on a different filesystem '
            'than the system\'s temporary directory'
        )
        
        with tempfile.TemporaryDirectory(prefix='tmpdir_', dir='.', ignore_cleanup_errors=True) as tmp_dirpath:
            yield tmp_dirpath
        return


@cache
def _filesystem_of_temporary_directory() -> int:
    """
    Returns the filesystem ID of the system's temporary directory.
    """
    return os.stat(tempfile.gettempdir()).st_dev
