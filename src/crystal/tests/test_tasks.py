from crystal.task import ProjectFreeSpaceTooLowError
from crystal.tests.util.data import MAX_TIME_TO_DOWNLOAD_XKCD_HOME_URL_BODY
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.server import served_project
from crystal.tests.util.subtests import SubtestsContext, awith_subtests
from crystal.tests.util.wait import wait_for
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.model import Project, Resource
import tempfile
from typing import NamedTuple
from unittest import skip
from unittest.mock import patch


# ------------------------------------------------------------------------------
# Test: DownloadResourceBodyTask

# (TODO: Add basic tests)


# ------------------------------------------------------------------------------
# Test: DownloadResourceTask
#       (+ DownloadResourceBodyTask)
#       (+ ParseResourceRevisionLinks)

# (TODO: Add basic tests)

@skip('not yet automated')
async def test_when_download_resource_then_displays_estimated_time_remaining() -> None:
    pass


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


# ------------------------------------------------------------------------------
