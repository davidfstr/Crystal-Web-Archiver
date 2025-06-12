from contextlib import redirect_stderr
from crystal import task
from crystal.browser import MainWindow as RealMainWindow
from crystal.browser.entitytree import _ErrorNode, ResourceGroupNode
from crystal.browser.tasktree import TaskTreeNode
from crystal.doc.generic import create_external_link, Link
from crystal.model import Project, Resource, ResourceGroup, RootResource
import crystal.task
from crystal.task import (
    _DownloadResourcesPlaceholderTask, CrashedTask,
    DownloadResourceGroupMembersTask, DownloadResourceGroupTask,
    DownloadResourceTask, ParseResourceRevisionLinks, Task,
    UpdateResourceGroupMembersTask,
)
from crystal.tests.util.controls import (
    click_button, select_menuitem_now, TreeItem,
)
from crystal.tests.util.runner import pump_wx_events
from crystal.tests.util.server import served_project
from crystal.tests.util.skip import skipTest
from crystal.tests.util.tasks import (
    append_deferred_top_level_tasks, clear_top_level_tasks_on_exit,
    first_task_title_progression, MAX_DOWNLOAD_DURATION_PER_ITEM,
    scheduler_disabled, scheduler_thread_context, step_scheduler,
    step_scheduler_now, ttn_for_task,
)
from crystal.tests.util.wait import (
    first_child_of_tree_item_is_not_loading_condition, wait_for, wait_while,
)
from crystal.tests.util.windows import OpenOrCreateDialog
from crystal.tests.util.xthreading import bg_call_and_wait as _bg_call_and_wait
from crystal.ui.tree import NodeView
from crystal.util import cli
from crystal.util.bulkheads import (
    capture_crashes_to_bulkhead_arg as capture_crashes_to_task_arg,
)
from crystal.util.bulkheads import (
    capture_crashes_to_self, capture_crashes_to_stderr, crashes_captured_to,
    run_bulkhead_call,
)
from crystal.util.bulkheads import BulkheadCell, capture_crashes_to
from crystal.util.ellipsis import Ellipsis, EllipsisType
from crystal.util.wx_bind import bind
from crystal.util.xos import is_asan, is_ci, is_mac_os
from crystal.util.xthreading import (
    bg_call_later, fg_call_and_wait, is_foreground_thread,
)
from io import StringIO
import sys
import threading
from typing import List, Tuple
from unittest import skip
from unittest.mock import patch
import wx

_CRASH = ValueError('Simulated crash')


# Marks tests that frequently trigger use-after-free errors by closing
# a project that is still in the middle of running tasks.
# 
# When CRYSTAL_IGNORE_USE_AFTER_FREE=False has been made the default
# and marked tests have been fixed to not trigger use-after-free errors,
# this decorator can be retired.
frequently_corrupts_memory = (
    skip('frequently corrupts memory')
    if is_mac_os() and is_ci() and not is_asan()
    else (lambda f: f)
)


# ------------------------------------------------------------------------------
# Test: capture_crashes_to*

async def test_capture_crashes_to_self_decorator_works() -> None:
    class MyTask(_DownloadResourcesPlaceholderTask):
        def __init__(self) -> None:
            super().__init__(1)
        
        @capture_crashes_to_self
        def foo_did_bar(self) -> None:
            raise _CRASH
    my_task = MyTask()
    
    assert my_task.crash_reason is None
    my_task.foo_did_bar()
    assert my_task.crash_reason is not None


async def test_capture_crashes_to_self_decorator_with_custom_return_value_works() -> None:
    class MyTask(_DownloadResourcesPlaceholderTask):
        def __init__(self) -> None:
            super().__init__(1)
        
        @capture_crashes_to_self(return_if_crashed=Ellipsis)
        def calculate_foo(self) -> int:
            if False:
                return 1
            else:
                raise _CRASH
    my_task = MyTask()
    
    assert my_task.crash_reason is None
    assert Ellipsis == my_task.calculate_foo()
    assert my_task.crash_reason is not None


async def test_capture_crashes_to_bulkhead_arg_decorator_works() -> None:
    class MyTask(_DownloadResourcesPlaceholderTask):
        def __init__(self) -> None:
            super().__init__(1)
        
        @capture_crashes_to_task_arg
        def task_foo_did_change(self, task: Task) -> None:
            raise _CRASH
    my_task = MyTask()
    other_task = _DownloadResourcesPlaceholderTask(1)
    
    assert other_task.crash_reason is None
    assert my_task.crash_reason is None
    
    my_task.task_foo_did_change(other_task)
    
    assert other_task.crash_reason is not None
    assert my_task.crash_reason is None


async def test_capture_crashes_to_bulkhead_arg_decorator_with_custom_return_value_works() -> None:
    class MyTask(_DownloadResourcesPlaceholderTask):
        def __init__(self) -> None:
            super().__init__(1)
        
        @capture_crashes_to_task_arg(return_if_crashed=Ellipsis)
        def calculate_foo(self, task: Task) -> int:
            if False:
                return 1
            else:
                raise _CRASH
    my_task = MyTask()
    other_task = _DownloadResourcesPlaceholderTask(1)
    
    assert other_task.crash_reason is None
    assert my_task.crash_reason is None
    
    assert Ellipsis == my_task.calculate_foo(other_task)
    
    assert other_task.crash_reason is not None
    assert my_task.crash_reason is None


async def test_capture_crashes_to_decorator_works() -> None:
    class MyTask(_DownloadResourcesPlaceholderTask):
        def __init__(self) -> None:
            super().__init__(1)
        
        def foo_did_bar(self) -> None:
            @capture_crashes_to(self)
            def fg_task() -> None:
                raise _CRASH
            fg_call_and_wait(fg_task)
    my_task = MyTask()
    
    assert my_task.crash_reason is None
    my_task.foo_did_bar()
    assert my_task.crash_reason is not None


async def test_capture_crashes_to_decorator_with_custom_return_value_works() -> None:
    bulkhead = BulkheadCell()
    
    @capture_crashes_to(bulkhead, return_if_crashed=Ellipsis)
    def calculate_foo() -> int:
        if False:
            return 1
        else:
            raise _CRASH
    
    assert bulkhead.crash_reason is None
    assert Ellipsis == calculate_foo()
    assert bulkhead.crash_reason is not None


def test_crashes_captured_to_context_manager_works() -> None:
    bulkhead = BulkheadCell()
    assert None == bulkhead.crash_reason
    
    try:
        with crashes_captured_to(bulkhead):
            pass
    except NotImplementedError:
        pass
    else:
        raise AssertionError(
            'Expected crashes_captured_to() to raise NotImplementedError')
    
    with crashes_captured_to(bulkhead, enter_if_crashed=True):
        pass
    assert None == bulkhead.crash_reason
    
    with crashes_captured_to(bulkhead, enter_if_crashed=True):
        def foo() -> None:
            def bar() -> None:
                raise _CRASH
            bar()
        foo()
    assert _CRASH == bulkhead.crash_reason


