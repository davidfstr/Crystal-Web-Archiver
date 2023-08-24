from crystal.browser.icons import TREE_NODE_ICONS
from crystal.task import SCHEDULING_STYLE_SEQUENTIAL, Task
from crystal.ui.tree2 import TreeView, NodeView, NULL_NODE_VIEW
from crystal.util.xthreading import fg_call_later, fg_call_and_wait, is_foreground_thread
from typing import List, Optional
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
    # The following limits are enforced for SCHEDULING_STYLE_SEQUENTIAL tasks only
    _MAX_VISIBLE_COMPLETED_CHILDREN = 5
    _MAX_VISIBLE_CHILDREN = 100
    
    # Optimize per-instance memory use, since there may be very many TaskTreeNode objects
    __slots__ = (
        'task',
        'tree_node',
        '_num_visible_complete_children',
        '_num_visible_children',
    )
    
    """
    View controller for an individual node of the task tree.
    """
    def __init__(self, task: Task) -> None:
        self.task = task
        
        if Task._USE_EXTRA_LISTENER_ASSERTIONS:
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
        
        self._num_visible_complete_children = 0
        self._num_visible_children = 0
        
        # NOTE: Transition to foreground thread here BEFORE making very many
        #       calls to self.task_did_append_child() so that we don't need to
        #       make very many thread transitions in that function
        def fg_task() -> None:
            # Update current progress dialog, if found,
            # in preparation for appending tasks
            # 
            # HACK: Reaches into a progress dialog managed elsewhere,
            #       in MainWindow._on_download_entity()
            progress_dialog_old_message = None  # type: Optional[str]
            if len(self.task.children) >= 100:
                assert is_foreground_thread()
                progress_dialog = wx.FindWindowByName('cr-starting-download')  # type: Optional[wx.Window]
                if progress_dialog is not None:
                    assert isinstance(progress_dialog, wx.ProgressDialog)
                    
                    # Try remove elapsed time from progress dialog,
                    # since we won't be able to keep it up to date soon
                    # 
                    # NOTE: This has no effect on macOS
                    progress_dialog.WindowStyleFlag &= ~wx.PD_ELAPSED_TIME
                    
                    # Change progress dialog message
                    progress_dialog_old_message = progress_dialog.Message
                    progress_dialog.Pulse(f'Adding {len(self.task.children):n} tasks...')
            else:
                progress_dialog = None
            
            # TODO: Optimize to use a bulk version of task_did_append_child()
            for child in self.task.children:
                self.task_did_append_child(self.task, child)
            
            if progress_dialog is not None:
                assert isinstance(progress_dialog, wx.ProgressDialog)
                
                # Restore old message in progress dialog
                assert is_foreground_thread()
                assert progress_dialog_old_message is not None
                progress_dialog.Pulse(progress_dialog_old_message)
        fg_call_and_wait(fg_task)
    
    def task_subtitle_did_change(self, task: Task) -> None:
        new_subtitle = self.task.subtitle  # capture
        def fg_task() -> None:
            self.tree_node.subtitle = new_subtitle
        # NOTE: Use no_profile=True because no obvious further optimizations exist
        fg_call_later(fg_task, no_profile=True)
    
    def task_did_complete(self, task: Task) -> None:
        self.task.listeners.remove(self)
    
    def task_did_append_child(self, task: Task, child: Task) -> None:
        def fg_task() -> None:
            if (task.scheduling_style == SCHEDULING_STYLE_SEQUENTIAL and
                    self._num_visible_children == self._MAX_VISIBLE_CHILDREN):
                # Find last_more_node, or create if missing
                last_child_tree_node = self.tree_node.children[-1]
                if isinstance(last_child_tree_node, _MoreNodeView):
                    last_more_node = last_child_tree_node
                else:
                    last_more_node = _MoreNodeView()
                    self.tree_node.append_child(last_more_node)
                
                # Increase more_count instead of appending new child
                last_more_node.more_count += 1
            else:
                # Append new child
                child_ttnode = TaskTreeNode(child)
                self.tree_node.append_child(child_ttnode.tree_node)
                self._num_visible_children += 1
            
            if child.complete:
                self.task_child_did_complete(task, child)
        fg_call_later(fg_task)
    
    def task_child_did_complete(self, task: Task, child: Task) -> None:
        def fg_task() -> None:
            if (task.scheduling_style == SCHEDULING_STYLE_SEQUENTIAL and
                    self._num_visible_complete_children == self._MAX_VISIBLE_COMPLETED_CHILDREN):
                # Find first_more_node, intermediate_nodes, and last_more_node
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
                
                def intermediate_tasks() -> List[Task]:
                    return self.task.children[
                        first_more_node.more_count :
                        (first_more_node.more_count + len(intermediate_nodes))
                    ]
                
                child_found_in_leading_complete_nodes = False
                for t in intermediate_tasks():
                    if t.complete:
                        if child == t:
                            child_found_in_leading_complete_nodes = True
                            break
                    else:
                        break
                
                if child_found_in_leading_complete_nodes:
                    self._num_visible_complete_children += 1
                    
                    # TODO: Rename: _num_visible_complete_children -> _num_leading_complete_children
                    # TODO: Rename: _MAX_VISIBLE_COMPLETED_CHILDREN -> _MAX_LEADING_COMPLETE_CHILDREN
                    while self._num_visible_complete_children > self._MAX_VISIBLE_COMPLETED_CHILDREN:
                        # Slide first of last_more_node up into last of intermediate_nodes
                        if last_more_node.more_count >= 1:
                            trailing_child_index = first_more_node.more_count + len(intermediate_nodes)
                            trailing_child_task = task.children[trailing_child_index]
                            trailing_child_ttnode = TaskTreeNode(trailing_child_task)
                            trailing_child_node = trailing_child_ttnode.tree_node
                            
                            intermediate_nodes.append(trailing_child_node)
                            last_more_node.more_count -= 1
                            
                            if trailing_child_task.complete:
                                if all((t.complete for t in intermediate_tasks())):
                                    self._num_visible_complete_children += 1
                        
                        # Slide first of intermediate_nodes up into first_more_node
                        intermediate_nodes_0_task = task.children[first_more_node.more_count]
                        assert intermediate_nodes_0_task.complete
                        first_more_node.more_count += 1
                        del intermediate_nodes[0]
                        self._num_visible_complete_children -= 1
                    
                    new_children = []
                    if first_more_node.more_count != 0:
                        new_children.append(first_more_node)
                    new_children.extend(intermediate_nodes)
                    if last_more_node.more_count != 0:
                        new_children.append(last_more_node)
                    
                    self._num_visible_children = len(intermediate_nodes)
                    self.tree_node.children = new_children
            else:
                self._num_visible_complete_children += 1
        fg_call_later(fg_task)
    
    def task_did_clear_children(self,
            task: Task,
            child_indexes: Optional[List[int]]=None
            ) -> None:
        if task != self.task:
            return
        def fg_task() -> None:
            if child_indexes is None:
                self.tree_node.children = []
                self._num_visible_complete_children = 0
                self._num_visible_children = 0
            else:
                if self.task.scheduling_style == SCHEDULING_STYLE_SEQUENTIAL:
                    raise NotImplementedError()
                self.tree_node.children = [
                    c
                    for (i, c) in enumerate(self.tree_node.children)
                    if i not in child_indexes
                ]
                # HACK: The only current caller that passes non-None
                #       child_indexes guarantees that no complete children
                #       will remain
                self._num_visible_complete_children = 0
                self._num_visible_children = len(self.tree_node.children)
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
        self._more_count = more_count
        self.title = f'{self._more_count:n} more'
    more_count = property(_get_more_count, _set_more_count)
