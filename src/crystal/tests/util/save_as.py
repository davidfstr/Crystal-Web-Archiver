from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from crystal.browser import MainWindow as RealMainWindow
from crystal.model import Project
from crystal.tests.util.controls import (
    file_dialog_returning, select_menuitem_now,
)
from crystal.tests.util.runner import pump_wx_events
from crystal.tests.util.wait import (
    wait_for, wait_for_future, wait_for_future_ignoring_result,
)
from unittest.mock import patch
import wx


_SAVE_AS_TIMEOUT = 32.0  # have observed 30.7s on build-macos


# === Save As (High Level) ===

async def save_as_without_ui(project: Project, new_project_dirpath: str) -> None:
    """
    Performs a Save As operation on a project, waiting for it to complete, without using the UI.
    
    Only use this if there is no MainWindow.
    If you have a MainWindow then instead use save_as_with_ui().
    """
    await wait_for_future(
        project.save_as(new_project_dirpath),
        _SAVE_AS_TIMEOUT,
        message=lambda: f'Timed out waiting {_SAVE_AS_TIMEOUT}s for save_as operation to complete for project {project!r}'
    )


async def save_as_with_ui(rmw: RealMainWindow, new_project_dirpath: str) -> None:
    """
    Performs a Save As operation on a project, waiting for it to complete, using the UI.

    Only use this if there is a MainWindow.
    If there is no MainWindow then instead use save_as_without_ui().
    """
    project = rmw.project
    async with wait_for_save_as_to_complete(project):
        start_save_as_with_ui(rmw, new_project_dirpath)


# === Save As (Low Level) ===

def start_save_as_with_ui(rmw: RealMainWindow, new_project_dirpath: str) -> None:
    """
    Starts a Save As operation on a project using the UI,
    but does NOT wait for it to complete.
    
    See also: save_as_with_ui()
    """
    with file_dialog_returning(new_project_dirpath):
        select_menuitem_now(
            menuitem=rmw._frame.MenuBar.FindItemById(wx.ID_SAVEAS))


@asynccontextmanager
async def wait_for_save_as_to_complete(project: Project) -> AsyncIterator[None]:
    """
    Context that upon entry spies on Project.save_as,
    yields for the caller to start a Save As operation,
    and upon exit waits for the save_as operation to fully complete.
    
    See also: save_as_with_ui()
    """
    timeout = _SAVE_AS_TIMEOUT
    
    save_as_called = False
    save_as_future = None
    
    original_save_as = project.save_as  # capture
    def save_as_wrapper(*args, **kwargs):
        """Wrapper for Project.save_as that captures the returned Future."""
        nonlocal save_as_future, save_as_called
        future = original_save_as(*args, **kwargs)
        save_as_called = True
        save_as_future = future
        return future
    
    with patch.object(project, 'save_as', save_as_wrapper):
        # Tell caller to start a Save As operation
        yield
        
        # Wait for Save As operation to fully complete
        await wait_for(lambda: save_as_called or None)
        assert save_as_future is not None
        await wait_for_future_ignoring_result(
            save_as_future,
            timeout,
            message=lambda: f'Timed out waiting {timeout}s for save_as operation to complete for project {project!r}',
            stacklevel_extra=1)
        
        # Sleep 1 event loop iteration for other observers of the Future
        # to finish their actions, notably MainWindow.on_save_complete
        # HACK: An actual wait would be more reliable than a sleep
        await pump_wx_events()
