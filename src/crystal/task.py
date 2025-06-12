from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Future
from contextlib import AbstractContextManager, nullcontext
import cProfile
from crystal.util import cli
from crystal.util.bulkheads import (
    Bulkhead, capture_crashes_to_self, capture_crashes_to_stderr,
    crashes_captured_to, CrashReason, does_not_capture_crashes,
    run_bulkhead_call,
)
from crystal.util.caffeination import Caffeination
from crystal.util.listenable import ListenableMixin
from crystal.util.profile import (
    create_profiling_context, ignore_runtime_from_enclosing_warn_if_slow,
    warn_if_slow,
)
from crystal.util.progress import ProgressBarCalculator
from crystal.util.test_mode import tests_are_running
from crystal.util.xcollections.dedup import dedup_list
from crystal.util.xcollections.lazy import (
    AppendableLazySequence, UnmaterializedItemError,
)
from crystal.util.xgc import gc_disabled
from crystal.util.xsqlite3 import is_database_closed_error
from crystal.util.xthreading import (
    bg_affinity, bg_call_later, fg_affinity, fg_call_and_wait, fg_call_later,
    fg_waiting_calling_thread, is_foreground_thread, NoForegroundThreadError,
)
from functools import wraps
import os
import shutil
import sys
import threading
from time import sleep
from time import sleep as scheduler_sleep
import traceback
from typing import Any, cast, final, Generic, List, Literal
from typing import NoReturn as Never
from typing import Optional, Tuple, TYPE_CHECKING, TypeVar
from typing_extensions import override, ParamSpec
from weakref import WeakSet

if TYPE_CHECKING:
    from crystal.doc.generic import Link
    from crystal.model import ResourceRevision


# Whether to collect profiling information about the scheduler thread.
# 
# When True, a 'scheduler.prof' file is written to the current directory
# after all projects have been closed. Such a file can be converted
# into a visual flamegraph using the "flameprof" PyPI module,
# or analyzed using the built-in "pstats" module.
_PROFILE_SCHEDULER = False


_P = ParamSpec('_P')
_R = TypeVar('_R')


# ------------------------------------------------------------------------------
# Scheduler (Early)

