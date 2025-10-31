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
    
    def restart(self) -> None:
        """
        Restarts this timer.
        """
        success = self.Start(-1)
        if not success:
            # Since the timer was already running, restarting it shouldn't require
            # any additional resources and therefore shouldn't fail
            raise AssertionError('Unable to restart timer that was already running')
    
    def stop(self) -> None:
        """
        Stops this timer.
        """
        self.Stop()
    
    # === Internal ===
    
    @capture_crashes_to_stderr
    def Notify(self) -> None:  # override
        self._action()


class TimerError(Exception):
    pass
