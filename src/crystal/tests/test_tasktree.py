from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import (
    AbstractContextManager, asynccontextmanager, contextmanager, nullcontext,
)
from crystal.browser.tasktree import _MoreNodeView, TaskTreeNode
from crystal.model import Project, Resource, ResourceGroup, RootResource
import crystal.task
from crystal.task import (
    _PlaceholderTask, DownloadResourceGroupMembersTask,
    DownloadResourceGroupTask, DownloadResourceTask,
    SCHEDULING_STYLE_ROUND_ROBIN, Task, UpdateResourceGroupMembersTask,
)
from crystal.tests.util.asserts import assertEqual
from crystal.tests.util.controls import click_button, TreeItem
from crystal.tests.util.data import MAX_TIME_TO_DOWNLOAD_404_URL
from crystal.tests.util.downloads import load_children_of_drg_task
from crystal.tests.util.server import served_project
from crystal.tests.util.tasks import (
    scheduler_disabled, scheduler_thread_context,
)
from crystal.tests.util.tasks import append_deferred_top_level_tasks
from crystal.tests.util.tasks import mark_as_complete as _mark_as_complete
from crystal.tests.util.tasks import ttn_for_task as _ttn_for_task
from crystal.tests.util.wait import (
    tree_has_no_children_condition, wait_for, wait_while,
)
from crystal.tests.util.windows import MainWindow, OpenOrCreateDialog
from crystal.ui.tree2 import NodeView as NodeView2
from crystal.ui.tree import NodeView
from crystal.util.xcollections.lazy import (
    AppendableLazySequence, UnmaterializedItem,
)
from typing import cast, Tuple
from unittest import skip
from unittest.mock import patch

# === Test: SCHEDULING_STYLE_SEQUENTIAL tasks: Limit visible children ===

