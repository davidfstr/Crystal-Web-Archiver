from __future__ import annotations

from concurrent.futures import Future
from contextlib import closing
from crystal.model.util import resolve_proxy
from crystal.util.xthreading import (
    fg_affinity,
)
from typing import (
    cast, TYPE_CHECKING,
)

if TYPE_CHECKING:
    from crystal.task import (
        Task,
    )
    from crystal.model.project import Project
    from crystal.model.resource import Resource
    from crystal.model.resource_revision import ResourceRevision


# ------------------------------------------------------------------------------
# RootResource

class RootResource:
    """
    Represents a resource whose existence is manually defined by the user.
    Persisted and auto-saved.
    """
    project: Project
    _name: str
    _resource: Resource
    # TODO: Alter the "deleted" value of _id from None to be a symbolic constant,
    #       like Resource's _DELETED_ID.
    _id: int  # or None if deleted
    
    # === Init ===
    
    @fg_affinity
    def __new__(cls, project: Project, name: str, resource: Resource, _id: int | None=None) -> RootResource:
        """
        Creates a new root resource.
        
        Arguments:
        * project -- associated `Project`.
        * name -- name. Possibly ''.
        * resource -- `Resource`.
        
        Raises:
        * ProjectReadOnlyError
        * CrossProjectReferenceError -- if `resource` belongs to a different project.
        * RootResource.AlreadyExists -- 
            if there is already a `RootResource` associated with the specified resource.
        * sqlite3.DatabaseError --
            if a database error occurred, preventing the creation of the new RootResource.
        """
        from crystal.model.project import CrossProjectReferenceError, Project, ProjectReadOnlyError
        from crystal.model.resource import Resource
        
        project = resolve_proxy(project)  # type: ignore[assignment]
        if not isinstance(project, Project):
            raise TypeError()
        if not isinstance(name, str):
            raise TypeError()
        if not isinstance(resource, Resource):
            raise TypeError()
        
        if resource.project != project:
            raise CrossProjectReferenceError('Cannot have a RootResource refer to a Resource from a different Project.')
        
        if resource in project._root_resources:
            raise RootResource.AlreadyExists
        else:
            self = object.__new__(cls)
            self.project = project
            self._name = name
            self._resource = resource
            
            if project._loading:
                assert _id is not None
                self._id = _id
            else:
                if project.readonly:
                    raise ProjectReadOnlyError()
                with project._db, closing(project._db.cursor()) as c:
                    c.execute('insert into root_resource (name, resource_id) values (?, ?)', (name, resource._id))
                    assert c.lastrowid is not None
                    _id = c.lastrowid  # capture
                self._id = _id
            project._root_resources[resource] = self
            
            if not project._loading:
                project._root_resource_did_instantiate(self)
            
            return self
    
    # === Delete ===
    
    @fg_affinity
    def delete(self) -> None:
        """
        Deletes this root resource.
        If it is referenced as a source, it will be replaced with None.
        
        Raises:
        * sqlite3.DatabaseError --
            if the delete fully failed due to a database error
        """
        from crystal.model.project import ProjectReadOnlyError
        
        groups_with_source_to_clear = [
            rg
            for rg in self.project.resource_groups
            if rg.source == self
        ]
        
        if self.project.readonly:
            raise ProjectReadOnlyError()
        try:
            with self.project._db:
                # Apply clear of sources
                for rg in groups_with_source_to_clear:
                    # NOTE: Use commit=False to merge changes into the following
                    #       committed transaction
                    rg._set_source(None, commit=False)
                
                with closing(self.project._db.cursor()) as c:
                    c.execute('delete from root_resource where id=?', (self._id,))
        except:
            # Rollback clear of sources in memory
            for rg in groups_with_source_to_clear:
                rg._set_source(self, update_database=False)
            
            raise
        self._id = None  # type: ignore[assignment]  # intentionally leave exploding None
        
        del self.project._root_resources[self.resource]
        
        self.project._root_resource_did_forget(self)
    
    # === Properties ===
    
    def _get_name(self) -> str:
        """
        Name of this root resource. Possibly ''.
        
        Setter Raises:
        * sqlite3.DatabaseError
        """
        return self._name
    @fg_affinity
    def _set_name(self, name: str) -> None:
        from crystal.model.project import ProjectReadOnlyError
        
        if self._name == name:
            return
        
        if self.project.readonly:
            raise ProjectReadOnlyError()
        with self.project._db, closing(self.project._db.cursor()) as c:
            c.execute('update root_resource set name=? where id=?', (
                name,
                self._id,))
        
        self._name = name
    name = cast(str, property(_get_name, _set_name))
    
    @property
    def display_name(self) -> str:
        """Name of this root resource that is used in the UI. Never ''."""
        return self.name or self.url
    
    @property
    def resource(self) -> Resource:
        return self._resource
    
    @property
    def url(self) -> str:
        return self.resource.url
    
    # === Operations: Download ===
    
    # TODO: Create the underlying task with the full RootResource
    #       so that the correct subtitle is displayed.
    def download(self, *, needs_result: bool=True) -> Future[ResourceRevision]:
        return self.resource.download(needs_result=needs_result)
    
    def create_download_task(self, *, needs_result: bool=True) -> Task:
        """
        Gets/creates a task to download this root resource.
        
        The caller is responsible for adding a returned created Task as the child of an
        appropriate parent task so that the UI displays it.
        
        A created task may be complete immediately after initialization,
        and a looked up task may be complete.
        """
        # TODO: Create the underlying task with the full RootResource
        #       so that the correct subtitle is displayed.
        return self.resource.create_download_task(needs_result=needs_result, is_embedded=False)
    
    # === Utility ===
    
    def __repr__(self):
        return 'RootResource({},{})'.format(repr(self.name), repr(self.resource.url))
    
    class AlreadyExists(Exception):
        """
        Raised when an attempt is made to create a new `RootResource` for a `Resource`
        that is already associated with an existing `RootResource`.
        """


# ------------------------------------------------------------------------------