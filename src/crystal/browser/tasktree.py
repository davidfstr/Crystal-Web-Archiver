from contextlib import contextmanager
from crystal.browser.icons import TREE_NODE_ICONS
from crystal.task import (
    captures_crashes_to,
    captures_crashes_to_stderr, captures_crashes_to_task_arg,
    CrashReason,
    DownloadResourceGroupMembersTask, SCHEDULING_STYLE_SEQUENTIAL, Task,
)
from crystal.ui.tree import NodeView as NodeView1
from crystal.ui.tree2 import TreeView, NodeView, NULL_NODE_VIEW
from crystal.util.xcollections.lazy import AppendableLazySequence, UnmaterializedItemError
from crystal.util.xthreading import fg_call_later, fg_call_and_wait, is_foreground_thread
from typing import Iterator, List, Optional, Tuple
import wx


class TaskTree:
    """
    View controller for the task tree
    """
    def __init__(self, parent_peer: wx.Window, root_task: Task) -> None:
        self.root = TaskTreeNode(root_task)
        
        self.tree = TreeView(parent_peer, name='cr-task-tree')
        self.tree.root = self.root.tree_node
        
        self.tree.peer.SetInitialSize((750, 200))
    
    @property
    def peer(self) -> wx.TreeCtrl:
        """The wx.TreeCtrl controlled by this class."""
        return self.tree.peer
    
    def dispose(self) -> None:
        self.root.dispose()
        self.tree.dispose()