async def test_when_start_downloading_large_group_then_show_100_children_plus_trailing_more_node() -> None:
    N = 3
    M = 2
    async with _project_with_resource_group_starting_to_download(
                resource_count=N + M + 1,
                small_max_visible_children=N,
                small_max_leading_complete_children=M,
                scheduler_thread_enabled=False,
            ) as (mw, project, download_rg_ttn, download_rg_members_ttn, _):
        parent_ttn = download_rg_members_ttn
        
        # Ensure only first 100 member download tasks are visible,
        # with a "# more" placeholder at the end
        assert 0 == _viewport_offset(parent_ttn)
        assert 0 + N == _materialized_child_task_count(parent_ttn)
        assert 0 == _unmaterialized_child_task_count(parent_ttn)
        (children_tns, children_tasks) = \
            (parent_ttn.tree_node.children, parent_ttn.task.children)
        assert len(children_tns) == N + 1
        assert all([_is_download_resource_node(tn) for tn in children_tns[:-1]])
        assert _is_more_node(children_tns[-1])
        assert M + 1 == _value_of_more_node(children_tns[-1])
        
        # Ensure leading "# more" placeholder inserted after M+1 tasks complete
        if True:
            for i in range(M):
                _mark_as_complete(children_tasks[i])
                assert 0 == _viewport_offset(parent_ttn)
                assert 0 + N == _materialized_child_task_count(parent_ttn)
                assert 0 == _unmaterialized_child_task_count(parent_ttn)
                (children_tns, children_tasks) = \
                    (parent_ttn.tree_node.children, parent_ttn.task.children)
                assert len(children_tns) == N + 1
                assert all([_is_download_resource_node(tn) for tn in children_tns[:-1]])
                assert _is_more_node(children_tns[-1])
                assert M + 1 == _value_of_more_node(children_tns[-1])
            
            _mark_as_complete(children_tasks[M])
            assert 1 == _viewport_offset(parent_ttn)
            assert 1 + N == _materialized_child_task_count(parent_ttn)
            assert 1 == _unmaterialized_child_task_count(parent_ttn)
            (children_tns, children_tasks) = \
                (parent_ttn.tree_node.children, parent_ttn.task.children)
            assert len(children_tns) == 1 + N + 1
            assert _is_more_node(children_tns[0])
            assert all([_is_download_resource_node(tn) for tn in children_tns[1:-1]])
            assert _is_more_node(children_tns[-1])
            assert 1 == _value_of_more_node(children_tns[0])
            assert M - 1 >= 1
            assert M + 1 - 1 == _value_of_more_node(children_tns[-1])
        
        # Ensure leading/trailing "# more" placeholder increments/decrements
        # as each task completes, until trailing "# more" placeholder disappears
        for i in range(M+1, M+M):
            _mark_as_complete(children_tasks[i])
            assert (i - M + 1) == _viewport_offset(parent_ttn)
            assert (i - M + 1) + N == _materialized_child_task_count(parent_ttn)
            assert (i - M + 1) == _unmaterialized_child_task_count(parent_ttn)
            (children_tns, children_tasks) = \
                (parent_ttn.tree_node.children, parent_ttn.task.children)
            if M + 1 - (i - M + 1) >= 1:
                assert len(children_tns) == 1 + N + 1
                assert _is_more_node(children_tns[0])
                assert all([_is_download_resource_node(tn) for tn in children_tns[1:-1]])
                assert _is_more_node(children_tns[-1])
                assert (i - M + 1) == _value_of_more_node(children_tns[0])
                assert M + 1 - (i - M + 1) == _value_of_more_node(children_tns[-1])
            else:
                assert len(children_tns) == 1 + N
                assert _is_more_node(children_tns[0])
                assert all([_is_download_resource_node(tn) for tn in children_tns[1:]])
                assert (i - M + 1) == _value_of_more_node(children_tns[0])
                assert M + 1 - (i - M + 1) == 0
        
        # Ensure leading "# more" placeholder increments as each task completes,
        # until all tasks complete
        if True:
            # Complete remaining tasks up to but not including the last task
            for (i, j) in zip(range(M+M, M+N), range(0, M)):
                _mark_as_complete(parent_ttn.task.children[i])
                assert (i - M + 1) == _viewport_offset(parent_ttn)
                assert M + N + 1 == _materialized_child_task_count(parent_ttn)
                assert (i - M + 1) == _unmaterialized_child_task_count(parent_ttn)
                (children_tns, children_tasks) = \
                    (parent_ttn.tree_node.children, parent_ttn.task.children)
                assert len(children_tns) == 1 + N - j
                assert _is_more_node(children_tns[0])
                assert all([_is_download_resource_node(tn) for tn in children_tns[1:]])
                assert (i - M + 1) == _value_of_more_node(children_tns[0])
            
            # Complete the last task
            assert parent_ttn.task.children[-2].complete
            assert not parent_ttn.task.children[-1].complete
            _mark_as_complete(parent_ttn.task.children[-1])
            assert parent_ttn.task.complete


@skip('covered by: test_when_start_downloading_large_group_then_show_100_children_plus_trailing_more_node')
async def test_given_downloading_large_group_and_many_uncompleted_children_remaining_when_child_completes_then_show_leading_more_node_plus_100_children_plus_trailing_more_node() -> None:
    pass


@skip('covered by: test_when_start_downloading_large_group_then_show_100_children_plus_trailing_more_node')
async def test_given_downloading_large_group_and_few_uncompleted_children_remaining_when_child_completes_then_show_leading_more_node_plus_up_to_100_children_but_no_trailing_more_node() -> None:
    pass


@skip('covered by: test_when_start_downloading_large_group_then_show_100_children_plus_trailing_more_node')
async def test_while_downloading_large_group_then_keeps_no_more_than_100_member_download_tasks_in_memory() -> None:
    # The referenced covering test ensures that:
    #     _materialized_child_task_count(...) - _unmaterialized_child_task_count(...) <= N
    # for any N, including 100
    pass


async def test_given_group_has_leading_completed_children_when_start_downloading_large_group_then_shows_no_more_then_5_leading_completed_children() -> None:
    N = 5
    M = 3
    
    with _children_marked_as_complete_upon_creation(list(range(1, (M + 1) + 1))):
        async with _project_with_resource_group_starting_to_download(
                    resource_count=N + M + 1,
                    small_max_visible_children=N,
                    small_max_leading_complete_children=M,
                    scheduler_thread_enabled=False,
                ) as (mw, project, download_rg_ttn, download_rg_members_ttn, _):
            parent_ttn = download_rg_members_ttn
            
            assertEqual(1, _viewport_offset(parent_ttn))
            assertEqual(N, _viewport_length(parent_ttn))


