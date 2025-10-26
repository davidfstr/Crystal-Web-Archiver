from concurrent.futures import Future
from crystal.browser.tasktree import _INTERACTIVE_SUFFIX
from crystal.model import (
    Resource, ResourceGroup, ResourceRevision, RootResource,
)
from crystal.server import ProjectServer
from crystal.task import (
    ASSUME_RESOURCES_DOWNLOADED_IN_SESSION_WILL_ALWAYS_REMAIN_FRESH,
    DownloadResourceGroupMembersTask,
    DownloadResourceGroupTask,
    DownloadResourceTask, ProjectFreeSpaceTooLowError, Task,
)
from crystal.tests.util.asserts import assertEqual, assertIn
from crystal.tests.util.console import console_output_copied
from crystal.tests.util.controls import click_button, TreeItem
from crystal.tests.util.data import (
    MAX_TIME_TO_DOWNLOAD_404_URL, MAX_TIME_TO_DOWNLOAD_XKCD_HOME_URL_BODY,
)
from crystal.tests.util.downloads import load_children_of_drg_task
from crystal.tests.util.server import (
    assert_does_open_webbrowser_to, fetch_archive_url, served_project,
)
from crystal.tests.util.skip import skipTest
from crystal.tests.util.slow import slow
from crystal.tests.util.subtests import awith_subtests, SubtestsContext
from crystal.tests.util.tasks import (
    append_deferred_top_level_tasks,
    downloads_patched_to_return_empty_revision,
    scheduler_disabled,
    scheduler_thread_context,
    step_scheduler,
    step_scheduler_until_done,
    ttn_for_task,
)
from crystal.tests.util.wait import wait_for
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.util.progress import ProgressBarCalculator
from crystal.util.xcollections.lazy import AppendableLazySequence
from crystal.util.xthreading import is_foreground_thread
import re
from typing import NamedTuple
from unittest import skip
from unittest.mock import ANY, Mock, patch, PropertyMock


# ==============================================================================
# Test: Tasks

# ------------------------------------------------------------------------------
# Test: Task

