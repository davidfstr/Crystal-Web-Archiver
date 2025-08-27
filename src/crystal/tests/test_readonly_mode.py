from collections.abc import Iterator
from contextlib import contextmanager
from crystal.browser import MainWindow as RealMainWindow
from crystal.model import Project, Resource, RootResource
from crystal.tests.util.controls import TreeItem
from crystal.tests.util.hdiutil import hdiutil_disk_image_mounted
from crystal.tests.util.save_as import save_as_with_ui
from crystal.tests.util.server import MockHttpServer, served_project
from crystal.tests.util.skip import skipTest
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util.tasks import wait_for_download_to_start_and_finish
from crystal.tests.util.wait import wait_for, first_child_of_tree_item_is_not_loading_condition
from crystal.tests.util.windows import OpenOrCreateDialog
import crystal.tests.util.xtempfile as xtempfile
from crystal.util.xos import is_mac_os, is_windows
import os
import stat
import subprocess
from textwrap import dedent
from unittest import skip

# ------------------------------------------------------------------------------
# Test: Open Project as Readonly

async def test_project_opens_as_readonly_when_user_requests_it_in_ui() -> None:
    with xtempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
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
    
    with xtempfile.TemporaryDirectory() as working_dirpath:
        volume_src_dirpath = os.path.join(working_dirpath, 'Project')
        os.mkdir(volume_src_dirpath)
        
        # Create empty project
        project_dirpath = os.path.join(volume_src_dirpath, 'Project.crystalproj')
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, project):
            pass

        # Create disk image with the project on it. Mount it as read-only.
        with hdiutil_disk_image_mounted(srcfolder=volume_src_dirpath, readonly=True) as volume_dirpath:
            assert os.path.exists(volume_dirpath)
            mounted_project_dirpath = os.path.join(volume_dirpath, 'Project.crystalproj')
            async with (await OpenOrCreateDialog.wait_for()).open(mounted_project_dirpath) as (mw, _):
                assert True == mw.readonly


@awith_subtests
async def test_project_opens_as_readonly_when_project_directory_or_database_is_locked(subtests: SubtestsContext) -> None:
    with xtempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
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
# Test: Unsaved Resources

async def test_when_readonly_project_has_source_resource_linking_to_target_url_with_no_corresponding_resource_then_can_still_browse_link_children_of_source_resource_in_entity_tree() -> None:
    """
    Tests the fix for GitHub issue #219: Ensures that when browsing a readonly project,
    expanding a resource node shows all link children even when some links correspond
    to URLs that have no saved Resource in the database. Those missing resources should
    be created as unsaved resources (id=_UNSAVED_ID) to allow browsing.
    """
    # ...because target URL can be represented by an unsaved Resource (id=_UNSAVED_ID)
    
    server = MockHttpServer({
        '/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <head><title>Home Page</title></head>
                <body>
                    <h1>Home</h1>
                    <p>Welcome to our site!</p>
                    <a href="/about/">About Us</a>
                    <a href="/contact">Contact</a>
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        ),
        '/about/': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <head><title>About Page</title></head>
                <body>
                    <h1>About Us</h1>
                    <p>We are a great company!</p>
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        ),
        '/contact': dict(
            status_code=200,
            headers=[('Content-Type', 'text/html')],
            content=dedent(
                """
                <!DOCTYPE html>
                <html>
                <head><title>Contact Page</title></head>
                <body>
                    <h1>Contact Us</h1>
                    <p>Email: contact@example.com</p>
                </body>
                </html>
                """
            ).lstrip('\n').encode('utf-8')
        )
    })
    
    with server:
        home_url = server.get_url('/')
        about_url = server.get_url('/about/')
        contact_url = server.get_url('/contact')
        
        with xtempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            # Create a new project and populate it
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, project):
                # Create RootResource for the home page
                home_r = Resource(project, home_url)
                home_rr = RootResource(project, 'Home', home_r)
                
                # Download the home page to discover and create resources
                # for linked pages A and B
                if True:
                    root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                    (home_ti,) = root_ti.Children
                    
                    # Expand the tree node to download the home page and discover links
                    home_ti.Expand()
                    await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
                    
                    # Verify that resources for page A and B were created as children
                    about_ti = home_ti.find_child(about_url, project.default_url_prefix)
                    contact_ti = home_ti.find_child(contact_url, project.default_url_prefix)
                
                # Find and delete the Resource for page B (contact page)
                contact_resource = project.get_resource(contact_url)
                assert contact_resource is not None
                contact_resource.delete()
                
            # Reopen the project as read-only
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as (mw, project):
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                (home_ti,) = root_ti.Children
                
                # Ensure both page A and B still appear as children
                home_ti.Expand()
                await wait_for(first_child_of_tree_item_is_not_loading_condition(home_ti))
                about_ti = home_ti.find_child(about_url, project.default_url_prefix)
                contact_ti = home_ti.find_child(contact_url, project.default_url_prefix)
                
                # Ensure the Resource for page B is marked as unsaved
                contact_resource = project.get_resource(contact_url)
                assert contact_resource is not None
                assert contact_resource._id == Resource._UNSAVED_ID


async def test_when_readonly_project_is_saved_then_becomes_writable_and_all_unsaved_resources_are_saved() -> None:
    """
    Tests that when a readonly project with unsaved resources is saved via Save As,
    the project becomes writable and all unsaved resources are properly saved to
    the database with real IDs (no longer _UNSAVED_ID).
    """
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        home_url = sp.get_request_url('https://xkcd.com/')
        comic2_url = sp.get_request_url('https://xkcd.com/2/')
        
        with xtempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            # Create a small project with 1 resource, opened as writable
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, project):
                # Download the home page
                if True:
                    home_r = Resource(project, home_url)
                    home_rr = RootResource(project, 'Home', home_r)
                    
                    root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                    (home_ti,) = root_ti.Children
                    home_ti.Expand()
                    await wait_for_download_to_start_and_finish(mw.task_tree)
                
            # Reopen the project as read-only
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as (mw, project):
                rmw = RealMainWindow._last_created
                assert rmw is not None
                
                # Create a Resource for a URL that isn't linked from the home page.
                # This should create an unsaved resource because the project is readonly.
                comic2_r = Resource(project, comic2_url)
                assert comic2_r._id == Resource._UNSAVED_ID
                
                # Save a writable copy of the project using Save As
                with xtempfile.TemporaryDirectory(suffix='.crystalproj') as new_project_dirpath:
                    os.rmdir(new_project_dirpath)
                    
                    assert mw.readonly == True
                    await save_as_with_ui(rmw, new_project_dirpath)
                    assert mw.readonly == False
                    
                    # Ensure the previously unsaved resource is now saved
                    assert comic2_r._id != Resource._UNSAVED_ID
                    assert isinstance(comic2_r._id, int)
                    assert comic2_r._id > 0


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