async def test_given_group_has_more_leading_completed_children_than_visible_children_when_start_downloading_then_moves_viewport_to_appropriate_location() -> None:
    N = 5
    M = 3
    
    with _children_marked_as_complete_upon_creation(list(range(1, (N + 1) + 1))):
        async with _project_with_resource_group_starting_to_download(
                    resource_count=N + M + 1,
                    small_max_visible_children=N,
                    small_max_leading_complete_children=M,
                    scheduler_thread_enabled=False,
                ) as (mw, project, download_rg_ttn, download_rg_members_ttn, _):
            parent_ttn = download_rg_members_ttn
            
            assertEqual(3, _viewport_offset(parent_ttn))
            assertEqual(N, _viewport_length(parent_ttn))
            
            # Ensure does not crash when update Task._next_child_index
            # in way that passes through children that were unmaterialized
            # (and which should be assumed to be complete)
            # 
            # In particular ensure UnmaterializedItemError is handled correctly.
            parent_ttn.task.try_get_next_task_unit()
    
    with _children_marked_as_complete_upon_creation(list(range(1, (N + M + 1) + 1))):
        async with _project_with_resource_group_starting_to_download(
                    resource_count=N + M + 2,
                    small_max_visible_children=N,
                    small_max_leading_complete_children=M,
                    scheduler_thread_enabled=False,
                ) as (mw, project, download_rg_ttn, download_rg_members_ttn, _):
            parent_ttn = download_rg_members_ttn
            
            assertEqual(6, _viewport_offset(parent_ttn))
            assertEqual(M + 1, _viewport_length(parent_ttn))
            
            # Ensure does not crash when update
            # (first_more_node, intermediate_nodes, last_more_node)
            # in way that passes through children that were unmaterialized
            # (and which should be assumed to be complete)
            # 
            # In particular ensure UnmaterializedItem is handled correctly.
            parent_ttn.task.try_get_next_task_unit()


# === Test: SCHEDULING_STYLE_SEQUENTIAL tasks: Limit leading completed children ===