@awith_subtests
async def test_some_tasks_may_complete_immediately(subtests) -> None:
    assert True == ASSUME_RESOURCES_DOWNLOADED_IN_SESSION_WILL_ALWAYS_REMAIN_FRESH, \
        'Expected optimization to be enabled: ASSUME_RESOURCES_DOWNLOADED_IN_SESSION_WILL_ALWAYS_REMAIN_FRESH'
    
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        if True:
            missing_url = sp.get_request_url('https://example.com/')
            
            comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            missing_r = Resource(project, missing_url)
            
            with subtests.test(task_type='DownloadResourceTask'):
                # Download the resource
                assert False == missing_r.already_downloaded_this_session
                dr_task = missing_r.download_with_task()  # uses DownloadResourceTask
                await wait_for(
                    lambda: dr_task.complete or None,
                    timeout=MAX_TIME_TO_DOWNLOAD_404_URL)
                assert True == missing_r.already_downloaded_this_session
                
                # Download the resource again, and ensure it downloads immediately
                dr_task = missing_r.create_download_task(needs_result=False)  # a DownloadResourceTask
                assert True == dr_task.complete
            
            with subtests.test(task_type='UpdateResourceGroupMembersTask'):
                # Covered by subtest: DownloadResourceGroupTask
                pass
            
            with subtests.test(task_type='DownloadResourceGroupMembersTask'):
                # Covered by subtest: DownloadResourceGroupTask
                pass
            
            with subtests.test(task_type='DownloadResourceGroupTask'):
                comic_rs = [
                    Resource(project, comic_pattern.replace('#', str(ordinal)))
                    for ordinal in [1, 2]
                ]
                
                comic_g = ResourceGroup(project, 'Comic', comic_pattern)
                assert None == comic_g.source
                
                COMIC_G_FINAL_MEMBER_COUNT = 10
                
                # Download the group (and all of its currently known members)
                for r in comic_rs:
                    assert False == r.already_downloaded_this_session
                drg_task = comic_g.create_download_task()  # a DownloadResourceGroupTask
                project.add_task(drg_task)
                await wait_for(
                    lambda: drg_task.complete or None,
                    timeout=(
                        MAX_TIME_TO_DOWNLOAD_404_URL +
                        (MAX_TIME_TO_DOWNLOAD_XKCD_HOME_URL_BODY * COMIC_G_FINAL_MEMBER_COUNT)
                    ))
                assert COMIC_G_FINAL_MEMBER_COUNT == len(comic_g.members)
                for r in comic_rs:
                    assert True == r.already_downloaded_this_session
                
                # Download the group again, and ensure it downloads immediately
                if True:
                    drg_task = comic_g.create_download_task()
                    
                    load_children_of_drg_task(drg_task, task_added_to_project=False)
                    
                    # Precondition
                    # NOTE: The group won't appear to be immediately downloaded yet
                    #       because no code has tried to access the lazily-loaded
                    #       DownloadResourceTask children yet and thus doesn't
                    #       know that all of those children are complete
                    assert (True, 0, False) == (
                        isinstance(drg_task._download_members_task.children, AppendableLazySequence),
                        drg_task._download_members_task.children.cached_prefix_len
                            if isinstance(drg_task._download_members_task.children, AppendableLazySequence)
                            else None,
                        drg_task.complete
                    )
                    
                    # TODO: Disable the scheduler thread before trying to control
                    #       it manually. Currently it's not safe to make the
                    #       scheduler_thread_context() assertion.
                    project.add_task(drg_task)
                    with scheduler_thread_context():
                        await step_scheduler(project, expect_done=True)
                    
                    # Postcondition
                    # NOTE: Adding the DownloadResourceGroupTask to the project's
                    #       task tree will cause the TaskTreeNode to start accessing
                    #       the DownloadResourceTask children because it wants to
                    #       create a paired TaskTreeNode for each such child.
                    #       These accesses cause the DownloadResourceTask children
                    #       to be created and observed as being already complete.
                    #       With all of those children complete the ancestor
                    #       DownloadResourceGroupTask will also be completed.
                    assert (True, COMIC_G_FINAL_MEMBER_COUNT, True) == (
                        isinstance(drg_task._download_members_task.children, AppendableLazySequence),
                        drg_task._download_members_task.children.cached_prefix_len
                            if isinstance(drg_task._download_members_task.children, AppendableLazySequence)
                            else None,
                        drg_task.complete
                    )


def test_given_running_tests_then_uses_extra_listener_assertions() -> None:
    assert True == Task._USE_EXTRA_LISTENER_ASSERTIONS_ALWAYS


# ------------------------------------------------------------------------------
# Test: DownloadResourceTask
#       (+ DownloadResourceBodyTask)
#       (+ ParseResourceRevisionLinks)

# (TODO: Add basic tests)

@skip('not yet automated')
async def test_when_download_resource_then_displays_estimated_time_remaining() -> None:
    pass


def test_format_of_estimated_time_remaining() -> None:
    if ProgressBarCalculator._VERBOSE:
        skipTest('cannot check format when verbose format is being used')
        return
    
    def format_remaining_str(second_count: int) -> str:
        class MockProgressBarCalculator(ProgressBarCalculator):
            pass
        
        pbc = MockProgressBarCalculator(initial=0, total=second_count)
        type(pbc).n = PropertyMock(return_value=0)  # type: ignore[assignment]
        type(pbc).total = PropertyMock(return_value=second_count)
        pbc._rc_n = Mock()
        type(pbc._rc_n).rate = PropertyMock(return_value=1)
        pbc._rc_total = Mock()
        type(pbc._rc_total).rate = PropertyMock(return_value=None)
        
        (remaining_str, time_per_item_str) = pbc.remaining_str_and_time_per_item_str()
        return remaining_str
    
    assertEqual('00:01', format_remaining_str(1))  # 1 second
    assertEqual('01:00', format_remaining_str(60))  # 1 minute
    assertEqual('1:00:00', format_remaining_str(60*60))  # 1 hr
    assertEqual('1d + 0:00:00', format_remaining_str(24*60*60))  # 1 day
    assertEqual('1d + 1:01:01', format_remaining_str(24*60*60 + 60*60 + 60 + 1))


