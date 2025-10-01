from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager, redirect_stderr
from crystal.browser import MainWindow as RealMainWindow
from crystal.model import Project, Resource, ResourceGroup, RootResource
import crystal.task
from crystal.task import (
    DownloadResourceGroupMembersTask, DownloadResourceGroupTask,
    DownloadResourceTask,
)
from crystal.tests.util.asserts import assertEqual, assertNotIn
from crystal.tests.util.downloads import load_children_of_drg_task
from crystal.tests.util.server import served_project
from crystal.tests.util.slow import slow
from crystal.tests.util.subtests import SubtestsContext, awith_subtests
from crystal.tests.util.tasks import (
    append_deferred_top_level_tasks,
    scheduler_disabled,
    step_scheduler,
    step_scheduler_until_done,
)
from crystal.tests.util.wait import wait_for
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.wx_dialog import mocked_show_modal
from crystal.util.xtyping import not_none
from io import StringIO
from unittest import skip
from unittest.mock import patch
import wx


# === Tests: Reopen Project ===

async def test_when_reopen_project_given_resource_group_was_downloading_then_resumes_downloading() -> None:
    # ...starting from correct member
    
    with scheduler_disabled(), served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        comic1_url = sp.get_request_url('https://xkcd.com/1/')
        comic2_url = sp.get_request_url('https://xkcd.com/2/')
        comic3_url = sp.get_request_url('https://xkcd.com/3/')
        comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        # Create new project, with a partially downloaded group
        async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
            project_dirpath = project.path
            
            comic1_rr = RootResource(project, '', Resource(project, comic1_url))
            comic2_rr = RootResource(project, '', Resource(project, comic2_url))
            comic3_rr = RootResource(project, '', Resource(project, comic3_url))
            
            comic_g = ResourceGroup(project, '', comic_pattern, source=None)
            comic_g.download()
            
            # Ensure task list has only a task to download the group
            append_deferred_top_level_tasks(project)
            (drg_task,) = project.root_task.children
            assert isinstance(drg_task, DownloadResourceGroupTask)
            assert comic_g == drg_task.group
            
            # Step scheduler until comic #1 and #2 are fully downloaded
            # (including embedded resources), but not #3
            if True:
                load_children_of_drg_task(drg_task, scheduler_thread_enabled=False)
                (_, drgm_task) = drg_task.children
                assert isinstance(drgm_task, DownloadResourceGroupMembersTask)
                
                (comic1_dr_task, comic2_dr_task, comic3_dr_task, *_) = drgm_task.children
                assert isinstance(comic1_dr_task, DownloadResourceTask)
                assert isinstance(comic2_dr_task, DownloadResourceTask)
                assert isinstance(comic3_dr_task, DownloadResourceTask)
                
                while not (comic1_dr_task.complete and 
                        comic2_dr_task.complete):
                    await step_scheduler(project)
                assert not comic3_dr_task.complete
                
                assert comic1_rr.resource.has_any_revisions()
                assert comic2_rr.resource.has_any_revisions()
                assert not comic3_rr.resource.has_any_revisions()
            
            # (Close the project, with top-level tasks still running)
        
        # Reopen same project, and resume downloads
        async with _open_project_with_resume_data(project_dirpath, resume=True) as project:
            assert project is not None
            # Ensure comic #1 and #2 are downloaded, but not #3
            if True:
                (comic1_rr, comic2_rr, comic3_rr) = project.root_resources
                
                assert comic1_rr.resource.has_any_revisions()
                assert comic2_rr.resource.has_any_revisions()
                assert not comic3_rr.resource.has_any_revisions()
                
                assert comic1_rr.resource.already_downloaded_this_session
                assert comic2_rr.resource.already_downloaded_this_session
                assert not comic3_rr.resource.already_downloaded_this_session
            
            (comic_g,) = project.resource_groups
            
            # Ensure task list has only a task to download the group
            append_deferred_top_level_tasks(project)
            (drg_task,) = project.root_task.children
            assert isinstance(drg_task, DownloadResourceGroupTask)
            assert comic_g == drg_task.group
            
            # Ensure group download task has children showing that
            # comic #1 and #2 are downloaded, but not #3
            if True:
                load_children_of_drg_task(drg_task, scheduler_thread_enabled=False)
                (_, drgm_task) = drg_task.children
                assert isinstance(drgm_task, DownloadResourceGroupMembersTask)
                
                (comic1_dr_task, comic2_dr_task, comic3_dr_task, *_) = drgm_task.children
                assert isinstance(comic1_dr_task, DownloadResourceTask)
                assert isinstance(comic2_dr_task, DownloadResourceTask)
                assert isinstance(comic3_dr_task, DownloadResourceTask)
                assert comic1_dr_task.complete
                assert comic2_dr_task.complete
                assert not comic3_dr_task.complete
                
                def assert_first_executed_child_is_correct() -> None:
                    assert (
                        drgm_task.children.index(comic3_dr_task) ==
                        drgm_task._next_child_index
                    )
                await step_scheduler(project, after_get=assert_first_executed_child_is_correct)
            
            # Step scheduler until comic #3 downloaded
            while not comic3_dr_task.complete:
                await step_scheduler(project)