async def test_given_showing_less_than_5_leading_completed_children_when_new_leading_child_completes_then_maintain_viewport_position_and_show_one_more_leading_completed_children() -> None:
    N = 5
    M = 3
    async with _project_with_resource_group_starting_to_download(
                resource_count=N + 4,
                small_max_visible_children=N,
                small_max_leading_complete_children=M,
                scheduler_thread_enabled=False,
            ) as (mw, project, download_rg_ttn, download_rg_members_ttn, _):
        parent_ttn = download_rg_members_ttn
        
        # Ensure starts with no leading completed children
        assert 0 == _viewport_offset(parent_ttn)
        assert 0 + N == _materialized_child_task_count(parent_ttn)
        assert 0 == _unmaterialized_child_task_count(parent_ttn)
        (children_tns, children_tasks) = \
            (parent_ttn.tree_node.children, parent_ttn.task.children)
        assert len(children_tns) == N + 1
        assert all([_is_download_resource_node(tn) for tn in children_tns[:-1]])
        assert _is_more_node(children_tns[-1])
        assert (
            [False] * N == 
            [_is_complete(tn) for tn in children_tns[:-1]]
        )
        
        # Case: test_given_showing_less_than_5_leading_completed_children_when_new_leading_child_completes_then_maintain_viewport_position_and_show_one_more_leading_completed_children
        _mark_as_complete(children_tasks[0])
        assert 0 == _viewport_offset(parent_ttn)
        assert 0 + N == _materialized_child_task_count(parent_ttn)
        assert 0 == _unmaterialized_child_task_count(parent_ttn)
        (children_tns, children_tasks) = \
            (parent_ttn.tree_node.children, parent_ttn.task.children)
        assert len(children_tns) == N + 1
        assert all([_is_download_resource_node(tn) for tn in children_tns[:-1]])
        assert _is_more_node(children_tns[-1])
        assert (
            [True] + ([False] * (N - 1)) == 
            [_is_complete(tn) for tn in children_tns[:-1]]
        )
        
        # Case: test_given_showing_less_than_5_leading_completed_children_when_new_nonleading_child_completes_then_maintain_viewport_position_and_show_same_number_of_leading_completed_children
        assert M >= 3
        _mark_as_complete(children_tasks[2])
        assert 0 == _viewport_offset(parent_ttn)
        assert 0 + N == _materialized_child_task_count(parent_ttn)
        assert 0 == _unmaterialized_child_task_count(parent_ttn)
        (children_tns, children_tasks) = \
            (parent_ttn.tree_node.children, parent_ttn.task.children)
        assert len(children_tns) == N + 1
        assert all([_is_download_resource_node(tn) for tn in children_tns[:-1]])
        assert _is_more_node(children_tns[-1])
        assert (
            [True, False, True] + ([False] * (N - 3)) == 
            [_is_complete(tn) for tn in children_tns[:-1]]
        )
        
        # Complete first M children
        assert N >= M + 1
        for t in children_tasks[:M]:
            if not t.complete:
                _mark_as_complete(t)
        assert 0 == _viewport_offset(parent_ttn)
        assert 0 + N == _materialized_child_task_count(parent_ttn)
        assert 0 == _unmaterialized_child_task_count(parent_ttn)
        (children_tns, children_tasks) = \
            (parent_ttn.tree_node.children, parent_ttn.task.children)
        assert len(children_tns) == N + 1
        assert all([_is_download_resource_node(tn) for tn in children_tns[:-1]])
        assert _is_more_node(children_tns[-1])
        assert (
            ([True] * M) + ([False] * (N - M)) == 
            [_is_complete(tn) for tn in children_tns[:-1]]
        )
        
        # Case: test_given_showing_5_leading_completed_children_when_new_leading_child_completes_with_a_following_noncompleted_child_then_shift_viewport_down_once_and_still_show_5_leading_completed_children
        _mark_as_complete(children_tasks[M])
        assert 1 == _viewport_offset(parent_ttn)
        assert 1 + N == _materialized_child_task_count(parent_ttn)
        assert 1 == _unmaterialized_child_task_count(parent_ttn)
        (children_tns, children_tasks) = \
            (parent_ttn.tree_node.children, parent_ttn.task.children)
        assert len(children_tns) == 1 + N + 1
        assert _is_more_node(children_tns[0])
        assert all([_is_download_resource_node(tn) for tn in children_tns[1:-1]])
        assert _is_more_node(children_tns[-1])
        assert (
            ([True] * M) + ([False] * (N - M)) == 
            [_is_complete(tn) for tn in children_tns[1:-1]]
        )
        
        # Case: test_given_showing_5_leading_completed_children_when_new_nonleading_child_completes_then_maintain_viewport_position_and_still_show_5_leading_completed_children
        assert N >= M + 2
        _mark_as_complete(children_tasks[M + 2])
        assert 1 == _viewport_offset(parent_ttn)
        assert 1 + N == _materialized_child_task_count(parent_ttn)
        assert 1 == _unmaterialized_child_task_count(parent_ttn)
        (children_tns, children_tasks) = \
            (parent_ttn.tree_node.children, parent_ttn.task.children)
        assert len(children_tns) == 1 + N + 1
        assert _is_more_node(children_tns[0])
        assert all([_is_download_resource_node(tn) for tn in children_tns[1:-1]])
        assert _is_more_node(children_tns[-1])
        assert (
            ([True] * M) + [False, True] + ([False] * (N - (M + 2))) == 
            [_is_complete(tn) for tn in children_tns[1:-1]]
        )
        
        # Case: test_given_showing_5_leading_completed_children_when_new_leading_child_completes_with_a_following_completed_child_then_shift_viewport_down_multiple_times_and_still_show_5_leading_completed_children
        _mark_as_complete(children_tasks[M + 1])
        assert 3 == _viewport_offset(parent_ttn)
        assert 3 + N == _materialized_child_task_count(parent_ttn)
        assert 3 == _unmaterialized_child_task_count(parent_ttn)
        (children_tns, children_tasks) = \
            (parent_ttn.tree_node.children, parent_ttn.task.children)
        assert len(children_tns) == 1 + N + 1
        assert _is_more_node(children_tns[0])
        assert all([_is_download_resource_node(tn) for tn in children_tns[1:-1]])
        assert _is_more_node(children_tns[-1])
        assert (
            ([True] * M) + ([False] * (N - M)) == 
            [_is_complete(tn) for tn in children_tns[1:-1]]
        )


