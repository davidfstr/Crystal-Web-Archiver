from collections.abc import Iterator
from contextlib import contextmanager
from crystal.browser import MainWindow as RealMainWindow
from crystal.model import Project, Resource, RootResource
# TODO: Extract shared utilities to own module
from crystal.tests.test_untitled_projects import (
    _temporary_directory_on_new_filesystem,
    _untitled_project,
)
from crystal.tests.util.asserts import assertEqual, assertIn, assertNotEqual
from crystal.tests.util.clipboard import FakeClipboard
from crystal.tests.util.controls import TreeItem, click_button
from crystal.tests.util.hdiutil import hdiutil_disk_image_mounted
from crystal.tests.util.save_as import save_as_with_ui
from crystal.tests.util.server import MockHttpServer, served_project, extracted_project
from crystal.tests.util.skip import skipTest
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util.tasks import scheduler_disabled, step_scheduler_until_done, wait_for_download_to_start_and_finish
from crystal.tests.util.wait import tree_has_no_children_condition, wait_for, first_child_of_tree_item_is_not_loading_condition
from crystal.tests.util.windows import MainWindow, MenuitemDisabledError, OpenOrCreateDialog, NewGroupDialog, NewRootUrlDialog, PreferencesDialog
from crystal.util.db import DatabaseCursor
from crystal.util.wx_dialog import mocked_show_modal
import crystal.tests.util.xtempfile as xtempfile
from crystal.util.xos import is_mac_os, is_windows
import os
import sqlite3
import stat
from textwrap import dedent
from unittest import skip
from unittest.mock import patch
import wx

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
                
                # Ensure all downloads have completed
                await wait_for(tree_has_no_children_condition(mw.task_tree))
                
                # Find and delete the Resource for page B (contact page)
                contact_resource = project.get_resource(contact_url)
                assert contact_resource is not None
                contact_resource.delete()
                
            # Reopen the project as read-only
            async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as (mw, project):
                assert project.readonly
                
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
                assertEqual(Resource._UNSAVED_ID, contact_resource._id)


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
# Test: Disabled Dialogs

async def test_given_readonly_project_then_edit_button_titled_get_info_and_when_clicked_opens_readonly_dialog() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        comic_pattern = 'https://xkcd.com/#/'
        
        # Open project as readonly
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as (mw, project):
            assert mw.readonly == True
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            
            # Test with RootResource
            if True:
                home_ti = root_ti.GetFirstChild()
                assert home_ti is not None
                home_ti.SelectItem()
                
                assert mw.edit_button.Enabled
                assertEqual('Get Info', mw.edit_button_label_type)
                
                # Click edit button to open dialog. Verify dialog is in readonly mode.
                click_button(mw.edit_button)
                if True:
                    nrud = await NewRootUrlDialog.wait_for()
                    
                    assertEqual('Root URL', nrud._dialog.Title)
                    
                    # Verify fields are disabled
                    assert not nrud.url_field.Enabled
                    assert not nrud.name_field.Enabled
                    
                    # Verify Advanced Options fields are disabled
                    assert not nrud.set_as_default_domain_checkbox.Enabled
                    assert not nrud.set_as_default_directory_checkbox.Enabled
                    
                    # Verify only Cancel button is present
                    assert nrud.cancel_button is not None
                    assert nrud.ok_button is None
                    
                    await nrud.cancel()
            
            # Test with ResourceGroup
            if True:
                comic_ti = root_ti.find_child(comic_pattern)
                comic_ti.SelectItem()
                
                assert mw.edit_button.Enabled
                assertEqual('Get Info', mw.edit_button_label_type)
                
                # Click edit button to open dialog. Verify dialog is in readonly mode.
                click_button(mw.edit_button)
                ngd = await NewGroupDialog.wait_for()
                if True:
                    assertEqual('Group', ngd._dialog.Title)
                    
                    # Verify fields are disabled
                    assert not ngd.pattern_field.Enabled
                    assert not ngd.source_field.Enabled
                    assert not ngd.name_field.Enabled
                    assert ngd.download_immediately_checkbox is None
                    
                    # Verify Advanced Options fields are disabled
                    assert not ngd.do_not_download_checkbox.Enabled
                    
                    # Verify only Cancel button is present
                    assert ngd.cancel_button is not None
                    assert ngd.ok_button is None
                    
                    await ngd.cancel()