async def test_capture_crashes_to_stderr_decorator_works() -> None:
    @capture_crashes_to_stderr
    def report_error() -> None:
        raise _CRASH
    
    with redirect_stderr(StringIO()) as captured_stderr:
        report_error()
    assert 'Exception in bulkhead:' in captured_stderr.getvalue()
    assert 'Traceback' in captured_stderr.getvalue()
    assert cli.TERMINAL_FG_RED in captured_stderr.getvalue()


async def test_capture_crashes_to_stderr_decorator_with_custom_return_value_works() -> None:
    @capture_crashes_to_stderr(return_if_crashed=Ellipsis)
    def calculate_foo() -> int:
        if False:
            return 1
        else:
            raise _CRASH
    
    with redirect_stderr(StringIO()) as captured_stderr:
        assert Ellipsis == calculate_foo()
    assert 'Exception in bulkhead:' in captured_stderr.getvalue()
    assert 'Traceback' in captured_stderr.getvalue()
    assert cli.TERMINAL_FG_RED in captured_stderr.getvalue()


async def test_given_callable_decorated_by_capture_crashes_to_star_decorator_when_run_bulkhead_call_used_then_calls_callable() -> None:
    @capture_crashes_to_stderr
    def protected_method():
        protected_method.called = True
    
    def unprotected_method():
        unprotected_method.called = True
    
    run_bulkhead_call(protected_method)
    assert True == getattr(protected_method, 'called', False)
    
    try:
        run_bulkhead_call(unprotected_method)
    except AssertionError:
        pass  # expected
    assert False == getattr(unprotected_method, 'called', False)


@skip('covered by: test_given_callable_decorated_by_capture_crashes_to_star_decorator_when_run_bulkhead_call_used_then_calls_callable')
async def test_given_not_callable_decorated_by_capture_crashes_to_star_decorator_when_run_bulkhead_call_used_then_raises() -> None:
    pass


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
    with redirect_stderr(StringIO()) as captured_stderr:
        class MyTask(_DownloadResourcesPlaceholderTask):
            def __init__(self) -> None:
                super().__init__(1)
            
            @capture_crashes_to_self
            def protected_method(self) -> None:
                raise _CRASH
        
        MyTask().protected_method()
    assert 'Exception in bulkhead:' in captured_stderr.getvalue()
    assert 'Traceback' in captured_stderr.getvalue()
    assert cli.TERMINAL_FG_YELLOW in captured_stderr.getvalue()


async def test_given_inside_wxpython_listener_when_exception_raised_then_traceback_printed_to_stderr_as_red_error() -> None:
    frame = wx.Frame(None, title='Button Frame')
    try:
        button = wx.Button(frame, label='Button')
        def action_func(event: wx.CommandEvent):
            raise _CRASH
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
        raise _CRASH
    with redirect_stderr(StringIO()) as captured_stderr:
        # NOTE: Most creators of background threads in Crystal prefer to use
        #       bg_call_later() rather than creating a Thread directly.
        #       
        #       bg_call_later() already enforces that its callable
        #       is wrapped with @capture_crashes_to* and reports any
        #       unhandled exceptions somewhere sensible, but bare
        #       Threads don't.
        thread = threading.Thread(target=bg_task)
        thread.start()
        thread.join()
    assert 'Exception in background thread:' in captured_stderr.getvalue()
    assert 'Traceback' in captured_stderr.getvalue()
    assert cli.TERMINAL_FG_RED in captured_stderr.getvalue()


async def test_given_inside_main_thread_when_exception_raised_then_traceback_printed_to_stderr_as_red_error() -> None:
    try:
        raise _CRASH
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
                raise _CRASH
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
# - DRGMT = DownloadResourceGroupMembersTask
# - DRGT = DownloadResourceGroupTask
# - DRT = DownloadResourceTask
# - T = Task

@frequently_corrupts_memory
async def test_when_T_try_get_next_task_unit_crashes_then_T_displays_as_crashed() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
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
                
                await step_scheduler(project, expect_done=True)
                
                # Postcondition
                assert download_r_task.crash_reason is not None


@frequently_corrupts_memory
async def test_when_DRT_child_task_did_complete_event_crashes_then_DRT_displays_as_crashed() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                # Create DownloadResourceTask
                home_r = Resource(project, home_url)
                home_r.download(); append_deferred_top_level_tasks(project)
                (download_r_task,) = project.root_task.children
                assert isinstance(download_r_task, DownloadResourceTask)
                
                # Precondition
                assert download_r_task.crash_reason is None
                
                # Download URL
                await step_scheduler(project)
                
                # Parse links
                #
                # Patch urljoin() to simulate effect of calling urlparse('//[oops'),
                # which raises an exception in stock Python:
                # https://discuss.python.org/t/urlparse-can-sometimes-raise-an-exception-should-it/44465
                # 
                # NOTE: Overrides the fix in commit 5aaaba57076d537a4872bb3cf7270112ca497a06,
                #       reintroducing the related bug it fixed.
                with patch('crystal.task.urljoin', side_effect=ValueError('Invalid IPv6 URL')):
                    await step_scheduler(project)
                
                # Postcondition:
                # Ensure crashed in DownloadResourceTask.child_task_did_complete(),
                # when tried to resolve relative_urls from links parsed by
                # ParseResourceRevisionLinks to absolute URLs
                assert download_r_task.crash_reason is not None


@frequently_corrupts_memory
async def test_when_DRGMT_load_children_crashes_then_DRGT_displays_as_crashed() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                Resource(project, atom_feed_url)
                Resource(project, rss_feed_url)
                
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
                
                # Precondition
                assert download_rg_members_task.crash_reason is None
                
                # Load children of DownloadResourceGroupMembersTask
                # 
                # Patch DownloadResourceGroupMembersTask.initialize_children() to reintroduce
                # a bug in DownloadResourceGroupMembersTask._load_children() that was
                # fixed in commit 44f5bd429201972d324df1287e673ddef9ffa936
                with patch.object(download_rg_members_task, 'initialize_children', side_effect=_CRASH):
                    await step_scheduler(project)
                
                # Postcondition
                assert download_rg_members_task.crash_reason is not None


@frequently_corrupts_memory
async def test_when_DRGMT_group_did_add_member_event_crashes_then_DRGT_displays_as_crashed() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                Resource(project, atom_feed_url)
                
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
                    # 
                    # TODO: Once that issue is fixed, replace the next line with:
                    #           raise _CRASH
                    raise AttributeError("'DownloadResourceGroupMembersTask' object has no attribute '_pbc'")
                
                # Precondition
                assert download_rg_members_task.crash_reason is None
                
                with patch.object(download_rg_members_task, 'notify_did_append_child', notify_did_append_child):
                    Resource(project, rss_feed_url)
                
                # Postcondition
                assert download_rg_members_task.crash_reason is not None


# ------------------------------------------------------------------------------
# Test: Common Crash Locations in TaskTreeNode
# 
# Below, some abbreviations are used in test names:
# - T = Task
# - TTN = TaskTreeNode

@skip('not yet automated: hard to automate: hard to patch')
async def test_when_TTN_task_crash_reason_did_change_crashes_at_top_level_then_crash_reason_printed_to_stderr() -> None:
    # TODO: In TaskTreeNode.task_crash_reason_did_change,
    #       crash the line: fg_call_later(fg_task, profile=False)
    #       even though that specific line is unrealistic,
    #       because there isn't a better more-realistic candidate line available
    pass


