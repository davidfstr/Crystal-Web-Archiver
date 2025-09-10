from collections.abc import Callable
from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.headless import is_headless_mode
from crystal.util.sizes import format_byte_size
from crystal.util.wx_dialog import position_dialog_initially, ShowModal
from crystal.util.xfunctools import partial2
from crystal.util.xos import is_wx_gtk, is_windows
from crystal.util.xthreading import fg_affinity, fg_call_later, fg_calls_paused, is_foreground_thread
from functools import wraps
import time
from typing import List, Optional, overload, Self, TypeVar
from typing_extensions import override
import wx

_DELAY_UNTIL_PROGRESS_DIALOG_SHOWS = 100 / 1000  # sec


# ------------------------------------------------------------------------------
# _AbstractProgressDialog

class _AbstractProgressDialog:
    _dialog_title: str  # abstract
    _CancelException: type[Exception]  # abstract
    
    _dialog_style: int | None
    _dialog: 'Optional[DeferredProgressDialog]'
    
    def __init__(self, parent: Optional[wx.Window]=None, *, window_modal: bool=False) -> None:
        self._dialog_style = None
        self._dialog = None
        self._parent = parent
        self._window_modal = window_modal
        self.reset()
    
    def reset(self) -> None:
        """
        Resets this progress listener to its initial state,
        hiding any progress dialogs.
        
        Afterward, the progress of a new operation may be
        reported through this same progress listener.
        """
        self._dialog_style = None
        if self._dialog is not None:
            self._dialog.Destroy()
            self._dialog = None  # very important; avoids segfaults
    
    def __enter__(self) -> Self:
        return self
    
    def __exit__(self, *args) -> None:
        self.reset()
    
    # === Utility ===

    # protected
    @fg_affinity
    def _update_can_cancel(self, can_cancel: bool, new_message: str) -> None:
        """
        Updates whether the visible progress dialog shows a cancel button or not,
        recreating the dialog with/without the button as necessary.
        
        Also updates the progress dialog to display the specified message.
        
        Does NOT raise _CancelException.
        """
        old_style = self._dialog_style
        new_style = (
            wx.PD_AUTO_HIDE|wx.PD_APP_MODAL
            if not can_cancel
            else wx.PD_AUTO_HIDE|wx.PD_APP_MODAL|wx.PD_CAN_ABORT|wx.PD_ELAPSED_TIME
        )
        new_name = 'cr-opening-project'
        
        if new_style != old_style:
            if self._dialog is not None:
                self._dialog.Destroy()
                self._dialog = None  # very important; avoids segfaults
            
            self._dialog_style = new_style
            self._dialog = DeferredProgressDialog(
                self._dialog_title,
                # NOTE: Message must be non-empty to size dialog correctly on Windows
                new_message,
                # (TODO: Shouldn't the value of the previous dialog version,
                #        if any, be preserved here?)
                # TODO: Shouldn't the maximum of the previous dialog version,
                #       if any, be preserved here?
                maximum=1,
                parent=self._parent,
                style=new_style,
                # Show dialog soon, only if it didn't complete in the meantime
                show_after=_DELAY_UNTIL_PROGRESS_DIALOG_SHOWS,
                window_modal=self._window_modal,
            )
            self._dialog.Name = new_name
        else:
            assert self._dialog is not None
            try:
                self._update(self._dialog.Value, new_message)
            except self._CancelException:
                # Ignore cancel request
                pass
    
    # protected
    @fg_affinity
    def _update(self, new_value: int, new_message: str='') -> None:
        """
        Updates the value of the progress bar in the visible progress dialog.
        
        Optionally also updates the message in the progress dialog as well.
        
        Raises:
        * _CancelException
        """
        assert self._dialog is not None
        (ok, _) = self._dialog.Update(new_value, new_message)
        if not ok:
            raise self._CancelException()
    
    # protected
    @fg_affinity
    def _pulse(self, new_message: str='') -> None:
        """
        Changes the progress bar in the visible progress dialog
        to be an indeterminate progress bar.
        
        Raises:
        * _CancelException
        """
        assert self._dialog is not None
        (ok, _) = self._dialog.Pulse(new_message)
        if not ok:
            raise self._CancelException()