async def test_given_readonly_project_and_get_info_button_pressed_then_copy_button_is_visible_and_works() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        comic_pattern = 'https://xkcd.com/#/'
        
        # Open project as readonly
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as (mw, project):
            assert mw.readonly == True
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            
            # Test: RootResource
            if True:
                home_url = 'https://xkcd.com/'
                home_ti = root_ti.find_child(home_url)
                home_ti.SelectItem()
                
                # Click Get Info button to open dialog
                click_button(mw.edit_button)
                nrud = await NewRootUrlDialog.wait_for()
                try:
                    with FakeClipboard() as clipboard:
                        original_label = nrud.copy_button.Label
                        click_button(nrud.copy_button)
                        assert nrud.copy_button.Label in [original_label, '✓'], \
                            "Copy button should respond to click"
                        assertEqual(home_url, clipboard.text)
                finally:
                    await nrud.cancel()
            
            # Test: ResourceGroup
            if True:
                comic_ti = root_ti.find_child(comic_pattern)
                comic_ti.SelectItem()
                
                # Click Get Info button to open dialog
                click_button(mw.edit_button)
                ngd = await NewGroupDialog.wait_for()
                try:
                    with FakeClipboard() as clipboard:
                        original_label = ngd.copy_button.Label
                        click_button(ngd.copy_button)
                        assert ngd.copy_button.Label in [original_label, '✓'], \
                            "Copy button should respond to click"
                        assertEqual(comic_pattern, clipboard.text)
                finally:
                    await ngd.cancel()


async def test_given_readonly_project_then_preferences_dialog_project_fields_are_disabled() -> None:
    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath:
        # Open project as readonly
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as (mw, project):
            assert mw.readonly == True
            
            # Open Preferences dialog
            click_button(mw.preferences_button)
            
            pref = await PreferencesDialog.wait_for()
            try:
                # Verify project-specific fields are disabled
                assert not pref.html_parser_field.Enabled, 'HTML parser field should be disabled in readonly mode'
                
                # Verify session fields are still enabled (not project-specific)
                assert pref.stale_before_checkbox.Enabled, 'Stale before checkbox should remain enabled'
                assert pref.cookie_field.Enabled, 'Cookie field should remain enabled'
                
                # Verify app fields are still enabled (not project-specific)
                assert pref.reset_callouts_button.Enabled, 'Reset callouts button should remain enabled'
                
                # Verify buttons are present (dialog should be functional)
                assert pref.ok_button is not None
                assert pref.cancel_button is not None
                assert pref.ok_button.Enabled
                assert pref.cancel_button.Enabled
            finally:
                await pref.cancel()


# ------------------------------------------------------------------------------
# Test: Disabled Menuitems

async def test_given_readonly_project_when_right_click_resource_node_then_url_prefix_menuitems_are_disabled() -> None:
    with xtempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, project):
            # Create a resource with a path that supports both domain and directory prefixes
            rr = RootResource(project, '', Resource(project, 'https://example.com/path/page.html'))
        
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as (mw, project):
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            rrn = root_ti.find_child(rr.resource.url, project.default_url_prefix)
            
            try:
                await mw.entity_tree.set_default_domain_to_entity_at_tree_item(rrn)
            except MenuitemDisabledError:
                pass  # OK
            else:
                raise AssertionError('Expected MenuitemDisabledError')
            
            try:
                await mw.entity_tree.set_default_directory_to_entity_at_tree_item(rrn)
            except MenuitemDisabledError:
                pass  # OK
            else:
                raise AssertionError('Expected MenuitemDisabledError')


async def test_given_readonly_project_with_existing_default_domain_when_right_click_resource_node_then_clear_domain_menuitem_is_disabled() -> None:
    with xtempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
        async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, project):
            # Create a resource with a path that supports both domain and directory prefixes
            rr = RootResource(project, '', Resource(project, 'https://example.com/path/page.html'))
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            rrn = root_ti.find_child(rr.resource.url, project.default_url_prefix)
            
            # Set default domain
            await mw.entity_tree.set_default_domain_to_entity_at_tree_item(rrn)
        
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath, readonly=True) as (mw, project):
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            rrn = root_ti.find_child(rr.resource.url, project.default_url_prefix)
            
            try:
                await mw.entity_tree.clear_default_domain_from_entity_at_tree_item(rrn)
            except MenuitemDisabledError:
                pass  # OK
            else:
                raise AssertionError('Expected MenuitemDisabledError')


# ------------------------------------------------------------------------------
# Test: Readonly <-> Writable Transitions

