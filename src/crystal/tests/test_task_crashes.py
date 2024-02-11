from contextlib import redirect_stderr
from crystal.task import (
    bulkhead,
    DownloadResourceGroupTask, DownloadResourceGroupMembersTask, 
    _DownloadResourcesPlaceholderTask, DownloadResourceTask,
    scheduler_thread_context, Task, UpdateResourceGroupMembersTask
)
from crystal.tests.util.controls import click_button
from crystal.tests.util.server import served_project
from crystal.tests.util.tasks import (
    append_deferred_top_level_tasks,
    clear_top_level_tasks_on_exit, scheduler_disabled
)
from crystal.tests.util.wait import wait_for
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.model import Project, Resource, ResourceGroup
from crystal.util import cli
from crystal.util.wx_bind import bind
from crystal.util.xfutures import Future
from crystal.util.xthreading import bg_call_later, is_foreground_thread
from io import StringIO
import sys
from typing import Callable, Optional, TypeVar
from unittest import skip
from unittest.mock import patch
import wx


_R = TypeVar('_R')


# ------------------------------------------------------------------------------
# Test: Print Unhandled Exceptions
#
# In general:
# - Tracebacks for all unhandled exceptions should be printed to the stderr.
# - If such an exception is forwarded to the GUI, it need only be printed in
#   a yellow warning color, since it should be visible to GUI-only users.
# - If such an exception is NOT forwarded to the GUI, it should be printed in
#   a red error color, since it is INVISIBLE to GUI-only users.

async def test_given_inside_bulkhead_when_unhandled_exception_raised_then_traceback_printed_to_stderr_as_yellow_warning() -> None:
    def the_bulkhead_caller() -> None:
        some_task = _DownloadResourcesPlaceholderTask(1)
        
        @bulkhead
        def the_bulkhead(task_context: Task) -> None:
            raise ValueError('Unhandled error inside bulkhead')
        the_bulkhead(some_task)
        
    with redirect_stderr(StringIO()) as captured_stderr:
        the_bulkhead_caller()
    assert 'Exception in bulkhead:' in captured_stderr.getvalue()
    assert 'Traceback' in captured_stderr.getvalue()
    assert cli.TERMINAL_FG_YELLOW in captured_stderr.getvalue()


async def test_given_inside_wxpython_listener_when_exception_raised_then_traceback_printed_to_stderr_as_red_error() -> None:
    frame = wx.Frame(None, title='Button Frame')
    try:
        button = wx.Button(frame, label='Button')
        def action_func(event: wx.CommandEvent):
            raise ValueError('Simulated error in wxPython listener')
        bind(button, wx.EVT_BUTTON, action_func)
        
        assert is_foreground_thread()
        with redirect_stderr(StringIO()) as captured_stderr:
            click_button(button)
        assert 'Exception in wxPython listener:' in captured_stderr.getvalue()
        assert 'Traceback' in captured_stderr.getvalue()
        assert cli.TERMINAL_FG_RED in captured_stderr.getvalue()
    finally:
        frame.Destroy()


async def test_given_inside_background_thread_when_exception_raised_then_traceback_printed_to_stderr_as_red_error() -> None:
    def bg_task() -> None:
        raise ValueError('Simulated error in background thread')
    with redirect_stderr(StringIO()) as captured_stderr:
        thread = bg_call_later(bg_task)
        thread.join()
    assert 'Exception in background thread:' in captured_stderr.getvalue()
    assert 'Traceback' in captured_stderr.getvalue()
    assert cli.TERMINAL_FG_RED in captured_stderr.getvalue()


async def test_given_inside_main_thread_when_exception_raised_then_traceback_printed_to_stderr_as_red_error() -> None:
    try:
        raise ValueError('Simulated crash in main thread')
    except Exception as e_:
        e = e_  # capture
    
    with redirect_stderr(StringIO()) as captured_stderr:
        sys.excepthook(type(e), e, e.__traceback__)
    assert 'Exception in main thread:' in captured_stderr.getvalue()
    assert 'Traceback' in captured_stderr.getvalue()
    assert cli.TERMINAL_FG_RED in captured_stderr.getvalue()


