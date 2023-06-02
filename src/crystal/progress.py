from overrides import overrides
import sys
from typing import Optional
import wx


class OpenProjectProgressListener:
    def opening_project(self, project_name: str) -> None:
        pass
    
    def loading_resources(self, resource_count: int) -> None:
        pass
    
    def loading_resource(self, index: int) -> None:
        pass
    
    def indexing_resources(self) -> None:
        pass
    
    def loading_root_resources(self, root_resource_count: int) -> None:
        pass
    
    def loading_resource_groups(self, resource_group_count: int) -> None:
        pass
    
    def loading_resource_group(self, index: int) -> None:
        pass
    
    def loading_root_resource_views(self) -> None:
        pass
    
    def loading_root_resource_view(self, index: int) -> None:
        pass
    
    def loading_resource_group_views(self) -> None:
        pass
    
    def loading_resource_group_view(self, index: int) -> None:
        pass
    
    def creating_entity_tree_nodes(self, entity_tree_node_count: int) -> None:
        pass
    
    def creating_entity_tree_node(self, index: int) -> None:
        pass


DummyOpenProjectProgressListener = OpenProjectProgressListener


class OpenProjectProgressDialog(OpenProjectProgressListener):
    _dialog: Optional[wx.ProgressDialog]
    _resource_count: Optional[int]
    _root_resource_count: Optional[int]
    _resource_group_count: Optional[int]
    _entity_tree_node_count: Optional[int]
    
    def __init__(self) -> None:
        self._dialog = None
        self._resource_count = None
        self._root_resource_count = None
        self._resource_group_count = None
        self._entity_tree_node_count = None
    
    def __enter__(self) -> OpenProjectProgressListener:
        return self
    
    @overrides
    def opening_project(self, project_name: str) -> None:
        self._dialog = wx.ProgressDialog(
            'Opening Project...',
            'Opening: ' + project_name,
            maximum=1,
            style=wx.PD_AUTO_HIDE|wx.PD_APP_MODAL|wx.PD_CAN_ABORT
        )
        self._dialog.Show()
    
    @overrides
    def loading_resources(self, resource_count: int) -> None:
        assert self._dialog is not None
        self._resource_count = resource_count
        self._dialog.SetRange(max(resource_count * 2, 1))
        self._dialog.Update(
            0,
            f'Loading {resource_count:n} resource(s)...')
    
    @overrides
    def loading_resource(self, index: int) -> None:
        assert self._dialog is not None
        (ok, _) = self._dialog.Update(index)
        if not ok:
            sys.exit()
    
    @overrides
    def indexing_resources(self) -> None:
        assert self._dialog is not None
        assert self._resource_count is not None
        self._dialog.Update(
            self._dialog.Value,
            f'Indexing {self._resource_count:n} resources(s)...')
    
    @overrides
    def loading_root_resources(self, root_resource_count: int) -> None:
        assert self._dialog is not None
        self._root_resource_count = root_resource_count
        self._dialog.Update(
            self._dialog.Value,
            f'Loading {root_resource_count:n} root resources(s)...')
    
    @overrides
    def loading_resource_groups(self, resource_group_count: int) -> None:
        assert self._dialog is not None
        self._resource_group_count = resource_group_count
        self._dialog.Update(
            self._dialog.Value,
            f'Loading {resource_group_count:n} resource groups...')
    
    @overrides
    def loading_resource_group(self, index: int) -> None:
        assert self._dialog is not None
        assert self._resource_count is not None
        assert self._resource_group_count is not None
        (ok, _) = self._dialog.Update(
            self._resource_count + (index * self._resource_count / self._resource_group_count))
        if not ok:
            sys.exit()
    
    @overrides
    def loading_root_resource_views(self) -> None:
        assert self._dialog is not None
        assert self._root_resource_count is not None
        self._dialog.Update(
            self._dialog.Value,
            f'Creating {self._root_resource_count:n} root resource views...')
    
    @overrides
    def loading_root_resource_view(self, index: int) -> None:
        pass
    
    @overrides
    def loading_resource_group_views(self) -> None:
        assert self._dialog is not None
        assert self._resource_group_count is not None
        self._dialog.Update(
            self._dialog.Value,
            f'Creating {self._resource_group_count} resource group views...')
    
    @overrides
    def loading_resource_group_view(self, index: int) -> None:
        pass
    
    @overrides
    def creating_entity_tree_nodes(self, entity_tree_node_count: int) -> None:
        assert self._dialog is not None
        assert self._root_resource_count is not None
        assert self._resource_group_count is not None
        if entity_tree_node_count != (self._root_resource_count + self._resource_group_count):
            raise AssertionError('Unexpected number of initial entity tree nodes')
        self._entity_tree_node_count = entity_tree_node_count
        
        self._dialog.Update(
            self._dialog.Value,
            f'Creating {entity_tree_node_count} entity tree nodes...')
    
    @overrides
    def creating_entity_tree_node(self, index: int) -> None:
        pass
    
    def __exit__(self, tp, value, tb) -> None:
        if self._dialog is not None:
            self._dialog.Destroy()