# ------------------------------------------------------------------------------
# OpenProjectProgressListener

_active_progress_listener = None  # type: Optional[OpenProjectProgressListener]


class CancelOpenProject(Exception):
    pass


class VetoUpgradeProject(Exception):
    pass


# NOTE: See subclass OpenProjectProgressDialog for the documentation of
#       the various methods in this interface.
class OpenProjectProgressListener:
    def opening_project(self) -> None:
        pass
    
    def upgrading_project(self, message: str) -> None:
        pass
    
    def will_upgrade_revisions(self, approx_revision_count: int, can_veto: bool) -> None:
        pass
    
    def upgrading_revision(self, index: int, revisions_per_second: float) -> None:
        pass
    
    def did_upgrade_revisions(self, revision_count: int) -> None:
        pass
    
    def loading_root_resources(self, root_resource_count: int) -> None:
        pass
    
    def loading_resource_groups(self, resource_group_count: int) -> None:
        pass
    
    def loading_root_resource_views(self) -> None:
        pass
    
    def loading_resource_group_views(self) -> None:
        pass
    
    def creating_entity_tree_nodes(self, entity_tree_node_count: int) -> None:
        pass
    
    def reset(self) -> None:
        pass


DummyOpenProjectProgressListener = OpenProjectProgressListener


