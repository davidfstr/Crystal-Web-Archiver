from collections.abc import Callable
from crystal.util.xfunctools import partial2
from crystal.util.xthreading import fg_call_later, is_foreground_thread
from functools import wraps
from typing import Optional


_DELAY_UNTIL_PROGRESS_DIALOG_SHOWS = 100 / 1000  # sec


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
    
    def upgrade_revisions_disk_error(self) -> None:
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


# ------------------------------------------------------------------------------
# SaveAsProgressListener

class CancelSaveAs(Exception):
    """Raised when a save operation is canceled by the user."""


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


# ------------------------------------------------------------------------------