# TODO: Extend test to check how user-facing UI responds to ProjectFreeSpaceTooLowError
#       condition. Currently the UI doesn't handle this condition well and
#       silently fails downloads.
@awith_subtests
async def test_given_project_on_disk_with_low_space_free_when_try_to_download_resource_revision_then_raises_exception(subtests: SubtestsContext) -> None:
    async def try_download_with_disk_usage(du: _DiskUsage, *, expect_failure: bool) -> None:
        assert project is not None
        with patch('shutil.disk_usage', return_value=du):
            r = Resource(project, home_url)
            try:
                rr_future = r.download_body()
                await wait_for(
                    lambda: rr_future.done() or None,
                    timeout=MAX_TIME_TO_DOWNLOAD_XKCD_HOME_URL_BODY)
                try:
                    rr_future.result()
                except ProjectFreeSpaceTooLowError:
                    if expect_failure:
                        pass  # expected
                    else:
                        assert False, f'Expected ProjectFreeSpaceTooLowError but got success when {du}'
                else:
                    if not expect_failure:
                        pass  # expected
                    else:
                        assert False, f'Expected success but got ProjectFreeSpaceTooLowError when {du}'
            finally:
                r.delete()
    
    with subtests.test('given project on small disk and less than 5 percent of disk free'):
        with served_project('testdata_xkcd.crystalproj.zip') as sp:
            # Define URLs
            home_url = sp.get_request_url('https://xkcd.com/')
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                await try_download_with_disk_usage(
                    _DiskUsage(total=100*1024*1024, used=(100-6)*1024*1024, free=6*1024*1024),
                    expect_failure=False)
                
                await try_download_with_disk_usage(
                    _DiskUsage(total=100*1024*1024, used=(100-4)*1024*1024, free=4*1024*1024),
                    expect_failure=True)
    
    with subtests.test('given project on large disk and less than 4 gib of disk free'):
        with served_project('testdata_xkcd.crystalproj.zip') as sp:
            # Define URLs
            home_url = sp.get_request_url('https://xkcd.com/')
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                await try_download_with_disk_usage(
                    _DiskUsage(total=1000*1024*1024*1024, used=(1000-6)*1024*1024*1024, free=6*1024*1024*1024),
                    expect_failure=False)
                
                await try_download_with_disk_usage(
                    _DiskUsage(total=1000*1024*1024*1024, used=(1000-3)*1024*1024*1024, free=3*1024*1024*1024),
                    expect_failure=True)


class _DiskUsage(NamedTuple):
    total: int
    used: int
    free: int


# ------------------------------------------------------------------------------
# Test: DownloadResourceGroupTask
#       (+ UpdateResourceGroupMembersTask)
#       (+ DownloadResourceGroupMembersTask)

# (TODO: Add basic tests)

@skip('not yet automated')
async def test_when_download_resource_group_members_then_displays_estimated_time_remaining() -> None:
    pass