class OpenProjectProgressDialog(_AbstractProgressDialog, OpenProjectProgressListener):
    _dialog_title = 'Opening Project...'  # override
    _CancelException = CancelOpenProject  # override
    
    _approx_revision_count: float | None
    _resource_count: int | None
    _root_resource_count: int | None
    _resource_group_count: int | None
    _entity_tree_node_count: int | None
    
    # NOTE: Only changed when tests are running
    _always_show_upgrade_required_modal = False
    _upgrading_revision_progress = 0  # type: Optional[int]
    
    def __init__(self) -> None:
        super().__init__()
        self._approx_revision_count = None
        self._resource_count = None
        self._root_resource_count = None
        self._resource_group_count = None
        self._entity_tree_node_count = None
    
    # === Phase 0 ===
    
    @override
    def opening_project(self) -> None:
        self._show_noncancelable_indeterminate_message(
            f'Opening project...')
    
    def _show_noncancelable_indeterminate_message(self, initial_message: str) -> None:
        # HACK: wxGTK does not reliably update wx.ProgressDialog's message
        #       immediately after it is shown. So be sure to initialize
        #       the wx.ProgressDialog's message immediately to what it will
        #       be updated to soon.
        self._update_can_cancel(False, initial_message)
        
        # Change dialog to show an indeterminate progress bar
        try:
            self._pulse(initial_message)
        except CancelOpenProject:
            # Ignore cancel request
            pass
    
    # === Phase 1: Upgrade Revisions ===
    
    @override
    def upgrading_project(self, message: str) -> None:
        """
        Called immediately before a minor upgrade of a project is about to start.
        
        No progress will be reported during the minor upgrade.
        """
        self._show_noncancelable_indeterminate_message(
            f'Upgrading project: {message}')
    
    @override
    def will_upgrade_revisions(self, approx_revision_count: int, can_veto: bool) -> None:
        """
        Called immediately before a major upgrade of project revisions is about
        to start. If can_veto is True then the upgrade can be deferred by
        raising VetoUpgradeProject.
        
        If can_veto is False then VetoUpgradeProject must not be raised.
        
        Raises:
        * VetoUpgradeProject -- if user declines to upgrade the project
        * CancelOpenProject -- if user cancels opening the project
        """
        HISTORICAL_MIN_MIGRATION_SPEED = 200  # revisions/sec
        
        self._approx_revision_count = approx_revision_count
        
        initial_message = f'Upgrading about {approx_revision_count:n} revision(s)...'
        self._update_can_cancel(True, initial_message)
        
        assert self._dialog is not None
        self._dialog.SetRange(max(approx_revision_count, 1))
        self._update(0, initial_message)
        
        eta_total_minutes = approx_revision_count // HISTORICAL_MIN_MIGRATION_SPEED // 60
        if eta_total_minutes <= 2 and not self._always_show_upgrade_required_modal:
            # Automatically accept an upgrade if it looks like it will be fast
            pass
        else:
            # Prompt whether to start/continue upgrade now
            
            # TODO: Report ETA as "X hours Y minutes" rather than as
            #       just "Z minutes", since a several hours may be
            #       required for large projects
            #
            # TODO: Consider using self._dialog as the parent of this message
            #       dialog rather than making it its own top-level dialog
            dialog = wx.MessageDialog(None,
                message=(
                    f'Your project needs to be upgraded. '
                    f'About {eta_total_minutes:n} minutes will be required.'
                    # (TODO: Provide a 1 sentence summary of the benefits
                    #        of upgrading.)
                ),
                caption='Upgrade Required',
                style=(
                    wx.YES_NO|wx.CANCEL
                    if can_veto
                    else wx.OK|wx.CANCEL
                ),
            )
            dialog.Name = 'cr-upgrade-required'
            with dialog:
                if can_veto:
                    dialog.SetYesNoCancelLabels('Continue', '&Later', wx.ID_CLOSE)
                else:
                    dialog.SetOKCancelLabels('Continue', wx.ID_CLOSE)
                dialog.SetEscapeId(wx.ID_CANCEL)
                dialog.SetAcceleratorTable(wx.AcceleratorTable([
                    wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('L'), wx.ID_NO),
                    wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('W'), wx.ID_CANCEL),
                ]))
                position_dialog_initially(dialog)
                choice = ShowModal(dialog)
            if choice in [wx.ID_YES, wx.ID_OK]:
                pass
            elif choice == wx.ID_NO:
                raise VetoUpgradeProject()
            elif choice == wx.ID_CANCEL:
                raise CancelOpenProject()
            else:
                raise AssertionError()
        
        OpenProjectProgressDialog._upgrading_revision_progress = 0
    
    @override
    def upgrading_revision(self, index: int, revisions_per_second: float) -> None:
        """
        Called about once every second while project is being upgraded,
        to report progress of the upgrade.
        
        Raises:
        * CancelOpenProject
        """
        print(f'Upgrading revisions: {index:n} / {self._approx_revision_count:n} ({int(revisions_per_second):n} rev/sec)')
        self._update(index)
        OpenProjectProgressDialog._upgrading_revision_progress = index
    
    @override
    def did_upgrade_revisions(self, revision_count: int) -> None:
        """
        Called immediately after a major upgrade completes.
        """
        assert self._dialog is not None
        self._dialog.SetRange(max(revision_count, 1))
        OpenProjectProgressDialog._upgrading_revision_progress = None  # done
    
    # === Phase 2: Load ===
    
    # Step 1
    @override
    def loading_root_resources(self, root_resource_count: int) -> None:
        """
        Raises:
        * CancelOpenProject
        """
        self._root_resource_count = root_resource_count
        
        initial_message = f'Loading {root_resource_count:n} root resources(s)...'
        self._update_can_cancel(True, initial_message)
        
        assert self._dialog is not None
        self._dialog.SetRange(5)
        self._update(0, initial_message)
    
    # Step 2
    @override
    def loading_resource_groups(self, resource_group_count: int) -> None:
        """
        Raises:
        * CancelOpenProject
        """
        self._resource_group_count = resource_group_count
        
        assert self._dialog is not None
        self._update(
            1,
            f'Loading {resource_group_count:n} resource groups...')
    
    # Step 3
    @override
    def loading_root_resource_views(self) -> None:
        """
        Raises:
        * CancelOpenProject
        """
        if self._root_resource_count is None:
            return
        
        assert self._dialog is not None
        self._update(
            2,
            f'Creating {self._root_resource_count:n} root resource views...')
    
    # Step 4
    @override
    def loading_resource_group_views(self) -> None:
        """
        Raises:
        * CancelOpenProject
        """
        if self._resource_group_count is None:
            return
        
        assert self._dialog is not None
        self._update(
            3,
            f'Creating {self._resource_group_count} resource group views...')
    
    # Step 5
    @override
    def creating_entity_tree_nodes(self, entity_tree_node_count: int) -> None:
        """
        Raises:
        * CancelOpenProject
        """
        if self._root_resource_count is None or self._resource_group_count is None:
            return
        
        assert self._dialog is not None
        if entity_tree_node_count != (self._root_resource_count + self._resource_group_count):
            raise AssertionError('Unexpected number of initial entity tree nodes')
        self._entity_tree_node_count = entity_tree_node_count
        
        self._update(
            4,
            f'Creating {entity_tree_node_count} entity tree nodes...')


