from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from crystal.browser.tasktree import TaskTreeNode
from crystal.model import Project, ResourceRevision
import crystal.task
from crystal.task import RootTask, _is_scheduler_thread, scheduler_affinity, Task
from crystal.tests.util.controls import TreeItem
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.wait import (
    DEFAULT_WAIT_PERIOD, tree_has_children_condition,
    tree_has_no_children_condition, wait_for, wait_while, WaitTimedOut,
)
from crystal.tests.util.xthreading import bg_call_and_wait
from crystal.util.xthreading import fg_affinity
from io import BytesIO
import re
import threading
from typing import List
from unittest.mock import patch
import wx

# ------------------------------------------------------------------------------
# Utility: Wait for Download

_MAX_DOWNLOAD_DURATION_PER_STANDARD_ITEM = (
    4 +  # fetch + parse time
    crystal.task.DELAY_BETWEEN_DOWNLOADS
) * 2.5  # fudge factor
_MAX_DOWNLOAD_DURATION_PER_LARGE_ITEM = (
    _MAX_DOWNLOAD_DURATION_PER_STANDARD_ITEM * 
    4
)
MAX_DOWNLOAD_DURATION_PER_ITEM = _MAX_DOWNLOAD_DURATION_PER_LARGE_ITEM

async def wait_for_download_to_start_and_finish(
        task_tree: wx.TreeCtrl,
        *, immediate_finish_ok: bool=False,
        stacklevel_extra: int=0
        ) -> None:
    period = DEFAULT_WAIT_PERIOD
    
    # Wait for start of download
    try:
        await wait_for(
            tree_has_children_condition(task_tree),
            timeout=4.0,  # 2.0s isn't long enough for Windows test runners on GitHub Actions
            message=lambda: f'Timed out waiting for download task to appear',
            stacklevel_extra=(1 + stacklevel_extra),
            screenshot_on_error=not immediate_finish_ok)
    except WaitTimedOut:
        if immediate_finish_ok:
            return
        else:
            raise
    
    # TODO: Eliminate fancy logic to determine `item_count` because it's no longer being used
    # 
    # Wait until download task is observed that says how many items are being downloaded
    item_count: int | None
    first_task_title_func = first_task_title_progression(task_tree)
    observed_titles = []  # type: List[str]
    did_start_download = False
    while True:
        download_task_title = first_task_title_func()
        if download_task_title is None:
            if did_start_download:
                # Didn't observe what the item count was
                # but we DID see evidence that a download actually started
                break
            if immediate_finish_ok:
                return
            raise AssertionError(
                'Download finished early without finding sub-resources. '
                'Did the download fail? '
                f'Task titles observed were: {observed_titles}')
        if download_task_title not in observed_titles:
            observed_titles.append(download_task_title)
        
        m = re.fullmatch(
            r'^(?:Downloading(?: group)?|Finding members of group): (.*?) -- (?:(\d+) of (?:at least )?(\d+) item\(s\)(?: -- .+)?(?: ⚡️)?|(.*))$',
            download_task_title)
        if m is None:
            raise AssertionError(
                f'Expected first task to be a download task but found task with title: '
                f'{download_task_title}')
        if m.group(4) is not None:
            if m.group(4) in [
                    'Waiting for response...',
                    'Parsing links...',
                    'Recording links...',
                    'Waiting before performing next request...']:
                did_start_download = True
            pass  # keep waiting
        else:
            did_start_download = True
            # NOTE: Currently unused. Just proving that we can calculate it.
            int(m.group(3))
            break
        
        await bg_sleep(period)
        continue
    assert did_start_download
    
    # Wait while downloading
    await wait_while(
        first_task_title_func,
        progress_timeout=MAX_DOWNLOAD_DURATION_PER_ITEM,
        progress_timeout_message=lambda: (
            f'Subresource download timed out after {MAX_DOWNLOAD_DURATION_PER_ITEM:.1f}s: '
            f'Stuck at status: {first_task_title_func()!r}'
        ),
        period=period,
    )
    
    # Ensure did finish downloading
    assert tree_has_no_children_condition(task_tree)()


def first_task_title_progression(task_tree: wx.TreeCtrl) -> Callable[[], str | None]:
    def first_task_title():
        root_ti = TreeItem.GetRootItem(task_tree)
        first_task_ti = root_ti.GetFirstChild()
        if first_task_ti is None:
            return None  # done
        return first_task_ti.Text
    return first_task_title


# ------------------------------------------------------------------------------
# Utility: Task -> TaskTreeNode

def ttn_for_task(task: Task) -> TaskTreeNode:
    for lis in task.listeners:
        if isinstance(lis, TaskTreeNode):
            return lis
    raise AssertionError(f'Unable to locate TaskTreeNode for {task!r}')

# ------------------------------------------------------------------------------
# Utility: Append Deferred Top-Level Tasks