@skip('covered by: test_given_showing_less_than_5_leading_completed_children_when_new_leading_child_completes_then_maintain_viewport_position_and_show_one_more_leading_completed_children')
async def test_given_showing_less_than_5_leading_completed_children_when_new_nonleading_child_completes_then_maintain_viewport_position_and_show_same_number_of_leading_completed_children() -> None:
    pass

    
@skip('covered by: test_given_showing_less_than_5_leading_completed_children_when_new_leading_child_completes_then_maintain_viewport_position_and_show_one_more_leading_completed_children')
async def test_given_showing_5_leading_completed_children_when_new_leading_child_completes_with_a_following_noncompleted_child_then_shift_viewport_down_once_and_still_show_5_leading_completed_children() -> None:
    pass

    
@skip('covered by: test_given_showing_less_than_5_leading_completed_children_when_new_leading_child_completes_then_maintain_viewport_position_and_show_one_more_leading_completed_children')
async def test_given_showing_5_leading_completed_children_when_new_nonleading_child_completes_then_maintain_viewport_position_and_still_show_5_leading_completed_children() -> None:
    pass

    
@skip('covered by: test_given_showing_less_than_5_leading_completed_children_when_new_leading_child_completes_then_maintain_viewport_position_and_show_one_more_leading_completed_children')
async def test_given_showing_5_leading_completed_children_when_new_leading_child_completes_with_a_following_completed_materialized_child_then_shift_viewport_down_multiple_times_and_still_show_5_leading_completed_children() -> None:
    pass


async def test_given_showing_5_leading_completed_children_when_new_leading_child_completes_with_a_following_completed_unmaterialized_child_then_shift_viewport_down_multiple_times_and_still_show_5_leading_completed_children() -> None:
    N = 5
    M = 3
    
    with _children_marked_as_complete_upon_creation([N + 1, N + 2]):
        async with _project_with_resource_group_starting_to_download(
                    resource_count=N + 4,
                    small_max_visible_children=N,
                    small_max_leading_complete_children=M,
                    scheduler_thread_enabled=False,
                ) as (mw, project, download_rg_ttn, download_rg_members_ttn, _):
            parent_ttn = download_rg_members_ttn
            
            (children_tns, children_tasks) = \
                (parent_ttn.tree_node.children, parent_ttn.task.children)
            
            # Complete first (N-1) children
            assert N >= M + 1
            for t in children_tasks[:N-1]:
                if not t.complete:
                    _mark_as_complete(t)
            assert 1 == _viewport_offset(parent_ttn)
            (children_tns, children_tasks) = \
                (parent_ttn.tree_node.children, parent_ttn.task.children)
            assert len(children_tns) == N + 2
            assert all([_is_download_resource_node(tn) for tn in children_tns[1:-1]])
            assert 1 == _value_of_more_node(children_tns[0])
            assert 3 == _value_of_more_node(children_tns[-1])
            
            # Complete child N.
            # 
            # Ensure shifts viewport 3 times:
            # - once for completed child (N) and
            # - once for completed child (N + 1) that becomes materialized
            # - once for completed child (N + 2) that becomes materialized
            _mark_as_complete(children_tasks[N - 1])
            assert 4 == _viewport_offset(parent_ttn)
            (children_tns, children_tasks) = \
                (parent_ttn.tree_node.children, parent_ttn.task.children)
            assert len(children_tns) == N + 1
            assert all([_is_download_resource_node(tn) for tn in children_tns[1:]])
            assert 4 == _value_of_more_node(children_tns[0])
            #assert 0 == _value_of_more_node(children_tns[-1])


