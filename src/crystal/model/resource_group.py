from __future__ import annotations

from collections.abc import Sequence
from contextlib import closing
from crystal.model.util import resolve_proxy
from crystal.util.bulkheads import run_bulkhead_call
from crystal.util.ellipsis import Ellipsis, EllipsisType
from crystal.util.listenable import ListenableMixin
from crystal.util.xthreading import (
    is_foreground_thread,
)
import math
import re
from re import Pattern
from shutil import COPY_BUFSIZE  # type: ignore[attr-defined]  # private API
from typing import (
    cast, List, Optional, TYPE_CHECKING, TypeAlias, Union,
)

if TYPE_CHECKING:
    from crystal.model.project import Project
    from crystal.model.resource import Resource
    from crystal.model.root_resource import RootResource
    from crystal.task import (
        DownloadResourceGroupTask,
    )


# ------------------------------------------------------------------------------
# ResourceGroup

ResourceGroupSource: TypeAlias = Union['RootResource', 'ResourceGroup', None]

class ResourceGroup(ListenableMixin):
    """
    Groups resource whose url matches a particular pattern.
    Persisted and auto-saved.
    """
    # TODO: Alter the "deleted" value of _id from None to be a symbolic constant,
    #       like Resource's _DELETED_ID.
    _id: int  # or None if deleted
    
    # === Init ===
    
    def __init__(self, 
            project: Project, 
            name: str,  # possibly ''
            url_pattern: str,
            source: ResourceGroupSource | EllipsisType=None,
            *, do_not_download: bool=False,
            _id: int | None=None) -> None:
        """
        Arguments:
        * project -- associated `Project`.
        * name -- name of this group. Possibly ''.
        * url_pattern -- url pattern matched by this group.
        * source -- source of this group, or Ellipsis if init_source() will be called later.
        
        Raises:
        * sqlite3.DatabaseError --
            if a database error occurred, preventing the creation of the new ResourceGroup.
        """
        from crystal.model.project import Project, ProjectReadOnlyError
        
        super().__init__()
        
        project = resolve_proxy(project)  # type: ignore[assignment]
        if not isinstance(project, Project):
            raise TypeError()
        if not isinstance(name, str):
            raise TypeError()
        if not isinstance(url_pattern, str):
            raise TypeError()
        
        if len(url_pattern) == 0:
            raise ValueError('Cannot create group with empty pattern')
        
        self.project = project
        self._name = name
        self.url_pattern = url_pattern
        self._url_pattern_re = ResourceGroup.create_re_for_url_pattern(url_pattern)
        self._source = None  # type: Union[ResourceGroupSource, EllipsisType]
        self._do_not_download = do_not_download
        self.last_downloaded_member = None  # type: Optional[Resource]
        
        # Calculate members on demand rather than up front
        self._members = None  # type: Optional[List[Resource]]
        
        if project._loading:
            assert _id is not None
            self._id = _id
            
            self._source = source
        else:
            if project.readonly:
                raise ProjectReadOnlyError()
            
            with project._db:
                # Queue: Create ResourceGroup in database
                with closing(project._db.cursor()) as c:
                    c.execute('insert into resource_group (name, url_pattern, do_not_download) values (?, ?, ?)', (name, url_pattern, do_not_download))
                    # (Defer commit until after source is set)
                    self._id = c.lastrowid
                
                # Queue: Set source of ResourceGroup in database
                if source is Ellipsis:
                    raise ValueError()
                self._set_source(source, commit=False)
                assert self._source == source
        project._resource_groups.append(self)
        
        if not project._loading:
            project._resource_group_did_instantiate(self)
    
    def init_source(self, source: ResourceGroupSource) -> None:
        """
        Initializes the source of a group that was initially created with
        source=Ellipsis.
        """
        if self._source is not Ellipsis:
            raise ValueError('Source already initialized')
        self._source = source
    
    # === Delete ===
    
    def delete(self) -> None:
        """
        Deletes this resource group.
        If it is referenced as a source, it will be replaced with None.
        
        Raises:
        * sqlite3.DatabaseError --
            if the delete fully failed due to a database error.
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
                    c.execute('delete from resource_group where id=?', (self._id,))
        except:
            # Rollback clear of sources in memory
            for rg in groups_with_source_to_clear:
                rg._set_source(self, update_database=False)
            
            raise
        self._id = None  # type: ignore[assignment]  # intentionally leave exploding None
        
        self.project._resource_groups.remove(self)
        
        self.project._resource_group_did_forget(self)
    
    # === Properties ===
    
    def _get_name(self) -> str:
        """
        Name of this resource group. Possibly ''.
        
        Setter Raises:
        * sqlite3.DatabaseError
        """
        return self._name
    def _set_name(self, name: str) -> None:
        from crystal.model.project import ProjectReadOnlyError
        
        if self._name == name:
            return
        
        if self.project.readonly:
            raise ProjectReadOnlyError()
        with self.project._db, closing(self.project._db.cursor()) as c:
            c.execute('update resource_group set name=? where id=?', (
                name,
                self._id,))
        
        self._name = name
    name = cast(str, property(_get_name, _set_name))
    
    @property
    def display_name(self) -> str:
        """Name of this group that is used in the UI."""
        return self.name or self.url_pattern
    
    def _get_source(self) -> ResourceGroupSource:
        """
        The "source" of this resource group.
        
        If the source of a resource group is set, the user asserts that downloading
        the source will reveal all of the members of this group. Thus a group's source
        acts as the source of its members.
        
        Setter Raises:
        * sqlite3.DatabaseError
        """
        if isinstance(self._source, EllipsisType):
            raise ValueError('Expected ResourceGroup.init_source() to have been already called')
        return self._source
    def _set_source(self,
            value: ResourceGroupSource,
            *, update_database: bool=True,
            commit: bool=True,
            ) -> None:
        from crystal.model.project import ProjectReadOnlyError
        from crystal.model.root_resource import RootResource
        
        if value == self._source:
            return
        
        if value is None:
            source_type = None
            source_id = None
        elif type(value) is RootResource:
            source_type = 'root_resource'
            source_id = value._id
        elif type(value) is ResourceGroup:
            source_type = 'resource_group'
            source_id = value._id
        else:
            raise ValueError('Not a valid type of source.')
        
        if self.project.readonly:
            raise ProjectReadOnlyError()
        if update_database:
            with self.project._db(commit=commit), closing(self.project._db.cursor()) as c:
                c.execute('update resource_group set source_type=?, source_id=? where id=?', (source_type, source_id, self._id))
        
        self._source = value
    source = cast(ResourceGroupSource, property(_get_source, _set_source))
    
    def _get_do_not_download(self) -> bool:
        """
        Whether members of this group should not be automatically downloaded
        in circumstances where otherwise they would be. Useful to explicitly
        exclude ads and other unwanted resources from the project.
        
        For example if members of a do-not-download group are embedded in
        an HTML resource those members will NOT be automatically downloaded
        when the HTML resource is downloaded.
        
        Setter Raises:
        * sqlite3.DatabaseError
        """
        return self._do_not_download
    def _set_do_not_download(self, value: bool) -> None:
        from crystal.model.project import ProjectReadOnlyError
        
        if self._do_not_download == value:
            return
        
        if self.project.readonly:
            raise ProjectReadOnlyError()
        with self.project._db, closing(self.project._db.cursor()) as c:
            c.execute('update resource_group set do_not_download=? where id=?', (value, self._id))
        
        self._do_not_download = value
        
        self.project._resource_group_did_change_do_not_download(self)
    do_not_download = cast(bool, property(_get_do_not_download, _set_do_not_download))
    
    @staticmethod
    def create_re_for_url_pattern(url_pattern: str) -> Pattern:
        """Converts a url pattern to a regex which matches it."""
        
        # Escape regex characters
        patstr = re.escape(url_pattern)
        
        # Replace metacharacters with tokens
        patstr = patstr.replace(r'\*\*', r'$**$')
        patstr = patstr.replace(r'\*', r'$*$')
        patstr = patstr.replace(r'\#', r'$#$')
        patstr = patstr.replace(r'\@', r'$@$')
        
        # Replace tokens
        patstr = patstr.replace(r'$**$', r'(.*)')
        patstr = patstr.replace(r'$*$', r'([^/?=&]*)')
        patstr = patstr.replace(r'$#$', r'([0-9]+)')
        patstr = patstr.replace(r'$@$', r'([a-zA-Z]+)')
        
        return re.compile(r'^' + patstr + r'$')
    
    @staticmethod
    def literal_prefix_for_url_pattern(url_pattern: str) -> str:
        """
        Returns the longest prefix of the specified url pattern that consists
        only of literal characters, possibly the empty string.
        """
        first_meta_index = math.inf
        for metachar in ['**', '*', '#', '@']:
            cur_meta_index = url_pattern.find(metachar)
            if cur_meta_index != -1 and cur_meta_index < first_meta_index:
                first_meta_index = cur_meta_index
        if first_meta_index == math.inf:
            return url_pattern
        else:
            assert isinstance(first_meta_index, int)
            return url_pattern[:first_meta_index]
    
    def __contains__(self, resource: Resource) -> bool:
        return self.contains_url(resource.url)
    
    def contains_url(self, resource_url: str) -> bool:
        return self._url_pattern_re.match(resource_url) is not None
    
    # NOTE: First access of members must be on foreground thread
    #       but subsequent accesses can be on any thread
    @property
    def members(self) -> Sequence[Resource]:
        """
        Returns the members of this group, in the order they were discovered.
        
        The returned collection is guaranteed to support the Collection
        interface efficiently (__iter__, __len__, __contains__).
        
        The returned collection currently also supports the Sequence interface
        (__getitem__) for convenience for callers that think in terms of indexes,
        but is only guaranteed to support the interface efficiently for callers
        that access members in a sequential fashion.
        
        Raises:
        * CancelLoadUrls
        """
        if self._members is None:
            if not is_foreground_thread():
                raise ValueError('First access of ResourceGroup.members must be done on foreground thread')
            self._members = self.project.resources_matching_pattern(
                url_pattern_re=self._url_pattern_re,
                literal_prefix=ResourceGroup.literal_prefix_for_url_pattern(self.url_pattern))
        return self._members
    
    # === Events ===
    
    # Called when a new Resource is created after the project has loaded
    def _resource_did_instantiate(self, resource: Resource) -> None:
        if self.contains_url(resource.url):
            if self._members is not None:
                self._members.append(resource)
            
            for lis in self.listeners:
                if hasattr(lis, 'group_did_add_member'):
                    run_bulkhead_call(lis.group_did_add_member, self, resource)  # type: ignore[attr-defined]
    
    def _resource_did_alter_url(self, 
            resource: Resource, old_url: str, new_url: str) -> None:
        if self._members is not None:
            if self.contains_url(old_url):
                self._members.remove(resource)
            if self.contains_url(new_url):
                self._members.append(resource)
    
    def _resource_will_delete(self, resource: Resource) -> None:
        if self.contains_url(resource.url):
            if self._members is not None:
                # NOTE: Slow. O(n). OK for now because deleting resources is rare.
                self._members.remove(resource)
    
    # === Operations: Download ===
    
    def download(self, *, needs_result: bool=False) -> DownloadResourceGroupTask:
        """
        Downloads this group asynchronously.
        
        A top-level Task will be created internally to display the progress.
        
        Raises:
        * ProjectClosedError -- If the project is closed.
        """
        if needs_result:
            raise ValueError('Download task for a group never has a result')
        task = self.create_download_task(needs_result=needs_result)
        if not task.complete:
            self.project.add_task(task)
        return task
    
    def create_download_task(self, *, needs_result: bool=False) -> DownloadResourceGroupTask:
        """
        Creates a Task to download this resource group.
        
        The caller is responsible for adding the returned Task as the child of an
        appropriate parent task so that the UI displays it.
        
        The created task may be complete immediately after initialization.
        """
        if needs_result:
            raise ValueError('Download task for a group never has a result')
        
        from crystal.task import DownloadResourceGroupTask
        return DownloadResourceGroupTask(self)
    
    def update_members(self) -> None:
        """
        Updates the membership of this group asynchronously.
        
        A top-level Task will be created internally to display the progress.
        
        Raises:
        * ProjectClosedError -- If the project is closed.
        """
        from crystal.task import UpdateResourceGroupMembersTask
        task = UpdateResourceGroupMembersTask(self)
        self.project.add_task(task)
    
    # === Utility ===

    def __repr__(self):
        return 'ResourceGroup({},{})'.format(repr(self.name), repr(self.url_pattern))


# ------------------------------------------------------------------------------
