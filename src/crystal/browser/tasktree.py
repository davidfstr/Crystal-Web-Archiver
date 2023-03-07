from crystal.browser.icons import TREE_NODE_ICONS
from crystal.task import Task
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
        for child in self.task.children:
            self.task_did_append_child(self.task, child)
    
    def task_subtitle_did_change(self, task: Task) -> None:
        def fg_task():
            self.tree_node.subtitle = self.task.subtitle
        fg_call_later(fg_task)
    
    def task_did_complete(self, task: Task) -> None:
        self.task.listeners.remove(self)
    
    def task_did_append_child(self, task: Task, child: Task) -> None:
        def fg_task():
            child_ttnode = TaskTreeNode(child)
            self.tree_node.append_child(child_ttnode.tree_node)
        fg_call_later(fg_task)
    
    def task_did_clear_children(self, task: Task) -> None:
        def fg_task():
            self.tree_node.children = []
        fg_call_later(fg_task)