@awith_subtests
async def test_given_download_resource_group_members_when_add_group_member_via_dynamic_browsing_then_new_member_is_queued_for_download(subtests) -> None:
    for children_loaded_before_member_added in [True, False]:
        with subtests.test(children_loaded_before_member_added=children_loaded_before_member_added):
            # NOTE: NOT using the xkcd test data, because I want all xkcd URLs to give HTTP 404
            with scheduler_disabled(), \
                    served_project('testdata_bongo.cat.crystalproj.zip') as sp:
                # Define URLs
                comic1_url = sp.get_request_url('https://xkcd.com/1/')
                comic2_url = sp.get_request_url('https://xkcd.com/2/')
                comic_pattern = sp.get_request_url('https://xkcd.com/#/')
                
                async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                    RootResource(project, '', Resource(project, comic1_url))
                    comic_g = ResourceGroup(project, '', comic_pattern)
                    
                    server = ProjectServer(project)
                    try:
                        drg_task = comic_g.create_download_task()
                        project.add_task(drg_task); append_deferred_top_level_tasks(project)
                        
                        drgm_task = drg_task._download_members_task
                        if children_loaded_before_member_added:
                            load_children_of_drg_task(drg_task, scheduler_thread_enabled=False)
                            assertEqual(1, _group_size_in_subtitle(drgm_task))
                        else:
                            assertEqual('Queued', drgm_task.subtitle)
                        
                        # Trigger start of dynamic download of new group member
                        # 
                        # Meanwhile:
                        # - Patch Resource.download() to start download and return an
                        #   already-completed Future with an arbitrary result,
                        #   rather than blocking on the foreground thread
                        # - Prevent foreground thread from being detected as the scheduler thread
                        super_resource_download = Resource.download
                        def resource_download(self: Resource, *args, **kwargs) -> 'Future[ResourceRevision]':
                            _ = super_resource_download(self, *args, **kwargs)
                            result = Future()  # type: Future[ResourceRevision]
                            result.set_result(ResourceRevision.create_from_error(self, Exception('Simulated error')))
                            return result
                        with patch.object(Resource, 'download', resource_download):
                            assert is_foreground_thread()
                            with scheduler_thread_context(enabled=False):
                                _ = await fetch_archive_url(comic2_url)
                        
                        # HACK: Force the newly-added DownloadResourceTask to run 
                        #       with non-interactive priority so that we can observe
                        #       the subtitle change in DownloadResourceGroupTask
                        append_deferred_top_level_tasks(project)
                        dr_task = project.root_task.children[-1]
                        assert isinstance(dr_task, DownloadResourceTask)
                        assert True == dr_task.interactive
                        dr_task._interactive = False
                        assert False == dr_task.interactive
                        
                        # 1. Step the DownloadResourceGroupTask
                        # 2. Process deferred event: DRGMT.group_did_add_member
                        await step_scheduler(project)
                        
                        # Ensure newly discovered group member is queued for download
                        assertEqual(2, _group_size_in_subtitle(drgm_task))
                    finally:
                        server.close()
                    
                    # Drain tasks explicitly, to avoid subtitle-related warning
                    await step_scheduler_until_done(project)


def _group_size_in_subtitle(t: DownloadResourceGroupMembersTask) -> int:
    m = re.search(r'(\d+) item\(s\)', t.subtitle)
    assert m is not None
    return int(m.group(1))


# ------------------------------------------------------------------------------
# Test: RootTask

# (TODO: Add basic tests)


# ==============================================================================
# Test: Interactive Priority Tasks

# TODO: Move this section to test_tasks.py because its tests don't really relate
#       to the Task Tree.

# --- Test: Interactive Priority Tasks: Task Becomes Interactive ---

async def test_when_resource_node_in_entity_tree_expanded_then_related_resource_downloaded_at_interactive_priority() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp, \
            scheduler_disabled():
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            home_resource = Resource(project, home_url)
            home_rr = RootResource(project, 'Home', home_resource)
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            (home_ti,) = root_ti.Children
            
            # Expand the resource node to create a DownloadResourceTask.
            # Should trigger Resource.download(interactive=True).
            () = project.root_task.children
            home_ti.Expand(); append_deferred_top_level_tasks(project)
            (download_task,) = project.root_task.children
            assert isinstance(download_task, DownloadResourceTask)
            assertEqual(home_resource, download_task.resource)
            
            # Ensure DownloadResourceTask has interactive=True priority
            assertEqual(True, download_task.interactive)
            
            # test_interactive_tasks_are_marked_in_the_task_tree_ui
            download_ttn = ttn_for_task(download_task)
            assert download_ttn.tree_node.subtitle.endswith(_INTERACTIVE_SUFFIX)