async def test_when_reopen_project_given_resource_was_downloading_then_resumes_downloading() -> None:
    with scheduler_disabled(), served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        comic1_url = sp.get_request_url('https://xkcd.com/1/')
        
        # Create new project, with a partially downloaded list of resources
        async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
            project_dirpath = project.path
            
            atom_feed_rr = RootResource(project, '', Resource(project, atom_feed_url))
            comic1_rr = RootResource(project, '', Resource(project, comic1_url))
            
            # Start downloading resources
            atom_feed_rr.download()
            comic1_rr.download()
            
            append_deferred_top_level_tasks(project)
            (atom_feed_dr_task, comic1_dr_task) = project.root_task.children
            assert isinstance(atom_feed_dr_task, DownloadResourceTask)
            assert isinstance(comic1_dr_task, DownloadResourceTask)

            # Step scheduler until resource #1 downloaded
            while not atom_feed_dr_task.complete:
                await step_scheduler(project)
            assert not comic1_dr_task.complete
        
        # Reopen same project, and resume downloads
        async with _open_project_with_resume_data(project_dirpath, resume=True) as project:
            (atom_feed_rr, comic1_rr) = project.root_resources
            
            # Ensure task list has only tasks to download the remaining resources
            append_deferred_top_level_tasks(project)
            (comic1_dr_task,) = project.root_task.children
            assert isinstance(comic1_dr_task, DownloadResourceTask)
            assert comic1_rr.resource == comic1_dr_task.resource
            
            # Step scheduler until resource #2 downloaded
            while not comic1_dr_task.complete:
                await step_scheduler(project)
            await step_scheduler(project, expect_done=True)
            
            # Ensure no download tasks left
            () = project.root_task.children


async def test_when_reopen_project_and_user_cancels_resume_then_does_not_resume_downloading() -> None:
    with scheduler_disabled(), served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        comic1_url = sp.get_request_url('https://xkcd.com/1/')

        # Create new project, with a partially downloaded list of resources
        async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
            project_dirpath = project.path
            
            atom_feed_rr = RootResource(project, '', Resource(project, atom_feed_url))
            comic1_rr = RootResource(project, '', Resource(project, comic1_url))
            
            atom_feed_rr.download()
            comic1_rr.download()
            
            append_deferred_top_level_tasks(project)
            (atom_feed_dr_task, comic1_dr_task) = project.root_task.children
            assert isinstance(atom_feed_dr_task, DownloadResourceTask)
            assert isinstance(comic1_dr_task, DownloadResourceTask)
            
            # Step scheduler until resource #1 downloaded
            while not atom_feed_dr_task.complete:
                await step_scheduler(project)
            assert not comic1_dr_task.complete
        
        # Reopen same project, and cancel resume
        async with _open_project_with_resume_data(project_dirpath, resume=False) as project:
            # Ensure no download tasks are resumed
            append_deferred_top_level_tasks(project)
            () = project.root_task.children