class TaskTreeNode:
    """
    View controller for an individual node of the task tree.
    """
    # The following limits are enforced for SCHEDULING_STYLE_SEQUENTIAL tasks only
    _MAX_LEADING_COMPLETE_CHILDREN = 5
    _MAX_VISIBLE_CHILDREN = 100
    
    _CRASH_TEXT_COLOR = wx.Colour(255, 0, 0)  # red
    _CRASH_SUBTITLE = 'Something went wrong'
    
    # Optimize per-instance memory use, since there may be very many TaskTreeNode objects
    __slots__ = (
        'task',
        'tree_node',
        '_num_visible_children',
        '_visible_children_offset',
        '_first_incomplete_child_index',
        '_ignore_complete_events',
    )
    
    def __init__(self, task: Task) -> None:
        self.task = task
        
        if task._use_extra_listener_assertions:
            assert self not in self.task.listeners
        if not task.complete:
            self.task.listeners.append(self)
        
        self.tree_node = NodeView()
        if self.task.icon_name is not None:
            self.tree_node.icon_set = (
                (wx.TreeItemIcon_Normal, TREE_NODE_ICONS()[self.task.icon_name]),
            )
        self.tree_node.title = self.task.title
        self.tree_node.subtitle = self.task.subtitle
        self.tree_node.expandable = not callable(task)
        
        self._num_visible_children = 0
        self._visible_children_offset = 0
        self._first_incomplete_child_index = 0
        self._ignore_complete_events = False
        
        # NOTE: Transition to foreground thread here BEFORE making very many
        #       calls to self.task_did_append_child() so that we don't need to
        #       make very many thread transitions in that function
        task_children_count = len(self.task.children)  # capture
        @captures_crashes_to(task)
        def fg_task() -> None:
            # Update current progress dialog, if found,
            # in preparation for appending tasks
            # 
            # HACK: Reaches into a progress dialog managed elsewhere,
            #       in MainWindow._on_download_entity()
            progress_dialog_old_message = None  # type: Optional[str]
            if DownloadResourceGroupMembersTask._LAZY_LOAD_CHILDREN:
                progress_dialog = None  # type: Optional[wx.Window]
            else:
                if task_children_count >= 100:
                    assert is_foreground_thread()
                    progress_dialog = wx.FindWindowByName('cr-starting-download')
                    if progress_dialog is not None:
                        assert isinstance(progress_dialog, wx.ProgressDialog)
                        
                        # Try remove elapsed time from progress dialog,
                        # since we won't be able to keep it up to date soon
                        # 
                        # NOTE: This has no effect on macOS
                        progress_dialog.WindowStyleFlag &= ~wx.PD_ELAPSED_TIME
                        
                        # Change progress dialog message
                        progress_dialog_old_message = progress_dialog.Message
                        progress_dialog.Pulse(f'Adding {task_children_count:n} tasks...')
                else:
                    progress_dialog = None
            
            self.task_did_set_children(self.task, task_children_count)
            
            if progress_dialog is not None:
                assert isinstance(progress_dialog, wx.ProgressDialog)
                
                # Restore old message in progress dialog
                assert is_foreground_thread()
                assert progress_dialog_old_message is not None
                progress_dialog.Pulse(progress_dialog_old_message)
        fg_call_and_wait(fg_task)
    
    @captures_crashes_to_task_arg
    def task_subtitle_did_change(self, task: Task) -> None:
        task_subtitle = self.task.subtitle  # capture
        task_crash_reason = self.task.crash_reason  # capture
        @captures_crashes_to(task)
        def fg_task() -> None:
            self.tree_node.subtitle = self._calculate_tree_node_subtitle(task_subtitle, task_crash_reason)
        # NOTE: Use profile=False because no obvious further optimizations exist
        fg_call_later(fg_task, profile=False)
    
    # NOTE: Cannot use @captures_crashes_to_task_arg because would create infinite loop
    @captures_crashes_to_stderr
    def task_crash_reason_did_change(self, task: Task) -> None:
        task_crash_reason = self.task.crash_reason  # capture
        task_subtitle = self.task.subtitle  # capture
        # NOTE: Cannot use @captures_crashes_to(task) because would create infinite loop
        @captures_crashes_to_stderr
        def fg_task() -> None:
            self.tree_node.subtitle = self._calculate_tree_node_subtitle(task_subtitle, task_crash_reason)
            if task_crash_reason is not None:
                self.tree_node.text_color = self._CRASH_TEXT_COLOR
                self.tree_node.bold = True
                # (TODO: Set tooltip when hovering over tree node text to task_crash_reason)
            else:
                self.tree_node.text_color = None
                self.tree_node.bold = False
                # (TODO: Clear tooltip when hovering over tree node text)
        # NOTE: Use profile=False because no obvious further optimizations exist
        fg_call_later(fg_task, profile=False)
    
    @classmethod
    def _calculate_tree_node_subtitle(cls,
            task_subtitle: str,
            task_crash_reason: Optional[CrashReason]) -> str:
        return (
            task_subtitle
            if task_crash_reason is None
            else cls._CRASH_SUBTITLE
        )
    
    @captures_crashes_to_task_arg
    def task_did_complete(self, task: Task) -> None:
        self.task.listeners.remove(self)
    
    @captures_crashes_to_task_arg
    def task_did_set_children(self, task: Task, child_count: int) -> None:
        if task.scheduling_style == SCHEDULING_STYLE_SEQUENTIAL:
            # Create tree node for each visible task
            visible_child_count = min(child_count, self._MAX_VISIBLE_CHILDREN)
            # NOTE: If `task.children` is an AppendableLazySequence then accessing it can
            #       (1) materialize a child that is already complete, and
            #       (2) call self.task_child_did_complete() on that child
            #           BEFORE the inside of the loop can call
            #           self.task_did_append_child() on this child
            #       So suppress the handling of any such
            #       self.task_child_did_complete() events temporarily.
            with self._complete_events_ignored():
                children_to_append = task.children[:visible_child_count]
                for child in children_to_append:
                    # NOTE: Will also call task_child_did_complete() if the
                    #       child is initially complete, but the event handling
                    #       will be suppressed by the enclosing block
                    self.task_did_append_child(task, child)
            assert self._num_visible_children == visible_child_count
            
            # Create more node as a placeholder for the remaining tasks, if needed
            if visible_child_count < child_count:
                @captures_crashes_to(task)
                def fg_task() -> None:
                    self.tree_node.append_child(_MoreNodeView(child_count - visible_child_count))
                fg_call_later(fg_task)
            
            # Apply deferred child-complete actions
            for child in children_to_append:
                if child.complete:
                    self.task_child_did_complete(task, child)
        else:
            # Greedily create tree node for each task
            for child in task.children:
                # NOTE: Will also call task_child_did_complete() if the
                #       child is initially complete
                self.task_did_append_child(task, child)
    
    @captures_crashes_to_task_arg
    def task_did_append_child(self, task: Task, child: Optional[Task]) -> None:
        if (task.scheduling_style == SCHEDULING_STYLE_SEQUENTIAL and
                self._num_visible_children == self._MAX_VISIBLE_CHILDREN):
            @captures_crashes_to(task)
            def fg_task() -> None:
                # Find last_more_node, or create if missing
                last_child_tree_node = self.tree_node.children[-1]
                if isinstance(last_child_tree_node, _MoreNodeView):
                    last_more_node = last_child_tree_node
                else:
                    last_more_node = _MoreNodeView()
                    self.tree_node.append_child(last_more_node)
                
                # Increase more_count instead of appending new child
                last_more_node.more_count += 1
            fg_call_later(fg_task)
        else:
            # Lookup (and materialize) child if necessary
            if child is None:
                child = task.children[-1]  # lookup child
            
            # Append tree node for new task child
            child_ttnode = TaskTreeNode(child)
            self._num_visible_children += 1
            @captures_crashes_to(task)
            def fg_task() -> None:
                self.tree_node.append_child(child_ttnode.tree_node)
            fg_call_later(fg_task)
        
        if child is not None and child.complete:
            self.task_child_did_complete(task, child)
    
    @contextmanager
    def _complete_events_ignored(self) -> Iterator[None]:
        assert self._ignore_complete_events == False
        self._ignore_complete_events = True
        try:
            yield
        finally:
            self._ignore_complete_events = False
    
    @captures_crashes_to_task_arg
    def task_child_did_complete(self, task: Task, child: Task) -> None:
        assert task is self.task
        if task.scheduling_style != SCHEDULING_STYLE_SEQUENTIAL:
            return
        
        if self._ignore_complete_events:
            return
        
        # Locate new index of first incomplete child
        # 
        # NOTE: If `task.children` is an AppendableLazySequence then accessing it can
        #       (1) materialize a child that is already complete, and
        #       (2) call self.task_child_did_complete() on that child
        #       So suppress the handling of any such
        #       self.task_child_did_complete() events temporarily.
        with self._complete_events_ignored():
            while self._first_incomplete_child_index < len(task.children):
                try:
                    child_is_complete = task.children[self._first_incomplete_child_index].complete
                except UnmaterializedItemError:
                    child_is_complete = True
                if not child_is_complete:
                    break
                self._first_incomplete_child_index += 1
        
        # Update desired offset of visible children
        old_visible_children_offset = self._visible_children_offset  # capture, cache
        new_visible_children_offset = max(
            old_visible_children_offset,
            self._first_incomplete_child_index - self._MAX_LEADING_COMPLETE_CHILDREN
        )
        if new_visible_children_offset == old_visible_children_offset:
            return
        self._visible_children_offset = new_visible_children_offset
        
        # Update visible children count
        self._num_visible_children = min(
            len(task.children) - new_visible_children_offset,
            self._MAX_VISIBLE_CHILDREN
        )
        
        # Create new trailing task tree nodes
        trailing_intermediate_nodes_to_add = [
            TaskTreeNode(task.children[trailing_child_index]).tree_node
            for trailing_child_index in range(
                max(
                    old_visible_children_offset + self._MAX_VISIBLE_CHILDREN,
                    new_visible_children_offset
                ),
                min(
                    new_visible_children_offset + self._MAX_VISIBLE_CHILDREN,
                    len(task.children)
                )
            )
        ]
        
        # Prepare: Unmaterialize tasks for old leading task tree nodes
        if isinstance(task.children, AppendableLazySequence):
            lazy_task_children = task.children  # capture
            leading_intermediate_task_indexes_to_remove = [
                leading_child_index
                for leading_child_index in range(
                    old_visible_children_offset,
                    new_visible_children_offset
                )
            ]
            def unmaterialize_tasks() -> None:
                for i in leading_intermediate_task_indexes_to_remove:
                    lazy_task_children.unmaterialize(i)
        else:
            def unmaterialize_tasks() -> None:
                pass
        
        # Update visible children
        task_children_count = len(task.children)  # capture
        @captures_crashes_to(task)
        def fg_task() -> None:
            # Find (first_more_node, intermediate_nodes, last_more_node)
            intermediate_nodes = list(self.tree_node.children)
            if isinstance(intermediate_nodes[0], _MoreNodeView):
                first_more_node = intermediate_nodes[0]
                del intermediate_nodes[0]
            else:
                first_more_node = _MoreNodeView()
            if isinstance(intermediate_nodes[-1], _MoreNodeView):
                last_more_node = intermediate_nodes[-1]
                del intermediate_nodes[-1]
            else:
                last_more_node = _MoreNodeView()
            
            # Revise (first_more_node, intermediate_nodes, last_more_node)
            first_more_node.more_count = new_visible_children_offset
            del intermediate_nodes[:(new_visible_children_offset - old_visible_children_offset)]
            intermediate_nodes.extend(trailing_intermediate_nodes_to_add)
            # NOTE: Internally asserts value is >= 0
            last_more_node.more_count = (
                task_children_count - len(intermediate_nodes) - first_more_node.more_count
            )
            
            # Commit changes to the children list
            new_children = []  # type: List[NodeView1]
            if first_more_node.more_count != 0:
                new_children.append(first_more_node)
            new_children.extend(intermediate_nodes)
            if last_more_node.more_count != 0:
                new_children.append(last_more_node)
            self.tree_node.children = new_children  # type: ignore[misc]
            
            # Perform: Unmaterialize tasks for old leading task tree nodes
            unmaterialize_tasks()
        fg_call_later(fg_task)
    
    @captures_crashes_to_task_arg
    def task_did_clear_children(self,
            task: Task,
            child_indexes: Optional[List[int]]=None
            ) -> None:
        assert task is self.task
        if child_indexes is None:
            self._num_visible_children = 0
            @captures_crashes_to(task)
            def fg_task() -> None:
                self.tree_node.children = []  # type: ignore[misc]
            fg_call_later(fg_task)
        else:
            if self.task.scheduling_style == SCHEDULING_STYLE_SEQUENTIAL:
                raise NotImplementedError()
            self._num_visible_children -= len(child_indexes)
            @captures_crashes_to(task)
            def fg_task() -> None:
                self.tree_node.children = [  # type: ignore[misc]
                    c
                    for (i, c) in enumerate(self.tree_node.children)
                    if i not in child_indexes
                ]
            fg_call_later(fg_task)
    
    def dispose(self) -> None:
        self.task.listeners.remove(self)
        self.tree_node.dispose()
        self.tree_node = NULL_NODE_VIEW
    
    def __repr__(self) -> str:
        return f'TaskTreeNode({self.task!r})'


class _MoreNodeView(NodeView):
    def __init__(self, more_count: int=0) -> None:
        self._more_count = -1
        
        super().__init__()
        self.icon_set = (
            (wx.TreeItemIcon_Normal, TREE_NODE_ICONS()['entitytree_more']),
        )
        self.more_count = more_count  # sets self.title too
    
    def _get_more_count(self) -> int:
        return self._more_count
    def _set_more_count(self, more_count: int) -> None:
        if more_count == self._more_count:
            return
        if more_count < 0:
            raise ValueError(f'Cannot set negative more_count: {more_count}')
        self._more_count = more_count
        self.title = f'{self._more_count:n} more'
    more_count = property(_get_more_count, _set_more_count)
