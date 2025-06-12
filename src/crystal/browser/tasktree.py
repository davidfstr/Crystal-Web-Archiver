from collections.abc import Iterator
from contextlib import contextmanager
from crystal.browser.icons import TREE_NODE_ICONS
from crystal.task import (
    CrashedTask, DownloadResourceGroupMembersTask, RootTask,
    SCHEDULING_STYLE_SEQUENTIAL, Task,
)
from crystal.ui.tree2 import NodeView, NULL_NODE_VIEW, TreeView
from crystal.ui.tree import NodeView as NodeView1
from crystal.util.bulkheads import (
    capture_crashes_to_bulkhead_arg as capture_crashes_to_task_arg,
)
from crystal.util.bulkheads import Bulkhead, BulkheadCell, capture_crashes_to
from crystal.util.bulkheads import capture_crashes_to_bulkhead_arg
from crystal.util.bulkheads import capture_crashes_to_stderr, CrashReason
from crystal.util.wx_bind import bind
from crystal.util.wx_treeitem_gettooltip import (
    EVT_TREE_ITEM_GETTOOLTIP, GetTooltipEvent,
)
from crystal.util.xcollections.lazy import (
    AppendableLazySequence, UnmaterializedItemError,
)
from crystal.util.xthreading import (
    fg_call_and_wait, fg_call_later, is_foreground_thread,
)
from crystal.util.xtraceback import format_exception_for_user
from typing import List, Optional, Tuple
import wx

_ID_DISMISS = 101