async def test_when_writable_project_becomes_readonly_then_edit_button_becomes_get_info() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            _untitled_project() as project, \
            RealMainWindow(project) as rmw, \
            _temporary_directory_on_new_filesystem() as save_dir:
        mw = await MainWindow.wait_for(timeout=1)
        
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        # Add some data to the project to ensure there's something to copy
        r = Resource(project, atom_feed_url)
        root_resource = RootResource(project, 'Atom Feed', r)
        rr_future = r.download()
        await step_scheduler_until_done(project)
        
        # Verify project starts as writable with "Edit" button
        assert not project.readonly
        assert not mw.readonly
        
        # Wait for entity tree to populate and select an item
        root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
        await wait_for(lambda: len(root_ti.Children) >= 1)
        root_ti.Children[0].SelectItem()  # Select the root resource
        
        # Verify initial state: button should say "Edit"
        assert mw.edit_button.Enabled
        assertEqual('Edit', mw.edit_button_label_type)
        assertNotEqual('Get Info', mw.edit_button_label_type)
        
        save_path = os.path.join(save_dir, 'SqliteUnwritableProject.crystalproj')
        
        # Mock DatabaseCursor.execute to fail on the specific SQLite pragma
        # that checks database writability
        original_execute = DatabaseCursor.execute
        def spy_execute(self, command: str, *args, **kwargs):
            if command == 'pragma user_version = user_version':
                raise sqlite3.OperationalError('attempt to write a readonly database')
            return original_execute(self, command, *args, **kwargs)
        
        # Run the save operation
        with patch.object(DatabaseCursor, 'execute', spy_execute), \
                patch('crystal.browser.ShowModal', mocked_show_modal(
                    'cr-save-error-dialog', wx.ID_OK)):
            await save_as_with_ui(rmw, save_path)
        
        assert project.readonly, \
            'Expected project to be reopened as read-only after SQLite error'
        assert mw.readonly, \
            'Expected UI to show that project was reopened as read-only'
        
        # Verify button text changed to "Get Info"
        # HACK: The preceding call to save_as_with_ui() doesn't always
        #       wait until the UI is fully updated
        await wait_for(lambda: mw.edit_button.Enabled or None)
        assertEqual('Get Info', mw.edit_button_label_type)
        assertNotEqual('Edit', mw.edit_button_label_type)


async def test_when_readonly_project_becomes_writable_then_get_info_button_becomes_edit() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            xtempfile.TemporaryDirectory() as tmp_dir:
        
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        # Create a titled project with some data, initially writable
        original_project_path = os.path.join(tmp_dir, 'OriginalProject.crystalproj')
        with Project(original_project_path) as project:
            assert not project.readonly, 'Original project should be writable'
            
            # Download a resource revision
            r = Resource(project, atom_feed_url)
            root_resource = RootResource(project, 'Atom Feed', r)
            rr_future = r.download()
            await step_scheduler_until_done(project)
            rr = rr_future.result()
        
        # Reopen the project as readonly
        with Project(original_project_path, readonly=True) as readonly_project, \
                RealMainWindow(readonly_project) as rmw:
            mw = await MainWindow.wait_for(timeout=1)
            assert readonly_project.readonly, 'Project should be opened as readonly'
            assert mw.readonly, 'UI should show project as readonly'
            
            # Wait for entity tree to populate and select an item
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            await wait_for(lambda: len(root_ti.Children) >= 1)
            root_ti.Children[0].SelectItem()  # Select the root resource
            
            # Verify initial state: button should say "Get Info"
            assert mw.edit_button.Enabled
            assertEqual('Get Info', mw.edit_button_label_type)
            assertNotEqual('Edit', mw.edit_button_label_type)
            
            # Perform Save As to make the project writable
            copy_project_path = os.path.join(tmp_dir, 'CopiedProject.crystalproj')
            await save_as_with_ui(rmw, copy_project_path)
            
            # Verify project is now writable
            assert not readonly_project.readonly, \
                'Project should be writable after save_as'
            assert not mw.readonly, \
                'UI should show project as writable after save_as'
            
            # Verify button text changed to "Edit"
            # HACK: The preceding call to save_as_with_ui() doesn't always
            #       wait until the UI is fully updated
            await wait_for(lambda: mw.edit_button.Enabled or None)
            assertEqual('Edit', mw.edit_button_label_type)
            assertNotEqual('Get Info', mw.edit_button_label_type)


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