async def test_given_inside_unraisable_context_when_exception_raised_then_traceback_printed_to_stderr_as_red_error() -> None:
    def object_holder() -> None:
        class CrashesDuringFinalization:
            def __del__(self) -> None:
                raise ValueError('Simulated error in object.__del__')
        CrashesDuringFinalization()
    
    with redirect_stderr(StringIO()) as captured_stderr:
        object_holder()
    assert 'Exception in unraisable context:' in captured_stderr.getvalue()
    assert 'Traceback' in captured_stderr.getvalue()
    assert cli.TERMINAL_FG_RED in captured_stderr.getvalue()


# ------------------------------------------------------------------------------
# Test: Common Crash Locations in Task
# 
# Below, some abbreviations are used in test names:
# - T = Task
# - DRT = DownloadResourceTask
# - DRGMT = DownloadResourceGroupMembersTask
# - DRGT = DownloadResourceGroupTask

async def test_when_T_try_get_next_task_unit_crashes_then_T_displays_as_crashed() -> None:
    with scheduler_disabled, scheduler_thread_context(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
            project = Project._last_opened_project
            assert project is not None
            
            with clear_top_level_tasks_on_exit(project):
                # Create DownloadResourceTask
                home_r = Resource(project, home_url)
                home_r.download(); append_deferred_top_level_tasks(project)
                (download_r_task,) = project.root_task.children
                assert isinstance(download_r_task, DownloadResourceTask)
                
                # Force DownloadResourceTask into an illegal state
                # (i.e. a container task with empty children)
                # which should crash the next call to DRG.try_get_next_task_unit()
                assert len(download_r_task.children) > 0
                download_r_task._children = []
                
                # Precondition
                assert download_r_task.crash_reason is None
                
                unit = project.root_task.try_get_next_task_unit()  # step scheduler
                assert unit is None
                
                # Postcondition
                assert download_r_task.crash_reason is not None


async def test_when_DRT_child_task_did_complete_event_crashes_then_DRT_displays_as_crashed() -> None:
    with scheduler_disabled, scheduler_thread_context(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
            project = Project._last_opened_project
            assert project is not None
            
            with clear_top_level_tasks_on_exit(project):
                # Create DownloadResourceTask
                home_r = Resource(project, home_url)
                home_r.download(); append_deferred_top_level_tasks(project)
                (download_r_task,) = project.root_task.children
                assert isinstance(download_r_task, DownloadResourceTask)
                
                # Precondition
                assert download_r_task.crash_reason is None
                
                # Download URL
                unit = project.root_task.try_get_next_task_unit()  # step scheduler
                assert unit is not None
                await _bg_call_and_wait(scheduler_thread_context()(unit))
                
                # Parse links
                unit = project.root_task.try_get_next_task_unit()  # step scheduler
                assert unit is not None
                # Patch urljoin() to simulate effect of calling urlparse('//[oops'),
                # which raises an exception in stock Python:
                # https://discuss.python.org/t/urlparse-can-sometimes-raise-an-exception-should-it/44465
                # 
                # NOTE: Overrides the fix in commit 5aaaba57076d537a4872bb3cf7270112ca497a06,
                #       reintroducing the related bug it fixed.
                with patch('crystal.task.urljoin', side_effect=ValueError('Invalid IPv6 URL')):
                    await _bg_call_and_wait(scheduler_thread_context()(unit))
                
                # Postcondition:
                # Ensure crashed in DownloadResourceTask.child_task_did_complete(),
                # when tried to resolve relative_urls from links parsed by
                # ParseResourceRevisionLinks to absolute URLs
                assert download_r_task.crash_reason is not None


async def test_when_DRGMT_load_children_crashes_then_DRGT_displays_as_crashed() -> None:
    with scheduler_disabled, scheduler_thread_context(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
            project = Project._last_opened_project
            assert project is not None
            
            with clear_top_level_tasks_on_exit(project):
                atom_feed_r = Resource(project, atom_feed_url)
                rss_feed_r = Resource(project, rss_feed_url)
                
                # Create DownloadResourceGroupMembersTask
                feed_g = ResourceGroup(project, '', feed_pattern, source=None)
                feed_g.download(); append_deferred_top_level_tasks(project)
                (download_rg_task,) = project.root_task.children
                assert isinstance(download_rg_task, DownloadResourceGroupTask)
                (update_rg_members_task, download_rg_members_task) = download_rg_task.children
                assert isinstance(update_rg_members_task, UpdateResourceGroupMembersTask)
                assert isinstance(download_rg_members_task, DownloadResourceGroupMembersTask)
                
                # Capture download_rg_members_task.{_pdb, _children_loaded, subtitle}
                # after exiting DownloadResourceGroupMembersTask.__init__()
                pbc_after_init = download_rg_members_task._pbc
                children_loaded_after_init = download_rg_members_task._children_loaded
                subtitle_after_init = download_rg_members_task.subtitle
                assert None == pbc_after_init
                assert False == children_loaded_after_init
                assert 'Queued' == subtitle_after_init
                
                initialize_children_error = ValueError(
                    'Simulated error raised by task_did_set_children() listener '
                    'that was called by initialize_children()'
                )
                
                # Precondition
                assert download_rg_members_task.crash_reason is None
                
                # Load children of DownloadResourceGroupMembersTask
                unit = project.root_task.try_get_next_task_unit()  # step scheduler
                assert unit is not None
                # Patch DownloadResourceGroupMembersTask.initialize_children() to reintroduce
                # a bug in DownloadResourceGroupMembersTask._load_children() that was
                # fixed in commit 44f5bd429201972d324df1287e673ddef9ffa936
                with patch.object(download_rg_members_task, 'initialize_children', side_effect=initialize_children_error):
                    await _bg_call_and_wait(scheduler_thread_context()(unit))
                
                # Postcondition
                assert download_rg_members_task.crash_reason is not None


async def test_when_DRGMT_group_did_add_member_event_crashes_then_DRGT_displays_as_crashed() -> None:
    with scheduler_disabled, scheduler_thread_context(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, _):
            project = Project._last_opened_project
            assert project is not None
            
            with clear_top_level_tasks_on_exit(project):
                atom_feed_r = Resource(project, atom_feed_url)
                
                # Create DownloadResourceGroupMembersTask
                feed_g = ResourceGroup(project, '', feed_pattern, source=None)
                feed_g.download(); append_deferred_top_level_tasks(project)
                (download_rg_task,) = project.root_task.children
                assert isinstance(download_rg_task, DownloadResourceGroupTask)
                (update_rg_members_task, download_rg_members_task) = download_rg_task.children
                assert isinstance(update_rg_members_task, UpdateResourceGroupMembersTask)
                assert isinstance(download_rg_members_task, DownloadResourceGroupMembersTask)
                
                super_notify_did_append_child = download_rg_members_task.notify_did_append_child
                def notify_did_append_child(*args, **kwargs):
                    super_notify_did_append_child(*args, **kwargs)
                    
                    # Simulate failure of `self._pbc.total += 1`
                    # due to self._pbc being unset, due to known issue:
                    # https://github.com/davidfstr/Crystal-Web-Archiver/issues/141
                    raise AttributeError("'DownloadResourceGroupMembersTask' object has no attribute '_pbc'")
                
                # Precondition
                assert download_rg_members_task.crash_reason is None
                
                with patch.object(download_rg_members_task, 'notify_did_append_child', notify_did_append_child):
                    rss_feed_r = Resource(project, rss_feed_url)
                
                # Postcondition
                assert download_rg_members_task.crash_reason is not None


# ------------------------------------------------------------------------------
# Utility

async def _bg_call_and_wait(callable: Callable[[], _R], *, timeout: Optional[float]=None) -> _R:
    """
    Start the specified callable on a background thread and
    waits for it to finish running.
    
    The foreground thread IS released while waiting, so the callable can safely
    make calls to fg_call_later() and fg_call_and_wait() without deadlocking.
    """
    result_cell = Future()  # type: Future[_R]
    def bg_task() -> None:
        result_cell.set_running_or_notify_cancel()
        try:
            result_cell.set_result(callable())
        except BaseException as e:
            result_cell.set_exception(e)
    bg_call_later(bg_task)
    # NOTE: Releases foreground thread while waiting
    await wait_for(lambda: result_cell.done() or None, timeout)
    return result_cell.result()


# ------------------------------------------------------------------------------