@frequently_corrupts_memory
async def test_when_TTN_task_crash_reason_did_change_crashes_in_deferred_fg_task_then_crash_reason_printed_to_stderr() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                # Create DownloadResourceTask and TaskTreeNode
                home_r = Resource(project, home_url)
                home_r.download(); append_deferred_top_level_tasks(project)
                (download_r_task,) = project.root_task.children
                assert isinstance(download_r_task, DownloadResourceTask)
                ttn_for_task(download_r_task)
                
                # Force DownloadResourceTask into an illegal state
                # (i.e. a container task with empty children)
                # which should crash the next call to DRG.try_get_next_task_unit()
                assert len(download_r_task.children) > 0
                download_r_task._children = []
                
                # Precondition
                assert download_r_task.crash_reason is None
                
                # In TaskTreeNode.task_crash_reason_did_change,
                # crash the line: ... = self._calculate_tree_node_subtitle(task_subtitle, task_crash_reason)
                with patch('crystal.browser.tasktree.TaskTreeNode._calculate_tree_node_subtitle', side_effect=_CRASH) as crash_point:
                    with redirect_stderr(StringIO()) as captured_stderr:
                        await step_scheduler(project, expect_done=True)
                
                # Postconditions
                if True:
                    assert download_r_task.crash_reason is not None
                    assert crash_point.call_count >= 1
                    
                    assert 'Exception in bulkhead:' in captured_stderr.getvalue()
                    assert 'Traceback' in captured_stderr.getvalue()
                    assert cli.TERMINAL_FG_RED in captured_stderr.getvalue()


@frequently_corrupts_memory
async def test_when_TTN_task_did_set_children_crashes_at_top_level_then_T_displays_as_crashed() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                Resource(project, atom_feed_url)
                Resource(project, rss_feed_url)
                
                # Create DownloadResourceGroupMembersTask
                feed_g = ResourceGroup(project, '', feed_pattern, source=None)
                feed_g.download(); append_deferred_top_level_tasks(project)
                (download_rg_task,) = project.root_task.children
                assert isinstance(download_rg_task, DownloadResourceGroupTask)
                (update_rg_members_task, download_rg_members_task) = download_rg_task.children
                assert isinstance(update_rg_members_task, UpdateResourceGroupMembersTask)
                assert isinstance(download_rg_members_task, DownloadResourceGroupMembersTask)
                
                # Precondition
                assert download_rg_members_task.crash_reason is None
                
                # In TaskTreeNode.task_did_set_children,
                # crash the assertion: assert self._num_visible_children == visible_child_count
                if True:
                    super_task_did_set_children = TaskTreeNode.task_did_set_children
                    # NOTE: Need some kind of @capture_crashes_to* here to pass caller checks
                    @capture_crashes_to_stderr
                    def task_did_set_children(self, task: Task, child_count: int) -> None:
                        # Corrupt the value of self._num_visible_children
                        self._num_visible_children += 100
                        return super_task_did_set_children(self, task, child_count)
                    
                    # Load children of DownloadResourceGroupMembersTask
                    with patch.object(TaskTreeNode, 'task_did_set_children', task_did_set_children):
                        await step_scheduler(project)
                
                # Postcondition
                assert download_rg_members_task.crash_reason is not None


@frequently_corrupts_memory
async def test_when_TTN_task_did_set_children_crashes_in_deferred_fg_task_then_T_displays_as_crashed() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                Resource(project, atom_feed_url)
                Resource(project, rss_feed_url)
                
                # Create DownloadResourceGroupMembersTask
                feed_g = ResourceGroup(project, '', feed_pattern, source=None)
                feed_g.download(); append_deferred_top_level_tasks(project)
                (download_rg_task,) = project.root_task.children
                assert isinstance(download_rg_task, DownloadResourceGroupTask)
                (update_rg_members_task, download_rg_members_task) = download_rg_task.children
                assert isinstance(update_rg_members_task, UpdateResourceGroupMembersTask)
                assert isinstance(download_rg_members_task, DownloadResourceGroupMembersTask)
                
                # Precondition
                assert download_rg_members_task.crash_reason is None
                
                # Load children of DownloadResourceGroupMembersTask
                # 
                # In TaskTreeNode.task_did_set_children,
                # crash the call: self.tree_node.append_child(...)
                with patch.object(NodeView, 'append_child', side_effect=_CRASH) as crash_point:
                    await step_scheduler(project)
                    await pump_wx_events()  # force deferral by fg_call_later() to run
                
                # Postcondition
                assert crash_point.call_count >= 1
                assert download_rg_members_task.crash_reason is not None


@frequently_corrupts_memory
async def test_when_TTN_task_did_append_child_crashes_at_top_level_then_T_displays_as_crashed() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                # Create DownloadResourceTask and TaskTreeNode
                home_r = Resource(project, home_url)
                home_r.download(); append_deferred_top_level_tasks(project)
                (download_r_task,) = project.root_task.children
                assert isinstance(download_r_task, DownloadResourceTask)
                ttn_for_task(download_r_task)
                
                # Precondition
                assert download_r_task.crash_reason is None
                
                # In TaskTreeNode.task_did_append_child,
                # crash the line: child = task.children[-1]  # lookup child
                if True:
                    super_task_did_append_child = TaskTreeNode.task_did_append_child
                    # NOTE: Need some kind of @capture_crashes_to* here to pass caller checks
                    @capture_crashes_to_stderr
                    def task_did_append_child(self, task: Task, child: Task | None) -> None:
                        # Corrupt the value of task.children
                        task._children = []
                        child = None  # force access of task.children
                        return super_task_did_append_child(self, task, child)
                    
                    # Load children of DownloadResourceGroupMembersTask
                    with patch.object(TaskTreeNode, 'task_did_append_child', task_did_append_child):
                        await step_scheduler(project)
                
                # Postcondition
                assert download_r_task.crash_reason is not None


@frequently_corrupts_memory
async def test_when_TTN_task_did_append_child_crashes_in_deferred_fg_task_then_T_displays_as_crashed() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                # Create DownloadResourceTask and TaskTreeNode
                home_r = Resource(project, home_url)
                home_r.download(); append_deferred_top_level_tasks(project)
                (download_r_task,) = project.root_task.children
                assert isinstance(download_r_task, DownloadResourceTask)
                ttn_for_task(download_r_task)
                
                # Precondition
                assert download_r_task.crash_reason is None
                
                # In TaskTreeNode.task_did_append_child,
                # Crash the line: self.tree_node.append_child(child_ttnode.tree_node)
                with patch.object(NodeView, 'append_child', side_effect=_CRASH) as crash_point:
                    await step_scheduler(project)
                    await pump_wx_events()  # force deferral by fg_call_later() to run
                
                # Postcondition
                assert crash_point.call_count >= 1
                assert download_r_task.crash_reason is not None


