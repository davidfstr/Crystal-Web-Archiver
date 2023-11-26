from contextlib import contextmanager
import crystal.task
from typing import Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    from crystal.task import DownloadResourceGroupTask


@contextmanager
def delay_between_downloads_minimized() -> Iterator[None]:
    old_value = crystal.task.DELAY_BETWEEN_DOWNLOADS
    # NOTE: Must be long enough so that download tasks stay around long enough
    #       to be observed, but short enough to provide a speed boost
    crystal.task.DELAY_BETWEEN_DOWNLOADS = 0.2
    try:
        yield
    finally:
        crystal.task.DELAY_BETWEEN_DOWNLOADS = old_value


def load_children_of_drg_task(
        drg_task: 'DownloadResourceGroupTask',
        *, scheduler_thread_enabled: bool=True,
        task_added_to_project: bool=True,
        ) -> None:
    if not (scheduler_thread_enabled == False or
            task_added_to_project == False):
        raise ValueError(
            'The specified task must not be scheduled on a '
            'running scheduler thread')
    
    # Precondition
    assert not drg_task._download_members_task._children_loaded
    
    task_unit = drg_task._download_members_task.try_get_next_task_unit()
    assert task_unit is not None
    task_unit()
    
    # Postcondition
    assert drg_task._download_members_task._children_loaded