@contextmanager
def _children_marked_as_complete_upon_creation(ordinals: list[int]) -> Iterator[None]:
    # Prepare: Mark appropriate children as complete immediately upon creation
    super_goc_download_task = Resource.get_or_create_download_task
    def get_or_create_download_task(*args, **kwargs) -> 'Tuple[DownloadResourceTask, bool]':
        (task, created) = super_goc_download_task(*args, **kwargs)
        
        for n in ordinals:
            if task.resource.url.endswith(f'/https/xkcd.com/{n}/'):
                _mark_as_complete(task)
                break
        
        return (task, created)
    
    with patch('crystal.model.Resource.get_or_create_download_task', get_or_create_download_task):
        yield


# === Test: DownloadResourceGroupMembersTask: Observe when group member added ===

async def test_given_downloading_group_and_many_uncompleted_children_remaining_when_group_member_added_then_trailing_more_node_shows_download_task_for_member_added() -> None:
    N = 3
    M = 1
    async with _project_with_resource_group_starting_to_download(
                resource_count=N + 2,
                small_max_visible_children=N,
                small_max_leading_complete_children=M,
                scheduler_thread_enabled=False,
            ) as (mw, project, download_rg_ttn, download_rg_members_ttn, create_resource):
        parent_ttn = download_rg_members_ttn
        
        # Ensure initially has trailing more node
        (children_tns, children_tasks) = \
            (parent_ttn.tree_node.children, parent_ttn.task.children)
        assert len(children_tns) == N + 1
        assert all([_is_download_resource_node(tn) for tn in children_tns[:-1]])
        assert _is_more_node(children_tns[-1])
        assert 2 == _value_of_more_node(children_tns[-1])
        assert 0 + N == _materialized_child_task_count(parent_ttn)
        assert 0 == _unmaterialized_child_task_count(parent_ttn)
        
        # Case: test_given_downloading_group_and_many_uncompleted_children_remaining_when_group_member_added_then_trailing_more_node_shows_download_task_for_member_added
        create_resource()
        (children_tns, children_tasks) = \
            (parent_ttn.tree_node.children, parent_ttn.task.children)
        assert len(children_tns) == N + 1
        assert all([_is_download_resource_node(tn) for tn in children_tns[:-1]])
        assert _is_more_node(children_tns[-1])
        assert 3 == _value_of_more_node(children_tns[-1])
        assert 0 + N == _materialized_child_task_count(parent_ttn)
        assert 0 == _unmaterialized_child_task_count(parent_ttn)
        
        # Complete tasks until more node disappears,
        # but adding a task will cause it to reappear
        assert N >= M+2
        for t in parent_ttn.task.children[:M+3]:
            _mark_as_complete(t)
        (children_tns, children_tasks) = \
            (parent_ttn.tree_node.children, parent_ttn.task.children)
        assert len(children_tns) == 1 + N
        assert _is_more_node(children_tns[0])
        assert all([_is_download_resource_node(tn) for tn in children_tns[1:]])
        assert (M+2) + N == _materialized_child_task_count(parent_ttn)
        assert (M+2) == _unmaterialized_child_task_count(parent_ttn)
        
        # Case: test_given_downloading_group_and_few_uncompleted_children_remaining_when_group_member_added_then_trailing_more_node_added_with_value_1
        create_resource()
        (children_tns, children_tasks) = \
            (parent_ttn.tree_node.children, parent_ttn.task.children)
        assert len(children_tns) == 1 + N + 1
        assert _is_more_node(children_tns[0])
        assert all([_is_download_resource_node(tn) for tn in children_tns[1:-1]])
        assert _is_more_node(children_tns[-1])
        assert 1 == _value_of_more_node(children_tns[-1])
        assert (M+2) + N == _materialized_child_task_count(parent_ttn)
        assert (M+2) == _unmaterialized_child_task_count(parent_ttn)
        
        # Complete tasks until more node disappears,
        # but adding a task will NOT cause it to reappear
        for t in parent_ttn.task.children[M+3:(M+3)+2]:
            _mark_as_complete(t)
        (children_tns, children_tasks) = \
            (parent_ttn.tree_node.children, parent_ttn.task.children)
        assert len(children_tns) == 1 + (N - 1)
        assert _is_more_node(children_tns[0])
        assert all([_is_download_resource_node(tn) for tn in children_tns[1:]])
        assert ((M+2)+2) + (N - 1) == _materialized_child_task_count(parent_ttn)
        assert ((M+2)+2) == _unmaterialized_child_task_count(parent_ttn)
        
        # Case: test_given_downloading_group_and_few_uncompleted_children_remaining_when_group_member_added_then_download_task_for_member_added
        create_resource()
        (children_tns, children_tasks) = \
            (parent_ttn.tree_node.children, parent_ttn.task.children)
        assert len(children_tns) == 1 + N
        assert _is_more_node(children_tns[0])
        assert all([_is_download_resource_node(tn) for tn in children_tns[1:]])
        assert ((M+2)+2) + N == _materialized_child_task_count(parent_ttn)
        assert ((M+2)+2) == _unmaterialized_child_task_count(parent_ttn)