async def test_when_reopen_project_as_readonly_then_does_not_resume_downloading() -> None:
    with scheduler_disabled(), served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        comic1_url = sp.get_request_url('https://xkcd.com/1/')

        # Create new project, with a partially downloaded list of resources
        async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
            project_dirpath = project.path
            
            atom_feed_rr = RootResource(project, '', Resource(project, atom_feed_url))
            comic1_rr = RootResource(project, '', Resource(project, comic1_url))
            
            atom_feed_rr.download()
            comic1_rr.download()
            
            append_deferred_top_level_tasks(project)
            (atom_feed_dr_task, comic1_dr_task) = project.root_task.children
            assert isinstance(atom_feed_dr_task, DownloadResourceTask)
            assert isinstance(comic1_dr_task, DownloadResourceTask)
            
            # Step scheduler until resource #1 downloaded
            while not atom_feed_dr_task.complete:
                await step_scheduler(project)
            assert not comic1_dr_task.complete
        
        # Reopen same project as read-only
        async with (await OpenOrCreateDialog.wait_for()).open(
                project_dirpath, readonly=True) as (mw, project):
            # Ensure no download tasks are resumed
            append_deferred_top_level_tasks(project)
            () = project.root_task.children
        
        # Reopen same project normally, and resume downloads
        async with _open_project_with_resume_data(project_dirpath, resume=True) as project:
            # Ensure download tasks are resumed
            append_deferred_top_level_tasks(project)
            (comic1_dr_task,) = project.root_task.children
            assert isinstance(comic1_dr_task, DownloadResourceTask)


# === Tests: Close Project + Resume Data ===

async def test_when_close_project_abruptly_and_reopen_project_with_stale_resume_data_then_resume_ignores_invalid_data() -> None:
    with scheduler_disabled(), served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        comic1_url = sp.get_request_url('https://xkcd.com/1/')
        comic2_url = sp.get_request_url('https://xkcd.com/2/')
        feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        # Create a project with stale resume data referring to a deleted ResourceGroup and Resource
        async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
            project_dirpath = project.path
            
            comic_g = ResourceGroup(project, '', comic_pattern, source=None)
            RootResource(project, '', Resource(project, comic1_url))
            comic2_rr = RootResource(project, '', Resource(project, comic2_url))
            feed_rr = RootResource(project, '', Resource(project, feed_url))
            
            # Start downloading a ResourceGroup and a Resource
            if True:
                comic_g.download()
                feed_rr.download()
                comic2_rr.download()  # will NOT delete later
                
                append_deferred_top_level_tasks(project)
                (drg_task, dr_task1, dr_task2) = project.root_task.children
                assert isinstance(drg_task, DownloadResourceGroupTask)
                assert isinstance(dr_task1, DownloadResourceTask)
                assert isinstance(dr_task2, DownloadResourceTask)
                assert comic_g == drg_task.group
                assert feed_rr.resource == dr_task1.resource
                assert comic2_rr.resource == dr_task2.resource
            
            # Create resume data referring to the ResourceGroup and Resource
            _autohibernate_now(project)
            
            # Forget the ResourceGroup and Resource. Ensure both continue to download anyway.
            if True:
                comic_g.delete()
                feed_rr.delete()
                feed_rr.resource.delete()  # HACK: Unrealistic. No way to delete Resource in the UI.
                # (comic2_rr is not deleted so it WILL be resumed later)
                
                append_deferred_top_level_tasks(project)
                (drg_task, dr_task1, dr_task2) = project.root_task.children
                assert isinstance(drg_task, DownloadResourceGroupTask)
                assert isinstance(dr_task1, DownloadResourceTask)
                assert isinstance(dr_task2, DownloadResourceTask)
                assert comic_g == drg_task.group
                assert feed_rr.resource == dr_task1.resource
                assert comic2_rr.resource == dr_task2.resource
            
            _close_project_abruptly(project)
        
        # Reopen the project
        async with _open_project_with_resume_data(project_dirpath, resume=True) as project:
            # Ensure that the stale resume data is ignored,
            # and the download of the non-stale Resource is resumed
            append_deferred_top_level_tasks(project)
            (dr_task2,) = project.root_task.children
            assert isinstance(dr_task2, DownloadResourceTask)


