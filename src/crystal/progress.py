from crystal.util.wx_dialog import position_dialog_initially, ShowModal
import sys
from typing import Optional, Type
from typing_extensions import override, Self
import wx


# ------------------------------------------------------------------------------
# _AbstractProgressDialog

class _AbstractProgressDialog:
    _dialog_title: str  # abstract
    _CancelException: Type[Exception]  # abstract
    
    _dialog_style: Optional[int]
    _dialog: Optional[wx.ProgressDialog]
    
    def __init__(self) -> None:
        self._dialog_style = None
        self._dialog = None
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
    
    # === Utility ===
    
    # protected
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
            self._dialog = wx.ProgressDialog(
                self._dialog_title,
                # NOTE: Message must be non-empty to size dialog correctly on Windows
                new_message,
                # (TODO: Shouldn't the value of the previous dialog version,
                #        if any, be preserved here?)
                # TODO: Shouldn't the maximum of the previous dialog version,
                #       if any, be preserved here?
                maximum=1,
                style=new_style
            )
            self._dialog.Name = new_name
            self._dialog.Show()
        else:
            assert self._dialog is not None
            try:
                self._update(self._dialog.Value, new_message)
            except self._CancelException:
                # Ignore cancel request
                pass
    
    # protected
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
    
    _approx_revision_count: Optional[float]
    _resource_count: Optional[int]
    _root_resource_count: Optional[int]
    _resource_group_count: Optional[int]
    _entity_tree_node_count: Optional[int]
    
    # NOTE: Only changed when tests are running
    _always_show_upgrade_required_modal = False
    
    def __init__(self) -> None:
        super().__init__()
        self._approx_revision_count = None
        self._resource_count = None
        self._root_resource_count = None
        self._resource_group_count = None
        self._entity_tree_node_count = None
    
    # === Enter ===
    
    def __enter__(self) -> Self:
        return self
    
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
    
    @override
    def did_upgrade_revisions(self, revision_count: int) -> None:
        """
        Called immediately after a major upgrade completes.
        """
        assert self._dialog is not None
        self._dialog.SetRange(max(revision_count, 1))
    
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
    
    # === Exit ===
    
    def __exit__(self, tp, value, tb) -> None:
        self.reset()


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