@skip('covered by: test_given_downloading_group_and_many_uncompleted_children_remaining_when_group_member_added_then_trailing_more_node_shows_download_task_for_member_added')
async def test_given_downloading_group_and_few_uncompleted_children_remaining_when_group_member_added_then_download_task_for_member_added() -> None:
    pass


@skip('covered by: test_given_downloading_group_and_many_uncompleted_children_remaining_when_group_member_added_then_trailing_more_node_shows_download_task_for_member_added')
async def test_given_downloading_group_and_few_uncompleted_children_remaining_when_group_member_added_then_trailing_more_node_added_with_value_1() -> None:
    pass


# === Test: RootTask ===

@skip('not yet automated')
async def test_when_top_level_task_finishes_then_is_removed_from_ui_soon(self) -> None:
    pass


# === Utility ===

@asynccontextmanager
async def _project_with_resource_group_starting_to_download(
        *, resource_count: int,
        small_max_visible_children: int,
        small_max_leading_complete_children: int,
        scheduler_thread_enabled: bool=True,
        ) -> AsyncIterator[tuple[MainWindow, Project, TaskTreeNode, TaskTreeNode, Callable[[], Resource]]]:
    if not (small_max_leading_complete_children <= small_max_visible_children):
        raise ValueError()
    
    scheduler_maybe_disabled = (
        scheduler_disabled()
        if not scheduler_thread_enabled
        else cast(AbstractContextManager, nullcontext())
    )  # type: AbstractContextManager
    
    # NOTE: NOT using the xkcd test data, because I want all xkcd URLs to give HTTP 404
    with scheduler_maybe_disabled, \
            served_project('testdata_bongo.cat.crystalproj.zip') as sp:
        # Define URLs
        if True:
            home_url = sp.get_request_url('https://xkcd.com/')
            
            comic_pattern = sp.get_request_url('https://xkcd.com/#/')
        
        # Use smaller values for children counts so that the test runs faster
        assert 100 == TaskTreeNode._MAX_VISIBLE_CHILDREN
        assert 5 == TaskTreeNode._MAX_LEADING_COMPLETE_CHILDREN
        with patch.object(TaskTreeNode, '_MAX_VISIBLE_CHILDREN', small_max_visible_children), \
                patch.object(TaskTreeNode, '_MAX_LEADING_COMPLETE_CHILDREN', small_max_leading_complete_children):
            
            async with (await OpenOrCreateDialog.wait_for()).create() as (mw, project):
                # Create group
                g = ResourceGroup(project, 'Comic', comic_pattern)
                
                # Create group members
                for i in range(1, resource_count + 1):
                    Resource(project, comic_pattern.replace('#', str(i)))
                
                # Start downloading group
                assert 0 == len(project.root_task.children)
                g.download(); append_deferred_top_level_tasks(project)
                
                (download_rg_task,) = project.root_task.children
                assert isinstance(download_rg_task, DownloadResourceGroupTask)
                load_children_of_drg_task(download_rg_task, scheduler_thread_enabled=scheduler_thread_enabled)
                (_, download_rg_members_task) = download_rg_task.children
                assert isinstance(download_rg_members_task, DownloadResourceGroupMembersTask)
                
                # Define: create_resource()
                next_resource_ordinal = resource_count + 1
                def create_resource() -> Resource:
                    nonlocal next_resource_ordinal
                    r = Resource(project, comic_pattern.replace('#', str(next_resource_ordinal)))
                    next_resource_ordinal += 1
                    return r
                
                download_rg_ttn = _ttn_for_task(download_rg_task)
                download_rg_members_ttn = _ttn_for_task(download_rg_members_task)
                try:
                    yield (
                        mw,
                        project,
                        download_rg_ttn,
                        download_rg_members_ttn,
                        create_resource,
                    )
                finally:
                    # Cleanup: Complete all children
                    _cleanup_download_of_resource_group(
                        download_rg_ttn,
                        download_rg_members_ttn,
                        project)


