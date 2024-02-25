from crystal.task import (
    ASSUME_RESOURCES_DOWNLOADED_IN_SESSION_WILL_ALWAYS_REMAIN_FRESH,
    ProjectFreeSpaceTooLowError, Task,
)
from crystal.tests.util.asserts import *
from crystal.tests.util.data import (
    MAX_TIME_TO_DOWNLOAD_404_URL,
    MAX_TIME_TO_DOWNLOAD_XKCD_HOME_URL_BODY
)
from crystal.tests.util.downloads import load_children_of_drg_task
from crystal.tests.util.server import served_project
from crystal.tests.util.skip import skipTest
from crystal.tests.util.subtests import SubtestsContext, awith_subtests
from crystal.tests.util.tasks import scheduler_thread_context
from crystal.tests.util.wait import wait_for
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.model import Project, Resource, ResourceGroup
from crystal.util.progress import ProgressBarCalculator
from crystal.util.xcollections.lazy import AppendableLazySequence
from typing import NamedTuple
from unittest import skip
from unittest.mock import patch, Mock, PropertyMock


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
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
            project = Project._last_opened_project
            assert project is not None
            
            missing_r = Resource(project, missing_url)
            
            with subtests.test(task_type='DownloadResourceTask'):
                # Download the resource
                assert False == missing_r.already_downloaded_this_session
                missing_rr_future = missing_r.download()  # uses DownloadResourceTask
                await wait_for(
                    lambda: missing_rr_future.done() or None,
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
                        task_unit = project.root_task.try_get_next_task_unit()
                        assert task_unit is None
                    
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
                    rr = rr_future.result()
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
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
                project = Project._last_opened_project
                assert project is not None
                
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
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
                project = Project._last_opened_project
                assert project is not None
                
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


# ------------------------------------------------------------------------------
# Test: RootTask

# (TODO: Add basic tests)


# ==============================================================================
# Test: Scheduler

@skip('covered by: test_when_scheduler_thread_event_loop_crashes_then_RT_marked_as_crashed_and_scheduler_crashed_task_appears')
async def test_when_scheduler_thread_crashes_then_scheduler_crashed_task_appears():
    pass


# ==============================================================================