async def test_when_close_project_normally_and_no_tasks_running_then_resume_data_in_database_is_cleared() -> None:
    with scheduler_disabled(), served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        comic1_url = sp.get_request_url('https://xkcd.com/1/')
        
        # Create new project, but with no downloads running at the time of closing
        async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
            project_dirpath = project.path
            
            comic1_rr = RootResource(project, '', Resource(project, comic1_url))
            comic1_rr.download()
            append_deferred_top_level_tasks(project)
            (comic1_dr_task,) = project.root_task.children
            assert isinstance(comic1_dr_task, DownloadResourceTask)
            
            _autohibernate_now(project)
            assert _project_has_resume_data(project)
            
            await step_scheduler_until_done(project)

        # Ensure resume data is cleared
        async with (await OpenOrCreateDialog.wait_for()).open(project_dirpath) as (mw, project):

            assert not _project_has_resume_data(project)


async def test_while_project_open_then_periodically_saves_resume_data_so_that_can_resume_after_abrupt_project_close() -> None:
    with scheduler_disabled(), served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        comic1_url = sp.get_request_url('https://xkcd.com/1/')

        with _frequent_autohibernates_enabled():
            # Create new project, with a partially downloaded list of resources
            async with (await OpenOrCreateDialog.wait_for()).create(delete=False) as (mw, project):
                project_dirpath = project.path
                
                atom_feed_rr = RootResource(project, '', Resource(project, atom_feed_url))
                comic1_rr = RootResource(project, '', Resource(project, comic1_url))
                
                atom_feed_rr.download()
                comic1_rr.download()
                
                append_deferred_top_level_tasks(project)
                (atom_feed_dr_task, comic1_dr_task) = project.root_task.children
                assert isinstance(atom_feed_dr_task, DownloadResourceTask)
                assert isinstance(comic1_dr_task, DownloadResourceTask)
                
                # Step scheduler until resource #1 downloaded
                while not atom_feed_dr_task.complete:
                    await step_scheduler(project)
                assert not comic1_dr_task.complete
                
                # Wait for autohibernate to save resume data
                _clear_project_resume_data(project)
                assert not _project_has_resume_data(project)
                await wait_for(lambda: _project_has_resume_data(project) or None, timeout=2)
                
                _close_project_abruptly(project)
            
            # Reopen the project
            async with _open_project_with_resume_data(project_dirpath, resume=True) as project:
                # Ensure that the download is resumed
                append_deferred_top_level_tasks(project)
                (comic1_dr_task,) = project.root_task.children
                assert isinstance(comic1_dr_task, DownloadResourceTask)


# === Tests: Close Project + Special Situations ===