class TaskTree:
    """
    View controller for the task tree
    """
    def __init__(self, parent_peer: wx.Window, root_task: Task) -> None:
        self.tree = TreeView(parent_peer, name='cr-task-tree')
        self.tree.delegate = self
        
        self.root = TaskTreeNode(root_task)
        self.tree.root = self.root.tree_node
        
        self._right_clicked_node = None  # type: Optional[TaskTreeNode]
        
        self.tree.peer.SetInitialSize((750, 200))
        
        bind(self.peer, wx.EVT_MOTION, self._on_mouse_motion)
        # For tests only
        bind(self.peer, EVT_TREE_ITEM_GETTOOLTIP, self._on_get_tooltip_event)
    
    @property
    def peer(self) -> wx.TreeCtrl:
        """The wx.TreeCtrl controlled by this class."""
        return self.tree.peer
    
    # === Event: Right Click ===
    
    @capture_crashes_to_stderr
    def on_right_click(self, event: wx.MouseEvent, node_view: NodeView) -> None:
        node = TaskTreeNode.for_node_view(node_view)
        self._right_clicked_node = node
        
        # Create popup menu
        menu = wx.Menu()
        bind(menu, wx.EVT_MENU, self._on_popup_menuitem_selected)
        if node is not None and isinstance(node.task, CrashedTask):
            menu.Append(_ID_DISMISS, node.task.dismiss_action_title)
        elif node is not None and self._is_dismissable_top_level_task(node.task):
            menu.Append(_ID_DISMISS, 'Dismiss')
        else:
            menu.Append(_ID_DISMISS, 'Dismiss')
            menu.Enable(_ID_DISMISS, False)
        
        # Show popup menu
        self.peer.PopupMenu(menu)
        menu.Destroy()
    
    def _on_popup_menuitem_selected(self, event: wx.MenuEvent) -> None:
        node = self._right_clicked_node
        assert node is not None
        
        item_id = event.GetId()
        if item_id == _ID_DISMISS:
            if isinstance(node.task, CrashedTask):
                node.task.dismiss()
            elif self._is_dismissable_top_level_task(node.task):
                self._dismiss_top_level_task(node.task)
            else:
                raise AssertionError(f'Do not know how to dismiss: {node.task}')
    
    @classmethod
    def _is_dismissable_top_level_task(cls, task: Task) -> bool:
        return (
            task.crash_reason is not None and
            isinstance(task.parent, RootTask) and
            task.parent.crash_reason is None
        )
    
    @classmethod
    def _dismiss_top_level_task(cls, task: Task) -> None:
        if not cls._is_dismissable_top_level_task(task):
            raise ValueError()
        if not task.complete:
            task.finish()
    
    # === Event: Mouse Motion, Get Tooltip ===
    
    # Update the tooltip whenever hovering the mouse over a tree node icon
    @capture_crashes_to_stderr
    def _on_mouse_motion(self, event: wx.MouseEvent) -> None:
        (tree_item_id, hit_flags) = self.peer.HitTest(event.Position)
        TREEITEM_BODY_FLAGS = (
            wx.TREE_HITTEST_ONITEMICON |
            wx.TREE_HITTEST_ONITEMLABEL
        )
        if (hit_flags & TREEITEM_BODY_FLAGS) != 0:
            new_tooltip = self._tooltip_for_tree_item_id(tree_item_id)
        else:
            new_tooltip = None
        
        if new_tooltip is None:
            self.peer.UnsetToolTip()
        else:
            self.peer.SetToolTip(new_tooltip)
    
    @capture_crashes_to_stderr
    def _on_get_tooltip_event(self, event: wx.Event) -> None:
        event.tooltip_cell[0] = self._tooltip_for_tree_item_id(event.tree_item_id)
    
    def _tooltip_for_tree_item_id(self, tree_item_id: wx.TreeItemId) -> str | None:
        node_view = self.peer.GetItemData(tree_item_id)  # type: NodeView
        node = TaskTreeNode.for_node_view(node_view)
        if node is None:
            return None
        return node.tooltip
    
    # === Dispose ===
    
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
        '_crash_reason_and_tooltip',
    )
    
    def __init__(self, task: Task) -> None:
        self.task = task
        
        # TODO: Export a listener reference to TaskTreeNode later in this function,
        #       after the inner NodeView is created.
        #       It seems risky to export a reference to an incomplete TaskTreeNode.
        if task._use_extra_listener_assertions:
            assert self not in self.task.listeners
        if not task.complete:
            self.task.listeners.append(self)
        
        self.tree_node = NodeView()
        self.tree_node.delegate = self
        if self.task.icon_name is not None:
            self.tree_node.icon_set = (
                (wx.TreeItemIcon_Normal, TREE_NODE_ICONS()[self.task.icon_name]),
            )
        self.tree_node.title = self.task.title
        self.tree_node.subtitle = self._calculate_tree_node_subtitle(
            self.task.subtitle,
            self.task.crash_reason)
        self.tree_node.text_color = self._calculate_tree_node_text_color(self.task.crash_reason)
        self.tree_node.bold = self._calculate_tree_node_bold(self.task.crash_reason)
        self.tree_node.expandable = not callable(task)
        
        self._num_visible_children = 0
        self._visible_children_offset = 0
        self._first_incomplete_child_index = 0
        self._ignore_complete_events = False
        self._crash_reason_and_tooltip = None  # type: Optional[Tuple[BaseException, str]]
        
        # NOTE: Transition to foreground thread here BEFORE making very many
        #       calls to self.task_did_append_child() so that we don't need to
        #       make very many thread transitions in that function
        task_children_count = len(self.task.children)  # capture
        @capture_crashes_to(task)
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
    
    @staticmethod
    def for_node_view(node_view: NodeView) -> 'Optional[TaskTreeNode]':
        node = node_view.delegate
        if node is None:
            return None
        elif isinstance(node, TaskTreeNode):
            return node
        else:
            raise AssertionError(
                f'Expected delegate of NodeView to be TaskTreeNode or None but found: {node}')
    
    # === Properties ===
    
    @classmethod
    def _calculate_tree_node_subtitle(cls,
            task_subtitle: str,
            task_crash_reason: CrashReason | None) -> str:
        return (
            task_subtitle
            if task_crash_reason is None
            else cls._CRASH_SUBTITLE
        )
    
    @classmethod
    def _calculate_tree_node_text_color(cls,
            task_crash_reason: CrashReason | None) -> wx.Colour | None:
        return (
            cls._CRASH_TEXT_COLOR
            if task_crash_reason is not None
            else None
        )
    
    @classmethod
    def _calculate_tree_node_bold(cls,
            task_crash_reason: CrashReason | None) -> bool:
        return task_crash_reason is not None
    
    @property
    def tooltip(self) -> str | None:
        """
        The tooltip to display when the mouse hovers over this node.
        """
        if self.task.crash_reason is None:
            # Clear any cached tooltip
            self._crash_reason_and_tooltip = None
            
            return None
        else:
            # Return cached tooltip, if available
            if self._crash_reason_and_tooltip is not None:
                (last_crash_reason, last_tooltip) = self._crash_reason_and_tooltip
                if last_crash_reason is self.task.crash_reason:
                    return last_tooltip
            
            # Calculate and cache tooltip
            tooltip = format_exception_for_user(self.task.crash_reason).rstrip('\n')
            self._crash_reason_and_tooltip = (self.task.crash_reason, tooltip)
            return tooltip
    
    # === Events ===
    
    @capture_crashes_to_task_arg
    def task_subtitle_did_change(self, task: Task) -> None:
        task_subtitle = self.task.subtitle  # capture
        task_crash_reason = self.task.crash_reason  # capture
        @capture_crashes_to(task)
        def fg_task() -> None:
            self.tree_node.subtitle = self._calculate_tree_node_subtitle(task_subtitle, task_crash_reason)
        # NOTE: Use profile=False because no obvious further optimizations exist
        fg_call_later(fg_task, profile=False)
    
    # NOTE: Cannot use @capture_crashes_to_task_arg because would create infinite loop
    @capture_crashes_to_stderr
    def task_crash_reason_did_change(self, task: Task) -> None:
        task_crash_reason = self.task.crash_reason  # capture
        task_subtitle = self.task.subtitle  # capture
        # NOTE: Cannot use @capture_crashes_to(task) because would create infinite loop
        @capture_crashes_to_stderr
        def fg_task() -> None:
            self.tree_node.subtitle = self._calculate_tree_node_subtitle(task_subtitle, task_crash_reason)
            self.tree_node.text_color = self._calculate_tree_node_text_color(task_crash_reason)
            self.tree_node.bold = self._calculate_tree_node_bold(task_crash_reason)
        # NOTE: Use profile=False because no obvious further optimizations exist
        fg_call_later(fg_task, profile=False)
    
    @capture_crashes_to_task_arg
    def task_did_complete(self, task: Task) -> None:
        self.task.listeners.remove(self)
    
    @capture_crashes_to_task_arg
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
                @capture_crashes_to(task)
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
    
    @capture_crashes_to_stderr
    def task_did_append_child(self, task: Task, child: Task | None) -> None:
        if isinstance(task, RootTask) and isinstance(child, CrashedTask):
            # Specially, allow RootTask to append a CrashedTask when RootTask is crashed
            bulkhead = BulkheadCell()  # type: Bulkhead
        else:
            bulkhead = task
        self._task_did_append_child(bulkhead, task, child)
    
    @capture_crashes_to_bulkhead_arg
    def _task_did_append_child(self, bulkhead: Bulkhead, task: Task, child: Task | None) -> None:
        if (task.scheduling_style == SCHEDULING_STYLE_SEQUENTIAL and
                self._num_visible_children == self._MAX_VISIBLE_CHILDREN):
            @capture_crashes_to(bulkhead)
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
            @capture_crashes_to(bulkhead)
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
    
    @capture_crashes_to_task_arg
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
        @capture_crashes_to(task)
        def fg_task() -> None:
            # Find (first_more_node, intermediate_nodes, last_more_node)
            intermediate_nodes = list(self.tree_node.children)
            if len(intermediate_nodes) == 0:
                # Node is disposed. Abort.
                assert self.tree_node.peer is None
                return
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
    
    @capture_crashes_to_task_arg
    def task_did_clear_children(self,
            task: Task,
            child_indexes: list[int] | None=None
            ) -> None:
        assert task is self.task
        if child_indexes is None:
            self._num_visible_children = 0
            @capture_crashes_to(task)
            def fg_task() -> None:
                self.tree_node.children = []  # type: ignore[misc]
            fg_call_later(fg_task)
        else:
            if self.task.scheduling_style == SCHEDULING_STYLE_SEQUENTIAL:
                raise NotImplementedError()
            self._num_visible_children -= len(child_indexes)
            @capture_crashes_to(task)
            def fg_task() -> None:
                self.tree_node.children = [  # type: ignore[misc]
                    c
                    for (i, c) in enumerate(self.tree_node.children)
                    if i not in child_indexes
                ]
            fg_call_later(fg_task)
    
    # === Dispose ===
    
    def dispose(self) -> None:
        self.task.listeners.remove(self)
        self.tree_node.dispose()
        self.tree_node = NULL_NODE_VIEW
    
    # === Utility ===
    
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
