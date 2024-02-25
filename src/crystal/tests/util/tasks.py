from __future__ import annotations

from contextlib import contextmanager
from crystal.browser.tasktree import TaskTreeNode
from crystal.model import Project
import crystal.task
from crystal.task import _is_scheduler_thread, scheduler_affinity, Task
from crystal.tests.util.controls import TreeItem
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.wait import (
    DEFAULT_WAIT_PERIOD, tree_has_children_condition, 
    tree_has_no_children_condition, wait_for, wait_while, WaitTimedOut
)
from crystal.util.xthreading import fg_affinity
import math
import re
import threading
from typing import Callable, List, Iterator, Optional
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
    item_count: Optional[int]
    first_task_title_func = first_task_title_progression(task_tree)
    observed_titles = []  # type: List[str]
    did_start_download = False
    while True:
        download_task_title = first_task_title_func()
        if download_task_title is None:
            if did_start_download:
                # Didn't observe what the item count was
                # but we DID see evidence that a download actually started
                item_count = None
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
            r'^(?:Downloading(?: group)?|Finding members of group): (.*?) -- (?:(\d+) of (?:at least )?(\d+) item\(s\)(?: -- .+)?|(.*))$',
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
            item_count = int(m.group(3))
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


def first_task_title_progression(task_tree: wx.TreeCtrl) -> Callable[[], Optional[str]]:
    def first_task_title():
        root_ti = TreeItem.GetRootItem(task_tree)
        assert root_ti is not None
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
def append_deferred_top_level_tasks(project: Project) -> None:
    """
    For any children whose appending to a project's RootTask was deferred by
    RootTask.append_child(), apply those appends now.
    
    Listeners that respond to the append of a child may take other actions
    directly after the append, such as completing the just-appended child.
    """
    # TODO: Shouldn't this method be marked as @scheduler_affinity,
    #       rather than asserting an interior scheduler_thread_context()?
    with scheduler_thread_context():
        project.root_task.append_deferred_top_level_tasks()
        
        # Postcondition
        assert len(project.root_task._children_to_add_soon) == 0


# ------------------------------------------------------------------------------
# Utility: Scheduler Manual Control

@contextmanager
def scheduler_disabled() -> Iterator[None]:
    """
    Context where the scheduler thread is disabled for any Projects that are opened.
    
    Projects opened before entering this context will continue to have active
    scheduler threads.
    """
    with patch('crystal.task.start_schedule_forever', lambda task: None), \
            scheduler_thread_context():
        yield


@contextmanager
def scheduler_thread_context() -> Iterator[None]:
    """
    Context which executes its contents as if it was on a scheduler thread.
    
    For testing use only.
    """
    old_is_scheduler_thread = _is_scheduler_thread()  # capture
    setattr(threading.current_thread(), '_cr_is_scheduler_thread', True)
    try:
        assert _is_scheduler_thread()
        yield
    finally:
        setattr(threading.current_thread(), '_cr_is_scheduler_thread', old_is_scheduler_thread)


def mark_as_complete(task: Task) -> None:
    assert not task.complete
    task.finish()
    assert task.complete


@contextmanager
@scheduler_affinity  # manual control of scheduler thread is assumed
def clear_top_level_tasks_on_exit(project: Project) -> Iterator[None]:
    try:
        yield
    finally:
        # Uncrash root task, if it was crashed
        project.root_task.crash_reason = None
        
        # Force root task children to complete
        for c in project.root_task.children:
            if not c.complete:
                mark_as_complete(c)
        
        # Clear root task children
        assert None == project.root_task.try_get_next_task_unit()
        assert len(project.root_task.children) == 0


# ------------------------------------------------------------------------------
