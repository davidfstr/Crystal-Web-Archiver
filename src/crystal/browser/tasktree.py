from crystal.browser.icons import TREE_NODE_ICONS
from crystal.task import SCHEDULING_STYLE_SEQUENTIAL, Task
from crystal.ui.tree2 import TreeView, NodeView
from crystal.util.xthreading import fg_call_later
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


class TaskTreeNode:
    # The following limits are enforced for SCHEDULING_STYLE_SEQUENTIAL tasks only
    _MAX_VISIBLE_COMPLETED_CHILDREN = 5
    _MAX_VISIBLE_CHILDREN = 100
    
    """
    View controller for an individual node of the task tree.
    """
    def __init__(self, task: Task) -> None:
        self.task = task
        self.task.listeners.append(self)
        
        self.tree_node = NodeView()
        if self.task.icon_name is not None:
            self.tree_node.icon_set = (
                (wx.TreeItemIcon_Normal, TREE_NODE_ICONS()[self.task.icon_name]),
            )
        self.tree_node.title = self.task.title
        self.tree_node.subtitle = self.task.subtitle
        self.tree_node.expandable = not callable(task)
        
        # TODO: Optimize for when task starts with a large number of children
        self._num_visible_complete_children = 0
        self._num_visible_children = 0
        for child in self.task.children:
            self.task_did_append_child(self.task, child)
    
    def task_subtitle_did_change(self, task: Task) -> None:
        def fg_task() -> None:
            self.tree_node.subtitle = self.task.subtitle
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
    
    def task_did_clear_children(self, task: Task) -> None:
        def fg_task() -> None:
            self.tree_node.children = []
            self._num_visible_complete_children = 0
            self._num_visible_children = 0
        fg_call_later(fg_task)


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
        self.title = '%d more' % self._more_count
    more_count = property(_get_more_count, _set_more_count)