# ------------------------------------------------------------------------------
# LoadUrlsProgressListener

class CancelLoadUrls(Exception):
    pass


# NOTE: See subclass LoadUrlsProgressDialog for the documentation of
#       the various methods in this interface.
class LoadUrlsProgressListener:
    def will_load_resources(self, approx_resource_count: int) -> None:
        pass
    
    def loading_resource(self, index: int) -> None:
        pass
    
    def did_load_resources(self, resource_count: int) -> None:
        pass
    
    def indexing_resources(self) -> None:
        pass
    
    def reset(self) -> None:
        pass


DummyLoadUrlsProgressListener = LoadUrlsProgressListener


class LoadUrlsProgressDialog(_AbstractProgressDialog, LoadUrlsProgressListener):
    _dialog_title = 'Loading URLs...'  # override
    _CancelException = CancelLoadUrls  # override
    
    def __init__(self) -> None:
        super().__init__()
    
    @override
    def will_load_resources(self, approx_resource_count: int) -> None:
        """
        Called immediately before resources will be loaded.
        
        Raises:
        * CancelLoadUrls
        """
        initial_message = f'Loading about {approx_resource_count:n} resource(s)...'
        self._update_can_cancel(True, initial_message)
        
        assert self._dialog is not None
        self._dialog.SetRange(max(approx_resource_count, 1))
        self._update(0, initial_message)
    
    @override
    def loading_resource(self, index: int) -> None:
        """
        Called periodically while resources are being loaded, to report progress.
        
        Raises:
        * CancelLoadUrls
        """
        self._update(index)
    
    @override
    def did_load_resources(self, resource_count: int) -> None:
        """
        Called immediately after resources finished loading.
        """
        assert self._dialog is not None
        self._resource_count = resource_count
        self._dialog.SetRange(max(resource_count, 1))
    
    @override
    def indexing_resources(self) -> None:
        """
        Raises:
        * CancelLoadUrls
        """
        assert self._dialog is not None
        assert self._resource_count is not None
        message = f'Indexing {self._resource_count:n} resources(s)...'
        self._update(self._dialog.GetRange(), message)


# ------------------------------------------------------------------------------
# SaveAsProgressListener

class CancelSaveAs(Exception):
    """Raised when a save operation is canceled by the user."""
    pass


# NOTE: See subclass SaveAsProgressDialog for the documentation of
#       the various methods in this interface.
class SaveAsProgressListener:
    def calculating_total_size(self, message: str) -> None:
        pass
    
    def total_size_calculated(self, total_file_count: int, total_byte_count: int) -> None:
        pass
    
    def copying(self, file_index: int, filename: str, bytes_copied: int, bytes_per_second: float) -> None:
        pass
    
    def did_copy_files(self) -> None:
        pass
    
    def reset(self) -> None:
        pass


DummySaveAsProgressListener = SaveAsProgressListener


def _cancel_or_fg_trampoline(func: Callable[..., None]) -> Callable[..., None]:
    """
    Alters the decorated function to raise CancelSaveAs if the user requested
    cancel. Otherwise runs the decorated function soon on the foreground thread.
    
    See also: @fg_trampoline
    """
    @wraps(func)
    def wrapped_func(self: 'SaveAsProgressDialog', *args, **kwargs) -> None:
        """
        Raises:
        * CancelSaveAs
        """
        if self._cancel_requested:
            # If the user has requested to cancel the operation,
            # raise CancelSaveAs to stop the operation.
            raise CancelSaveAs()
        if is_foreground_thread():
            func(self, *args, **kwargs)
        else:
            fg_call_later(partial2(func, self, *args, **kwargs))
    return wrapped_func