@fg_affinity
@scheduler_affinity  # manual control of scheduler thread is assumed
def append_deferred_top_level_tasks(project: Project) -> None:
    """
    For any children whose appending to a project's RootTask was deferred by
    RootTask.append_child(), apply those appends now.
    
    Listeners that respond to the append of a child may take other actions
    directly after the append, such as completing the just-appended child.
    """
    project.root_task.append_deferred_top_level_tasks()
    
    # Postcondition
    assert len(project.root_task._children_to_add_soon) == 0


# ------------------------------------------------------------------------------
# Utility: Scheduler Manual Control

@contextmanager
def scheduler_disabled(*, simulate_thread_never_dies: bool = False) -> Iterator[DisabledScheduler]:
    """
    Context where the scheduler thread is disabled for any Projects that are opened.
    
    Projects opened before entering this context will continue to have active
    scheduler threads.
    
    Arguments:
    * simulate_thread_never_dies --
        If True, the FIRST fake scheduler thread created in this context will always
        report that it's alive, simulating a stuck scheduler thread that never
        stops. This is useful for testing timeout scenarios.
    """
    start_call_count = 0
    stop_call_count = 0
    
    class FakeSchedulerThread:
        def __init__(self, root_task: RootTask, simulate_thread_never_dies: bool) -> None:
            self._root_task = root_task
            self._simulate_thread_never_dies = simulate_thread_never_dies
            
            # Fake ident, to prevent AttributeError when get_thread_stack() is called
            self.ident = None
        
        def join(self, timeout: float | None = None) -> None:
            nonlocal stop_call_count
            stop_call_count += 1
            
            if self._simulate_thread_never_dies:
                return
            
            if self._root_task.complete:
                # Scheduler thread is already stopped or stopping
                return
            
            if self._root_task._cancel_tree_soon and not self._root_task.cancelled:
                # HACK: Patch to disable thread affinity checks when stepping the scheduler,
                #       because this Thread.join() may be called from a background thread
                #       (while running tests) which is synchronized with both the
                #       foreground thread and the scheduler thread, but is hard to
                #       prove to the affinity checking decorators properly.
                def mock_is_foreground_thread(_expect: bool | None=None) -> bool:
                    if _expect is not None:
                        return _expect
                    else:
                        return True
                with patch('crystal.util.xthreading.is_foreground_thread', mock_is_foreground_thread), \
                        patch('crystal.task.is_synced_with_scheduler_thread', return_value=True):
                    # Step the scheduler one last time to ensure that the
                    # cancellation is processed.
                    step_scheduler_now(root_task=self._root_task, expect_done=True)
                assert self._root_task.cancelled
                assert self._root_task.complete
            else:
                raise AssertionError('Expected the scheduler thread to be stopping')
        
        def is_alive(self) -> bool:
            if self._simulate_thread_never_dies:
                return True
            return not self._root_task.complete
    
    def start_fake_scheduler_thread(root_task: RootTask) -> FakeSchedulerThread:
        nonlocal start_call_count
        start_call_count += 1
        return FakeSchedulerThread(
            root_task,
            # Only first thread created within the scheduler_disabled() context
            # may simulate the thread never dying.
            simulate_thread_never_dies if start_call_count == 1 else False)
    
    with patch('crystal.task.start_scheduler_thread', wraps=start_fake_scheduler_thread) as start_func_mock, \
            scheduler_thread_context():
        yield DisabledScheduler(
            start_count_func=lambda: start_call_count,
            stop_count_func=lambda: stop_call_count
        )


class DisabledScheduler:
    def __init__(self, start_count_func, stop_count_func) -> None:
        self._start_count_func = start_count_func
        self._stop_count_func = stop_count_func

    @property
    def start_count(self) -> int:
        """Returns the number of times the scheduler thread was started."""
        return self._start_count_func()
    
    @property
    def stop_count(self) -> int:
        """Returns the number of times the scheduler thread was stopped."""
        return self._stop_count_func()


@contextmanager
def scheduler_thread_context(enabled: bool=True) -> Iterator[None]:
    """
    Context which executes its contents as if it was on a scheduler thread.
    
    For testing use only.
    """
    old_is_scheduler_thread = _is_scheduler_thread()  # capture
    setattr(threading.current_thread(), '_cr_is_scheduler_thread', enabled)
    try:
        assert enabled == _is_scheduler_thread()
        yield
    finally:
        setattr(threading.current_thread(), '_cr_is_scheduler_thread', old_is_scheduler_thread)


