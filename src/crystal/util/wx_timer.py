from collections.abc import Callable
from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.wx_bind import bind
from crystal.util.xthreading import fg_affinity
import wx


class Timer(wx.EvtHandler):
    """
    Runs an action on the foreground thread every X milliseconds.
    
    Wraps the wx.Timer API to be more usable and reliable.
    """
    
    @fg_affinity  # because wx.Timer must be manipulated on foreground thread
    def __init__(self, 
            action: Callable[[], None],
            period: int,
            *, one_shot: bool = False,
            ) -> None:
        """
        Starts a timer that calls the specified action repeatedly
        at the specified period (in milliseconds).
        
        Raises:
        * TimerError -- if timer could not be started
        """
        super().__init__()
        self._timer = wx.Timer(self)
        self._action = action
        
        bind(self, wx.EVT_TIMER, self._notify)
        
        if one_shot:
            success = self._timer.StartOnce(period)
        else:
            success = self._timer.Start(period)
        if not success:
            raise TimerError('Failed to start timer')
    
    # === Operations ===
    
    @fg_affinity  # because wx.Timer must be manipulated on foreground thread
    def restart(self) -> None:
        """
        Restarts this timer.
        """
        success = self._timer.Start(-1)
        if not success:
            # Since the timer was already running, restarting it shouldn't require
            # any additional resources and therefore shouldn't fail
            raise AssertionError('Unable to restart timer that was already running')
    
    @fg_affinity  # because wx.Timer must be manipulated on foreground thread
    def stop(self) -> None:
        """
        Stops this timer.
        """
        self._timer.Stop()
    
    # === Internal ===
    
    @capture_crashes_to_stderr
    @fg_affinity
    def _notify(self, event: wx.TimerEvent) -> None:
        self._action()


class TimerError(Exception):
    pass