async def test_when_resource_matching_root_resource_or_resource_group_requested_from_project_server_then_related_resource_downloaded_at_interactive_priority() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp, \
            scheduler_disabled():
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        comic1_url = sp.get_request_url('https://xkcd.com/1/')
        comic2_url = sp.get_request_url('https://xkcd.com/2/')
        comic_url_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            home_r = Resource(project, home_url)
            home_rr = RootResource(project, 'Home', home_r)
            
            comic_group = ResourceGroup(project, 'Comics', comic_url_pattern, source=home_rr)
            
            # Start the project server
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            (home_ti, comic_group_ti) = root_ti.Children
            home_ti.SelectItem()
            with assert_does_open_webbrowser_to(ANY):
                click_button(mw.view_button)
            
            # Case 1: Test dynamic download of RootResource at interactive priority
            if True:
                () = project.root_task.children
                
                # Request the root resource URL, which should trigger dynamic download
                with console_output_copied() as console_output, \
                        downloads_patched_to_return_empty_revision():
                    home_page = await fetch_archive_url(home_url)
                assertIn(
                    f"*** Dynamically downloading root resource 'Home':",
                    console_output.getvalue())
                
                # Verify the created download task has interactive=True priority
                append_deferred_top_level_tasks(project)
                (home_download_task,) = [
                    task for task in project.root_task.children
                    if isinstance(task, DownloadResourceTask) and task.resource == home_r
                ]
                assertEqual(True, home_download_task.interactive)
            
            # Case 2: Test dynamic download of ResourceGroup member at interactive priority
            if True:
                # Request a comic URL that matches the resource group
                with console_output_copied() as console_output, \
                        downloads_patched_to_return_empty_revision():
                    comic1_page = await fetch_archive_url(comic1_url)
                assertIn(
                    f"*** Dynamically downloading new resource in group 'Comics':",
                    console_output.getvalue())
                
                # Verify the created download task has interactive=True priority
                append_deferred_top_level_tasks(project)
                comic1_resource = project.get_resource(comic1_url)
                assert comic1_resource is not None
                (comic1_download_task,) = [
                    task for task in project.root_task.children
                    if isinstance(task, DownloadResourceTask) and task.resource == comic1_resource
                ]
                assertEqual(True, comic1_download_task.interactive)


@skip('not yet automated')
async def test_when_partially_downloaded_resource_requested_from_project_server_then_existing_download_task_escalated_to_interactive_priority() -> None:
    pass


@skip('not yet automated')
async def test_when_not_in_archive_page_served_and_groups_are_predicted_then_related_resource_bodies_are_downloaded_at_interactive_priority() -> None:
    pass


@skip('not yet automated')
async def test_when_download_button_pressed_on_not_in_archive_page_then_related_resource_downloaded_at_interactive_priority() -> None:
    # However any created ResourceGroup (if any) is NOT downloaded at interactive priority.
    pass


# --- Test: Interactive Priority Tasks: Interactive Task Behavior ---

