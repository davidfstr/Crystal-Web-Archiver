from collections.abc import Callable
from crystal.util.bulkheads import capture_crashes_to_stderr
import wx


class Timer(wx.Timer):
    """
    Runs an action every X milliseconds.
    
    Wraps the wx.Timer API to be more usable and reliable.
    """
    
    def __init__(self, action: Callable[[], None], milliseconds: int) -> None:
        """
        Starts a timer that calls the specified action at the specified period.
        
        Raises:
        * TimerError -- if timer could not be started
        """
        super().__init__()
        self._action = action
        if not self.Start(milliseconds):
            raise TimerError('Failed to start timer')
    
    # === Operations ===
    
    def stop(self) -> None:
        """
        Stops this timer.
        
        After this timer is stopped there is no way to restart it.
        """
        self.Stop()
    
    # === Internal ===
    
    @capture_crashes_to_stderr
    def Notify(self) -> None:  # override
        self._action()


class TimerError(Exception):
    pass