@frequently_corrupts_memory
async def test_when_TTN_task_child_did_complete_crashes_at_top_level_then_T_displays_as_crashed() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                # Create DownloadResourceTask and TaskTreeNode
                home_r = Resource(project, home_url)
                home_r.download(); append_deferred_top_level_tasks(project)
                (download_r_task,) = project.root_task.children
                assert isinstance(download_r_task, DownloadResourceTask)
                ttn_for_task(download_r_task)
                
                # Precondition
                assert download_r_task.crash_reason is None
                
                # In TaskTreeNode.task_child_did_complete,
                # crash the line: with self._complete_events_ignored():
                with patch.object(TaskTreeNode, '_complete_events_ignored', side_effect=_CRASH) as crash_point:
                    await step_scheduler(project)
                    await pump_wx_events()  # force deferral by fg_call_later() to run
                
                # Postcondition
                assert crash_point.call_count >= 1
                assert download_r_task.crash_reason is not None


@frequently_corrupts_memory
async def test_when_TTN_task_child_did_complete_crashes_in_deferred_fg_task_then_T_displays_as_crashed() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                # Create DownloadResourceTask and TaskTreeNode
                home_r = Resource(project, home_url)
                home_r.download(); append_deferred_top_level_tasks(project)
                (download_r_task,) = project.root_task.children
                assert isinstance(download_r_task, DownloadResourceTask)
                ttn_for_task(download_r_task)
                
                # Precondition
                assert download_r_task.crash_reason is None
                
                # In TaskTreeNode.task_child_did_complete,
                # crash the line: self.tree_node.children = new_children
                with patch.object(TaskTreeNode, '_MAX_LEADING_COMPLETE_CHILDREN', 0), \
                        patch.object(NodeView, 'set_children', side_effect=_CRASH) as crash_point:
                    await step_scheduler(project)
                    await pump_wx_events()  # force deferral by fg_call_later() to run
                
                # Postcondition
                assert crash_point.call_count >= 1
                assert download_r_task.crash_reason is not None


@skip('not yet automated')
async def test_when_TTN_task_did_clear_children_crashes_at_top_level_then_T_displays_as_crashed() -> None:
    # TODO: Crash the line: if self.task.scheduling_style == SCHEDULING_STYLE_SEQUENTIAL: raise NotImplementedError()
    pass


@skip('not yet automated')
async def test_when_TTN_task_did_clear_children_crashes_in_deferred_fg_task_then_T_displays_as_crashed() -> None:
    # TODO: Crash the line: self.tree_node.children = [... if i not in child_indexes]
    pass


# ------------------------------------------------------------------------------
# Test: Common Crash Locations in entitytree.Node
# 
# Below, some abbreviations are used in test names:
# - ET = EntityTree
# - RGN = ResourceGroupNode
# - RN = _ResourceNode

@skip('not yet automated')
async def test_when_RN_on_expanded_crashes_at_top_level_then_children_replaced_with_error_node() -> None:
    # TODO: In _ResourceNode.on_expanded,
    #       crash the line: self.download_future = self.resource.download()
    pass


@skip('not yet automated')
async def test_when_RN_on_expanded_crashes_while_updating_children_then_children_replaced_with_error_node() -> None:
    # TODO: In _ResourceNode.update_children,
    #       crash the line: children.append(RootResourceNode(...))
    pass


@frequently_corrupts_memory
async def test_when_RGN_on_expanded_crashes_while_loading_urls_then_children_replaced_with_error_node() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                Resource(project, atom_feed_url)
                Resource(project, rss_feed_url)
                
                # Create ResourceGroupNode
                feed_g = ResourceGroup(project, '', feed_pattern, source=None)
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                feed_ti = root_ti.find_child(feed_pattern)
                
                # In ResourceGroupNode.on_expanded,
                # crash the line: self.resource_group.project.load_urls()
                with patch.object(project, 'load_urls', side_effect=_CRASH):
                    feed_ti.Expand()
                    await wait_for(first_child_of_tree_item_is_not_loading_condition(feed_ti))
                
                # Postconditions
                (error_ti,) = feed_ti.Children
                assert _ErrorNode.CRASH_TITLE == error_ti.Text
                assert _ErrorNode.CRASH_TEXT_COLOR == error_ti.TextColour
                assert True == error_ti.Bold


@frequently_corrupts_memory
async def test_when_RGN_on_expanded_crashes_while_updating_children_then_children_replaced_with_error_node() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                Resource(project, atom_feed_url)
                Resource(project, rss_feed_url)
                
                # Create ResourceGroupNode
                feed_g = ResourceGroup(project, '', feed_pattern, source=None)
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                feed_ti = root_ti.find_child(feed_pattern)
                
                # In ResourceGroupNode.update_children,
                # crash the line: children_rs.append(NormalResourceNode(...))
                with patch('crystal.browser.entitytree.NormalResourceNode', side_effect=_CRASH):
                    feed_ti.Expand()
                    await wait_for(first_child_of_tree_item_is_not_loading_condition(feed_ti))
                
                # Postconditions
                (error_ti,) = feed_ti.Children
                assert _ErrorNode.CRASH_TITLE == error_ti.Text
                assert _ErrorNode.CRASH_TEXT_COLOR == error_ti.TextColour
                assert True == error_ti.Bold


@frequently_corrupts_memory
async def test_when_RGN_update_children_crashes_during_ET_resource_did_instantiate_then_RGN_children_replaced_with_error_node() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                Resource(project, atom_feed_url)
                
                # Create ResourceGroupNode
                feed_g = ResourceGroup(project, '', feed_pattern, source=None)
                root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                feed_ti = root_ti.find_child(feed_pattern)
                
                # Expand ResourceGroupNode
                feed_ti.Expand()
                await wait_for(first_child_of_tree_item_is_not_loading_condition(feed_ti))
                
                super_update_children = ResourceGroupNode.update_children
                # NOTE: Need some kind of @capture_crashes_to* here to pass caller checks
                @capture_crashes_to_stderr
                def update_children(self, *args, **kwargs) -> None:
                    update_children.called = True  # type: ignore[attr-defined]
                    return super_update_children(self, *args, **kwargs)
                update_children.called = False  # type: ignore[attr-defined]
                
                # In ResourceGroupNode.update_children,
                # crash the line: children_rs.append(NormalResourceNode(...))
                with patch('crystal.browser.entitytree.NormalResourceNode', side_effect=_CRASH), \
                        patch.object(ResourceGroupNode, 'update_children', update_children):
                    Resource(project, rss_feed_url)
                    await wait_for(lambda: update_children.called or None)  # type: ignore[attr-defined]
                
                # Postconditions
                (error_ti,) = feed_ti.Children
                assert _ErrorNode.CRASH_TITLE == error_ti.Text
                assert _ErrorNode.CRASH_TEXT_COLOR == error_ti.TextColour
                assert True == error_ti.Bold


# ------------------------------------------------------------------------------
# Test: Common Crash Locations in EntityTree

