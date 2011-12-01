import time
from xthreading import fg_call_later

class Task(object):
    """
    Encapsulates a long-running process that reports its status occasionally.
    A task may depend on the results of a child task during its execution.
    
    Generally there are two kinds of tasks:
    (1) Leaf tasks
        - Performs a single long-running operation on a background thread
          and completes immediately after this operation is complete.
    (2) Container tasks
        - Uses child tasks to perform all its work.
        - May add additional children tasks over time to perform additional work.
    
    Tasks must generally be manipulated on the foreground thread unless
    documented otherwise.
    """
    
    def __init__(self, title):
        self._title = title
        self._subtitle = 'Queued'
        self._complete = False
    
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
            print '%s -> %s' % (self, value)
            self._subtitle = value
            # TODO: Notify listeners of change to: subtitle
        fg_call_later(fg_task)
    subtitle = property(_get_subtitle, _set_subtitle)
    
    @property
    def complete(self):
        """
        Whether this task is complete.
        """
        return self._complete
    
    def finish(self):
        """
        Marks this task as completed.
        Threadsafe.
        """
        def fg_task():
            self.subtitle = 'Complete'
            self._complete = True
            # TODO: Notify listeners of change to: complete
        fg_call_later(fg_task)

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