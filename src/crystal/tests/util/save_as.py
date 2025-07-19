from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from crystal.model import (
    Project,
)
from crystal.tests.util.runner import pump_wx_events
from crystal.tests.util.wait import wait_for, wait_for_future_ignoring_result
from unittest.mock import patch


@asynccontextmanager
async def wait_for_save_as_to_complete(project: Project) -> AsyncIterator[None]:
    """
    Context that upon entry spies on Project.save_as,
    yields for the caller to start a Save As operation,
    and upon exit waits for the save_as operation to fully complete.
    """
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
        await wait_for_future_ignoring_result(save_as_future)
        
        # Sleep 1 event loop iteration for other observers of the Future
        # to finish their actions, notably MainWindow.on_save_complete
        # HACK: An actual wait would be more reliable than a sleep
        await pump_wx_events()