@slow  # 22s on Apple M3 2024
async def test_when_top_level_task_is_interactive_priority_then_is_scheduled_before_any_non_interactive_tasks() -> None:
    # NOTE: Test both cases because there's a rare branch tested by the False case,
    #       where DownloadResourceGroupMembersTask.group_did_add_member() is called
    #       self._children_loaded == False.
    for populate_download_group_task_members in [True, False]:
        with served_project('testdata_xkcd.crystalproj.zip') as sp, \
                scheduler_disabled():
            # Define URLs
            comic_url_pattern = sp.get_request_url('https://xkcd.com/#/')
            comic1_url = sp.get_request_url('https://xkcd.com/1/')
            comic2_url = sp.get_request_url('https://xkcd.com/2/')
            comic3_url = sp.get_request_url('https://xkcd.com/3/')
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                # Create comic ResourceGroup and some Resources to make it downloadable
                comic_group = ResourceGroup(project, 'Comics', comic_url_pattern)
                Resource(project, comic1_url)
                Resource(project, comic3_url)
                
                # Create comic #2 RootResource
                comic2_rr = RootResource(project, 'Comic #2', Resource(project, comic2_url))
                
                # Get entity tree nodes
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                comic_group_ti = root_ti.find_child(comic_url_pattern, project.default_url_prefix)
                comic2_ti = root_ti.find_child(comic2_url, project.default_url_prefix)
                
                # Start download of comic group at non-interactive priority
                comic_group_ti.SelectItem()
                click_button(mw.download_button)
                
                if populate_download_group_task_members:
                    # Populate download tasks for the group's members
                    await step_scheduler(project)
                    
                    # Ensure that inside the DownloadGroupTask that there is a DownloadResourceTask
                    # matching the DownloadResourceTask that will be added to the top-level later
                    (download_group_task,) = project.root_task.children
                    assert isinstance(download_group_task, DownloadResourceGroupTask)
                    (urgm_task, drgm_task) = download_group_task.children
                    assert isinstance(drgm_task, DownloadResourceGroupMembersTask)
                    (dr_task,) = [
                        t for t in drgm_task.children
                        if isinstance(t, DownloadResourceTask) and t.resource.url == comic2_url
                    ]
                    assertEqual(False, dr_task.interactive)
                
                # Start download of comic #2 at interactive priority
                comic2_ti.SelectItem()
                comic2_ti.Expand(); append_deferred_top_level_tasks(project)
                
                # Ensure tasks are scheduled at top-level with correct priority
                (download_group_task, download_resource_task) = project.root_task.children
                assertEqual(False, download_group_task.interactive)
                assertEqual(True, download_resource_task.interactive)
                
                with patch.object(download_group_task, 'try_get_next_task_unit', 
                            wraps=download_group_task.try_get_next_task_unit) as spy_group_try_get_next, \
                        patch.object(download_resource_task, 'try_get_next_task_unit', 
                            wraps=download_resource_task.try_get_next_task_unit) as spy_resource_try_get_next:
                    
                    # Step the scheduler until DownloadResourceTask complete
                    while not download_resource_task.complete:
                        await step_scheduler(project)
                        assert spy_resource_try_get_next.call_count > 0, \
                            'DownloadResourceTask should have been called'
                        assertEqual(0, spy_group_try_get_next.call_count,
                            'DownloadResourceGroupTask should not be called while interactive task is running')
                    
                    # Step the scheduler until DownloadResourceGroupTask complete
                    while not download_group_task.complete:
                        await step_scheduler(project)
                    assert spy_group_try_get_next.call_count > 0, \
                        'DownloadResourceGroupTask should be called after interactive task completes'


@skip('not yet automated')
async def test_when_top_level_task_is_interactive_priority_then_descendent_download_tasks_do_not_delay_between_downloads() -> None:
    pass


@skip('covered by: test_when_resource_node_in_entity_tree_expanded_then_related_resource_downloaded_at_interactive_priority')
async def test_interactive_tasks_are_marked_in_the_task_tree_ui() -> None:
    pass


# --- Test: Interactive Priority Tasks: Interactive Tasks Always (Aliased) at Top Level ---