class SaveAsProgressDialog(_AbstractProgressDialog, SaveAsProgressListener):
    """
    Dialog that shows progress while saving a project to a new location.
    """
    _dialog_title = 'Saving Project...'
    _CancelException = CancelSaveAs
    
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, window_modal=True)
        self._total_byte_count = 0
        self._total_file_count = 0
        self._value_shift = 0
        self._cancel_requested = False
    
    @_cancel_or_fg_trampoline
    @capture_crashes_to_stderr
    @override
    def calculating_total_size(self, message: str) -> None:
        """
        Called when starting to calculate the total size of files to copy.
        
        Raises:
        * CancelSaveAs
        """
        self._update_can_cancel(True, message)
        
        assert self._dialog is not None
        self._dialog.Show()  # show immediately
        self._pulse(message)
    
    @_cancel_or_fg_trampoline
    @capture_crashes_to_stderr
    @override
    def total_size_calculated(self, total_file_count: int, total_byte_count: int) -> None:
        """
        Called when the total file and byte count have been calculated.

        Raises:
        * CancelSaveAs
        """
        self._total_byte_count = total_byte_count
        self._total_file_count = total_file_count
        
        # Calculate how much to down-shift values so that they fit in a C int
        # (a 32-bit signed integer on most platforms)
        max_value = total_byte_count
        value_shift = 0
        while max_value > 2**31 - 1:
            max_value >>= 1
            value_shift += 1
        self._value_shift = value_shift

        assert self._dialog is not None
        self._dialog.SetRange(total_byte_count >> self._value_shift)
    
    @_cancel_or_fg_trampoline
    @capture_crashes_to_stderr
    @override
    def copying(self, file_index: int, filename: str, bytes_copied: int, bytes_per_second: float) -> None:
        """
        Called periodically during the copy operation, reporting progress.
        
        Raises:
        * CancelSaveAs
        """
        assert self._dialog is not None
        self._update(
            bytes_copied >> self._value_shift,
            f'Copying {format_byte_size(bytes_copied)} of about {format_byte_size(self._total_byte_count)} ' +
            f'({format_byte_size(int(bytes_per_second))}/s)')
    
    @_cancel_or_fg_trampoline
    @capture_crashes_to_stderr
    @override
    def did_copy_files(self) -> None:
        """
        Called when all files have been copied.
        
        Raises:
        * CancelSaveAs
        """
        assert self._dialog is not None
        self._update(
            self._dialog.GetRange(),
            'Copy complete')
    
    # === Utility ===
    
    @override
    def _update(self, *args, **kwargs) -> None:
        try:
            super()._update(*args, **kwargs)
        except CancelSaveAs:
            # Tell the next-called @_cancel_or_fg_trampoline method to raise CancelSaveAs
            self._cancel_requested = True
    
    @override
    def _pulse(self, *args, **kwargs) -> None:
        try:
            super()._pulse(*args, **kwargs)
        except CancelSaveAs:
            # Tell the next-called @_cancel_or_fg_trampoline method to raise CancelSaveAs
            self._cancel_requested = True


# ------------------------------------------------------------------------------
# DeferredProgressDialog

_R = TypeVar('_R')

_Call = tuple[str, tuple[object, ...], dict[str, object]]