# NOTE: This has not been observed to be a *common* crash location.
#       It is, however, the only test currently covering what happens what
#       a crash happens at the level of the EntityTree itself (as opposed
#       to inside one of its nodes).
@frequently_corrupts_memory
async def test_when_ET_root_resource_did_instantiate_crashes_then_updating_entity_tree_crashed_task_appears() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            rmw = RealMainWindow._last_created
            assert rmw is not None
            
            with clear_top_level_tasks_on_exit(project):
                # Preconditions
                et_root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                () = et_root_ti.Children
                
                with patch('crystal.browser.entitytree.RootResourceNode', side_effect=_CRASH):
                    RootResource(project, 'Home', Resource(project, home_url))
                
                # Postconditions
                if True:
                    assert rmw.entity_tree.crash_reason is not None
                    
                    et_root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                    () = et_root_ti.Children
                    
                    project.root_task.append_deferred_top_level_tasks()
                    (updating_et_crashed_task,) = project.root_task.children
                    assert isinstance(updating_et_crashed_task, CrashedTask)
                
                # test_given_updating_entity_tree_crashed_task_at_top_level_when_right_click_task_then_menu_appears_with_enabled_refresh_menuitem
                root_ti = TreeItem.GetRootItem(mw.task_tree)
                (scheduler_crashed_ti,) = root_ti.Children
                def show_popup(menu: wx.Menu) -> None:
                    (refresh_menuitem,) = (
                        mi for mi in menu.MenuItems
                        if mi.ItemLabelText == 'Refresh'
                    )
                    assert refresh_menuitem.Enabled
                    
                    # test_when_click_refresh_menuitem_for_updating_entity_tree_crashed_task_then_recreates_unexpanded_top_level_entities_in_entity_tree_and_task_is_removed
                    select_menuitem_now(menu, refresh_menuitem.Id)
                    if True:
                        assert rmw.entity_tree.crash_reason is None
                        
                        et_root_ti = TreeItem.GetRootItem(mw.entity_tree.window)
                        (home_ti,) = et_root_ti.Children
                        
                        # RT -- notices all finished children; clears them
                        step_scheduler_now(project, expect_done=True)
                        
                        () = project.root_task.children
                await scheduler_crashed_ti.right_click_showing_popup_menu(show_popup)


# ------------------------------------------------------------------------------
# Test: Crashes Cascade to Ancestors
# 
# Below, some abbreviations are used in test names:
# - DRBT = DownloadResourceBodyTask
# - DRGMT = DownloadResourceGroupMembersTask
# - DRGT = DownloadResourceGroupTask
# - DRT = DownloadResourceTask
# - PRRL = ParseResourceRevisionLinks
# - RT = RootTask
# - URGMT = UpdateResourceGroupMembersTask

@skip('not yet automated: hard to crash DRT (or any leaf task) in a realistic way')
async def test_when_DRBT_child_of_DRT_crashes_then_DRT_displays_as_crashed() -> None:
    pass


@skip('not yet automated: hard to crash PRRL (or any leaf task) in a realistic way')
async def test_when_PRRL_child_of_DRT_crashes_then_DRT_displays_as_crashed() -> None:
    pass


@frequently_corrupts_memory
async def test_when_DRT_child_of_DRT_crashes_then_parent_DRT_displays_as_crashed() -> None:
    assert (
        task.SCHEDULING_STYLE_SEQUENTIAL == 
        DownloadResourceTask.scheduling_style
    )
    
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                # Create DownloadResourceTask
                home_r = Resource(project, home_url)
                home_r.download(); append_deferred_top_level_tasks(project)
                (download_r_task,) = project.root_task.children
                assert isinstance(download_r_task, DownloadResourceTask)
                
                # Precondition
                assert download_r_task.crash_reason is None
                
                # RT > DRT > DownloadResourceBodyTask
                def check() -> None:
                    assert not download_r_task.children[0].complete
                await step_scheduler(project, after_get=check)
                assert download_r_task.children[0].complete
                
                # RT > DRT > ParseResourceRevisionLinks
                def check() -> None:
                    assert not download_r_task.children[1].complete
                await step_scheduler(project, after_get=check)
                assert download_r_task.children[1].complete
                assert len(download_r_task.children) >= 3
                
                # RT > DRT > DRT[0] > DownloadResourceBodyTask
                def check() -> None:
                    assert not download_r_task.children[2].children[0].complete
                await step_scheduler(project, after_get=check)
                assert download_r_task.children[2].children[0].complete
                
                # RT > DRT > DRT[0] > ParseResourceRevisionLinks
                await _step_scheduler_with_unit_from_PRRL_and_crash_task(
                    download_r_task.children[2].children[1],
                    home_r)
                
                await step_scheduler(project, expect_done=True)
                
                # Postconditions:
                # 1. Ensure crashed in DownloadResourceTask.child_task_did_complete(),
                #    when tried to resolve relative_urls from links parsed by
                #    ParseResourceRevisionLinks to absolute URLs
                # 2. Ensure crash cascades to parent of inner DownloadResourceTask
                # 3. Ensure crash cascade stops just before reaching the RootTask
                assert download_r_task.children[2].crash_reason is not None
                assert download_r_task.crash_reason is not None
                assert project.root_task.crash_reason is None
                
                root_ti = TreeItem.GetRootItem(mw.task_tree)
                (download_r_ti,) = root_ti.Children
                
                # test_when_hover_mouse_over_crashed_task_then_tooltip_with_user_facing_traceback_appears
                tooltip = download_r_ti.Tooltip()
                assert tooltip is not None
                assert 'ValueError: Invalid IPv6 URL' in tooltip, f'Tooltip was: {tooltip}'
                assert (
                    'at crystal/task.py:' in tooltip or
                    'at crystal/task.pyc:' in tooltip or
                    r'at crystal\task.pyc:' in tooltip
                ), f'Tooltip was: {tooltip}'
                
                # test_given_crashed_task_not_at_top_level_when_right_click_task_then_menu_appears_with_disabled_dismiss_menuitem
                download_r_ti.Expand()
                (download_rb_ti, prrl_ti, download_r1_ti, *_) = download_r_ti.Children
                assert download_r1_ti.Text.endswith(TaskTreeNode._CRASH_SUBTITLE)
                def show_popup(menu: wx.Menu) -> None:
                    (dismiss_menuitem,) = (
                        mi for mi in menu.MenuItems
                        if mi.ItemLabelText == 'Dismiss'
                    )
                    assert not dismiss_menuitem.Enabled
                await download_r1_ti.right_click_showing_popup_menu(show_popup)
                
                # test_given_regular_crashed_task_at_top_level_when_right_click_task_then_menu_appears_with_enabled_dismiss_menuitem
                def show_popup(menu: wx.Menu) -> None:
                    (dismiss_menuitem,) = (
                        mi for mi in menu.MenuItems
                        if mi.ItemLabelText == 'Dismiss'
                    )
                    assert dismiss_menuitem.Enabled
                    
                    # test_when_click_dismiss_menuitem_for_regular_top_level_crashed_task_then_task_is_removed
                    if True:
                        select_menuitem_now(menu, dismiss_menuitem.Id)
                        
                        # RT -- notices all finished children; clears them
                        step_scheduler_now(project, expect_done=True)
                        
                        () = root_ti.Children
                await download_r_ti.right_click_showing_popup_menu(show_popup)


@frequently_corrupts_memory
async def test_when_DRT_child_of_DRGMT_crashes_then_DRGMT_displays_as_crashed() -> None:
    assert (
        task.SCHEDULING_STYLE_SEQUENTIAL == 
        DownloadResourceGroupMembersTask.scheduling_style
    )
    skipTest('covered by: test_when_DRT_child_of_DRT_crashes_then_parent_DRT_displays_as_crashed')