async def test_when_download_resource_at_interactive_priority_given_same_resource_not_already_in_task_tree_then_new_task_scheduled_as_top_level_task_at_interactive_priority() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp, \
            scheduler_disabled():
        # Define URLs
        comic1_url = sp.get_request_url('https://xkcd.com/1/')
        comic2_url = sp.get_request_url('https://xkcd.com/2/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create comic #1 RootResource
            comic1_resource = Resource(project, comic1_url)
            comic1_rr = RootResource(project, 'Comic #1', comic1_resource)
            
            # Create comic #2 RootResource
            comic2_resource = Resource(project, comic2_url)
            comic2_rr = RootResource(project, 'Comic #2', comic2_resource)
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            comic1_ti = root_ti.find_child(comic1_url, project.default_url_prefix)
            comic2_ti = root_ti.find_child(comic2_url, project.default_url_prefix)
            
            () = project.root_task.children
            
            # Start download of comic #1 at non-interactive priority
            comic1_ti.SelectItem()
            click_button(mw.download_button)
            
            # Start download of comic #2 at interactive priority
            comic2_ti.SelectItem()
            comic2_ti.Expand(); append_deferred_top_level_tasks(project)
            
            # Ensure both DownloadResourceTasks are scheduled at top-level with correct priority
            if True:
                (comic1_download_task, comic2_download_task) = project.root_task.children
                
                assert isinstance(comic1_download_task, DownloadResourceTask)
                assertEqual(comic1_resource, comic1_download_task.resource)
                assertEqual(False, comic1_download_task.interactive)
                
                assert isinstance(comic2_download_task, DownloadResourceTask)
                assertEqual(comic2_resource, comic2_download_task.resource)
                assertEqual(True, comic2_download_task.interactive)


# NOTE: See the (populate_download_group_task_members == True) case of the referenced test
@skip('covered by: test_when_top_level_task_is_interactive_priority_then_is_scheduled_before_any_non_interactive_tasks')
async def test_when_download_resource_at_interactive_priority_given_same_resource_already_in_task_tree_but_not_at_top_level_then_task_alias_scheduled_as_top_level_task_at_interactive_priority() -> None:
    pass


async def test_when_download_resource_at_interactive_priority_given_same_resource_already_in_task_tree_at_top_level_then_either_top_level_task_upgraded_to_interactive_priority_or_new_top_level_task_created_at_interactive_priority() -> None:
    # - If the same resource is requested with needs_result=False first and then
    #   needs_result=True second then two top-level tasks will be created.
    #   (This is the only scenario currently exercised by this test.)
    # - In all other combinations a single top-level task will be shared.
    
    with served_project('testdata_xkcd.crystalproj.zip') as sp, \
            scheduler_disabled():
        # Define URLs
        comic1_url = sp.get_request_url('https://xkcd.com/1/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            # Create comic #1 RootResource
            comic1_resource = Resource(project, comic1_url)
            comic1_rr = RootResource(project, 'Comic #1', comic1_resource)
            
            root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
            comic1_ti = root_ti.find_child(comic1_url, project.default_url_prefix)
            
            # Start download of comic #1 RootResource at non-interactive priority
            # by selecting corresponding entity tree node and pressing Download button
            () = project.root_task.children
            comic1_ti.SelectItem()
            click_button(mw.download_button)
            append_deferred_top_level_tasks(project)
            
            # Ensure DownloadResourceTask for comic #1 scheduled at top-level of task tree
            # with interactive=False priority
            (comic1_download_task,) = project.root_task.children
            assert isinstance(comic1_download_task, DownloadResourceTask)
            assertEqual(comic1_resource, comic1_download_task.resource)
            assertEqual(False, comic1_download_task.interactive)
            
            # Restart download of comic #1 RootResource at interactive priority
            # by selecting corresponding entity tree node and expanding it
            comic1_ti.SelectItem()
            comic1_ti.Expand(); append_deferred_top_level_tasks(project)
            
            # Either:
            # 1. Ensure the same DownloadResourceTask is still at top-level of task tree
            #    but now upgraded to interactive=True priority
            # 2. A new DownloadResourceTask is at top-level of task tree
            #    with interactive=True priority
            if len(project.root_task.children) == 1:
                (same_comic1_download_task,) = project.root_task.children
                assert same_comic1_download_task is comic1_download_task  # same instance
                assert isinstance(same_comic1_download_task, DownloadResourceTask)
                assertEqual(comic1_resource, same_comic1_download_task.resource)
                assertEqual(True, same_comic1_download_task.interactive)  # upgraded priority
            else:
                (_, new_comic1_download_task) = project.root_task.children
                assert isinstance(new_comic1_download_task, DownloadResourceTask)
                assertEqual(comic1_resource, new_comic1_download_task.resource)
                assertEqual(True, new_comic1_download_task.interactive)


# ==============================================================================
# Test: Scheduler

@skip('covered by: test_when_scheduler_thread_event_loop_crashes_then_RT_marked_as_crashed_and_scheduler_crashed_task_appears')
async def test_when_scheduler_thread_crashes_then_scheduler_crashed_task_appears():
    pass


# ==============================================================================