class DeferredProgressDialog:
    """
    Similar to wx.ProgressDialog but is hidden by default
    and auto-shows itself only after a delay.
    
    If the related operation completes quickly then no progress dialog
    will be shown at all.
    """
    def __init__(self,
            # wx.ProgressDialog parameters
            title,
            message,
            maximum=100,
            parent=None,
            style=wx.PD_APP_MODAL|wx.PD_AUTO_HIDE,
            
            # DeferredProgressDialog parameters
            show_after: float | None=None,
            window_modal: bool=False,
            
            # Unknown parameters
            *args,
            **kwargs) -> None:
        if show_after is None:
            raise ValueError('Expected show_after=... keyword argument')
        
        self._dialog = None  # type: Optional[wx.ProgressDialog]
        self._calls = [(
            '__init__',
            (title, message, maximum, parent, style) + args,
            kwargs
        )]  # type: List[_Call]
        self._show_at = time.monotonic() + show_after
        self._window_modal = window_modal
        
        self._shown = False
        self._name = None  # type: Optional[str]
        self._value = 0
        self._maximum = maximum
    
    @overload
    def _call(self, call: _Call) -> None: ...
    @overload
    def _call(self, call: _Call, default_result: _R) -> _R: ...
    def _call(self, call, default_result=None):
        if not self._shown:
            # Defer operation
            self._calls.append(call)
            return default_result
        else:
            # Apply operation
            return getattr(self._dialog, call[0])(*call[1], **call[2])
    
    # === Properties ===
    
    def _get_name(self) -> str | None:
        return self._name
    def _set_name(self, name: str) -> None:
        self._name = name
        self._call(('SetName', (name,), {}))
    Name = property(_get_name, _set_name)
    
    @property
    def Value(self) -> int:
        return self._value
    
    def SetRange(self, maximum: int) -> None:
        self._maximum = maximum
        self._call(('SetRange', (maximum,), {}))
    
    def GetRange(self) -> int:
        return self._maximum
    
    # === Operations ===
    
    def IsShown(self) -> bool:
        return self._shown
    
    def Show(self) -> None:
        """
        Shows this progress dialog.
        
        If configured to show as window modal, then it will
        be shown as a window modal dialog.
        """
        if self._shown:
            return
        
        # Silently refuse to show if running in headless mode
        if is_headless_mode():
            return
        
        # Show now. Apply deferred operations.
        assert len(self._calls) >= 1
        assert self._calls[0][0] == '__init__'
        # NOTE: At least on Windows, the wx.ProgressDialog constructor may immediately
        #       try to process events on a nested event loop. We don't want
        #       arbitrary foreground callables to run here because the
        #       DeferredProgressDialog instance is in an inconsistent state.
        with fg_calls_paused():
            self._dialog = wx.ProgressDialog(*self._calls[0][1], **self._calls[0][2])
        self._shown = True
        if self._window_modal:
            # NOTE: Not using ShowWindowModal() from util/wx_dialog.py here
            #       because it does not properly handle the special cases for
            #       wx.ProgressDialog.
            if is_wx_gtk() or is_windows():
                # For ProgressDialog:
                # 1. GTK warns when showing a dialog as modal (or window-modal), so don't
                # 2. Windows tries to run its own event loop when showing a modal dialog
                #    and expects to be able call Exit() during that event loop.
                #    However Crystal does not run model dialogs in a "real" model loop,
                #    so that Exit() call will cause an assertion failure like:
                #    > C++ assertion ""IsRunning()"" failed at ..\..\src\common\evtloopcmn.cpp(92) in wxEventLoopBase::Exit(): Use ScheduleExit() on not running loop
                self._dialog.Show()
            else:
                # macOS fully supports window-modal dialogs
                self._dialog.ShowWindowModal()
        for call in self._calls[1:]:
            self._call(call)
        self._calls.clear()
    
    def Destroy(self) -> None:
        # Defer/apply operation
        self._call(('Destroy', (), {}))
        
        if self._dialog is not None:
            self._dialog = None
        self._shown = False
    
    def Update(self, value: int, newmsg: str='') -> tuple[bool, bool]:
        # Show self if show_at time has passed
        if not self._shown and time.monotonic() >= self._show_at:
            self.Show()
        
        # Defer/apply operation
        self._value = value
        return self._call(('Update', (value, newmsg), {}), (True, False))
    
    def Pulse(self, newmsg: str) -> tuple[bool, bool]:
        # Show self if show_at time has passed
        if not self._shown and time.monotonic() >= self._show_at:
            self.Show()
        
        # Defer/apply operation
        return self._call(('Pulse', (newmsg,), {}), (True, False))


# ------------------------------------------------------------------------------