@frequently_corrupts_memory
async def test_when_URGMT_child_of_DRGT_crashes_then_DRGT_displays_as_crashed_after_DRGMT_child_completes() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                home_r = Resource(project, home_url)
                Resource(project, atom_feed_url)
                Resource(project, rss_feed_url)
                
                # Create UpdateResourceGroupMembersTask
                home_rr = RootResource(project, 'Home', home_r)
                feed_g = ResourceGroup(project, '', feed_pattern, source=home_rr)
                feed_g.download(); append_deferred_top_level_tasks(project)
                (download_rg_task,) = project.root_task.children
                assert isinstance(download_rg_task, DownloadResourceGroupTask)
                (update_rg_members_task, download_rg_members_task) = download_rg_task.children
                assert isinstance(update_rg_members_task, UpdateResourceGroupMembersTask)
                assert isinstance(download_rg_members_task, DownloadResourceGroupMembersTask)
                
                # Preconditions
                assert download_rg_task.crash_reason is None
                assert update_rg_members_task.crash_reason is None
                
                # RT > DRGT > URGMT > DRT > DownloadResourceBodyTask
                def check() -> None:
                    assert not update_rg_members_task.children[0].children[0].complete
                await step_scheduler(project, after_get=check)
                assert update_rg_members_task.children[0].children[0].complete
                
                # RT > DRGT > DRGMT @ _load_children_and_update_completed_status
                def check() -> None:
                    assert len(download_rg_members_task.children) == 0
                await step_scheduler(project, after_get=check)
                assert len(download_rg_members_task.children) == 2
                
                # RT > DRGT > URGMT > DRT > ParseResourceRevisionLinks
                await _step_scheduler_with_unit_from_PRRL_and_crash_task(
                    update_rg_members_task.children[0].children[1],
                    home_r)
                
                # RT > DRGT > DRGMT > ... (doesn't matter)
                await step_scheduler(project)
                
                # 1. RT > DRGT > URGMT -- notices crashed child
                # 2. RT > DRGT > DRGMT > ... (doesn't matter)
                await step_scheduler(project)
                
                # Postconditions #1:
                # 1. Ensure crashed in DownloadResourceTask.child_task_did_complete(),
                #    when tried to resolve relative_urls from links parsed by
                #    ParseResourceRevisionLinks to absolute URLs
                # 2. Ensure crash cascades to URGMT
                # 3. Ensure crash does NOT cascade to DRGT yet,
                #    because DRGMT is not complete
                # 4. Ensure crash does not cascade to the RootTask
                assert update_rg_members_task.children[0].crash_reason is not None
                assert update_rg_members_task.crash_reason is not None
                assert download_rg_task.crash_reason is None
                assert project.root_task.crash_reason is None
                
                # Wait for DRGMT to complete
                while not download_rg_members_task.complete:
                    assert download_rg_members_task.crash_reason is None
                    
                    # RT > DRGT > DRGMT > ... (doesn't matter)
                    await step_scheduler(project)
                
                # RT > DRGT -- notices crashed URGMT child
                await step_scheduler(project, expect_done=True)
                
                # Postconditions #2
                # 1. Ensure crash from URGMT cascades to DRGT after DRGMT completes
                # 2. Ensure crash does not cascade to the RootTask
                assert download_rg_task.crash_reason is not None
                assert project.root_task.crash_reason is None
                
                root_ti = TreeItem.GetRootItem(mw.task_tree)
                (download_rg_ti,) = root_ti.Children
                
                # test_when_hover_mouse_over_crashed_task_then_tooltip_with_user_facing_traceback_appears
                tooltip = download_rg_ti.Tooltip()
                assert tooltip is not None
                assert 'ValueError: Invalid IPv6 URL' in tooltip, f'Tooltip was: {tooltip}'
                assert (
                    'at crystal/task.py:' in tooltip or
                    'at crystal/task.pyc:' in tooltip or
                    r'at crystal\task.pyc:' in tooltip
                ), f'Tooltip was: {tooltip}'


