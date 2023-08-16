from crystal.task import (
    ASSUME_RESOURCES_DOWNLOADED_IN_SESSION_WILL_ALWAYS_REMAIN_FRESH,
    ProjectFreeSpaceTooLowError
)
from crystal.tests.util.asserts import *
from crystal.tests.util.data import (
    MAX_TIME_TO_DOWNLOAD_404_URL,
    MAX_TIME_TO_DOWNLOAD_XKCD_HOME_URL_BODY
)
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.screenshots import screenshot_if_raises
from crystal.tests.util.server import served_project
from crystal.tests.util.skip import skipTest
from crystal.tests.util.subtests import SubtestsContext, awith_subtests
from crystal.tests.util.wait import wait_for
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.model import Project, Resource, ResourceGroup, RootResource
from crystal.util.progress import ProgressBarCalculator
import tempfile
from tqdm import tqdm
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
        
        with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
            async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
                project = Project._last_opened_project
                assert project is not None
                
                missing_r = Resource(project, missing_url)
                
                with subtests.test(task_type='DownloadResourceTask'):
                    # Download the resource
                    assert False == missing_r.already_downloaded_this_session
                    missing_rr_future = missing_r.download()  # uses DownloadResourceTask
                    with screenshot_if_raises():
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
                    with screenshot_if_raises():
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
                    drg_task = comic_g.create_download_task()
                    assert True == drg_task.complete


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
            if True:
                home_url = sp.get_request_url('https://xkcd.com/')
            
            with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
                async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
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
            if True:
                home_url = sp.get_request_url('https://xkcd.com/')
            
            with tempfile.TemporaryDirectory(suffix='.crystalproj') as project_dirpath:
                async with (await OpenOrCreateDialog.wait_for()).create(project_dirpath) as (mw, _):
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

@skip('not yet automated')
async def test_when_get_task_unit_raises_unexpected_exception_then_scheduler_restarts():
    pass


@skip('not yet automated')
async def test_when_run_task_unit_raises_unexpected_exception_then_scheduler_restarts():
    pass


# ==============================================================================