# NOTE: Covered by test_given_download_resource_task_running_at_any_step_when_close_project_then_drt_cancels_without_error.
#       However this test has more specific checks (than the other test) for a particular regression.
async def test_given_download_resource_task_running_when_close_project_then_drt_cancels_without_delay() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp, \
            patch('crystal.task._DOWNLOAD_DELAY_STYLE', 'after_every_page'):
        # Define URLs
        comic_url = sp.get_request_url('https://xkcd.com/1/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            rmw = RealMainWindow._last_created
            assert rmw is not None
            
            # Create and start download task
            comic_rr = RootResource(project, '', Resource(project, comic_url))
            comic_rr.download()
            
            append_deferred_top_level_tasks(project)
            (comic_dr_task,) = project.root_task.children
            assert isinstance(comic_dr_task, DownloadResourceTask)
            
            # Step scheduler until about to complete the last child
            # of the DownloadResourceTask
            while True:
                if not not_none(comic_dr_task._download_body_task).complete:
                    # Step until _download_body_task is complete
                    pass
                elif not not_none(comic_dr_task._parse_links_task).complete:
                    # Step until _parse_links_task is complete
                    pass
                else:
                    # Stop until all but the last child is complete
                    child_tasks = comic_dr_task.children
                    if child_tasks[-2].complete and not child_tasks[-1].complete:
                        break
                await step_scheduler(project)
            
            # Close the window, cancelling the last child of the DownloadResourceTask,
            # hopefully triggering this logic:
            # 
            #     self.subtitle = 'Waiting before performing next request...'  # ⭐ WANT
            #     if task.cancelled:
            #         # Download did not actually finish. Do not wait.
            #         pass  # ⭐ WANT
            #     else:
            #         if is_foreground_thread():
            #             raise AssertionError(...)  # ⚠️ do not want
            #         sleep(DELAY_BETWEEN_DOWNLOADS)  # ⚠️ do not want
            with patch('crystal.task.sleep', wraps=crystal.task.sleep) as spy_sleep, \
                    patch.object(
                        comic_dr_task, 'child_task_did_complete',
                        wraps=comic_dr_task.child_task_did_complete
                        ) as spy_child_task_did_complete, \
                    patch.object(
                        comic_dr_task, '_set_subtitle',
                        wraps=comic_dr_task._set_subtitle
                        ) as spy_set_subtitle, \
                    redirect_stderr(StringIO()) as captured_stderr:
                rmw.close()
                
                assert spy_child_task_did_complete.call_count >= 1
                spy_set_subtitle.assert_any_call('Waiting before performing next request...')
                assertEqual(0, spy_sleep.call_count)
                assertNotIn('AssertionError', captured_stderr.getvalue())
                assertNotIn('Traceback', captured_stderr.getvalue())
                
                assert comic_dr_task.complete


# NOTE: Test is skipped, despite being implemented, because it is slow.
#       As the decorator notes, its functionality should be covered by another test.
@skip('covered by: test_given_download_resource_group_task_with_source_running_at_any_step_when_close_project_then_drgt_cancels_without_error')
@awith_subtests
async def test_given_download_resource_task_running_at_any_step_when_close_project_then_drt_cancels_without_error(subtests: SubtestsContext) -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        comic_url = sp.get_request_url('https://xkcd.com/1/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create and start download task
            comic_rr = RootResource(project, '', Resource(project, comic_url))
            comic_rr.download()
            
            append_deferred_top_level_tasks(project)
            (comic_dr_task,) = project.root_task.children
            assert isinstance(comic_dr_task, DownloadResourceTask)
            
            # Step scheduler until DownloadResourceTask is complete,
            # counting the number of steps required
            drt_step_count = 0
            while not comic_dr_task.complete:
                await step_scheduler(project)
                drt_step_count += 1
            await step_scheduler(project, expect_done=True)
        
        for n in range(drt_step_count + 1):
            print(f'Testing cancel after {n}/{drt_step_count} step(s)')
            with subtests.test(cancel_after_n_steps=n):
                async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                    rmw = RealMainWindow._last_created
                    assert rmw is not None
                    
                    # Create and start download task
                    comic_rr = RootResource(project, '', Resource(project, comic_url))
                    comic_rr.download()
                    
                    append_deferred_top_level_tasks(project)
                    (comic_dr_task,) = project.root_task.children
                    assert isinstance(comic_dr_task, DownloadResourceTask)
                    
                    for _ in range(n):
                        await step_scheduler(project)
                    
                    with redirect_stderr(StringIO()) as captured_stderr:
                        rmw.close()
                        assertNotIn('Traceback', captured_stderr.getvalue())
                        assert comic_dr_task.complete


# NOTE: Test is skipped, despite being implemented, because it is slow.
#       As the decorator notes, its functionality should be covered by another test.
@skip('covered by: test_given_download_resource_group_task_with_source_running_at_any_step_when_close_project_then_drgt_cancels_without_error')
@awith_subtests
async def test_given_download_resource_group_task_without_source_running_at_any_step_when_close_project_then_drgt_cancels_without_error(subtests: SubtestsContext) -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create RootResources for the feeds
            atom_feed_rr = RootResource(project, '', Resource(project, atom_feed_url))
            rss_feed_rr = RootResource(project, '', Resource(project, rss_feed_url))
            
            # Create and start download ResourceGroup task
            feed_g = ResourceGroup(project, '', feed_pattern, source=None)
            feed_g.download()
            
            append_deferred_top_level_tasks(project)
            (feed_drg_task,) = project.root_task.children
            assert isinstance(feed_drg_task, DownloadResourceGroupTask)
            
            # Step scheduler until DownloadResourceGroupTask is complete,
            # counting the number of steps required
            drgt_step_count = 0
            while not feed_drg_task.complete:
                await step_scheduler(project)
                drgt_step_count += 1
            await step_scheduler(project, expect_done=True)
        
        for n in range(drgt_step_count + 1):
            print(f'Testing cancel after {n}/{drgt_step_count} step(s)')
            with subtests.test(cancel_after_n_steps=n):
                async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                    rmw = RealMainWindow._last_created
                    assert rmw is not None
                    
                    # Create RootResources for the feeds
                    atom_feed_rr = RootResource(project, '', Resource(project, atom_feed_url))
                    rss_feed_rr = RootResource(project, '', Resource(project, rss_feed_url))
                    
                    # Create and start download ResourceGroup task
                    feed_g = ResourceGroup(project, '', feed_pattern, source=None)
                    feed_g.download()
                    
                    append_deferred_top_level_tasks(project)
                    (feed_drg_task,) = project.root_task.children
                    assert isinstance(feed_drg_task, DownloadResourceGroupTask)
                    
                    for _ in range(n):
                        await step_scheduler(project)
                    
                    with redirect_stderr(StringIO()) as captured_stderr:
                        rmw.close()
                        assertNotIn('Traceback', captured_stderr.getvalue())
                        assert feed_drg_task.complete


@slow  # 115s on Apple M3 2024
@awith_subtests
async def test_given_download_resource_group_task_with_source_running_at_any_step_when_close_project_then_drgt_cancels_without_error(subtests: SubtestsContext) -> None:
    # A DownloadResourceGroupTask with a source will have a task tree that looks like:
    # 
    #   - DownloadResourceGroupTask
    #       - UpdateResourceGroupMembersTask
    #           - DownloadResourceTask (for a RootResource source)
    #               - ...
    #       - DownloadResourceGroupMembersTask
    #           - DownloadResourceTask 1
    #               - DownloadResourceBodyTask
    #               - ParseResourceRevisionLinks
    #               - DownloadResourceTask 1
    #                   - ...
    #               - ...
    #               - DownloadResourceTask N
    #                   - ...
    #           - ...
    #           - DownloadResourceTask N
    #               - ...
    # 
    # Therefore the following task types are covered by this test:
    #   - DownloadResourceGroupTask
    #   - UpdateResourceGroupMembersTask
    #   - DownloadResourceGroupMembersTask
    #   - DownloadResourceTask
    #   - DownloadResourceBodyTask
    #   - ParseResourceRevisionLinks
    
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create RootResources
            home_rr = RootResource(project, '', Resource(project, home_url))
            atom_feed_rr = RootResource(project, '', Resource(project, atom_feed_url))
            rss_feed_rr = RootResource(project, '', Resource(project, rss_feed_url))
            
            # Create and start download ResourceGroup task
            feed_g = ResourceGroup(project, '', feed_pattern, source=home_rr)
            feed_g.download()
            
            append_deferred_top_level_tasks(project)
            (feed_drg_task,) = project.root_task.children
            assert isinstance(feed_drg_task, DownloadResourceGroupTask)
            
            # Step scheduler until DownloadResourceGroupTask is complete,
            # counting the number of steps required
            drgt_step_count = 0
            while not feed_drg_task.complete:
                await step_scheduler(project)
                drgt_step_count += 1
            await step_scheduler(project, expect_done=True)
        
        for n in range(drgt_step_count + 1):
            print(f'Testing cancel after {n}/{drgt_step_count} step(s)')
            with subtests.test(cancel_after_n_steps=n):
                async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                    rmw = RealMainWindow._last_created
                    assert rmw is not None
                    
                    # Create RootResources
                    home_rr = RootResource(project, '', Resource(project, home_url))
                    atom_feed_rr = RootResource(project, '', Resource(project, atom_feed_url))
                    rss_feed_rr = RootResource(project, '', Resource(project, rss_feed_url))
                    
                    # Create and start download ResourceGroup task
                    feed_g = ResourceGroup(project, '', feed_pattern, source=home_rr)
                    feed_g.download()
                    
                    append_deferred_top_level_tasks(project)
                    (feed_drg_task,) = project.root_task.children
                    assert isinstance(feed_drg_task, DownloadResourceGroupTask)
                    
                    for _ in range(n):
                        await step_scheduler(project)
                    
                    with redirect_stderr(StringIO()) as captured_stderr:
                        rmw.close()
                        assertNotIn('Traceback', captured_stderr.getvalue())
                        assert feed_drg_task.complete


# === Utility ===

@asynccontextmanager
async def _open_project_with_resume_data(
        project_dirpath: str,
        resume: bool=True,
        ) -> AsyncIterator[Project]:
    """
    Opens a project with resume data, simulating the behavior of the
    `OpenOrCreateDialog` when it asks the user whether to resume downloads.
    
    If `resume` is `True`, it simulates the user clicking "Resume Downloads".
    If `resume` is `False`, it simulates the user clicking "Cancel".
    """
    with patch(
            'crystal.browser.ShowModal',
            mocked_show_modal('cr-resume-downloads', wx.ID_OK if resume else wx.ID_CANCEL)
            ) as show_modal_method:
        async def wait_for_project_to_unhibernate() -> None:
            await wait_for(lambda: (1 == show_modal_method.call_count) or None)
        
        async with (await OpenOrCreateDialog.wait_for()).open(
                project_dirpath, wait_func=wait_for_project_to_unhibernate) as (mw, project):
            yield project


def _autohibernate_now(project: Project) -> None:
    """
    Simulates the automatic hibernation of a project.
    """
    project.hibernate_tasks()


@contextmanager
def _frequent_autohibernates_enabled() -> Iterator[None]:
    """
    Enables frequent automatic hibernation for projects that become opened.
    """
    with patch(
            'crystal.browser.MainWindow._AUTOHIBERNATE_PERIOD',
            20  # milliseconds
            ):
        yield


def _close_project_abruptly(project: Project) -> None:
    """
    Simulates an abrupt close of a project, similar to unmounting the disk
    where the project database is stored.
    """
    # Causes subsequent SQLite operations to fail with:
    #     sqlite3.ProgrammingError('Cannot operate on a closed database.')
    # 
    # A real unmount of a disk on macOS causes subsequent SQLite operations to fail with:
    #     sqlite3.DatabaseError('database disk image is malformed')
    project._db._db.close()


def _project_has_resume_data(project: Project) -> bool:
    """
    Checks if the project has any resume data in the database.
    """
    hibernated_project_str = project._get_property('hibernated_state', default=None)
    return hibernated_project_str is not None


def _clear_project_resume_data(project: Project) -> None:
    """
    Clears the resume data from the project database.
    """
    project._delete_property('hibernated_state')