def _cleanup_download_of_resource_group(
        download_rg_ttn: TaskTreeNode,
        download_rg_members_ttn: TaskTreeNode,
        project: Project) -> None:
    parent_ttn = download_rg_members_ttn
    
    # Cleanup: Complete all children
    children = parent_ttn.task.children
    materialized_children = (
        [
            t for t in children._cached_prefix
            if not isinstance(t, UnmaterializedItem)
        ] + list(children[children.cached_prefix_len:])
        if isinstance(children, AppendableLazySequence)
        else children
    )
    for t in materialized_children:
        if not t.complete:
            _mark_as_complete(t)
    assert _is_complete(download_rg_members_ttn.tree_node)
    assert _is_complete(download_rg_ttn.tree_node)
    assert None == project.root_task.try_get_next_task_unit()  # clear root task
    assert len(project.root_task.children) == 0


def _viewport(ttn: TaskTreeNode) -> tuple[int, int, bool, bool]:
    """
    Returns information about the visible tasks in the specified TaskTreeNode.
    """
    tn_children = ttn.tree_node.children
    if len(tn_children) == 0:
        return (0, 0, False, False)
    
    # Calculate: offset, has_first_more_node
    first_node = tn_children[0]
    if isinstance(first_node, _MoreNodeView):
        offset = first_node.more_count
        has_first_more_node = True
    else:
        offset = 0
        has_first_more_node = False
    
    # Calculate: length, has_last_more_node
    last_node = tn_children[-1]
    has_last_more_node = isinstance(last_node, _MoreNodeView)
    length = (
        len(tn_children) -
        (1 if has_first_more_node else 0) -
        (1 if has_last_more_node else 0)
    )
    
    return (offset, length, has_first_more_node, has_last_more_node)


def _viewport_offset(ttn: TaskTreeNode) -> int:
    (offset, _, _, _) = _viewport(ttn)
    return offset


def _viewport_length(ttn: TaskTreeNode) -> int:
    (_, length, _, _) = _viewport(ttn)
    return length


def _materialized_child_task_count(parent_ttn: TaskTreeNode) -> int:
    """
    Returns the number of task children that have ever been materialized,
    including any task children that were unmaterialized later.
    """
    children = parent_ttn.task.children
    if isinstance(children, AppendableLazySequence):
        return children.cached_prefix_len
    elif isinstance(children, list):
        return len(children)
    else:
        raise AssertionError(f'Unrecognized type of children list: {children!r}')


def _unmaterialized_child_task_count(parent_ttn: TaskTreeNode) -> int:
    """
    Returns the number of task children that were once materialized
    but were unmaterialized later.
    """
    children = parent_ttn.task.children
    if isinstance(children, AppendableLazySequence):
        return sum([
            isinstance(t, UnmaterializedItem)
            for t in children._cached_prefix
        ])
    elif isinstance(children, list):
        return 0
    else:
        raise AssertionError(f'Unrecognized type of children list: {children!r}')


def _is_download_resource_node(tn: NodeView) -> bool:
    return not _is_more_node(tn)


def _is_more_node(tn: NodeView) -> bool:
    return _value_of_more_node(tn) is not None


def _value_of_more_node(tn: NodeView) -> int | None:
    tn_title = tn.title
    if not tn_title.endswith(' more'):
        return None
    return int(tn_title[:-len(' more')])


def _is_complete(tn: NodeView) -> bool:
    assert isinstance(tn, NodeView2)
    return tn.subtitle == 'Complete'