def scheduler_affinity(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """
    Marks the decorated function as needing to be called from either the
    scheduler thread or a task that is synced with the scheduler thread.
    
    Calling the decorated function from an inappropriate context will immediately
    raise an AssertionError.
    
    The following kinds of manipulations need to happen on the scheduler thread:
    - read/writes to Task.children,
      except for the RootTask (which only requires accesses to be on the foreground thread)
    """
    if __debug__:  # no -O passed on command line?
        @wraps(func)
        def wrapper(*args, **kwargs):
            assert is_synced_with_scheduler_thread()
            return func(*args, **kwargs)  # cr-traceback: ignore
        return wrapper
    else:
        return func


# ------------------------------------------------------------------------------
# Task

# TODO: Move these constants inside Task
SCHEDULING_STYLE_NONE = 0
"""Scheduling style for leaf tasks, that have no children."""
SCHEDULING_STYLE_SEQUENTIAL = 1
"""Each child will be fully executed before moving on to the next child."""
SCHEDULING_STYLE_ROUND_ROBIN = 2
"""One task unit will be executed from each child during a scheduler pass."""


class Task(ListenableMixin, Bulkhead, Generic[_R]):
    """
    Encapsulates a long-running process that reports its status occasionally.
    A task may depend on the results of a child task during its execution.
    
    Generally there are two kinds of tasks:
    (1) Leaf tasks
        - Performs a single long-running operation on a background thread
          and completes immediately after this operation is complete.
            - The operation is executed by the __call__() method,
              which must be implemented by leaf task subclasses.
    (2) Container tasks
        - Uses child tasks to perform all its work.
            - Should define the 'scheduling_style' property in its class definition.
            - Should add the initial set of children in its constructor.
        - May add additional children tasks over time to perform additional work.
            - Generally this is done upon the completion of a child task.
        - Automatically listen to child tasks. A container task may override:
            o child_task_subtitle_did_change -- Notified when a child of this task changed its subtitle
            o child_task_did_complete -- Notified when a child of this task completed
    
    Tasks must generally be manipulated on the foreground thread unless
    documented otherwise.
    
    A task's result can be obtained from its future.
    
    Using tasks:
    - Arbitrary code can perform some action in the background by creating a task,
      adding a listener to the task's future (or otherwise storing the future),
      and scheduling the task within the project using Project.add_task().
    - A task may perform a subtask by creating a Task object for the subtask,
      and scheduling the subtask within itself using Task.append_child().
    
    A parent task is responsible for disposing each of its child tasks using 
    Task.dispose() after it has processed the child's result.
    Any tasks scheduled directly on a project's root task with Project.add_task()
    will have its result automatically disposed once the task is complete.
    So if you care about the result of a task you plan to schedule on a project, 
    be sure to save the task's future *before* scheduling it.
    
    Tasks are not allowed to be complete immediately after initialization
    unless explicitly documented in the Task class's docstring.
    """
    # Abstract fields for subclasses to override
    icon_name = None  # type: Optional[str]  # abstract
    """The name of the icon resource used for this task, or None to use the default icon."""
    scheduling_style = SCHEDULING_STYLE_NONE  # abstract for container task types
    """For a container task, defines the order that task units from children will be executed in."""
    all_children_complete_implies_this_task_complete = True
    """For a container task, whether all of its children being complete implies that the container should be complete."""
    all_incomplete_children_crashed_implies_this_task_should_crash = True
    """For a container task, whether all of its incomplete children being crashed implies that the container should crash as well."""
    
    _USE_EXTRA_LISTENER_ASSERTIONS_ALWAYS = (
        tests_are_running()
    )
    _USE_EXTRA_LISTENER_ASSERTIONS_WHEN_CHILD_COUNT_BELOW = 50
    _REPORTED_TASKS_WITH_MANY_LISTENERS = WeakSet()  # type: WeakSet[Task]
    
    # Optimize per-instance memory use, since there may be very many Task objects
    __slots__ = (
        '_title',
        '_subtitle',
        '_crash_reason',
        '_parent',
        '_children',
        '_num_children_complete',
        '_complete',
        '_did_yield_self',
        '_future',
        # NOTE: Used differently by SCHEDULING_STYLE_SEQUENTIAL and SCHEDULING_STYLE_ROUND_ROBIN
        '_next_child_index',
        
        # Necessary to support weak references to task objects,
        # such as by Task._REPORTED_TASKS_WITH_MANY_LISTENERS
        '__weakref__',
    )
    
    def __init__(self, title: str) -> None:
        super().__init__()
        
        self._title = title
        self._subtitle = 'Queued'
        self._crash_reason = None  # type: Optional[CrashReason]
        self._parent = None  # type: Optional[Task]
        self._children = []  # type: Sequence[Task]
        self._num_children_complete = 0
        self._complete = False
        
        self._did_yield_self = False            # used by leaf tasks
        self._future = None  # type: Optional[Future[_R]]  # used by leaf tasks
        self._next_child_index = 0
    
    # === Bulkhead ===
    
    def _get_crash_reason(self) -> CrashReason | None:
        return self._crash_reason
    def _set_crash_reason(self, value: CrashReason | None) -> None:
        self._crash_reason = value
        for lis in self.listeners:
            if hasattr(lis, 'task_crash_reason_did_change'):
                run_bulkhead_call(lis.task_crash_reason_did_change, self)  # type: ignore[attr-defined]
    crash_reason = cast(Optional[CrashReason], property(_get_crash_reason, _set_crash_reason))
    
    # === Properties ===
    
    @property
    def title(self) -> str:
        """
        The title of this task. Fixed upon initialization.
        """
        return self._title
    
    def _get_subtitle(self) -> str:
        """
        The subtitle for this task.
        """
        return self._subtitle
    def _set_subtitle(self, value: str) -> None:
        if self._subtitle == 'Complete':
            assert value == 'Complete', \
                f'Cannot change subtitle of completed task {self!r} to {value!r}'
        self._subtitle = value
        for lis in self.listeners:
            if hasattr(lis, 'task_subtitle_did_change'):
                run_bulkhead_call(lis.task_subtitle_did_change, self)  # type: ignore[attr-defined]
    subtitle = property(_get_subtitle, _set_subtitle)
    
    # TODO: Alter parent tracking to support multiple parents,
    #       since in truth a Task can already have multiple parents,
    #       but we currently only remember one parent at a time.
    @property
    def parent(self) -> Task | None:
        """
        The most-recently set parent of this task or None if no such parent
        exists or this task type doesn't permit parent tracking.
        """
        return self._parent
    
    @property
    def children(self) -> Sequence[Task]:
        """
        Children task of this task.
        
        Callers should use append_child() instead of modifying the returned list.
        
        Task subclasses require (and enforce) that accesses to the 
        children list occur on a particular thread, usually the scheduler thread.
        """
        # For tasks that have been added to the task tree,
        # force any children access to synchronize with scheduler thread
        if self.parent is not None:
            if not is_synced_with_scheduler_thread():
                cur_task = self
                while cur_task.parent is not None:
                    cur_task = cur_task.parent
                self_within_root_task = isinstance(cur_task, RootTask)
                
                if self_within_root_task:
                    raise AssertionError(
                        'Unsafe to access children of a task within a RootTask '
                        'without the caller being synchronized with '
                        'the scheduler thread')
        
        return self._children
    
    @final
    @property
    def children_unsynchronized(self) -> Sequence[Task]:
        """
        Children task of this task, possibly in an inconsistent state if
        accesses normally need to be synchronized with a particular thread
        and the caller is not on that thread.
        
        Callers should use append_child() instead of modifying the returned list.
        """
        return self._children
    
    @property
    def num_children_complete(self) -> int:
        return self._num_children_complete
    
    @property
    def complete(self) -> bool:
        """
        Whether this task is complete.
        """
        return self._complete
    
    @property
    def future(self) -> Future[_R]:
        """
        Returns a Future that receives the result of this task.
        
        This property is only defined by default for leaf tasks.
        Container tasks may optionally override this if they
        conceptually return a value.
        """
        if callable(self):
            if self._future is None:
                self._future = Future()
            return self._future
        else:
            raise ValueError('Container tasks do not define a result by default.')
    
    @capture_crashes_to_self
    def dispose(self) -> None:
        """
        Replaces this task's future with a new future that raises a 
        TaskDisposedException, allowing the original future to be
        garbage-collected if it isn't referenced elsewhere.
        """
        self._future = _FUTURE_WITH_TASK_DISPOSED_EXCEPTION  # garbage collect old value
    
    # === Protected Operations: Lazy Children ===
    
    def initialize_children(self, children: Sequence[Task]) -> Callable[[], None]:
        """
        Initializes this task's children to the specified sequence.
        
        Tasks are pre-initialized with an initially empty list of children
        so it is not necessary for a subclass to call this method if
        the subclass plans to instead use append_child() to populate that
        empty list.
        """
        assert len(self._children) == 0, (
            f'Cannot replace existing children with new children. '
            f'Current children are: {self._children}'
        )
        self._children = children
        
        def notify_task_did_set_children():
            for lis in self.listeners:
                if hasattr(lis, 'task_did_set_children'):
                    run_bulkhead_call(lis.task_did_set_children, self, len(children))  # type: ignore[attr-defined]
        return notify_task_did_set_children
    
    def materialize_child(self, child: Task, *, already_complete_ok: bool=False) -> None:
        """
        Called when the specified child of this task has been instantiated
        and is ready to be listened to.
        
        Upon return the child is said to be "materialized".
        """
        if child.complete and not already_complete_ok:
            raise ValueError(
                f'Child being appended is already complete, '
                f'and already_completed_ok is False. '
                f'self={self}, child={child}')
        
        if self._use_extra_listener_assertions:
            assert child in self._children
        # NOTE: child._parent may already be set to a different parent
        child._parent = self
        
        if self._use_extra_listener_assertions:
            assert self not in child.listeners, (
                f'Expected {self=} to not already be listening to {child=}. '
                f'Was child added multiple times to the same parent?'
            )
        if len(child.listeners) >= 50:
            if child not in Task._REPORTED_TASKS_WITH_MANY_LISTENERS:
                Task._REPORTED_TASKS_WITH_MANY_LISTENERS.add(child)
                print(f'*** Task has many listeners and may be leaking them: {child}', file=sys.stderr)
                for lis in child.listeners:
                    print(f'    - {lis}')
        child.listeners.append(self)
    
    def notify_did_append_child(self, child: Task | None) -> None:
        """
        Notifies listeners that a child was appended to this task's children.
        
        The child might not be materialized/instantiated yet.
        
        Arguments:
        * child -- the child that was appended iff it is materialized,
            or None if the child is not materialized.
        """
        for lis in self.listeners:
            if hasattr(lis, 'task_did_append_child'):
                run_bulkhead_call(lis.task_did_append_child, self, child)  # type: ignore[attr-defined]
    
    # === Protected Operations: Greedy Children ===
    
    def append_child(self, child: Task, *, already_complete_ok: bool=False) -> None:
        """
        Appends the specified task at the end of this task's children.
        
        By default the specified child task is not permitted to already be
        complete, because normally this task's listeners expect to receive a
        "task_did_complete" event in the future when a child becomes complete.
        If an already-complete task is added by this method then that event
        won't be fired.
        
        If already_complete_ok=True then the specified child task is allowed
        to already be complete and the caller is responsible for handling
        any special behavior related to adding an already-complete task,
        such as proactively firing the "task_did_complete" event on this task.
        """
        if not isinstance(self._children, list):
            raise ValueError('Cannot call append_child() after calling initialize_children()')
        
        self._children.append(child)
        self.materialize_child(child, already_complete_ok=already_complete_ok)
        
        self.notify_did_append_child(child)
    
    # === Protected Operations: Finish & Cleanup ===
    
    def finish(self) -> None:
        """
        Marks this task as completed.
        """
        # Mark as complete immediately, because caller may check this task's complete status
        self._complete = True
        
        self.subtitle = 'Complete'
        
        # NOTE: Making a copy of the listener list since it is likely to be modified by callees.
        for lis in list(self.listeners):
            if hasattr(lis, 'task_did_complete'):
                run_bulkhead_call(lis.task_did_complete, self)  # type: ignore[attr-defined]
    
    def finalize_children(self, final_children: list[Task]) -> None:
        """
        Replace all completed children with a new set of completed children.
        
        NOTE: task_did_complete() events are NOT fired for the new final_children,
        because its assumed that most of them were children of this task before
        and that their task_did_complete() events were already fired.
        """
        if not all([c.complete for c in self.children]):
            raise ValueError('Some children are not complete.')
        if not all([c.complete for c in final_children]):
            raise ValueError('Some final children are not complete.')
        did_clear = self.clear_children_if_all_complete()
        assert did_clear
        
        for c in final_children:
            self.append_child(c, already_complete_ok=True)
        # NOTE: Must manually update some bookkeeping normally done by
        #       task_did_complete() because that event type isn't being fired
        self._num_children_complete = len(final_children)
    
    def clear_children_if_all_complete(self) -> bool:
        """
        Clears all of this task's children if they are all complete.
        Returns whether the children were cleared.
        """
        all_children_complete = all(c.complete for c in self.children)
        if all_children_complete:
            for child in self._children:
                child._parent = None
                if self._use_extra_listener_assertions:
                    assert self not in child.listeners
            self._children = []
            self._num_children_complete = 0
            
            self._next_child_index = 0
            
            # NOTE: Call these listeners also inside the lock
            #       because they are likely to be updating
            #       data structures that need to be strongly
            #       synchronized with the modified child list.
            for lis in self.listeners:
                if hasattr(lis, 'task_did_clear_children'):
                    run_bulkhead_call(lis.task_did_clear_children, self)  # type: ignore[attr-defined]
        return all_children_complete
    
    def clear_completed_children(self) -> None:
        """
        Clears all of this task's children which are complete.
        """
        if self._next_child_index != 0:
            raise ValueError('Unsafe to call clear_completed_children unless _next_child_index == 0')
        
        child_indexes_to_remove = [i for (i, c) in enumerate(self._children) if c.complete]  # capture
        if len(child_indexes_to_remove) == 0:
            return
        for child in [c for c in self._children if c.complete]:
            child._parent = None
            if self._use_extra_listener_assertions:
                assert self not in child.listeners, (
                    f'Expected {self=} to no longer be listening to completed {child=}'
                )
        self._children = [c for c in self.children if not c.complete]
        self._num_children_complete = 0
        
        # NOTE: Call these listeners also inside the lock
        #       because they are likely to be updating
        #       data structures that need to be strongly
        #       synchronized with the modified child list.
        for lis in self.listeners:
            if hasattr(lis, 'task_did_clear_children'):
                run_bulkhead_call(lis.task_did_clear_children, self, child_indexes_to_remove)  # type: ignore[attr-defined]
    
    # === Public Operations ===
    
    @capture_crashes_to_self
    @fg_affinity
    def try_get_next_task_unit(self) -> Callable[[], None] | None:
        """
        Returns a callable ("task unit") that completes a unit of work for
        this task, or None if no more units can be provided until at least
        one of the previously returned units completes.
        
        Task units may be run on any thread.
        
        If this is a leaf task, its own __call__() method will be returned
        as the solitary task unit. As a task unit, it must be designed to
        run on any thread.
        """
        
        # If this task previously crashed and either itself or its children are
        # in a potentially invalid state, refuse to run this task any further
        if self.crash_reason is not None:
            return None
        
        if self.complete:
            return None
        
        if callable(self):
            if not self._did_yield_self:
                self._did_yield_self = True
                return self._call_self_and_record_result
            else:
                return None
        else:
            if len(self.children) == 0:
                raise ValueError(f'Container task has no children tasks: {self!r}')
            
            if self.scheduling_style == SCHEDULING_STYLE_NONE:
                raise ValueError('Container task has not specified a scheduling style.')
            elif self.scheduling_style == SCHEDULING_STYLE_SEQUENTIAL:
                while self._next_child_index < len(self.children):
                    try:
                        next_child_complete = self.children[self._next_child_index].complete
                    except UnmaterializedItemError:
                        # Assume that any unmaterialized item must be complete
                        next_child_complete = True
                    if next_child_complete:
                        self._next_child_index += 1
                    else:
                        cur_child_index = self._next_child_index
                        while cur_child_index < len(self.children):
                            cur_child = self.children[cur_child_index]
                            if cur_child.crash_reason is not None:
                                # If child crashed then this parent task cannot
                                # proceed and must crash for the same reason
                                self.crash_reason = cur_child.crash_reason
                                return None
                            unit = cur_child.try_get_next_task_unit()
                            if unit is not None:
                                return unit
                            cur_child_index += 1
                        return None
                # (All children are complete yet this container task is not complete)
                
                if type(self).all_children_complete_implies_this_task_complete:
                    if isinstance(self.children, list):
                        assert all([c.complete for c in self.children])
                    elif isinstance(self.children, AppendableLazySequence):
                        assert all([c.complete for c in self.children.materialized_items()])
                    else:
                        # No safe way to assert that all children are complete
                        pass
                    assert not self.complete  # checked earlier in this function
                    raise AssertionError(
                        f'{self!r} has all complete children yet is not itself marked as complete')
                else:
                    return None
            elif self.scheduling_style == SCHEDULING_STYLE_ROUND_ROBIN:
                if self._next_child_index == 0:
                    # NOTE: Ignore known-slow operation that has no further obvious optimizations
                    with ignore_runtime_from_enclosing_warn_if_slow():
                        schedule_check_result = self._notify_did_schedule_all_children()
                    if not isinstance(schedule_check_result, bool):
                        return schedule_check_result
                cur_child_index = self._next_child_index
                while True:
                    unit = self.children[cur_child_index].try_get_next_task_unit()
                    if unit is not None:
                        self._next_child_index = (cur_child_index + 1) % len(self.children)
                        return unit
                    cur_child_index = (cur_child_index + 1) % len(self.children)
                    if cur_child_index == self._next_child_index:
                        # Wrapped around and back to where we started without finding anything to do
                        if type(self).all_incomplete_children_crashed_implies_this_task_should_crash:
                            first_crashed_child = next((c for c in self.children if c.crash_reason is not None), None)
                            if first_crashed_child is not None:
                                # Presumably this parent task cannot proceed because all
                                # child tasks are either crashed or complete.
                                # So crash this parent task with the same reason
                                # as one of the crashed children.
                                self.crash_reason = first_crashed_child.crash_reason
                        return None
                    if cur_child_index == 0:
                        # NOTE: Ignore known-slow operation that has no further obvious optimizations
                        with ignore_runtime_from_enclosing_warn_if_slow():
                            schedule_check_result = self._notify_did_schedule_all_children()
                        if not isinstance(schedule_check_result, bool):
                            return schedule_check_result
                        elif schedule_check_result == True:
                            # Invalidate self._next_child_index,
                            # because children may have changed
                            self._next_child_index = 0
            else:
                raise ValueError('Container task has an unknown scheduling style (%s).' % self.scheduling_style)
    
    def _notify_did_schedule_all_children(self) -> bool | Callable[[], None] | None:
        if hasattr(self, 'did_schedule_all_children'):
            self.did_schedule_all_children()  # type: ignore[attr-defined]
            # (Children may have changed)
            if len(self.children) == 0:
                # Handle zero-children case in usual manner
                return self.try_get_next_task_unit()
            return True  # children may have changed
        else:
            return False  # children did not change
    
    @bg_affinity
    @capture_crashes_to_self
    def _call_self_and_record_result(self) -> None:
        if TYPE_CHECKING:
            assert isinstance(self, _LeafTask[_R])  # type: ignore[misc]
        
        # (Ignore client requests to cancel)
        if self._future is None:
            self._future = Future()
        if self._future.done():
            raise AssertionError(f'Future for {self!r} was already done')
        self._future.set_running_or_notify_cancel()
        try:
            # NOTE: Prefer `self.__call__()` over `self()` because the former
            #       is easier to mock in automated tests
            self._future.set_result(self.__call__())
        except BaseException as e:
            self._future.set_exception(e)
        finally:
            self.finish()
    
    # === Internal Events ===
    
    @final
    @capture_crashes_to_self
    def task_subtitle_did_change(self, task: Task) -> None:
        if self._use_extra_listener_assertions:
            assert task in self.children_unsynchronized
        
        if hasattr(self, 'child_task_subtitle_did_change'):
            self.child_task_subtitle_did_change(task)
    
    @final
    @capture_crashes_to_self
    def task_did_complete(self, task: Task) -> None:
        if self._use_extra_listener_assertions:
            assert task in self.children_unsynchronized
        
        self._num_children_complete += 1
        
        task.listeners.remove(self)
        if self._use_extra_listener_assertions:
            assert self not in task.listeners
        
        if hasattr(self, 'child_task_did_complete'):
            self.child_task_did_complete(task)
        for lis in self.listeners:
            if hasattr(lis, 'task_child_did_complete'):
                run_bulkhead_call(lis.task_child_did_complete, self, task)  # type: ignore[attr-defined]
    
    @final
    @capture_crashes_to_self
    def task_crash_reason_did_change(self, task: Task) -> None:
        if self._use_extra_listener_assertions:
            assert task in self.children_unsynchronized
        
        if hasattr(self, 'child_task_did_crash'):
            self.child_task_did_crash(task)
    
    # === Utility ===
    
    @property
    def _use_extra_listener_assertions(self) -> bool:
        return (
            # Enable assertions if forced on
            Task._USE_EXTRA_LISTENER_ASSERTIONS_ALWAYS or
            # Enable assertions if child count is low enough
            # that assertions aren't too expensive
            len(self._children) < Task._USE_EXTRA_LISTENER_ASSERTIONS_WHEN_CHILD_COUNT_BELOW
        )


class TaskDisposedException(Exception):
    pass

_TASK_DISPOSED_EXCEPTION = TaskDisposedException()

_FUTURE_WITH_TASK_DISPOSED_EXCEPTION = Future()  # type: Future[Any]
_FUTURE_WITH_TASK_DISPOSED_EXCEPTION.set_exception(_TASK_DISPOSED_EXCEPTION)


# ------------------------------------------------------------------------------
# _LeafTask, _PureContainerTask

class _LeafTask(Generic[_R], Task[_R]):  # abstract
    """
    A leaf task is a callable that returns a result.
    That result can be accessed through the .future attribute.
    """
    # Optimize per-instance memory use, since there may be very many Task objects
    __slots__ = ()
    
    def __call__(self) -> _R:  # abstract
        raise NotImplementedError()


class _PureContainerTask(Task[Never]):  # abstract
    """
    A pure container task is a container task that has no result of its own.
    
    Non-pure container tasks should inherit directly from Task[ResultType].
    """
    # Optimize per-instance memory use, since there may be very many Task objects
    __slots__ = ()


# ------------------------------------------------------------------------------
# CrashedTask

class CrashedTask(_LeafTask[Never]):
    """
    Crashed task that presents a fixed title.
    """
    # TODO: Rename icon as 'tree_warning' so that icon owned by EntityTree
    #       is not referenced here (in a TaskTree context).
    icon_name = 'entitytree_warning'
    
    def __init__(self,
            title: str,
            reason: CrashReason,
            dismiss_func: Callable[[], None],
            dismiss_action_title: str='Dismiss') -> None:
        super().__init__(title=title)
        self.crash_reason = reason
        self._dismiss_func = dismiss_func  # type: Optional[Callable[[], None]]
        self.dismiss_action_title = dismiss_action_title
    
    @bg_affinity
    def __call__(self) -> Never:
        raise AssertionError('Cannot run a crashed task')
    
    def dismiss(self) -> None:
        if self._dismiss_func is not None:
            self._dismiss_func()
            self._dismiss_func = None  # garbage collect


# ------------------------------------------------------------------------------
# DownloadResourceTask

from crystal.model import Resource
from urllib.parse import urljoin

# Limit how fast Crystal can download from a remote server to avoid overwhelming
# any particular remote server.
DELAY_BETWEEN_DOWNLOADS = 0.5  # secs

# Configures where the DELAY_BETWEEN_DOWNLOADS delay is inserted
# into the download process. Options are:
# * 'after_every_page' -- 
#     A delay is inserted after downloading a page and all its embedded resources.
#     Simulates user browsing behavior most closely.
# * 'after_every_resource' --
#     A delay is inserted after downloading a page and after each of its
#     embedded resources is downloaded.
#     Uses server-side compute & bandwidth more slowly.
_DOWNLOAD_DELAY_STYLE = 'after_every_page'  # type: Literal['after_every_page', 'after_every_resource']

# NOTE: This optimization is important for downloading large projects.
#       Do not recommend disabling.
ASSUME_RESOURCES_DOWNLOADED_IN_SESSION_WILL_ALWAYS_REMAIN_FRESH = True

# For small disks/filesystems,
# the minimum fraction of total disk space required to download any more resources
_SMALL_DISK_MIN_PROJECT_FREE_FRACTION = 0.05

# For large disks/filesystems,
# the minimum free disk space required to download any more resources
_LARGE_DISK_MIN_PROJECT_FREE_BYTES = 1024 * 1024 * 1024 * 4  # 4 GiB

_MAX_EMBEDDED_RESOURCE_RECURSION_DEPTH = 3


def _get_abstract_resource_title(abstract_resource: Resource | RootResource) -> str:
    """
    Arguments:
    * abstract_resource -- a Resource or a RootResource.
    """
    resource = abstract_resource.resource
    name = getattr(abstract_resource, 'name', '') or ''
    if name != '':
        return '{} - {}'.format(resource.url, name)
    else:
        return '%s' % (resource.url)


# Whether to collect profiling information about Resource.default_revision()
# as used by DownloadResourceBodyTask.
# 
# When True, a 'default_revision.prof' file is written to the current directory
# after all projects have been closed. Such a file can be converted
# into a visual flamegraph using the "flameprof" PyPI module,
# or analyzed using the built-in "pstats" module.
_PROFILE_READ_REVISION = False

PROFILE_RECORD_LINKS = os.environ.get('CRYSTAL_NO_PROFILE_RECORD_LINKS', 'False') != 'True'

class DownloadResourceBodyTask(_LeafTask['ResourceRevision']):
    """
    Downloads a single resource's body.
    This is the most basic task, located at the leaves of the task tree.
    
    Returns a ResourceRevision.
    
    This task is never complete immediately after initialization.
    """
    icon_name = 'tasktree_download_resource_body'
    
    _dr_profiling_context = None  # type: AbstractContextManager[Optional[cProfile.Profile]]
    
    # Optimize per-instance memory use, since there may be very many DownloadResourceBodyTask objects
    __slots__ = (
        '_resource',
        'did_download',
    )
    
    def __init__(self, abstract_resource: Resource | RootResource) -> None:
        """
        Arguments:
        * abstract_resource -- a Resource or a RootResource.
        """
        super().__init__(
            title='Downloading body: ' + _get_abstract_resource_title(abstract_resource))
        self._resource = abstract_resource.resource  # type: Resource
        self.did_download = None  # type: Optional[bool]
    
    @bg_affinity
    def __call__(self) -> ResourceRevision:
        """
        Raises:
        * CannotDownloadWhenProjectReadOnlyError --
            If resource is not already downloaded and project is read-only.
        * ProjectFreeSpaceTooLowError --
            If the project does not have enough free disk space to safely
            download more resources.
        * ProjectHasTooManyRevisionsError
        """
        # Return the resource's fresh (already-downloaded) default revision if available
        if self._resource.definitely_has_no_revisions:
            body_revision = None
        else:
            @does_not_capture_crashes
            def fg_task() -> ResourceRevision | None:
                DRBT = DownloadResourceBodyTask
                if DRBT._dr_profiling_context is None:
                    DRBT._dr_profiling_context = create_profiling_context(
                        'default_revision.prof',
                        enabled=_PROFILE_READ_REVISION)
                with DRBT._dr_profiling_context:
                    return self._resource.default_revision(stale_ok=False)
            # NOTE: Use profile=False because no obvious further optimizations exist
            body_revision = fg_call_and_wait(fg_task, profile=False)
        if body_revision is not None:
            self.did_download = False
            return body_revision
        else:
            self.did_download = True
        
        if self._resource.project.readonly:
            raise CannotDownloadWhenProjectReadOnlyError()
        
        disk_usage = shutil.disk_usage(self._resource.project.path)
        min_free_bytes = min(
            int(disk_usage.total * _SMALL_DISK_MIN_PROJECT_FREE_FRACTION),
            _LARGE_DISK_MIN_PROJECT_FREE_BYTES
        )
        if disk_usage.free < min_free_bytes:
            raise ProjectFreeSpaceTooLowError()
        
        # TODO: Report errors (embedded in the ResourceRevision) using the completion subtitle.
        #       Need to add support for this behavior to Task.
        try:
            from crystal.download import download_resource_revision
            return download_resource_revision(self._resource, self)
        finally:
            if _DOWNLOAD_DELAY_STYLE == 'after_every_resource':
                self.subtitle = 'Waiting before performing next request...'
                assert not is_foreground_thread()
                sleep(DELAY_BETWEEN_DOWNLOADS)
    
    def __repr__(self) -> str:
        return f'<DownloadResourceBodyTask for {self._resource.url!r}>'


class CannotDownloadWhenProjectReadOnlyError(Exception):
    pass


class ProjectFreeSpaceTooLowError(Exception):
    pass


class DownloadResourceTask(Task['ResourceRevision']):
    """
    Downloads a resource and all of its embedded resources recursively.
    
    Returns the ResourceRevision for the resource body.
    This is returned before all embedded resources have finished downloading,
    unless you specially use get_future(wait_for_embedded=True).
    
    This task may be complete immediately after initialization.
    """
    icon_name = 'tasktree_download_resource'
    scheduling_style = SCHEDULING_STYLE_SEQUENTIAL
    
    # Optimize per-instance memory use, since there may be very many
    # DownloadResourceTask objects
    __slots__ = (
        '_abstract_resource',
        '_is_embedded',
        '_pbc',
        '_download_body_task',
        '_parse_links_task',
        '_already_downloaded_task',
        '_download_body_with_embedded_future',
    )
    
    def __init__(self,
            abstract_resource: Resource | RootResource,
            *, needs_result: bool=True,
            is_embedded: bool=False,
            ) -> None:
        """
        Arguments:
        * abstract_resource -- a Resource or a RootResource.
        """
        super().__init__(
            title='Downloading: ' + _get_abstract_resource_title(abstract_resource))
        self._abstract_resource = abstract_resource
        self._is_embedded = is_embedded
        self._pbc = None  # type: Optional[ProgressBarCalculator]
        
        resource = abstract_resource.resource  # cache
        
        self._download_body_task = (
            None
            if resource.already_downloaded_this_session and not needs_result
            else resource.create_download_body_task()
        )  # type: Optional[DownloadResourceBodyTask]
        self._parse_links_task = None  # type: Optional[ParseResourceRevisionLinks]
        self._already_downloaded_task = (
            _ALREADY_DOWNLOADED_PLACEHOLDER_TASK
            if resource.already_downloaded_this_session
            else None
        )
        
        if self._download_body_task is not None:
            self.append_child(self._download_body_task)
        if self._already_downloaded_task is not None:
            self.append_child(self._already_downloaded_task, already_complete_ok=True)
        
        self._download_body_with_embedded_future = None  # type: Optional[Future[ResourceRevision]]
        
        # Prevent other DownloadResourceTasks created during this session from
        # attempting to redownload this resource since they would duplicate
        # the same actions and waste time
        if ASSUME_RESOURCES_DOWNLOADED_IN_SESSION_WILL_ALWAYS_REMAIN_FRESH:
            resource.already_downloaded_this_session = True
        
        # Apply deferred child-complete actions
        t = self._already_downloaded_task
        if t is not None:
            assert t.complete
            self.task_did_complete(t)
        # (NOTE: self.complete might be True now)
    
    @property
    def future(self) -> Future[ResourceRevision]:
        return self.get_future(wait_for_embedded=False)
    
    def get_future(self, wait_for_embedded: bool=False) -> Future[ResourceRevision]:
        if self._download_body_task is None:
            assert self._already_downloaded_task is not None
            return self._already_downloaded_task.future
        else:
            if not wait_for_embedded:
                return self._download_body_task.future
            else:
                if self._download_body_with_embedded_future is None:
                    self._download_body_with_embedded_future = Future()
                return self._download_body_with_embedded_future
    
    @override
    @capture_crashes_to_self
    def dispose(self) -> None:
        super().dispose()
        if self._download_body_task is not None:
            self._download_body_task.dispose()
        self._download_body_with_embedded_future = \
            _FUTURE_WITH_TASK_DISPOSED_EXCEPTION  # garbage collect old value
    
    # === Properties ===
    
    @property
    def resource(self) -> Resource:
        return self._abstract_resource.resource
    
    # === Events ===
    
    @capture_crashes_to_self
    def child_task_subtitle_did_change(self, task: Task) -> None:
        if task is self._download_body_task:
            if not task.complete:
                self.subtitle = task.subtitle
    
    @capture_crashes_to_self
    def child_task_did_complete(self, task: Task) -> None:
        from crystal.model import (
            ProjectHasTooManyRevisionsError, RevisionBodyMissingError,
        )
        
        if task is self._download_body_task:
            if self._already_downloaded_task is not None:
                # Don't reparse links or attempt to redownload embedded resources
                pass
            else:
                try:
                    body_revision = self._download_body_task.future.result()
                except (CannotDownloadWhenProjectReadOnlyError,
                        ProjectFreeSpaceTooLowError,
                        ProjectHasTooManyRevisionsError):
                    # Ignore error
                    pass
                    
                    # Behave as if there are no embedded resources
                except Exception as e:
                    if is_database_closed_error(e):
                        # Probably the project was closed. Ignore error.
                        pass
                    else:
                        print(
                            f'*** Unexpected error while downloading: {self.resource.url}',
                            file=sys.stderr)
                        traceback.print_exc(file=sys.stderr)
                    
                    # Behave as if there are no embedded resources
                else:
                    # 1. If revision is an error page then do not download any embedded
                    #    resources automatically. Poorly written error pages may
                    #    themselves download other resources with errors,
                    #    recursing infinitely.
                    # 2. Don't try to parse files known to be binary files
                    status_code = body_revision.status_code or 500
                    is_error_page = (status_code // 100) in (4, 5)  # HTTP 4xx or 5xx
                    if not is_error_page and not body_revision.is_recognized_binary_type:
                        self._parse_links_task = ParseResourceRevisionLinks(self._abstract_resource, body_revision)
                        self.append_child(self._parse_links_task)
                
                # (Don't dispose self._download_body_task because its future is
                #  used for this task's own future.)
        
        elif task is self._parse_links_task:
            try:
                try:
                    (links, _) = self._parse_links_task.future.result()
                finally:
                    self._parse_links_task.dispose()
            except RevisionBodyMissingError:
                assert self._download_body_task is not None
                body_revision = self._download_body_task.future.result()
                
                print(
                    f'*** {body_revision!s} is missing its body on disk. Redownloading it.',
                    file=sys.stderr)
                
                # Delete the malformed revision
                fg_call_and_wait(lambda: body_revision.delete())
                
                # Retry download of the revision
                redownload_body_task = self.resource.create_download_body_task()
                self.append_child(redownload_body_task)
                
                self._download_body_task = redownload_body_task  # reinterpret
                self._parse_links_task = None  # reinterpret
            else:
                # Identify embedded resources
                @does_not_capture_crashes
                def fg_task() -> list[Resource]:
                    embedded_resources = []
                    link_urls_seen = set()
                    base_url = self.resource.url  # cache
                    project = self.resource.project  # cache
                    dnd_groups = [g for g in project.resource_groups if g.do_not_download]  # cache
                    for link in links:
                        if not link.embedded:
                            continue
                        
                        link_url = urljoin(base_url, link.relative_url)
                        if link_url in link_urls_seen:
                            continue
                        else:
                            link_urls_seen.add(link_url)
                        
                        # Normalize the URL and look it up in the project
                        # 
                        # NOTE: Normally this should not perform any database
                        #       queries, unless one of the related Resources
                        #       was deleted sometime between being created
                        #       by ParseResourceRevisionLinks and being
                        #       accessed here.
                        link_resource = Resource(project, link_url)
                        if not any([g.contains_url(link_resource.url) for g in dnd_groups]):
                            embedded_resources.append(link_resource)
                    return embedded_resources
                embedded_resources = fg_call_and_wait(fg_task)
                
                # Create and append download task for each embedded resource
                new_download_tasks = []
                ancestor_downloading_resources = self._ancestor_downloading_resources()  # cache
                if len(ancestor_downloading_resources) > _MAX_EMBEDDED_RESOURCE_RECURSION_DEPTH:
                    # Avoid infinite recursion when resource identifies an alias
                    # of itself (probably incorrectly) as an embedded resource of 
                    # itself, or when a chain of embedded resources links to 
                    # an alias of itself
                    pass
                else:
                    for resource in dedup_list(embedded_resources):
                        if resource in ancestor_downloading_resources:
                            # Avoid infinite recursion when resource identifies itself
                            # (probably incorrectly) as an embedded resource of itself,
                            # or when a chain of embedded resources links to itself
                            continue
                        new_download_tasks.append(
                            resource.create_download_task(needs_result=False, is_embedded=True))
                for t in new_download_tasks:
                    self.append_child(t, already_complete_ok=True)
                
                # Start computing estimated time remaining
                self._pbc = ProgressBarCalculator(
                    initial=self.num_children_complete,
                    total=len(self.children),
                )
                
                for t in [t for t in new_download_tasks if t.complete]:
                    self.task_did_complete(t)
                # (NOTE: self.complete might be True now)
        
        else:
            assert isinstance(task, (
                DownloadResourceTask,
                _DownloadResourcesPlaceholderTask,
                _AlreadyDownloadedPlaceholderTask
            ))
            task.dispose()
            
            if isinstance(task, DownloadResourceTask):
                # Revise estimated time remaining
                assert self._pbc is not None
                self._pbc.update(1)
        
        # NOTE: The `self.complete` check is necessary to avoid double-completing
        #       this task in the scenario where a self._parse_links_task child task
        #       finds that ALL discovered links have already been downloaded, 
        #       which implies that the download task related to the last link
        #       will have already completed this task.
        if self.complete:
            return
        
        assert 0 <= self.num_children_complete <= len(self.children)
        if self._pbc is None:
            subtitle_suffix = ''
        else:
            (remaining_str, time_per_item_str) = \
                self._pbc.remaining_str_and_time_per_item_str()
            subtitle_suffix = f' -- {remaining_str} remaining ({time_per_item_str})'
        self.subtitle = (
            f'{self.num_children_complete:n} of '
            f'{len(self.children):n} item(s){subtitle_suffix}'
        )
        
        if self.num_children_complete == len(self.children):
            # Complete self._download_body_with_embedded_future,
            # with value of self._download_body_task.future
            if self._download_body_task is not None:
                exc = self._download_body_task.future.exception()
                if self._download_body_with_embedded_future is None:
                    self._download_body_with_embedded_future = Future()
                if not self._download_body_with_embedded_future.done():  # not disposed
                    if exc is not None:
                        self._download_body_with_embedded_future.set_exception(exc)
                    else:
                        self._download_body_with_embedded_future.set_result(
                            self._download_body_task.future.result())
            
            # Cull children, allowing related memory to be freed
            if self._already_downloaded_task is not None:
                # No DownloadResourceTask children exist to cull
                pass
            else:
                final_children = []
                num_downloaded_resources = 0
                for c in self.children:
                    if (c is self._download_body_task or 
                            c is self._parse_links_task):
                        final_children.append(c)
                    elif (isinstance(c, DownloadResourceBodyTask) or
                            isinstance(c, ParseResourceRevisionLinks)):
                        # Forget old copies of these tasks
                        pass
                    else:
                        assert isinstance(task, DownloadResourceTask)
                        num_downloaded_resources += 1
                final_children.append(_DownloadResourcesPlaceholderTask(
                    num_downloaded_resources))
                self.finalize_children(final_children)
            
            if (_DOWNLOAD_DELAY_STYLE == 'after_every_page' and
                    not self._is_embedded and
                    self._download_body_task is not None and
                    self._download_body_task.did_download):
                self.subtitle = 'Waiting before performing next request...'
                assert not is_foreground_thread()
                sleep(DELAY_BETWEEN_DOWNLOADS)
            
            self.finish()
    
    def _ancestor_downloading_resources(self) -> list[Resource]:
        ancestors = []
        cur_task = self  # type: Optional[Task]
        while cur_task is not None:
            if isinstance(cur_task, DownloadResourceTask):
                ancestors.append(cur_task.resource)
            cur_task = cur_task.parent
        return ancestors
    
    def finish(self) -> None:
        if self._pbc is not None:
            self._pbc.close()
            self._pbc = None  # garbage collect
        super().finish()
    
    def __repr__(self) -> str:
        return f'<DownloadResourceTask for {self.resource.url!r}>'


class ParseResourceRevisionLinks(_LeafTask['Tuple[List[Link], List[Resource]]']):
    """
    Parses the list of linked resources from the specified ResourceRevision.
    
    Returns a tuple of a list of Links and a list of Resources.
    
    This task is never complete immediately after initialization.
    """
    icon_name = 'tasktree_parse'
    
    def __init__(self, abstract_resource, resource_revision):
        """
        Arguments:
        * abstract_resource -- a Resource or a RootResource.
        * resource_revision -- a ResourceRevision.
        """
        super().__init__(
            title='Finding links in: ' + _get_abstract_resource_title(abstract_resource))
        self._resource_revision = resource_revision
    
    @bg_affinity
    def __call__(self) -> Tuple[List[Link], List[Resource]]:
        """
        Raises:
        * RevisionBodyMissingError
        """
        self.subtitle = 'Parsing links...'
        links = self._resource_revision.links()  # raises RevisionBodyMissingError
        
        r = self._resource_revision.resource  # cache
        r_url = r.url  # cache
        urls = [urljoin(r_url, link.relative_url) for link in links]
        if len(urls) == 0:
            linked_resources = []  # type: List[Resource]
        else:
            self.subtitle = 'Recording links...'
            def record_links() -> list[Resource]:
                return Resource.bulk_create(r.project, urls, r.url)
            linked_resources = fg_call_and_wait(record_links)
        
        return (links, linked_resources)
    
    @override
    @capture_crashes_to_self
    def dispose(self) -> None:
        super().dispose()
        self._resource_revision = None
    
    def __repr__(self) -> str:
        return (
            f'<ParseResourceRevisionLinks for RR {self._resource_revision._id}>'
            if self._resource_revision is not None
            else f'<ParseResourceRevisionLinks for RR ?>'
        )


_NO_VALUE = object()

# TODO: Annotate: is a _LeafTask[_R]; value is _R; __call__ returns _R
class _PlaceholderTask(_LeafTask):  # abstract
    """
    Leaf task that presents a fixed title and starts as completed.
    
    This task will be complete immediately after initialization iff prefinish=True.
    """
    icon_name = 'tasktree_done'
    
    def __init__(self,
            title: str,
            value: object=_NO_VALUE,
            exception: Exception | None=None,
            prefinish: bool=False) -> None:
        super().__init__(title=title)
        self._value = value
        self._exception = exception
        
        if prefinish:
            self._complete = True  # HACK: pre-finish this part
            self.finish()
    
    @bg_affinity
    def __call__(self):
        if self._value is not _NO_VALUE:
            return self._value
        elif self._exception is not None:
            raise self._exception
        else:
            return None  # default value


class _FlyweightPlaceholderTask(_PlaceholderTask):  # abstract
    """
    Abstract _PlaceholderTask that should only ever have one instance.
    
    This task is always complete immediately after initialization.
    """
    def __init__(self, title: str) -> None:
        super().__init__(title, prefinish=True)
    
    # Ignore any crash reason set on a flyweight task
    @override
    def _set_crash_reason(self, value: CrashReason | None) -> None:
        # NOTE: Swallowing the bad set operation rather than raising another
        #       exception because calling error-handling code is not expected
        #       to be able to handle a followup exception raised in this context.
        pass
    
    # Ignore any parent set on a flyweight task
    @property
    @override
    def parent(self) -> Task | None:
        return None


class _AlreadyDownloadedPlaceholderTask(_FlyweightPlaceholderTask):
    """
    Placeholder task that marks resources that have already been downloaded.
    
    This task is always complete immediately after initialization.
    """
    def __init__(self) -> None:
        super().__init__(title='Already downloaded')
    
    def __repr__(self) -> str:
        return f'_ALREADY_DOWNLOADED_PLACEHOLDER_TASK'

_ALREADY_DOWNLOADED_PLACEHOLDER_TASK = _AlreadyDownloadedPlaceholderTask()


class _DownloadResourcesPlaceholderTask(_PlaceholderTask):
    """
    Placeholder task that replaces 0 or more DownloadResourceTasks,
    allowing them to be garbage-collected.
    
    This task is always complete immediately after initialization.
    """
    def __init__(self, item_count: int) -> None:
        super().__init__(
            title='Downloading %d item%s' % (
                item_count,
                's' if item_count != 1 else ''
            ),
            prefinish=True,
        )
    
    def __repr__(self) -> str:
        return f'<_DownloadResourcesPlaceholderTask {self.title!r}>'


# ------------------------------------------------------------------------------
# DownloadResourceGroupTask

from crystal.model import Resource, ResourceGroup, RootResource


class UpdateResourceGroupMembersTask(_PureContainerTask):
    """
    Given a ResourceGroup, runs a single child task that downloads the group's
    configured "source". This child task can be either a DownloadResourceTask or
    a DownloadResourceGroupTask, depending on the source type.
    
    This task primarily serves to provide a nice title describing why the child
    task is being run.
    
    This task may be complete immediately after initialization.
    """
    icon_name = 'tasktree_update_group'
    scheduling_style = SCHEDULING_STYLE_SEQUENTIAL
    
    def __init__(self, group: ResourceGroup) -> None:
        super().__init__(
            title='Finding members of group: %s' % group.display_name)
        self.group = group
        
        if group.source is None:
            self.finish()
        else:
            download_task = group.source.create_download_task(needs_result=False)  # is_embedded=False
            self.append_child(download_task, already_complete_ok=True)
            if download_task.complete:
                self.task_did_complete(download_task)
        # (NOTE: self.complete might be True now)
    
    @capture_crashes_to_self
    def child_task_subtitle_did_change(self, task: Task) -> None:
        if not task.complete:
            self.subtitle = task.subtitle
    
    @capture_crashes_to_self
    def child_task_did_complete(self, task: Task) -> None:
        task.dispose()
        
        if self.num_children_complete == len(self.children):
            self.finish()
    
    def __repr__(self) -> str:
        # TODO: Consider including just the group pattern,
        #       and surrounding the result with <>.
        return f'UpdateResourceGroupMembersTask({self.group!r})'


class DownloadResourceGroupMembersTask(_PureContainerTask):
    """
    Downloads the members of a specified ResourceGroup.
    If the group's members change during the task execution,
    additional child tasks will be created to download any additional group members.
    
    This task may be complete immediately after initialization.
    """
    # TODO: Always lazy-load children, inlining this constant
    _LAZY_LOAD_CHILDREN = True
    
    icon_name = 'tasktree_download_group_members'
    scheduling_style = SCHEDULING_STYLE_SEQUENTIAL
    all_children_complete_implies_this_task_complete = False
    
    def __init__(self, group: ResourceGroup) -> None:
        super().__init__(
            title='Downloading members of group: %s' % group.display_name)
        self.group = group
        self._deferred_events = []  # type: List[Callable[[], None]]
        self._done_updating_group = False
        
        # Loaded later by _load_children
        self._pbc = None  # type: Optional[ProgressBarCalculator]
        self._children_loaded = False
        
        if self._use_extra_listener_assertions:
            assert self not in self.group.listeners
        self.group.listeners.append(self)  # publicize self (to other threads)
    
    @override
    @capture_crashes_to_self
    def try_get_next_task_unit(self) -> Callable[[], None] | None:
        # Load children, if not already done
        if not self._children_loaded:
            return self._load_children_and_update_completed_status
        
        # Process deferred events, if any
        assert is_foreground_thread()  # to access self._deferred_events
        if len(self._deferred_events) > 0:
            deferred_events = self._deferred_events  # capture
            self._deferred_events = []
            
            assert is_synced_with_scheduler_thread()
            for event in deferred_events:
                event()
        
        return super().try_get_next_task_unit()
    
    @capture_crashes_to_self
    def _load_children_and_update_completed_status(self) -> None:
        @does_not_capture_crashes
        def fg_task() -> None:
            self._load_children()
            self._update_completed_status()
        fg_call_and_wait(fg_task)
    
    @fg_affinity
    def _load_children(self) -> None:
        if self._children_loaded:
            return
        
        group = self.group  # cache
        
        if self._LAZY_LOAD_CHILDREN:
            def createitem(i: int) -> DownloadResourceTask:
                return group.members[i].create_download_task(needs_result=False, is_embedded=False)
            def materializeitem(t: DownloadResourceTask) -> None:
                self.materialize_child(t, already_complete_ok=True)
                if t.complete:
                    self.task_did_complete(t)
            def unmaterializeitem(t: DownloadResourceTask) -> None:
                t.dispose()
            
            notify_task_did_set_children = self.initialize_children(
                AppendableLazySequence[DownloadResourceTask](
                    createitem_func=createitem,
                    materializeitem_func=materializeitem,
                    unmaterializeitem_func=unmaterializeitem,
                    len_func=lambda: len(group.members)
                )
            )
            
            self._pbc = ProgressBarCalculator(
                initial=0,
                total=len(self.children),
            )
            self._children_loaded = True  # after self._pbc = ...; before self._update_subtitle()
            self._update_subtitle()
            
            # NOTE: The children list may be accessed immediately by "task_did_set_children"
            #       listeners and therefore may immediately materialize children
            #       and may immediately call child-complete actions
            notify_task_did_set_children()
            # (NOTE: self.complete might be True now)
        else:
            with gc_disabled():  # don't garbage collect while allocating many objects
                member_download_tasks = [
                    member.create_download_task(needs_result=False, is_embedded=False)
                    for member in group.members
                ]
                
                for t in member_download_tasks:
                    self.append_child(t, already_complete_ok=True)
        
            self._pbc = ProgressBarCalculator(
                initial=0,
                total=len(self.children),
            )
            self._children_loaded = True  # after self._pbc = ...; before self._update_subtitle()
            self._update_subtitle()
        
            # Apply deferred child-complete actions
            for t in [t for t in member_download_tasks if t.complete]:
                self.task_did_complete(t)
            # (NOTE: self.complete might be True now)
        
        assert self._children_loaded  # because set earlier in this function
    
    @capture_crashes_to_self
    def group_did_add_member(self, group: ResourceGroup, member: Resource) -> None:
        if not is_synced_with_scheduler_thread():
            assert is_foreground_thread()  # to access: self._children_loaded, self._deferred_events
            if self._children_loaded:
                # Defer
                self._deferred_events.append(lambda: self.group_did_add_member(group, member))
            else:
                # Ignore
                pass
            return
        
        assert self._children_loaded
        assert self._pbc is not None
        
        if self._LAZY_LOAD_CHILDREN:
            self.notify_did_append_child(None)
        else:
            download_task = member.create_download_task(needs_result=False, is_embedded=False)
            self.append_child(download_task, already_complete_ok=True)
        
        self._pbc.total += 1
        self._update_subtitle()
        
        if not self._LAZY_LOAD_CHILDREN:
            # Apply deferred child-complete actions
            if download_task.complete:
                self.task_did_complete(download_task)
            # (NOTE: self.complete might be True now)
    
    @capture_crashes_to_self
    def group_did_finish_updating(self) -> None:
        self._done_updating_group = True
        self._update_subtitle()
        self._update_completed_status()
    
    @capture_crashes_to_self
    def child_task_did_complete(self, task: Task) -> None:
        task.dispose()
        
        assert isinstance(task, DownloadResourceTask)
        self.group.last_downloaded_member = task.resource
        
        assert self._children_loaded
        assert self._pbc is not None
        self._pbc.update(1)  # self._pbc.n += 1
        self._update_subtitle()
        self._update_completed_status()
    
    def _update_subtitle(self) -> None:
        if not self._children_loaded:
            return
        assert self._pbc is not None
        
        of_phrase = 'of at least' if not self._done_updating_group else 'of'
        (remaining_str, time_per_item_str) = \
            self._pbc.remaining_str_and_time_per_item_str()
        self.subtitle = (
            f'{self.num_children_complete:n} {of_phrase} '
            f'{len(self.children):n} item(s) -- '
            f'{remaining_str} remaining ({time_per_item_str})'
        )
    
    def _update_completed_status(self):
        if (self._children_loaded and
                self.num_children_complete == len(self.children) and 
                self._done_updating_group):
            if not self.complete:
                self.finish()
    
    def finish(self) -> None:
        if self.complete:
            print(f'Warning: finish() called on already-finished task. Ignoring call.', file=sys.stderr)
            traceback.print_stack(file=sys.stderr)
            return
        
        self.group.listeners.remove(self)
        if self._use_extra_listener_assertions:
            assert self not in self.group.listeners
        
        if self._pbc is not None:
            self._pbc.close()
            self._pbc = None  # garbage collect
        
        super().finish()
    
    def __repr__(self) -> str:
        # TODO: Consider including just the group pattern,
        #       and surrounding the result with <>.
        return f'DownloadResourceGroupMembersTask({self.group!r})'


class DownloadResourceGroupTask(_PureContainerTask):
    """
    Downloads a resource group. This involves updating the groups set of
    members and downloading them, in parallel.
    
    This task may be complete immediately after initialization.
    """
    icon_name = 'tasktree_download_group'
    scheduling_style = SCHEDULING_STYLE_ROUND_ROBIN
    
    def __init__(self, group: ResourceGroup) -> None:
        super().__init__(
            title='Downloading group: %s' % group.display_name)
        self._update_members_task = UpdateResourceGroupMembersTask(group)
        self._download_members_task = DownloadResourceGroupMembersTask(group)
        self._started_downloading_members = False
        
        self.append_child(self._update_members_task, already_complete_ok=True)
        self.append_child(self._download_members_task, already_complete_ok=True)
        
        # Prevent system idle sleep while downloading a potentially large group
        Caffeination.add_caffeine()
        
        # Apply deferred child-complete actions
        for t in [t for t in [self._update_members_task, self._download_members_task] if t.complete]:
            self.task_did_complete(t)
        # (NOTE: self.complete might be True now)
    
    @property
    def group(self) -> ResourceGroup:
        return self._update_members_task.group
    
    @capture_crashes_to_self
    def child_task_subtitle_did_change(self, task: Task) -> None:
        if task == self._update_members_task and not self._started_downloading_members:
            self.subtitle = 'Updating group members...'
        elif task == self._download_members_task:
            self.subtitle = task.subtitle
            self._started_downloading_members = True
    
    @capture_crashes_to_self
    def child_task_did_complete(self, task: Task) -> None:
        task.dispose()
        
        if task == self._update_members_task:
            self._download_members_task.group_did_finish_updating()
        
        if self.num_children_complete == len(self.children) and not self.complete:
            self.finish()
    
    @capture_crashes_to_self
    def child_task_did_crash(self, task: Task) -> None:
        if task == self._update_members_task:
            self._download_members_task.group_did_finish_updating()
    
    def finish(self) -> None:
        Caffeination.remove_caffeine()
        
        super().finish()
    
    def __repr__(self) -> str:
        # TODO: Consider including just the group pattern,
        #       and surrounding the result with <>.
        return f'DownloadResourceGroupTask({self.group!r})'


# ------------------------------------------------------------------------------
# RootTask

class RootTask(_PureContainerTask):
    """
    Task whose primary purpose is to serve as the root task.
    External code must create and add its child tasks.
    
    Access to this task's children list must be synchronized with the
    foreground thread.
    """
    icon_name = None
    scheduling_style = SCHEDULING_STYLE_ROUND_ROBIN
    all_children_complete_implies_this_task_complete = False
    all_incomplete_children_crashed_implies_this_task_should_crash = False
    
    def __init__(self) -> None:
        super().__init__(title='ROOT')
        self.subtitle = 'Running'
        self._children_to_add_soon = []  # type: List[Tuple[Task, bool]]
    
    # === Bulkhead ===
    
    @override
    def _get_crash_reason(self) -> CrashReason | None:
        return self._crash_reason
    @override
    @capture_crashes_to_stderr
    def _set_crash_reason(self, reason: CrashReason | None) -> None:
        if reason is None:
            self._crash_reason = None
        else:
            if self._crash_reason is not None:
                # Ignore subsequent crashes until the first one is cleared
                return
            self._crash_reason = reason
            
            # Try to mark all preexisting tasks with "scheduler crashed" subtitle
            try:
                # NOTE: Might raise if RootTask is in a sufficiently invalid state
                self._mark_children_subtitles_as_scheduler_crashed(self)
            except Exception:
                # Fail silently
                pass
            
            # Report crash to Task Tree
            @fg_affinity
            def dismiss_all_scheduled_tasks() -> None:
                # Clear the crash reason
                self.crash_reason = None
                
                # Remove all top-level tasks, including the CrashedTask
                self._next_child_index = 0
                for child in self.children:
                    if not child.complete:
                        child.finish()
                self.clear_completed_children()
            crash_reason_view = CrashedTask(
                'Scheduler crashed',
                reason,
                dismiss_all_scheduled_tasks,
                dismiss_action_title='Dismiss All')
            # NOTE: Might raise if RootTask is in a sufficiently invalid state
            self.append_child(crash_reason_view)
            @does_not_capture_crashes
            def fg_task() -> None:
                # NOTE: Might raise if RootTask is in a sufficiently invalid state
                self.append_deferred_top_level_tasks()
            fg_call_and_wait(fg_task)
    crash_reason = cast(Optional[CrashReason], property(_get_crash_reason, _set_crash_reason))
    
    @classmethod
    def _mark_children_subtitles_as_scheduler_crashed(cls, parent: Task) -> None:
        for child in parent.children:
            if child.complete:
                continue
            child.subtitle = 'Scheduler crashed'
            cls._mark_children_subtitles_as_scheduler_crashed(child)
    
    # === Properties ===
    
    @property  # type: ignore[misc]
    @fg_affinity  # force any access to synchronize with foreground thread
    @override
    def children(self) -> Sequence[Task]:
        # NOTE: Bypass the usual thread synchronization check in super().children,
        #       because here the analogous check is handled by @fg_affinity
        return self._children
    
    @override
    def append_child(self, child: Task, *, already_complete_ok: bool=False) -> None:
        """
        Appends a child to this RootTasks's children, queuing it to be
        scheduled soon.
        
        Can be called from any thread.
        
        Raises:
        * ProjectClosedError -- if this project is closed
        """
        @does_not_capture_crashes
        def fg_task() -> None:
            assert child not in self.children
            assert child not in [c for (c, _) in self._children_to_add_soon]
            
            if self.complete:
                from crystal.model import ProjectClosedError
                raise ProjectClosedError()
            
            # Defer append child until next call to RootTask.try_get_next_task_unit(),
            # which will have a lock on the scheduler thread (and access to Task.children)
            self._children_to_add_soon.append((child, already_complete_ok))
        # NOTE: Must synchronize access to {self.children,
        #       self._children_to_add_soon, self.complete} with foreground thread
        fg_call_and_wait(fg_task)
    
    @fg_affinity
    @scheduler_affinity
    def append_deferred_top_level_tasks(self) -> None:
        if len(self._children_to_add_soon) != 0:
            children_to_add_soon = list(self._children_to_add_soon)  # capture
            self._children_to_add_soon.clear()
            
            # Append deferred children
            for (child, already_complete_ok) in children_to_add_soon:
                super().append_child(child, already_complete_ok=already_complete_ok)
            assert len(self._children_to_add_soon) == 0, \
                'RootTask._children_to_add_soon was modified concurrently unexpectedly'
    
    # === Public Operations ===
    
    @override
    @capture_crashes_to_self
    @fg_affinity
    @scheduler_affinity
    def try_get_next_task_unit(self) -> Callable[[], None] | None:
        if self.complete:
            return None
        
        self.append_deferred_top_level_tasks()
        
        # Only the root task is allowed to have no children normally
        if len(self.children) == 0:
            return None
        
        return super().try_get_next_task_unit()
    
    # === Events ===
    
    @capture_crashes_to_self
    def child_task_did_complete(self, task: Task) -> None:
        run_bulkhead_call(task.dispose)
    
    @capture_crashes_to_self
    def did_schedule_all_children(self) -> None:
        # Remove completed children after each scheduling pass
        self.clear_completed_children()
    
    # === Protected Operations: Finish & Cleanup ===
    
    @override
    def clear_children_if_all_complete(self) -> bool:
        raise NotImplementedError(
            'RootTask does not support clear_children_if_all_complete '
            'because the current implementation of that method in Task '
            'is not prepared to deal with concurrent modification of '
            'RootTask.children.')
    
    @override
    def clear_completed_children(self) -> None:
        @does_not_capture_crashes
        def fg_task() -> None:
            super(RootTask, self).clear_completed_children()
        # NOTE: Must synchronize access to RootTask.children with foreground thread
        fg_call_and_wait(fg_task)
    
    # === Public Operations ===
    
    def interrupt(self) -> None:
        """
        Stop all descendent tasks, asynchronously,
        by interrupting the scheduler thread.
        """
        self.finish()
    
    # === Utility ===
    
    def __repr__(self) -> str:
        return f'<RootTask at 0x{id(self):x}>'


# ------------------------------------------------------------------------------
# Scheduler

# TODO: Eliminate polling by adding logic to sleep appropriately until the
#       root task has more children to process.
_ROOT_TASK_POLL_INTERVAL = .1 # secs


def start_schedule_forever(root_task: RootTask) -> None:
    """
    Asynchronously runs the specified RootTask until it completes,
    or until there is no foreground thread remaining.
    """
    # NOTE: Don't use @crashes_captured_to(root_task) because a RootTask
    #       crashed in this outer context could not have the crash dismissed
    #       such that the RootTask would actually start running again properly
    @capture_crashes_to_stderr
    def bg_daemon_task() -> None:
        setattr(threading.current_thread(), '_cr_is_scheduler_thread', True)
        assert _is_scheduler_thread()
        assert is_synced_with_scheduler_thread()
        
        if _PROFILE_SCHEDULER:
            profiling_context = cProfile.Profile()  # type: AbstractContextManager[Optional[cProfile.Profile]]
        else:
            profiling_context = nullcontext(enter_result=None)
        try:
            with profiling_context as profiler:
                while True:
                    # NOTE: Use enter_if_crashed=True so that the usual
                    #       `sleep(_ROOT_TASK_POLL_INTERVAL)` logic will be
                    #       used to poll until the root task becomes uncrashed
                    with crashes_captured_to(root_task, enter_if_crashed=True):
                        if root_task.crash_reason is None:
                            # NOTE: Some decorators omitted as a (speculative) performance optimization
                            #@does_not_capture_crashes
                            #@fg_affinity
                            #@scheduler_affinity
                            def fg_task() -> tuple[Callable[[], None] | None, bool]:
                                return (
                                    run_bulkhead_call(root_task.try_get_next_task_unit),
                                    root_task.complete
                                )
                            try:
                                (unit, task_complete) = fg_call_and_wait(fg_task)
                            except NoForegroundThreadError:
                                return
                        else:
                            unit = None
                            task_complete = False
                        
                        if unit is None:
                            if task_complete:
                                return
                            else:
                                scheduler_sleep(_ROOT_TASK_POLL_INTERVAL)
                                continue
                        run_bulkhead_call(unit)  # Run unit directly on this scheduler thread
        finally:
            if _PROFILE_SCHEDULER:
                assert profiler is not None
                profiler.dump_stats('scheduler.prof')
    bg_call_later(bg_daemon_task, daemon=True)


def is_synced_with_scheduler_thread() -> bool:
    """
    Returns whether this thread is a scheduler thread,
    or this thread is running a task that a scheduler thread is waiting on.
    """
    if _is_scheduler_thread():
        return True
    if is_foreground_thread():
        if _is_scheduler_thread(fg_waiting_calling_thread()):
            return True
    return False


def _is_scheduler_thread(thread: threading.Thread | None=None) -> bool:
    """
    Returns whether this thread is a scheduler thread,
    responsible for running Tasks in a Project.
    """
    if thread is None:
        thread = threading.current_thread()
    return getattr(thread, '_cr_is_scheduler_thread', False)


# ------------------------------------------------------------------------------
