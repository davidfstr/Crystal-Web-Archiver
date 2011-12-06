import time
from xthreading import fg_call_later

SCHEDULING_STYLE_NONE = 0
SCHEDULING_STYLE_SEQUENTIAL = 1
SCHEDULING_STYLE_ROUND_ROBIN = 2

class Task(object):
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
            - Should set the 'scheduling_style' property in its constructor.
            - Should add the initial set of children in its constructor.
        - May add additional children tasks over time to perform additional work.
            - Generally this is done upon the completion of a child task.
        - Automatically listen to child tasks. A container task may override:
            o child_task_subtitle_did_change
            o child_task_did_complete
    
    Tasks must generally be manipulated on the foreground thread unless
    documented otherwise.
    """
    
    def __init__(self, title):
        self._title = title
        self._subtitle = 'Queued'
        self.scheduling_style = SCHEDULING_STYLE_NONE
        self._children = []
        self._num_children_complete = 0
        self._complete = False
        self.listeners = []
        
        self._did_yield_self = False            # used by leaf tasks
        # TODO: Consider merging the following two fields
        self._first_incomplete_child_index = 0  # used by SCHEDULING_STYLE_SEQUENTIAL
        self._next_child_index = 0              # used by SCHEDULING_STYLE_ROUND_ROBIN
    
    # === Properties ===
    
    @property
    def title(self):
        """
        The title of this task. Fixed upon initialization.
        """
        return self._title
    
    def _get_subtitle(self):
        """
        The subtitle for this task.
        The setter (but not the getter) is threadsafe.
        """
        return self._subtitle
    def _set_subtitle(self, value):
        def fg_task():
            #print '%s -> %s' % (self, value)
            self._subtitle = value
            
            for lis in self.listeners:
                if hasattr(lis, 'task_subtitle_did_change'):
                    lis.task_subtitle_did_change(self)
        fg_call_later(fg_task)
    subtitle = property(_get_subtitle, _set_subtitle)
    
    @property
    def children(self):
        return self._children
    
    @property
    def num_children_complete(self):
        return self._num_children_complete
    
    @property
    def complete(self):
        """
        Whether this task is complete.
        """
        return self._complete
    
    # === Protected Operations ===
    
    def append_child(self, child):
        self._children.append(child)
        child.listeners.append(self)
        
        for lis in self.listeners:
            if hasattr(lis, 'task_did_append_child'):
                lis.task_did_append_child(self, child)
    
    def finish(self):
        """
        Marks this task as completed.
        Threadsafe.
        """
        def fg_task():
            self._complete = True
            self.subtitle = 'Complete'
            
            for lis in self.listeners:
                if hasattr(lis, 'task_did_complete'):
                    lis.task_did_complete(self)
        fg_call_later(fg_task)
    
    # === Public Operations ===
    
    def try_get_next_task_unit(self):
        """
        Returns a callable ("task unit") that completes a unit of work for
        this task, or None if no more units can be provided until at least
        one of the previously returned units completes.
        
        Task units may be run on any thread.
        
        If this is a leaf task, its own __call__() method will be returned
        as the solitary task unit. As a task unit, it must be designed to
        run on any thread.
        """
        
        if self.complete:
            return None
        
        if callable(self):
            if not self._did_yield_self:
                self._did_yield_self = True
                return self
            else:
                return None
        else:
            if len(self.children) == 0:
                raise ValueError('Container task has no children tasks.')
            
            if self.scheduling_style == SCHEDULING_STYLE_NONE:
                raise ValueError('Container task has not specified a scheduling style.')
            elif self.scheduling_style == SCHEDULING_STYLE_SEQUENTIAL:
                while self._first_incomplete_child_index < len(self.children):
                    if self.children[self._first_incomplete_child_index].complete:
                        self._first_incomplete_child_index += 1
                    else:
                        cur_child_index = self._first_incomplete_child_index
                        while cur_child_index < len(self.children):
                            unit = self.children[cur_child_index].try_get_next_task_unit()
                            if unit is not None:
                                return unit
                            cur_child_index += 1
                        return None
                return None
            elif self.scheduling_style == SCHEDULING_STYLE_ROUND_ROBIN:
                cur_child_index = self._next_child_index
                while True:
                    unit = self.children[cur_child_index].try_get_next_task_unit()
                    if unit is not None:
                        self._next_child_index = (cur_child_index + 1) % len(self.children)
                        return unit
                    cur_child_index = (cur_child_index + 1) % len(self.children)
                    if cur_child_index == self._next_child_index:
                        # Wrapped around and back to where we started without finding anything to do
                        return None
            else:
                raise ValueError('Container task has an unknown scheduling style (%s).' % self.scheduling_style)
    
    # === Internal Events ===
    
    def task_subtitle_did_change(self, task):
        if hasattr(self, 'child_task_subtitle_did_change'):
            self.child_task_subtitle_did_change(task)
    
    def task_did_complete(self, task):
        self._num_children_complete += 1
        
        if hasattr(self, 'child_task_did_complete'):
            self.child_task_did_complete(task)
        
        task.listeners.remove(self)

class DownloadResourceBodyTask(Task):
    """
    Downloads a single resource's body.
    This is the most basic task, located at the leaves of the task tree.
    """
    
    def __init__(self):
        Task.__init__(self, title='Downloading body: URL - TITLE')
    
    def __call__(self):
        self.subtitle = 'Waiting for response...'
        time.sleep(.2)
        self.subtitle = 'Receiving response...'
        time.sleep(.8)
        self.finish()

class DownloadResourceTask(Task):
    """
    Downloads a resource and all of its embedded resources recursively.
    """
    def __init__(self, num_child_resources=2):
        Task.__init__(self, title='Downloading: URL - TITLE')
        self._num_child_resources = num_child_resources
        self._download_body_task = DownloadResourceBodyTask()
        
        self.scheduling_style = SCHEDULING_STYLE_SEQUENTIAL
        self.append_child(self._download_body_task)
    
    def child_task_subtitle_did_change(self, task):
        if task is self._download_body_task:
            if not task.complete:
                self.subtitle = task.subtitle
    
    def child_task_did_complete(self, task):
        if task is self._download_body_task:
            # Create subtasks to download all embedded resources
            for i in xrange(self._num_child_resources):
                self.append_child(DownloadResourceTask(0))
        
        self.subtitle = '%s of %s item(s)' % (self.num_children_complete, len(self.children))
        
        if self.num_children_complete == len(self.children):
            self.finish()

class UpdateResourceGroupMembersTask(Task):
    """
    Given a ResourceGroup, runs a single child task that downloads the group's
    configured "source". This child task can be either a DownloadResourceTask or
    a DownloadResourceGroupTask, depending on the source type.
    
    This task primarily serves to provide a nice title describing why the child
    task is being run.
    """
    def __init__(self, num_child_resources_of_source=0):
        Task.__init__(self, title='Finding members of group: TITLE')
        
        self.scheduling_style = SCHEDULING_STYLE_SEQUENTIAL
        self.append_child(DownloadResourceTask(num_child_resources_of_source))
    
    def child_task_subtitle_did_change(self, task):
        if not task.complete:
            self.subtitle = task.subtitle
    
    def child_task_did_complete(self, task):
        if self.num_children_complete == len(self.children):
            self.finish()

class DownloadResourceGroupMembersTask(Task):
    """
    Downloads the members of a specified ResourceGroup.
    If the group's members change during the task execution,
    additional child tasks will be created to download any additional group members.
    """
    def __init__(self, num_initial_members=2, group_already_up_to_date=False):
        Task.__init__(self, title='Downloading members of group: TITLE')
        self._done_updating_group = group_already_up_to_date
        
        self.scheduling_style = SCHEDULING_STYLE_SEQUENTIAL
        for i in xrange(num_initial_members):
            self.append_child(DownloadResourceTask())
        self._update_subtitle()
    
    def group_did_add_member(self, member):
        self.append_child(DownloadResourceTask())
        self._update_subtitle()
    
    def group_did_finish_updating(self):
        self._done_updating_group = True
        self._update_completed_status()
    
    def child_task_did_complete(self, task):
        self._update_subtitle()
        self._update_completed_status()
    
    def _update_subtitle(self):
        of_phrase = 'of at least' if not self._done_updating_group else 'of'
        self.subtitle = '%s %s %s item(s)' % (self.num_children_complete, of_phrase, len(self.children))
    
    def _update_completed_status(self):
        if self.num_children_complete == len(self.children) and self._done_updating_group:
            self.finish()

class DownloadResourceGroupTask(Task):
    """
    Downloads a resource group. This involves updating the groups set of
    members and downloading them, in parallel.
    """
    def __init__(self):
        Task.__init__(self, title='Downloading group: TITLE')
        self._update_members_task = UpdateResourceGroupMembersTask(num_child_resources_of_source=1)
        self._download_members_task = DownloadResourceGroupMembersTask()
        
        self.scheduling_style = SCHEDULING_STYLE_ROUND_ROBIN
        self.append_child(self._update_members_task)
        self.append_child(self._download_members_task)
    
    def child_task_subtitle_did_change(self, task):
        if task == self._download_members_task:
            self.subtitle = task.subtitle
    
    def child_task_did_complete(self, task):
        if task == self._update_members_task:
            self._download_members_task.group_did_finish_updating()
        
        if self.num_children_complete == len(self.children):
            self.finish()

class RootTask(Task):
    """
    Task whose primary purpose is to serve as the root task.
    External code must create and add its child tasks.
    
    This task never completes.
    """
    def __init__(self):
        Task.__init__(self, title='ROOT')
        self.subtitle = 'Running'
        
        self.scheduling_style = SCHEDULING_STYLE_ROUND_ROBIN

# ----------------------------------------------------------------------------------------

def schedule_forever(task):
    """
    Runs the specified task synchronously until it completes execution.
    
    This is intended for testing, until a full scheduler class is written.
    """
    
    while True:
        unit = task.try_get_next_task_unit()
        if unit is None:
            if task.complete:
                break
            else:
                raise ValueError('Incomplete root task is refusing to yield units.')
        unit()
