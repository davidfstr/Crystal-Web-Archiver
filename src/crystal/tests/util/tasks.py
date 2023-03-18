from __future__ import annotations

import crystal.task
from crystal.tests.util.controls import TreeItem
from crystal.tests.util.runner import bg_sleep
from crystal.tests.util.wait import (
    DEFAULT_WAIT_PERIOD, tree_has_children_condition, 
    tree_has_no_children_condition, wait_for, wait_while, WaitTimedOut
)
import math
import re
from typing import Callable, List, Optional
import wx


# ------------------------------------------------------------------------------
# Utility: Wait for Download

async def wait_for_download_to_start_and_finish(
        task_tree: wx.TreeCtrl,
        *, immediate_finish_ok: bool=False,
        ) -> None:
    # TODO: Allow caller to tune "max_download_duration_per_item"
    max_download_duration_per_standard_item = (
        4 +  # fetch + parse time
        crystal.task.DELAY_BETWEEN_DOWNLOADS
    ) * 2.5  # fudge factor
    max_download_duration_per_large_item = (
        max_download_duration_per_standard_item * 
        4
    )
    
    period = DEFAULT_WAIT_PERIOD
    
    # Wait for start of download
    try:
        await wait_for(tree_has_children_condition(task_tree))
    except WaitTimedOut:
        if immediate_finish_ok:
            return
        else:
            raise
    
    # Wait until download task is observed that says how many items are being downloaded
    item_count: int
    first_task_title_func = first_task_title_progression(task_tree)
    observed_titles = []  # type: List[str]
    while True:
        download_task_title = first_task_title_func()
        if download_task_title is None:
            if immediate_finish_ok:
                return
            raise AssertionError(
                'Download finished early without finding sub-resources. '
                'Did the download fail? '
                f'Task titles observed were: {observed_titles}')
        if download_task_title not in observed_titles:
            observed_titles.append(download_task_title)
        
        m = re.fullmatch(
            r'^(?:Downloading(?: group)?|Finding members of group): (.*?) -- (?:(\d+) of (?:at least )?(\d+) item\(s\)|(.*))$',
            download_task_title)
        if m is None:
            raise AssertionError(
                f'Expected first task to be a download task but found task with title: '
                f'{download_task_title}')
        if m.group(4) is not None:
            pass  # keep waiting
        else:
            # NOTE: Currently unused. Just proving that we can calculate it.
            item_count = int(m.group(3))
            break
        
        await bg_sleep(period)
        continue
    
    # Wait while downloading
    await wait_while(
        first_task_title_func,
        total_timeout=math.inf,  # progress timeout is sufficient
        progress_timeout=max_download_duration_per_large_item,
        progress_timeout_message=lambda: (
            f'Subresource download timed out after {max_download_duration_per_large_item:.1f}s: '
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