@frequently_corrupts_memory
async def test_when_DRGMT_child_of_DRGT_crashes_then_DRGT_displays_as_crashed_after_URGMT_child_completes() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        feed_pattern = sp.get_request_url('https://xkcd.com/*.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                home_r = Resource(project, home_url)
                Resource(project, atom_feed_url)
                Resource(project, rss_feed_url)
                
                # Create DownloadResourceGroupMembersTask
                home_rr = RootResource(project, 'Home', home_r)
                feed_g = ResourceGroup(project, '', feed_pattern, source=home_rr)
                feed_g.download(); append_deferred_top_level_tasks(project)
                (download_rg_task,) = project.root_task.children
                assert isinstance(download_rg_task, DownloadResourceGroupTask)
                (update_rg_members_task, download_rg_members_task) = download_rg_task.children
                assert isinstance(update_rg_members_task, UpdateResourceGroupMembersTask)
                assert isinstance(download_rg_members_task, DownloadResourceGroupMembersTask)
                
                # Preconditions
                assert download_rg_task.crash_reason is None
                assert download_rg_members_task.crash_reason is None
                
                # RT > DRGT > URGMT > ... (doesn't matter)
                def check() -> None:
                    assert not update_rg_members_task.children[0].children[0].complete
                await step_scheduler(project, after_get=check)
                assert update_rg_members_task.children[0].children[0].complete
                
                # RT > DRGT > DRGMT @ _load_children_and_update_completed_status
                def check() -> None:
                    assert len(download_rg_members_task.children) == 0
                await step_scheduler(project, after_get=check)
                assert len(download_rg_members_task.children) == 2
                
                # RT > DRGT > URGMT > ... (doesn't matter)
                def check() -> None:
                    assert not update_rg_members_task.children[0].children[1].complete
                await step_scheduler(project, after_get=check)
                assert update_rg_members_task.children[0].children[1].complete
                
                # RT > DRGT > DRGMT > DRT > DownloadResourceBodyTask
                def check() -> None:
                    assert not download_rg_members_task.children[0].children[0].complete
                await step_scheduler(project, after_get=check)
                assert download_rg_members_task.children[0].children[0].complete
                
                # RT > DRGT > URGMT > ... (doesn't matter)
                def check() -> None:
                    assert not update_rg_members_task.children[0].children[2].children[0].complete
                await step_scheduler(project, after_get=check)
                assert update_rg_members_task.children[0].children[2].children[0].complete
                
                # RT > DRGT > DRGMT > DRT > ParseResourceRevisionLinks
                await _step_scheduler_with_unit_from_PRRL_and_crash_task(
                    download_rg_members_task.children[0].children[1],
                    home_r)
                
                # RT > DRGT > URGMT > ... (doesn't matter)
                await step_scheduler(project)
                
                # 1. RT > DRGT > DRGMT -- notices crashed child
                # 2. RT > DRGT > URGMT > ... (doesn't matter)
                await step_scheduler(project)
                
                # Postconditions #1:
                # 1. Ensure crashed in DownloadResourceTask.child_task_did_complete(),
                #    when tried to resolve relative_urls from links parsed by
                #    ParseResourceRevisionLinks to absolute URLs
                # 2. Ensure crash cascades to DRGMT
                # 3. Ensure crash does NOT cascade to DRGT yet,
                #    because URGMT is not complete
                # 4. Ensure crash does not cascade to the RootTask
                assert download_rg_members_task.children[0].crash_reason is not None
                assert download_rg_members_task.crash_reason is not None
                assert download_rg_task.crash_reason is None
                assert project.root_task.crash_reason is None
                
                # Wait for URGMT to complete
                while not update_rg_members_task.complete:
                    assert update_rg_members_task.crash_reason is None
                    
                    # RT > DRGT > URGMT > ... (doesn't matter)
                    await step_scheduler(project)
                
                # RT > DRGT -- notices crashed DRGMT child
                await step_scheduler(project, expect_done=True)
                
                # Postconditions #2
                # 1. Ensure crash from DRGMT cascades to DRGT after URGMT completes
                # 2. Ensure crash does not cascade to the RootTask
                assert download_rg_task.crash_reason is not None
                assert project.root_task.crash_reason is None
                
                root_ti = TreeItem.GetRootItem(mw.task_tree)
                (download_rg_ti,) = root_ti.Children
                
                # test_when_hover_mouse_over_crashed_task_then_tooltip_with_user_facing_traceback_appears
                tooltip = download_rg_ti.Tooltip()
                assert tooltip is not None
                assert 'ValueError: Invalid IPv6 URL' in tooltip, f'Tooltip was: {tooltip}'
                assert (
                    'at crystal/task.py:' in tooltip or
                    'at crystal/task.pyc:' in tooltip or
                    r'at crystal\task.pyc:' in tooltip
                ), f'Tooltip was: {tooltip}'


# ------------------------------------------------------------------------------
# Test: Crashes at the Top-Level and Root

@skip('covered by: test_when_DRT_child_of_DRT_crashes_then_parent_DRT_displays_as_crashed, test_when_URGMT_child_of_DRGT_crashes_then_DRGT_displays_as_crashed_after_DRGMT_child_completes, test_when_DRGMT_child_of_DRGT_crashes_then_DRGT_displays_as_crashed_after_URGMT_child_completes')
async def test_when_child_of_RT_crashes_then_RT_does_NOT_display_as_crashed() -> None:
    pass


@frequently_corrupts_memory
async def test_when_RT_try_get_next_task_unit_crashes_then_RT_marked_as_crashed() -> None:
    with scheduler_disabled(), \
            served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        rss_feed_url = sp.get_request_url('https://xkcd.com/rss.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            with clear_top_level_tasks_on_exit(project):
                root_task = project.root_task
                
                # Create DownloadResourceTask #1 in RootTask, pre-appended
                home_r = Resource(project, home_url)
                home_r.download(); append_deferred_top_level_tasks(project)
                
                # Create DownloadResourceTask #2 in RootTask, un-appended
                atom_feed_r = Resource(project, atom_feed_url)
                atom_feed_r.download()
                
                # Preconditions
                assert root_task.crash_reason is None
                (download_r_task1,) = project.root_task.children
                assert isinstance(download_r_task1, DownloadResourceTask)
                
                # RT @ try_get_next_task_unit
                # 
                # In RootTask.try_get_next_task_unit,
                # in RootTask.append_deferred_top_level_tasks,
                # crash the line: super().append_child(...)
                super_append_child = Task.append_child
                def append_child(self, child: Task, *args, **kwargs) -> None:
                    if isinstance(child, DownloadResourceTask):
                        # Simulate crash when appending a DownloadResourceTask
                        append_child.call_count += 1  # type: ignore[attr-defined]
                        raise _CRASH
                    else:
                        return super_append_child(self, child, *args, **kwargs)
                append_child.call_count = 0  # type: ignore[attr-defined]
                with patch.object(Task, 'append_child', append_child):
                    await step_scheduler(project, expect_done=True)
                    assert append_child.call_count >= 1  # type: ignore[attr-defined]
                
                # Postconditions
                assert root_task.crash_reason is not None
                (download_r_task1, scheduler_crashed_task) = project.root_task.children
                assert isinstance(download_r_task1, DownloadResourceTask)
                assert isinstance(scheduler_crashed_task, CrashedTask)
                for child in root_task.children:
                    if not isinstance(child, CrashedTask) and not child.complete:
                        assert child.subtitle in ['Scheduler crashed', 'Complete'], \
                            f'Top-level task has unexpected subtitle: {child.subtitle}'
                
                root_ti = TreeItem.GetRootItem(mw.task_tree)
                (download_r_ti, scheduler_crashed_ti) = root_ti.Children
                
                # test_when_hover_mouse_over_crashed_task_then_tooltip_with_user_facing_traceback_appears
                tooltip = scheduler_crashed_ti.Tooltip()
                assert tooltip is not None
                assert 'ValueError: Simulated crash' in tooltip, f'Tooltip was: {tooltip}'
                assert (
                    'at crystal/task.py:' in tooltip or
                    'at crystal/task.pyc:' in tooltip or
                    r'at crystal\task.pyc:' in tooltip
                ), f'Tooltip was: {tooltip}'
                assert 'in append_deferred_top_level_tasks' in tooltip, f'Tooltip was: {tooltip}'
                
                # test_given_scheduler_crashed_task_at_top_level_when_right_click_task_then_menu_appears_with_enabled_dismiss_all_menuitem
                def show_popup(menu: wx.Menu) -> None:
                    (dismiss_all_menuitem,) = (
                        mi for mi in menu.MenuItems
                        if mi.ItemLabelText == 'Dismiss All'
                    )
                    assert dismiss_all_menuitem.Enabled
                    
                    # test_when_click_dismiss_all_menuitem_for_scheduler_crashed_task_then_all_top_level_tasks_are_removed
                    select_menuitem_now(menu, dismiss_all_menuitem.Id)
                    () = root_ti.Children
                await scheduler_crashed_ti.right_click_showing_popup_menu(show_popup)
                
                # ...and new top level tasks can be added that will run
                if True:
                    # Create DownloadResourceTask #3 in RootTask, pre-appended
                    rss_feed_r = Resource(project, rss_feed_url)
                    rss_feed_r.download(); append_deferred_top_level_tasks(project)
                    
                    # Preconditions
                    assert root_task.crash_reason is None
                    (download_r_task2,) = project.root_task.children
                    assert isinstance(download_r_task2, DownloadResourceTask)
                    
                    # Ensure task runs (at least one step)
                    await step_scheduler(project)


@skip('covered by: test_when_RT_try_get_next_task_unit_crashes_then_RT_marked_as_crashed')
async def test_when_RT_marked_as_crashed_then_scheduler_crashed_task_appears_and_all_other_tasks_marked_with_scheduler_crashed_subtitle() -> None:
    pass


@frequently_corrupts_memory
async def test_when_scheduler_thread_event_loop_crashes_then_RT_marked_as_crashed_and_scheduler_crashed_task_appears() -> None:
    with served_project('testdata_xkcd.crystalproj.zip') as sp:
        # Define URLs
        home_url = sp.get_request_url('https://xkcd.com/')
        atom_feed_url = sp.get_request_url('https://xkcd.com/atom.xml')
        
        async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
            root_task = project.root_task
            
            # Crash the scheduler event loop, for project
            super_scheduler_sleep = crystal.task.scheduler_sleep
            def scheduler_sleep(*args, **kwargs) -> None:
                f = sys._getframe(1)
                root_task_of_caller = f.f_locals['root_task']
                if root_task_of_caller == root_task and not scheduler_sleep.called:  # type: ignore[attr-defined]
                    scheduler_sleep.called = True  # type: ignore[attr-defined]
                    raise _CRASH
                else:
                    super_scheduler_sleep(*args, **kwargs)
            scheduler_sleep.called = False  # type: ignore[attr-defined]
            with patch('crystal.task.scheduler_sleep', scheduler_sleep):
                # Create DownloadResourceTask
                home_r = Resource(project, home_url)
                home_r.download()
                
                first_task_title = first_task_title_progression(mw.task_tree)
                def progression_func():
                    if root_task.crash_reason is not None:
                        # Stop
                        if (len(root_task.children) >= 1 and 
                                isinstance(root_task.children[-1], CrashedTask)):
                            return None
                        else:
                            return '(crashed; waiting for CrashedTask to appear)'
                    else:
                        # Keep waiting while first task title is changing
                        title = first_task_title()
                        if title is None:
                            return '(waiting for first task to start)'
                        else:
                            return title
                await wait_while(
                    progression_func,
                    progress_timeout=MAX_DOWNLOAD_DURATION_PER_ITEM)
            
            # Postconditions
            assert scheduler_sleep.called  # type: ignore[attr-defined]
            assert root_task.crash_reason is not None
            (*_, scheduler_crashed_task) = root_task.children
            assert isinstance(scheduler_crashed_task, CrashedTask)
            for child in root_task.children:
                if isinstance(child, CrashedTask):
                    continue
                assert child.subtitle in ['Scheduler crashed', 'Complete'], \
                    f'Top-level task has unexpected subtitle: {child.subtitle}'
            
            root_ti = TreeItem.GetRootItem(mw.task_tree)
            (*_, scheduler_crashed_ti) = root_ti.Children
            
            # test_when_hover_mouse_over_crashed_task_then_tooltip_with_user_facing_traceback_appears
            tooltip = scheduler_crashed_ti.Tooltip()
            assert tooltip is not None
            assert 'ValueError: Simulated crash' in tooltip, f'Tooltip was: {tooltip}'
            assert (
                'at crystal/task.py:' in tooltip or
                'at crystal/task.pyc:' in tooltip or
                r'at crystal\task.pyc:' in tooltip
            ), f'Tooltip was: {tooltip}'
            assert 'in bg_daemon_task' in tooltip, f'Tooltip was: {tooltip}'
            
            # Dismiss scheduler crash, clearing the task tree
            scheduler_crashed_task.dismiss()
            assert len(root_task.children) == 0


# ------------------------------------------------------------------------------
# Test: Dismissing Crashes

@skip('covered by: test_when_DRT_child_of_DRT_crashes_then_parent_DRT_displays_as_crashed')
async def test_given_regular_crashed_task_at_top_level_when_right_click_task_then_menu_appears_with_enabled_dismiss_menuitem() -> None:
    pass


@skip('covered by: test_when_DRT_child_of_DRT_crashes_then_parent_DRT_displays_as_crashed')
async def test_when_click_dismiss_menuitem_for_regular_top_level_crashed_task_then_task_is_removed() -> None:
    pass


@skip('covered by: test_when_RT_try_get_next_task_unit_crashes_then_RT_marked_as_crashed')
async def test_given_scheduler_crashed_task_at_top_level_when_right_click_task_then_menu_appears_with_enabled_dismiss_all_menuitem() -> None:
    pass


@skip('covered by: test_when_RT_try_get_next_task_unit_crashes_then_RT_marked_as_crashed')
async def test_when_click_dismiss_all_menuitem_for_scheduler_crashed_task_then_all_top_level_tasks_are_removed() -> None:
    pass


@skip('covered by: test_when_ET_root_resource_did_instantiate_crashes_then_updating_entity_tree_crashed_task_appears')
async def test_given_updating_entity_tree_crashed_task_at_top_level_when_right_click_task_then_menu_appears_with_enabled_refresh_menuitem() -> None:
    pass


@skip('covered by: test_when_ET_root_resource_did_instantiate_crashes_then_updating_entity_tree_crashed_task_appears')
async def test_when_click_refresh_menuitem_for_updating_entity_tree_crashed_task_then_recreates_unexpanded_top_level_entities_in_entity_tree_and_task_is_removed() -> None:
    pass


# TODO: Make this menuitem *enabled* iff the top-level ancestor task is crashed (very likely),
#       and make dismissing it have the same effect as dismissing the ancestor top-level task
@skip('covered by: test_when_DRT_child_of_DRT_crashes_then_parent_DRT_displays_as_crashed')
async def test_given_crashed_task_not_at_top_level_when_right_click_task_then_menu_appears_with_disabled_dismiss_menuitem() -> None:
    pass


# ------------------------------------------------------------------------------
# Test: Crash Node Tooltips

_test_names = [
    'test_when_DRT_child_of_DRT_crashes_then_parent_DRT_displays_as_crashed',
    'test_when_URGMT_child_of_DRGT_crashes_then_DRGT_displays_as_crashed_after_DRGMT_child_completes',
    'test_when_DRGMT_child_of_DRGT_crashes_then_DRGT_displays_as_crashed_after_URGMT_child_completes',
    'test_when_RT_try_get_next_task_unit_crashes_then_RT_marked_as_crashed',
    'test_when_scheduler_thread_event_loop_crashes_then_RT_marked_as_crashed_and_scheduler_crashed_task_appears',
]
@skip(f'covered by: {", ".join(_test_names)}')
async def test_when_hover_mouse_over_crashed_task_then_tooltip_with_user_facing_traceback_appears() -> None:
    pass


# ------------------------------------------------------------------------------
# Utility

async def _step_scheduler_with_unit_from_PRRL_and_crash_task(prrl_task: Task, home_r: Resource) -> None:
    """
    Performs one unit of work from the scheduler,
    where the unit of work comes from a ParseResourceRevisionLinks (PRRL) task,
    and simulate a crash when running the unit of work.
    """
    project = home_r.project
    
    assert isinstance(prrl_task, ParseResourceRevisionLinks)
    
    _PRRL_call_result__1_link = (
        [create_external_link('/', type_title='Simulated Link', title=None, embedded=True)],
        [home_r]
    )  # type: Tuple[List[Link], List[Resource]]
    
    assert not prrl_task.complete
    # 1. Force ParseResourceRevisionLinks to return 1 embedded link.
    # 2. Patch urljoin() to simulate effect of calling urlparse('//[oops'),
    #    which raises an exception in stock Python:
    #    https://discuss.python.org/t/urlparse-can-sometimes-raise-an-exception-should-it/44465
    #    
    #    NOTE: Overrides the fix in commit 5aaaba57076d537a4872bb3cf7270112ca497a06,
    #          reintroducing the related bug it fixed.
    with patch.object(prrl_task, '__call__', return_value=_PRRL_call_result__1_link) as mock_call, \
            patch('crystal.task.urljoin', side_effect=ValueError('Invalid IPv6 URL')):
        await step_scheduler(project)
        assert mock_call.call_count >= 1
    assert prrl_task.complete


# ------------------------------------------------------------------------------
