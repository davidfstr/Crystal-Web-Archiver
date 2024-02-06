from __future__ import annotations

from crystal.tests.util.screenshots import take_error_screenshot
from crystal.tests.util.runner import bg_sleep
import datetime
import time
from typing import Callable, Optional, TYPE_CHECKING, TypeVar, Union
import warnings
import wx

if TYPE_CHECKING:
    from crystal.tests.util.controls import TreeItem


_T = TypeVar('_T')

_T1 = TypeVar('_T1')
_T2 = TypeVar('_T2')
_T3 = TypeVar('_T3')


# The hard timeout for waits = the soft timeout * HARD_TIMEOUT_MULTIPLIER
HARD_TIMEOUT_MULTIPLIER = 2.0


# ------------------------------------------------------------------------------
# Utility: Wait While

async def wait_while(
        progression_func: Callable[[], Optional[_T]],
        *, progress_timeout: Optional[float]=None,
        progress_timeout_message: Optional[Callable[[], str]]=None,
        period: Optional[float]=None,
        ) -> None:
    """
    Waits while the specified progression returns different non-None values
    at least every `progress_timeout` seconds, checking every `period` seconds,
    until a None value is returned.
    
    Raises:
    * WaitTimedOut -- 
        if the `progress_timeout` expires while waiting for
        a differing value from the specified progression
    """
    def print_new_status(status: object) -> None:
        print('[' + datetime.datetime.now().strftime('%H:%M:%S.%f') + ']' + ' ' + str(status))
    
    last_status = progression_func()
    if last_status is None:
        return  # done
    print_new_status(last_status)
    
    def do_check_status() -> Optional[bool]:
        nonlocal last_status
        
        current_status = progression_func()
        if current_status is None:
            print_new_status('DONE')
            return True  # done
        
        changed_status = (current_status != last_status)  # capture
        last_status = current_status  # reinterpret
        
        if changed_status:
            print_new_status(current_status)
            return False  # progress
        else:
            return None  # no progress
    
    while True:
        is_done = (await wait_for(
            do_check_status,
            timeout=progress_timeout,
            period=period,
            message=progress_timeout_message,
        ))  # type: bool
        if is_done:
            return


# ------------------------------------------------------------------------------
# Utility: Wait For

DEFAULT_WAIT_TIMEOUT = 2.0  # arbitrary
DEFAULT_WAIT_PERIOD = 0.1  # arbitrary


async def wait_for(
        condition: Callable[[], Optional[_T]],
        timeout: Optional[float]=None,
        *, period: Optional[float]=None,
        message: Optional[Callable[[], str]]=None,
        stacklevel_extra: int=0,
        screenshot_on_error: bool=True,
        ) -> _T:
    """
    Waits up to `timeout` seconds for the specified condition to become non-None,
    returning the result of the condition, checking every `period` seconds.
    
    Raises:
    * WaitTimedOut -- if the timeout expires before the condition becomes non-None
    """
    if timeout is None:
        timeout = DEFAULT_WAIT_TIMEOUT
    if period is None:
        period = DEFAULT_WAIT_PERIOD
    
    soft_timeout = timeout
    hard_timeout = timeout * HARD_TIMEOUT_MULTIPLIER
    
    start_time = time.time()  # capture
    hard_timeout_exceeded = False
    try:
        while True:
            condition_result = condition()
            if condition_result is not None:
                return condition_result
            
            # Raise if hard timeout exceeded
            delta_time = time.time() - start_time
            if delta_time > hard_timeout:
                if message is not None:
                    # Use caller-provided failure message if available
                    message_str = message()
                elif hasattr(condition, 'description'):
                    condition_description = condition.description  # type: ignore[attr-defined]
                    message_str = f'Timed out waiting {timeout}s for {condition_description}'
                else:
                    message_str = f'Timed out waiting {timeout}s for {condition!r}'
                
                # Screenshot the timeout error
                if screenshot_on_error:
                    take_error_screenshot()
                
                hard_timeout_exceeded = True
                raise WaitTimedOut(message_str)
            
            await bg_sleep(period)
    finally:
        # Warn if soft timeout exceeded
        if not hard_timeout_exceeded:
            delta_time = time.time() - start_time
            if delta_time > soft_timeout:
                message_suffix_str = None
                if message is not None:
                    # Use caller-provided failure message if available
                    message_suffix_str = message()
                elif hasattr(condition, 'description'):
                    condition_description = condition.description  # type: ignore[attr-defined]
                    message_suffix_str = f'{condition_description}'
                else:
                    message_suffix_str = f'{condition!r}'
                
                warnings.warn(
                    'Soft timeout exceeded (%.1fs > %.1fs). %s' % (
                        delta_time,
                        soft_timeout,
                        message_suffix_str
                    ),
                    stacklevel=(2 + stacklevel_extra))


class WaitTimedOut(Exception):
    pass


def window_condition(name: str, *, hidden_ok: bool=False) -> Callable[[], Optional[wx.Window]]:
    def window() -> Optional[wx.Window]:
        window = wx.FindWindowByName(name)  # type: Optional[wx.Window]
        if window is None:
            return None
        if not hidden_ok and not window.IsShown():
            return None
        return window
    window.description = (  # type: ignore[attr-defined]
        f'window {name!r} to appear'
        if not hidden_ok
        else f'window {name!r} to be created'
    )
    return window


def first_child_of_tree_item_is_not_loading_condition(
        ti: TreeItem
        ) -> Callable[[], Optional[wx.TreeItemId]]:
    def first_child_of_tree_item_is_not_loading() -> Optional[TreeItem]:
        first_child_ti = ti.GetFirstChild()
        if first_child_ti is None:
            return None
        if first_child_ti.Text == 'Loading...':
            return None
        return first_child_ti
    return first_child_of_tree_item_is_not_loading


def tree_has_children_condition(
        tree: wx.TreeCtrl, 
        ) -> Callable[[], Optional[bool]]:
    return not_condition(tree_has_no_children_condition(tree))


def tree_has_no_children_condition(
        tree: wx.TreeCtrl, 
        ) -> Callable[[], Optional[bool]]:
    from crystal.tests.util.controls import TreeItem
    return tree_item_has_no_children_condition(TreeItem(tree, tree.GetRootItem()))


def tree_item_has_no_children_condition(
        ti: TreeItem
        ) -> Callable[[], Optional[bool]]:
    def tree_item_has_no_children() -> Optional[bool]:
        first_child_tii = ti.tree.GetFirstChild(ti.id)[0]
        if not first_child_tii.IsOk():
            return True
        else:
            return None
    return tree_item_has_no_children


def is_enabled_condition(window: wx.Window) -> Callable[[], Optional[bool]]:
    def is_enabled() -> Optional[bool]:
        return window.Enabled or None
    return is_enabled


def not_condition(condition: Callable[[], Optional[_T]]) -> Callable[[], Optional[bool]]:
    def not_() -> Optional[bool]:
        if condition():
            return None
        else:
            return True
    return not_


def or_condition(
        *conditions: Callable[[], Optional[_T]]
        ) -> Callable[[], Optional[_T]]:
    def or_() -> Optional[_T]:
        for condition in conditions:
            result = condition()
            if result is not None:
                return result
        return None
    return or_


# ------------------------------------------------------------------------------