@scheduler_affinity  # manual control of scheduler thread is assumed
async def step_scheduler(
        project: Project,
        *, expect_done: bool=False,
        after_get: Callable[[], None] | None=None,
        ) -> bool:
    """
    Performs one unit of work from the scheduler.
    
    Returns whether the scheduler is done and no work is left.
    
    Arguments:
    * expect_done -- Whether it's expected that no work is left.
    
    Raises:
    * SchedulerIsBlockedWaiting
    """
    _ensure_scheduler_is_not_waiting_or_woke_up(project.root_task)
    unit = project.root_task.try_get_next_task_unit()
    # NOTE: The real scheduler thread clears the wake event immediately
    #       after fetching a task unit
    project.root_task.scheduler_should_wake_event.clear()
    if after_get is not None:
        after_get()
    if unit is None:
        if not expect_done:
            raise AssertionError('Expected there to be no more tasks')
        _set_scheduler_is_waiting(project.root_task, True)
        return True
    else:
        if expect_done:
            raise AssertionError('Expected there to be at least one task remaining')
        await bg_call_and_wait(scheduler_thread_context()(unit))
        return False


@scheduler_affinity  # manual control of scheduler thread is assumed
def step_scheduler_now(
        project: Project | None = None,
        *, root_task: RootTask | None = None,
        expect_done: bool=False,
        no_progress_ok: bool=False,
        ) -> None:
    """
    Performs one unit of work from the scheduler.
    
    Must specify either `project` or `root_task`.
    
    Arguments:
    * expect_done -- Whether it's expected that no work is left. Must be True.
    
    Raises:
    * SchedulerIsBlockedWaiting
    """
    if project is not None:
        if root_task is not None:
            raise ValueError('Cannot specify both project and root_task')
        root_task = project.root_task
    else:  # project is None
        if root_task is None:
            raise ValueError('Must specify either project or root_task')
    
    if expect_done != True:
        raise ValueError('step_scheduler_now() only supports expect_done=True')
    try:
        _ensure_scheduler_is_not_waiting_or_woke_up(root_task)
    except SchedulerIsBlockedWaiting:
        if no_progress_ok:
            return
        else:
            raise
    unit = root_task.try_get_next_task_unit()
    # NOTE: The real scheduler thread clears the wake event immediately
    #       after fetching a task unit
    root_task.scheduler_should_wake_event.clear()
    assert expect_done
    assert unit is None
    _set_scheduler_is_waiting(root_task, True)


@scheduler_affinity  # manual control of scheduler thread is assumed
async def step_scheduler_until_done(project: Project) -> None:
    """
    Raises:
    * SchedulerIsBlockedWaiting
    """
    _ensure_scheduler_is_not_waiting_or_woke_up(project.root_task)
    while True:
        unit = project.root_task.try_get_next_task_unit()  # step scheduler
        # NOTE: The real scheduler thread clears the wake event immediately
        #       after fetching a task unit
        project.root_task.scheduler_should_wake_event.clear()
        if unit is None:
            _set_scheduler_is_waiting(project.root_task, True)
            break
        await bg_call_and_wait(scheduler_thread_context()(unit))


@scheduler_affinity  # manual control of scheduler thread is assumed
def _ensure_scheduler_is_not_waiting_or_woke_up(root_task: RootTask) -> None:
    """
    Raises:
    * SchedulerIsBlockedWaiting
    """
    is_waiting = getattr(root_task.scheduler_should_wake_event, '_is_waiting', False)
    assert isinstance(is_waiting, bool)
    if is_waiting:
        if root_task.scheduler_should_wake_event.is_set():
            # Woke up
            _set_scheduler_is_waiting(root_task, False)
        else:
            raise SchedulerIsBlockedWaiting(
                'Caller expected scheduler to be ready to run next task unit, '
                'but scheduler is still waiting on a wake event')
    else:
        # Not waiting
        return


class SchedulerIsBlockedWaiting(AssertionError):
    pass


@scheduler_affinity  # manual control of scheduler thread is assumed
def _set_scheduler_is_waiting(root_task: RootTask, value: bool) -> None:
    root_task.scheduler_should_wake_event._is_waiting = value  # type: ignore[attr-defined]


@scheduler_affinity  # manual control of scheduler thread is assumed
def mark_as_complete(task: Task) -> None:
    assert not task.complete
    RootTask._cancel_tree_now(task)
    assert task.complete


@contextmanager
def downloads_patched_to_return_empty_revision() -> Iterator[None]:
    """
    Patches DownloadResourceTask to immediately return an empty ResourceRevision
    as its response. Useful to avoid DownloadResourceTask needing to run any
    logic on the scheduler thread, especially if the scheduler thread is disabled.
    """
    def get_future_with_result(self, *args, **kwargs) -> Future[ResourceRevision]:
        future = Future()  # type: Future[ResourceRevision]
        future.set_result(ResourceRevision.create_from_response(self.resource, None, BytesIO()))
        return future
    
    # Request the root resource URL, which should trigger dynamic download
    with patch('crystal.task.DownloadResourceTask.get_future', new=get_future_with_result):
        yield
