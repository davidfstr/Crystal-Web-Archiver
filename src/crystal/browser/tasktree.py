from crystal.ui.tree2 import TreeView, NodeView
import wx

class TaskTree(object):
    """
    View controller for the task tree
    """
    def __init__(self, parent_peer: wx.Window, root_task) -> None:
        self.root = TaskTreeNode(root_task)
        
        self.tree = TreeView(parent_peer, name='cr-task-tree')
        self.tree.root = self.root.tree_node
        
        self.tree.peer.SetInitialSize((750, 200))
    
    @property
    def peer(self) -> wx.TreeCtrl:
        """The wx.TreeCtrl controlled by this class."""
        return self.tree.peer

class TaskTreeNode(object):
    """
    View controller for an individual node of the task tree.
    """
    def __init__(self, task):
        self.task = task
        self.task.listeners.append(self)
        
        self.tree_node = NodeView()
        self.tree_node.title = self.task.title
        self.tree_node.subtitle = self.task.subtitle
        self.tree_node.expandable = not callable(task)
        for child in self.task.children:
            self.task_did_append_child(self.task, child)
    
    def task_subtitle_did_change(self, task):
        self.tree_node.subtitle = self.task.subtitle
    
    def task_did_complete(self, task):
        self.task.listeners.remove(self)
    
    def task_did_append_child(self, task, child):
        child_ttnode = TaskTreeNode(child)
        self.tree_node.append_child(child_ttnode.tree_node)
    
    def task_did_clear_children(self, task):
        self.tree_node.children = []
