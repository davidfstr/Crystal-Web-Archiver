"""
Persistent data model.

Unless otherwise specified, all changes to models are auto-saved.

Model objects may only be manipulated on the foreground thread.
Callers that attempt to do otherwise may get thrown `ProgrammingError`s.
"""

from __future__ import annotations

from collections import OrderedDict
import copy
from crystal.plugins import (
    phpbb as plugins_phpbb,
    substack as plugins_substack,
)   
from crystal.progress import DummyOpenProjectProgressListener, OpenProjectProgressListener
from crystal.util import http_date
from crystal.util.db import (
    DatabaseConnection,
    DatabaseCursor,
    get_column_names_of_table,
    is_no_such_column_error_for,
)
from crystal.util.urls import is_unrewritable_url, requote_uri
from crystal.util.xdatetime import datetime_is_aware
from crystal.util.xfutures import Future
from crystal.util.xthreading import bg_call_later, fg_call_and_wait
import cgi
import datetime
import io
import json
import mimetypes
import os
import re
import shutil
import sqlite3
from typing import (
    Any, Callable, cast, Dict, Iterable, List, Optional, Pattern, TYPE_CHECKING, Tuple,
    TypedDict, Union
)
from urllib.parse import urlparse, urlunparse

if TYPE_CHECKING:
    from crystal.doc.generic import Document, Link
    from crystal.server import ProjectServer
    from crystal.task import DownloadResourceTask, DownloadResourceGroupTask, Task


class Project:
    """
    Groups together a set of resources that are downloaded and any associated settings.
    Persisted and auto-saved.
    """
    
    FILE_EXTENSION = '.crystalproj'
    
    # Project structure constants
    _DB_FILENAME = 'database.sqlite'
    _RESOURCE_REVISION_DIRNAME = 'revisions'
    
    def __init__(self,
            path: str,
            progress_listener: Optional[OpenProjectProgressListener]=None,
            *, readonly: bool=False) -> None:
        """
        Loads a project from the specified filepath, or creates a new one if none is found.
        
        Arguments:
        * path -- 
            path to a directory (ideally with the `FILE_EXTENSION` extension)
            from which the project is to be loaded.
        """
        if progress_listener is None:
            progress_listener = DummyOpenProjectProgressListener()
        
        self.path = path
        self.listeners = []  # type: List[object]
        
        self._properties = dict()               # type: Dict[str, str]
        self._resources = OrderedDict()         # type: Dict[str, Resource]
        self._root_resources = OrderedDict()    # type: Dict[Resource, RootResource]
        self._resource_groups = []              # type: List[ResourceGroup]
        self._readonly = True  # will reinitialize after database is located
        
        def initially_readonly(can_write_db: bool) -> bool:
            return readonly or not can_write_db
        
        self._min_fetch_date = None
        
        progress_listener.opening_project(os.path.basename(path))
        
        self._loading = True
        try:
            if os.path.exists(path):
                # Load from existing project
                
                if not Project.is_valid(path):
                    raise ProjectFormatError('Project format is invalid.')
                
                db_filepath = os.path.join(path, self._DB_FILENAME)  # cache
                db = sqlite3.connect(db_filepath)
                can_write_db = (
                    # Can write to *.crystalproj
                    # (is not Locked on macOS, is not on read-only volume)
                    os.access(path, os.W_OK) and
                    # Can write to database
                    # (is not Locked on macOS, is not Read Only on Windows, is not on read-only volume)
                    os.access(db_filepath, os.W_OK)
                )
                
                self._readonly = initially_readonly(can_write_db)
                self._db = DatabaseConnection(db, lambda: self.readonly)
                
                c = self._db.cursor()
                
                # Upgrade database schema to latest version (unless is readonly)
                if not self.readonly:
                    self._apply_migrations(c)
                
                # Load project properties
                for (name, value) in c.execute('select name, value from project_property'):
                    self._set_property(name, value)
                
                # Load Resources
                [(resource_count,)] = c.execute('select count(1) from resource')
                progress_listener.loading_resources(resource_count)
                for (url, id) in c.execute('select url, id from resource'):
                    Resource(self, url, _id=id)
                
                # Load RootResources
                [(root_resource_count,)] = c.execute('select count(1) from root_resource')
                progress_listener.loading_root_resources(root_resource_count)
                for (name, resource_id, id) in c.execute('select name, resource_id, id from root_resource'):
                    resource = self._get_resource_with_id(resource_id)
                    RootResource(self, name, resource, _id=id)
                
                # Load ResourceGroups
                [(resource_group_count,)] = c.execute('select count(1) from resource_group')
                progress_listener.loading_resource_groups(resource_group_count)
                group_2_source = {}
                for (index, (name, url_pattern, source_type, source_id, id)) in enumerate(c.execute(
                        'select name, url_pattern, source_type, source_id, id from resource_group')):
                    progress_listener.loading_resource_group(index)
                    group = ResourceGroup(self, name, url_pattern, _id=id)
                    group_2_source[group] = (source_type, source_id)
                for (group, (source_type, source_id)) in group_2_source.items():
                    if source_type is None:
                        source_obj = None
                    elif source_type == 'root_resource':
                        source_obj = self._get_root_resource_with_id(source_id)
                    elif source_type == 'resource_group':
                        source_obj = self._get_resource_group_with_id(source_id)
                    else:
                        raise ProjectFormatError('Resource group %s has invalid source type "%s".' % (group._id, source_type))
                    group._init_source(source_obj)
                
                # (ResourceRevisions are loaded on demand)
            else:
                # Create new project
                
                os.mkdir(path)
                os.mkdir(os.path.join(path, self._RESOURCE_REVISION_DIRNAME))
                
                db_filepath = os.path.join(path, self._DB_FILENAME)  # cache
                db = sqlite3.connect(db_filepath)
                can_write_db = True
                
                self._readonly = initially_readonly(can_write_db)
                self._db = DatabaseConnection(db, lambda: self.readonly)
                
                c = self._db.cursor()
                c.execute('create table project_property (name text unique not null, value text)')
                progress_listener.loading_resources(resource_count=0)
                c.execute('create table resource (id integer primary key, url text unique not null)')
                progress_listener.loading_root_resources(root_resource_count=0)
                c.execute('create table root_resource (id integer primary key, name text not null, resource_id integer unique not null, foreign key (resource_id) references resource(id))')
                progress_listener.loading_resource_groups(resource_group_count=0)
                c.execute('create table resource_group (id integer primary key, name text not null, url_pattern text not null, source_type text, source_id integer)')
                c.execute('create table resource_revision (id integer primary key, resource_id integer not null, request_cookie text, error text not null, metadata text not null)')
                c.execute('create index resource_revision__resource_id on resource_revision (resource_id)')
        finally:
            self._loading = False
        
        # Hold on to the root task and scheduler
        import crystal.task
        self.root_task = crystal.task.RootTask()
        crystal.task.start_schedule_forever(self.root_task)
        
        # Hold on to the server connection
        self._server = None  # type: Optional[ProjectServer]
        
        # Define initial configuration
        self._request_cookie = None  # type: Optional[str]
    
    @staticmethod
    def is_valid(path):
        return (
            os.path.exists(path) and 
            os.path.exists(os.path.join(path, Project._DB_FILENAME)) and
            os.path.exists(os.path.join(path, Project._RESOURCE_REVISION_DIRNAME)))
    
    @classmethod
    def _apply_migrations(cls, c: DatabaseCursor) -> None:
        """
        Upgrades this project's database schema to the latest version.
        
        Raises:
        * ProjectReadOnlyError
        """
        # Add resource_revision.request_cookie column if missing
        if 'request_cookie' not in get_column_names_of_table(c, 'resource_revision'):
            c.execute('alter table resource_revision add column request_cookie text')
    
    # === Properties ===
    
    @property
    def title(self) -> str:
        return os.path.basename(self.path)
    
    @property
    def readonly(self) -> bool:
        """
        Whether this project has been opened as read-only during the current session.
        
        When opened as read-only, no modifications to the project's content on disk
        will be attempted. In particular:
        * no new resources can be added,
        * no new resource revisions can be downloaded, and
        * no database schema migrations can be performed,
        * among other restrictions.
        
        This property is configured only for the current session
        and is not persisted.
        """
        return self._readonly
    
    def _get_property(self, name: str, default: str) -> str:
        return self._properties.get(name, default)
    def _set_property(self, name: str, value: str) -> None:
        if not self._loading:
            if self.readonly:
                raise ProjectReadOnlyError()
            c = self._db.cursor()
            c.execute('insert or replace into project_property (name, value) values (?, ?)', (name, value))
            self._db.commit()
        self._properties[name] = value
    
    def _get_default_url_prefix(self):
        """
        URL prefix for the majority of this project's resource URLs.
        The UI will display resources under this prefix as relative URLs.
        """
        return self._get_property('default_url_prefix', None)
    def _set_default_url_prefix(self, value):
        self._set_property('default_url_prefix', value)
    default_url_prefix = property(_get_default_url_prefix, _set_default_url_prefix)
    
    def get_display_url(self, url):
        """
        Returns a displayable version of the provided URL.
        If the URL lies under the configured `default_url_prefix`, that prefix will be stripped.
        """
        default_url_prefix = self.default_url_prefix
        if default_url_prefix is None:
            return url
        if url.startswith(default_url_prefix):
            return url[len(default_url_prefix):]
        else:
            return url
    
    def _get_request_cookie(self) -> Optional[str]:
        return self._request_cookie
    def _set_request_cookie(self, request_cookie: Optional[str]) -> None:
        self._request_cookie = request_cookie
    request_cookie = property(_get_request_cookie, _set_request_cookie, doc=
        """
        The current Cookie HTTP header value to use for authenticating to
        resources fetched from this project's default domain (as specified
        in this project's Default URL Prefix).
        
        This property is configured only for the current session
        and is not persisted.
        """)
    
    def request_cookie_applies_to(self, url: str) -> bool:
        """
        Whether this project's request_cookie should be used when fetching
        a resource at the specified URL.
        """
        default_url_prefix = self.default_url_prefix  # capture
        return (
            default_url_prefix is not None and
            not default_url_prefix.endswith('/') and
            url.startswith(default_url_prefix + '/')
        )
    
    def request_cookies_in_use(self, *, most_recent_first: bool=True) -> List[str]:
        """
        Returns all distinct Cookie HTTP header values used by revisions in this project.
        """
        ordering = 'desc' if most_recent_first else 'asc'
        
        c = self._db.cursor()
        return [
            rc for (rc,) in
            c.execute(f'select distinct request_cookie from resource_revision where request_cookie is not null order by id {ordering}')
        ]
    
    def _get_min_fetch_date(self) -> Optional[datetime.datetime]:
        return self._min_fetch_date
    def _set_min_fetch_date(self, min_fetch_date: Optional[datetime.datetime]) -> None:
        if min_fetch_date is not None:
            if not datetime_is_aware(min_fetch_date):
                raise ValueError('Expected an aware datetime (with a UTC offset)')
        self._min_fetch_date = min_fetch_date
        if not self._loading:
            for lis in self.listeners:
                if hasattr(lis, 'min_fetch_date_did_change'):
                    lis.min_fetch_date_did_change()  # type: ignore[attr-defined]
    min_fetch_date = property(
        _get_min_fetch_date,
        _set_min_fetch_date,
        doc="""
        If non-None then any resource fetched <= this datetime
        will be considered stale and subject to being redownloaded.
        
        This property is configured only for the current session
        and is not persisted.
        """)
    
    @property
    def resources(self) -> Iterable[Resource]:
        return self._resources.values()
    
    def get_resource(self, url: str) -> Optional[Resource]:
        """Returns the `Resource` with the specified URL or None if no such resource exists."""
        return self._resources.get(url, None)
    
    def _get_resource_with_id(self, resource_id):
        """Returns the `Resource` with the specified ID or None if no such resource exists."""
        # PERF: O(n) when it could be O(1)
        return next((r for r in self._resources.values() if r._id == resource_id), None)
    
    @property
    def root_resources(self) -> Iterable[RootResource]:
        return self._root_resources.values()
    
    def get_root_resource(self, resource: Resource) -> Optional[RootResource]:
        """Returns the `RootResource` with the specified `Resource` or None if none exists."""
        return self._root_resources.get(resource, None)
    
    def _get_root_resource_with_id(self, root_resource_id):
        """Returns the `RootResource` with the specified ID or None if no such root resource exists."""
        # PERF: O(n) when it could be O(1)
        return next((rr for rr in self._root_resources.values() if rr._id == root_resource_id), None)
    
    def _get_root_resource_with_name(self, name):
        """Returns the `RootResource` with the specified name or None if no such root resource exists."""
        # PERF: O(n) when it could be O(1)
        return next((rr for rr in self._root_resources.values() if rr.name == name), None)
    
    @property
    def resource_groups(self) -> Iterable[ResourceGroup]:
        return self._resource_groups
    
    def get_resource_group(self, name: str) -> Optional[ResourceGroup]:
        """Returns the `ResourceGroup` with the specified name or None if no such resource exists."""
        # PERF: O(n) when it could be O(1)
        return next((rg for rg in self._resource_groups if rg.name == name), None)
    
    def _get_resource_group_with_id(self, resource_group_id):
        """Returns the `ResourceGroup` with the specified ID or None if no such resource exists."""
        # PERF: O(n) when it could be O(1)
        return next((rg for rg in self._resource_groups if rg._id == resource_group_id), None)
    
    # === Tasks ===
    
    def add_task(self, task: Task) -> None:
        """
        Schedules the specified top-level task for execution, if not already done.
        """
        if task not in self.root_task.children:
            self.root_task.append_child(task)
    
    # === Events ===
    
    # Called when a new Resource is created after the project has loaded
    def _resource_did_instantiate(self, resource: Resource) -> None:
        # Notify resource groups (which are like hardwired listeners)
        for rg in self.resource_groups:
            rg._resource_did_instantiate(resource)
        
        # Notify normal listeners
        for lis in self.listeners:
            if hasattr(lis, 'resource_did_instantiate'):
                lis.resource_did_instantiate(resource)  # type: ignore[attr-defined]
    
    # Called when a new ResourceRevision is created after the project has loaded
    def _resource_revision_did_instantiate(self, revision: ResourceRevision) -> None:
        # Notify normal listeners
        for lis in self.listeners:
            if hasattr(lis, 'resource_revision_did_instantiate'):
                lis.resource_revision_did_instantiate(revision)  # type: ignore[attr-defined]
    
    def _resource_did_alter_url(self, 
            resource: Resource, old_url: str, new_url: str) -> None:
        del self._resources[old_url]
        self._resources[new_url] = resource
        
        # Notify resource groups (which are like hardwired listeners)
        for rg in self.resource_groups:
            rg._resource_did_alter_url(resource, old_url, new_url)
    
    def _resource_did_delete(self, resource: Resource) -> None:
        del self._resources[resource.url]
        
        # Notify resource groups (which are like hardwired listeners)
        for rg in self.resource_groups:
            rg._resource_did_delete(resource)
    
    # === Server ===
    
    def start_server(self, **server_kwargs) -> ProjectServer:
        """
        Starts an HTTP server that serves pages from this project.
        
        If an HTTP server is already running, does nothing.
        """
        if self._server is None:
            import crystal.server
            self._server = crystal.server.ProjectServer(self, **server_kwargs)
        return self._server
    
    @property
    def server_running(self) -> bool:
        return self._server is not None
    
    # === Close ===
    
    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        self._db.close()
    
    # === Context Manager ===
    
    def __enter__(self) -> Project:
        return self
    
    def __exit__(self, exc_type, exc_value, exc_traceback) -> None:
        self.close()


class CrossProjectReferenceError(Exception):
    pass


class ProjectFormatError(Exception):
    pass


class ProjectReadOnlyError(Exception):
    pass


class _WeakTaskRef:
    """
    Holds a reference to a Task until that task completes.
    """
    def __init__(self, task=None):
        self._task = None
        self.task = task
    
    def _get_task(self):
        return self._task
    def _set_task(self, value):
        if self._task:
            self._task.listeners.remove(self)
        self._task = value
        if self._task:
            self._task.listeners.append(self)
    task = property(_get_task, _set_task)
    
    def task_did_complete(self, task):
        self.task = None


class Resource:
    """
    Represents an entity, potentially downloadable.
    Either created manually or discovered through a link from another resource.
    Persisted and auto-saved.
    """
    project: Project
    _url: str
    _download_body_task_ref: _WeakTaskRef
    _download_task_ref: _WeakTaskRef
    _download_task_noresult_ref: _WeakTaskRef
    already_downloaded_this_session: bool
    _id: int  # or None if deleted
    
    def __new__(cls, project: Project, url: str, _id=None) -> Resource:
        """
        Looks up an existing resource with the specified URL or creates a new
        one if no preexisting resource matches.
        
        Arguments:
        * project -- associated `Project`.
        * url -- absolute URL to this resource (ex: http), or a URI (ex: mailto).
        """
        
        if _id is None:
            url_alternatives = cls.resource_url_alternatives(project, url)
            
            # Find first matching existing alternative URL, to provide
            # backward compatibility with older projects that use less-normalized
            # forms of the original URL
            for urla in url_alternatives:
                if urla in project._resources:
                    return project._resources[urla]
            
            normalized_url = url_alternatives[-1]
        else:
            # Always use original URL if loading from saved resource
            normalized_url = url
        del url  # prevent accidental usage later
        
        self = object.__new__(cls)
        self.project = project
        self._url = normalized_url
        self._download_body_task_ref = _WeakTaskRef()
        self._download_task_ref = _WeakTaskRef()
        self._download_task_noresult_ref = _WeakTaskRef()
        self.already_downloaded_this_session = False
        
        if project._loading:
            self._id = _id
        else:
            if project.readonly:
                raise ProjectReadOnlyError()
            c = project._db.cursor()
            c.execute('insert into resource (url) values (?)', (normalized_url,))
            project._db.commit()
            assert c.lastrowid is not None
            self._id = c.lastrowid
        project._resources[normalized_url] = self
        
        if not project._loading:
            project._resource_did_instantiate(self)
        
        return self
    
    @staticmethod
    def resource_url_alternatives(project: Project, url: str) -> List[str]:
        """
        Given an original URL, perhaps computed from a link or directly input
        by the user, return a list of alternative URLs that become progressively
        more-and-more normalized, ending with the fully normal form of the URL.
        
        Each alternative URL returned corresponds to a way that a URL was 
        stored in a Project in a previous version of Crystal, and future
        versions of Crystal should attempt to fetch the less-normalized
        URL versions in preference to the more-normalized versions of an
        URL from a project whenever those less-normalized versions already
        exist in a project.
        
        Newer projects will attempt to save new URLs in the most normalized
        form possible.
        """
        alternatives = []
        
        # Always yield original URL first
        alternatives.append(url)
        
        url_parts = list(urlparse(url))  # clone to make mutable
        
        # Strip fragment component
        # TODO: Recommend restricting fragment-stripping to the 
        #       ('http', 'https') schemes. That would however be a 
        #       (hopefully small) breaking change, 
        #       whose impact should be considered.
        if url_parts[5] != '':  # fragment; strip if present
            url_parts[5] = ''
            alternatives.append(urlunparse(url_parts))
        
        # TODO: Consider extending these normalization rules to apply to
        #       certain additional less-common schemes like 'ftp'
        new_url: str
        if url_parts[0].lower() in ('http', 'https'):  # scheme
            # Normalize domain name
            if _is_ascii(url_parts[1]):  # netloc (domain)
                netloc_lower = url_parts[1].lower()
                if url_parts[1] != netloc_lower:
                    url_parts[1] = netloc_lower
                    alternatives.append(urlunparse(url_parts))
            else:
                # TODO: Support internationalized domains names and advanced
                #       case normalization from RFC 4343
                pass
            
            # Normalize missing path to /
            if url_parts[2] == '':  # path
                url_parts[2] = '/'
                alternatives.append(urlunparse(url_parts))
            
            # Percent-encode the URL (as per RFC 3986) if it wasn't already
            old_url = urlunparse(url_parts)
            new_url = requote_uri(old_url)
            if new_url != old_url:
                alternatives.append(new_url)
            del url_parts  # prevent accidental future use
        else:
            new_url = urlunparse(url_parts)
        
        # Allow plugins to normalize URLs further
        old_url = new_url
        for normalize_url in (plugins_phpbb.normalize_url, plugins_substack.normalize_url):
            try:
                new_url = normalize_url(old_url)
            except Exception:  # ignore errors
                new_url = old_url
            else:
                if new_url != old_url:
                    alternatives.append(new_url)
                    old_url = new_url  # reinterpret
        
        return alternatives
    
    @property
    def resource(self) -> Resource:
        """
        Returns self.
        
        This property is useful when a Resource and a RootResource are used in the same
        context. Both Resource and RootResource have a 'resource' property that returns
        the underlying resource.
        """
        return self
    
    @property
    def url(self) -> str:
        return self._url
    
    # NOTE: Usually a resource's URL will be in normal form when it is created,
    #       unless it was loaded from disk in non-normal form.
    @property
    def normalized_url(self) -> str:
        return self.resource_url_alternatives(self.project, self._url)[-1]
    
    def download_body(self):
        """
        Returns a Future<ResourceRevision> that downloads (if necessary) and returns an
        up-to-date version of this resource's body.
        
        The returned Future may invoke its callbacks on any thread.
        
        A top-level Task will be created internally to display the progress.
        
        Future Raises:
        * CannotDownloadWhenProjectReadOnlyError --
            If resource is not already downloaded and project is read-only.
        """
        task = self.create_download_body_task()
        self.project.add_task(task)
        return task.future
    
    def create_download_body_task(self):
        """
        Creates a Task to download this resource's body.
        
        The caller is responsible for adding the returned Task as the child of an
        appropriate parent task so that the UI displays it.
        """
        def task_factory():
            from crystal.task import DownloadResourceBodyTask
            return DownloadResourceBodyTask(self)
        return self._get_task_or_create(self._download_body_task_ref, task_factory)
    
    def download(self, wait_for_embedded: bool=False, needs_result: bool=True) -> Future:
        """
        Returns a Future[ResourceRevision] that downloads (if necessary) and returns an
        up-to-date version of this resource's body. If a download is performed, all
        embedded resources will be downloaded as well.
        
        The returned Future may invoke its callbacks on any thread.
        
        A top-level Task will be created internally to display the progress.
        
        By default the returned future waits only for the resource itself
        to finish downloading but not for any embedded resources to finish
        downloading. Pass wait_for_embedded=True if you also want to wait
        for embedded resources.
        
        If needs_result=False then the caller is declaring that it does
        not need and will ignore the result of the returned future,
        which enables additional optimizations.
        
        Future Raises:
        * CannotDownloadWhenProjectReadOnlyError --
            If resource is not already downloaded and project is read-only.
        """
        task = self.create_download_task(needs_result=needs_result)
        self.project.add_task(task)
        return task.get_future(wait_for_embedded)
    
    def create_download_task(self, needs_result: bool=True) -> DownloadResourceTask:
        """
        Creates a Task to download this resource and all its embedded resources.
        
        The caller is responsible for adding the returned Task as the child of an
        appropriate parent task so that the UI displays it.
        """
        def task_factory():
            from crystal.task import DownloadResourceTask
            return DownloadResourceTask(self, needs_result=needs_result)
        return self._get_task_or_create(
            self._download_task_ref if needs_result else self._download_task_noresult_ref,
            task_factory
        )
    
    def _get_task_or_create(self, task_ref, task_factory):
        if task_ref.task is not None:
            return task_ref.task
        
        task = task_factory()
        task_ref.task = task
        return task
    
    def has_any_revisions(self) -> bool:
        """
        Returns whether any revisions of this resource have been downloaded.
        """
        c = self.project._db.cursor()
        c.execute('select 1 from resource_revision where resource_id=? limit 1', (self._id,))
        return c.fetchone() is not None
    
    def default_revision(self, *, stale_ok: bool=True) -> Optional[ResourceRevision]:
        """
        Loads and returns the "default" revision of this resource, which is the revision
        that will be displayed when this resource is served or exported.
        
        If no revisions of this resource have been downloaded, None is returned.
        
        If stale_ok=False and the most up-to-date revision of this resource is
        still stale, return None rather than returning a stale revision.
        """
        project = self.project  # cache
        
        revisions = self.revisions()
        for revision in reversed(revisions):  # prioritize most recently downloaded
            if stale_ok:
                return revision
            else:
                revision_is_stale = False
                if project.request_cookie_applies_to(self.url) and project.request_cookie is not None:
                    if revision.request_cookie != project.request_cookie:
                        revision_is_stale = True  # reinterpret
                if project.min_fetch_date is not None:
                    # TODO: Consider storing the fetch date explicitly
                    #       rather than trying to derive it from the 
                    #       Date and Age HTTP headers
                    fetch_date = revision.date_plus_age  # cache
                    if (fetch_date is not None and 
                            fetch_date <= project.min_fetch_date):
                        revision_is_stale = True  # reinterpret
                
                if not revision_is_stale:
                    return revision
        return None
    
    def revisions(self) -> List[ResourceRevision]:
        """
        Loads and returns a list of `ResourceRevision`s downloaded for this resource.
        If no such revisions exist, an empty list is returned.
        
        Revisions will be returned in the order they were downloaded,
        from least-recent to most-recent.
        """
        RR = ResourceRevision
        
        revs = []  # type: list[ResourceRevision]
        c = self.project._db.cursor()
        try:
            rows = c.execute(
                'select request_cookie, error, metadata, id '
                    'from resource_revision where resource_id=? order by id asc',
                (self._id,)
            )  # type: Iterable[Tuple[Any, Any, Any, Any]]
        except Exception as e:
            if is_no_such_column_error_for('request_cookie', e):
                # Fetch from <=1.2.0 database schema
                old_rows = c.execute(
                    'select error, metadata, id '
                        'from resource_revision where resource_id=? order by id asc',
                    (self._id,)
                )  # type: Iterable[Tuple[Any, Any, Any]]
                rows = ((None, c0, c1, c2) for (c0, c1, c2) in old_rows)
            else:
                raise
        for (request_cookie, error, metadata, id) in rows:
            revs.append(ResourceRevision.load(
                resource=self,
                request_cookie=request_cookie,
                error=RR._decode_error(error),
                metadata=RR._decode_metadata(metadata),
                id=id))
        return revs
    
    def revision_for_etag(self) -> Dict[str, ResourceRevision]:
        """
        Returns a map of each known ETag to a matching ResourceRevision that is NOT an HTTP 304.
        """
        revision_for_etag = {}
        for revision in self.revisions():
            if revision.is_http_304:
                continue
            etag = revision.etag
            if etag is not None:
                revision_for_etag[etag] = revision
        return revision_for_etag
    
    # NOTE: Only used from a Python REPL at the moment
    def try_normalize_url(self) -> bool:
        """
        Tries to alter this resource's URL to be in normal form,
        unless there is already an existing resource with that URL.
        """
        new_url = self.normalized_url
        if new_url == self._url:
            return True
        return self._try_alter_url(new_url)
    
    def _try_alter_url(self, new_url: str) -> bool:
        """
        Tries to alter this resource's URL to new specified URL,
        unless there is already an existing resource with that URL.
        """
        project = self.project  # cache
        
        if new_url in project._resources:
            return False
        
        if project.readonly:
            raise ProjectReadOnlyError()
        c = project._db.cursor()
        c.execute('update resource set url=? where id=?', (new_url, self._id,))
        project._db.commit()
        
        old_url = self._url  # capture
        self._url = new_url
        
        project._resource_did_alter_url(self, old_url, new_url)
        
        return True
    
    # NOTE: Only used from a Python REPL at the moment
    def delete(self) -> None:
        project = self.project
        
        # Ensure not referenced by a RootResource
        c = project._db.cursor()
        root_resource_ids = [
            id
            for (id,) in 
            c.execute('select id from root_resource where resource_id=?', (self._id,))
        ]
        if len(root_resource_ids) > 0:
            raise ValueError(f'Cannot delete {self!r} referenced by RootResource {root_resource_ids!r}')
        
        # Delete ResourceRevision children
        for rev in self.revisions():
            rev.delete()
        
        # Delete Resource itself
        if project.readonly:
            raise ProjectReadOnlyError()
        c = project._db.cursor()
        c.execute('delete from resource where id=?', (self._id,))
        project._db.commit()
        self._id = None  # type: ignore[assignment]  # intentionally leave exploding None
        
        project._resource_did_delete(self)
    
    def __repr__(self):
        return "Resource(%s)" % (repr(self.url),)


class RootResource:
    """
    Represents a resource whose existence is manually defined by the user.
    Persisted and auto-saved.
    """
    project: Project
    name: str
    resource: Resource
    
    def __new__(cls, project: Project, name: str, resource: Resource, _id=None) -> RootResource:
        """
        Creates a new root resource.
        
        Arguments:
        * project -- associated `Project`.
        * name -- display name.
        * resource -- `Resource`.
        
        Raises:
        * CrossProjectReferenceError -- if `resource` belongs to a different project.
        * RootResource.AlreadyExists -- 
            if there is already a `RootResource` associated with the specified resource.
        * ProjectReadOnlyError
        """
        
        if resource.project != project:
            raise CrossProjectReferenceError('Cannot have a RootResource refer to a Resource from a different Project.')
        
        if resource in project._root_resources:
            raise RootResource.AlreadyExists
        else:
            self = object.__new__(cls)
            self.project = project
            self.name = name
            self.resource = resource
            
            if project._loading:
                self._id = _id
            else:
                if project.readonly:
                    raise ProjectReadOnlyError()
                c = project._db.cursor()
                c.execute('insert into root_resource (name, resource_id) values (?, ?)', (name, resource._id))
                project._db.commit()
                self._id = c.lastrowid
            project._root_resources[resource] = self
            return self
    
    def delete(self) -> None:
        """
        Deletes this root resource.
        If it is referenced as a source, it will be replaced with None.
        """
        for rg in self.project.resource_groups:
            if rg.source == self:
                rg.source = None
        
        if self.project.readonly:
            raise ProjectReadOnlyError()
        c = self.project._db.cursor()
        c.execute('delete from root_resource where id=?', (self._id,))
        self.project._db.commit()
        self._id = None
        
        del self.project._root_resources[self.resource]
    
    @property
    def url(self) -> str:
        return self.resource.url
    
    # TODO: Create the underlying task with the full RootResource
    #       so that the correct subtitle is displayed.
    def download(self, needs_result: bool=True) -> Future:
        return self.resource.download(needs_result=needs_result)
    
    # TODO: Create the underlying task with the full RootResource
    #       so that the correct subtitle is displayed.
    def create_download_task(self, needs_result: bool=True) -> Task:
        return self.resource.create_download_task(needs_result=needs_result)
    
    def __repr__(self):
        return "RootResource(%s,%s)" % (repr(self.name), repr(self.resource.url))
    
    class AlreadyExists(Exception):
        """
        Raised when an attempt is made to create a new `RootResource` for a `Resource`
        that is already associated with an existing `RootResource`.
        """
        pass


class ResourceRevision:
    """
    A downloaded revision of a `Resource`. Immutable.
    Persisted. Loaded on demand.
    """
    resource: Resource
    request_cookie: Optional[str]
    error: Optional[Exception]
    metadata: Optional[ResourceRevisionMetadata]
    _id: int
    has_body: bool
    
    # === Init ===
    
    @staticmethod
    def create_from_error(
            resource: Resource,
            error: Exception,
            request_cookie: Optional[str]=None
            ) -> ResourceRevision:
        """
        Creates a revision that encapsulates the error encountered when fetching the revision.
        
        Threadsafe.
        """
        return ResourceRevision._create_from_stream(
            resource,
            request_cookie=request_cookie,
            error=error)
    
    @staticmethod
    def create_from_response(
            resource: Resource,
            metadata: Optional[ResourceRevisionMetadata],
            body_stream: io.BytesIO,
            request_cookie: Optional[str]=None
            ) -> ResourceRevision:
        """
        Creates a revision with the specified metadata and body.
        
        Threadsafe. The passed body stream will be read synchronously until EOF,
        so it is recommended that this method be invoked on a background thread.
        
        Arguments:
        * resource -- resource that this is a revision of.
        * metadata -- JSON-encodable dictionary of resource metadata.
        * body_stream -- file-like object containing the revision body.
        """
        try:
            self = ResourceRevision._create_from_stream(
                resource,
                request_cookie=request_cookie,
                metadata=metadata,
                body_stream=body_stream)
        except Exception as e:
            return ResourceRevision.create_from_error(resource, e, request_cookie)
        else:
            # TODO: I don't think the following code actually works,
            #       because the Date header it's trying to add won't actually
            #       be saved to the database...
            # 
            # If no HTTP Date header was returned by the origin server,
            # auto-populate it with the current datetime, as per RFC 7231
            date_str = self._get_first_value_of_http_header('date')
            if date_str is None:
                if self.metadata is not None:
                    self.metadata['headers'].append((
                        'Date',
                        http_date.format(datetime.datetime.now(datetime.timezone.utc))
                    ))
                    assert self.date is not None
            
            return self
    
    @staticmethod
    def _create_from_stream(
            resource: Resource,
            *, request_cookie: Optional[str]=None,
            error: Optional[Exception]=None,
            metadata: Optional[ResourceRevisionMetadata]=None,
            body_stream: Optional[io.BytesIO]=None
            ) -> ResourceRevision:
        self = ResourceRevision()
        self.resource = resource
        self.request_cookie = request_cookie
        self.error = error
        self.metadata = metadata
        # (self._id computed below)
        self.has_body = body_stream is not None
        
        project = self.project
        
        # Need to do this first to get the database ID
        def fg_task():
            RR = ResourceRevision
            
            if project.readonly:
                raise ProjectReadOnlyError()
            c = project._db.cursor()
            c.execute(
                'insert into resource_revision '
                    '(resource_id, request_cookie, error, metadata) values (?, ?, ?, ?)', 
                (resource._id, request_cookie, RR._encode_error(error), RR._encode_metadata(metadata)))
            project._db.commit()
            self._id = c.lastrowid
        fg_call_and_wait(fg_task)
        
        if body_stream:
            try:
                body_filepath = os.path.join(project.path, Project._RESOURCE_REVISION_DIRNAME, str(self._id))
                with open(body_filepath, 'wb') as body_file:
                    shutil.copyfileobj(body_stream, body_file)
            except Exception:
                # Rollback database commit
                def fg_task():
                    if project.readonly:
                        raise ProjectReadOnlyError()
                    c = project._db.cursor()
                    c.execute('delete from resource_revision where id=?', (self._id,))
                    project._db.commit()
                fg_call_and_wait(fg_task)
                raise
        
        if not project._loading:
            project._resource_revision_did_instantiate(self)
        
        return self
    
    @staticmethod
    def _create_from_revision_and_new_metadata(
            revision: ResourceRevision,
            metadata: ResourceRevisionMetadata
            ) -> ResourceRevision:
        self = ResourceRevision()
        self.resource = revision.resource
        self.request_cookie = revision.request_cookie
        self.error = revision.error
        self.metadata = metadata
        self._id = revision._id
        self.has_body = revision.has_body
        return self
    
    @staticmethod
    def load(
            resource: Resource,
            request_cookie: Optional[str],
            error: Optional[Exception],
            metadata: Optional[ResourceRevisionMetadata],
            id: int) -> ResourceRevision:
        self = ResourceRevision()
        self.resource = resource
        self.request_cookie = request_cookie
        self.error = error
        self.metadata = metadata
        self._id = id
        self.has_body = os.path.exists(self._body_filepath)
        return self
    
    @classmethod
    def _encode_error(cls, error):
        return json.dumps(cls._encode_error_dict(error))
    
    @staticmethod
    def _encode_error_dict(error):
        if error is None:
            error_dict = None
        elif isinstance(error, _PersistedError):
            error_dict = {
                'type': error.type,
                'message': error.message,
            }
        else:
            error_dict = {
                'type': type(error).__name__,
                'message': str(error),
            }
        return error_dict
    
    @staticmethod
    def _encode_metadata(metadata):
        return json.dumps(metadata)
    
    @staticmethod
    def _decode_error(db_error):
        error_dict = json.loads(db_error)
        if error_dict is None:
            return None
        else:
            return _PersistedError(error_dict['message'], error_dict['type'])
    
    @staticmethod
    def _decode_metadata(db_metadata):
        return json.loads(db_metadata)
    
    # === Properties ===
    
    @property
    def project(self):
        return self.resource.project
    
    @property
    def _url(self):
        return self.resource.url
    
    @property
    def error_dict(self):
        return self._encode_error_dict(self.error)
    
    def _ensure_has_body(self):
        if not self.has_body:
            raise ValueError('Resource "%s" has no body.' % self._url)
    
    @property
    def _body_filepath(self):
        return os.path.join(self.project.path, Project._RESOURCE_REVISION_DIRNAME, str(self._id))
    
    # === Metadata ===
    
    @property
    def is_http(self):
        """Returns whether this resource was fetched using HTTP."""
        # HTTP resources are presently the only ones with metadata
        return self.metadata is not None
    
    @property
    def status_code(self) -> Optional[int]:
        if self.metadata is None:
            return None
        else:
            return self.metadata['status_code']
    
    @property
    def is_redirect(self):
        """Returns whether this resource is a redirect."""
        return self.is_http and (self.metadata['status_code'] // 100) == 3
    
    def _get_first_value_of_http_header(self, name: str) -> Optional[str]:
        name = name.lower()  # reinterpret
        if self.metadata is None:
            return None
        for (cur_name, cur_value) in self.metadata['headers']:
            if name == cur_name.lower():
                return cur_value
        return None
    
    @property
    def redirect_url(self) -> Optional[str]:
        """
        Returns the resource to which this resource redirects,
        or None if it cannot be determined or this is not a redirect.
        """
        if self.is_redirect:
            return self._get_first_value_of_http_header('location')
        else:
            return None
    
    @property
    def _redirect_title(self) -> Optional[str]:
        if self.is_redirect:
            metadata = self.metadata  # cache
            if metadata is None:
                return None
            return '%s %s' % (metadata['status_code'], metadata['reason_phrase'])
        else:
            return None
    
    @property
    def declared_content_type_with_options(self) -> Optional[str]:  # ex: 'text/html; charset=utf-8'
        if self.is_http:
            return self._get_first_value_of_http_header('content-type')
        else:
            return None
    
    @property
    def declared_content_type(self) -> Optional[str]:  # ex: 'text/html'
        """Returns the MIME content type declared for this resource, or None if not declared."""
        content_type_with_options = self.declared_content_type_with_options
        if content_type_with_options is None:
            return None
        else:
            (content_type, content_type_options) = cgi.parse_header(content_type_with_options)
            return content_type
    
    @property
    def declared_charset(self) -> Optional[str]:  # ex: 'utf-8'
        """Returns the charset declared for this resource, or None if not declared."""
        content_type_with_options = self.declared_content_type_with_options
        if content_type_with_options is None:
            return None
        else:
            (content_type, content_type_options) = cgi.parse_header(content_type_with_options)
            return content_type_options.get('charset')
    
    @property
    def content_type(self) -> Optional[str]:  # ex: 'utf-8'
        """Returns the MIME content type declared or guessed for this resource, or None if unknown."""
        declared = self.declared_content_type
        if declared is not None:
            return declared
        (content_type, encoding) = mimetypes.guess_type(self._url)
        return content_type
    
    @property
    def is_html(self) -> bool:
        """Returns whether this resource is HTML."""
        return self.content_type == 'text/html'
    
    @property
    def is_css(self) -> bool:
        """Returns whether this resource is CSS."""
        return self.content_type == 'text/css'
    
    @property
    def is_json(self) -> bool:
        """Returns whether this resource is JSON."""
        return self.content_type == 'application/json'
    
    @property
    def is_xml(self) -> bool:
        """Returns whether this resource is XML."""
        return self.content_type == 'text/xml'
    
    @property
    def date(self) -> Optional[datetime.datetime]:
        """
        The datetime this revision was generated by the original origin server,
        or None if unknown.
        """
        date_str = self._get_first_value_of_http_header('date')
        if date_str is None:
            # No Date HTTP header
            return None
        try:
            date = http_date.parse(date_str)
        except ValueError:
            # Invalid Date HTTP header
            return None
        else:
            return date.replace(tzinfo=datetime.timezone.utc)
    
    @property
    def age(self) -> Optional[int]:
        """
        The time in seconds this revision was in a proxy cache,
        or None if unknown.
        """
        age_str = self._get_first_value_of_http_header('age')
        if age_str is None:
            # No Age HTTP header
            return None
        try:
            age = int(age_str)  # may raise ValueError
            if age < 0:
                raise ValueError()
            return age
        except ValueError:
            # Invalid Age HTTP header
            return None
    
    @property
    def date_plus_age(self) -> Optional[datetime.datetime]:
        """
        The datetime this revision was generated by the intermediate
        server it was fetched from, in server time, or None if unknown.
        
        Should approximately equal the datetime this revision was fetched.
        """
        date = self.date  # cache
        if date is None:
            # No Date HTTP header
            return None
        age = self.age  # cache
        if age is None:
            return date
        else:
            return date + datetime.timedelta(seconds=age)
    
    @property
    def etag(self) -> Optional[str]:
        return self._get_first_value_of_http_header('etag')
    
    # === Body ===
    
    def size(self):
        """
        Returns the size of this resource's body.
        """
        self._ensure_has_body()
        return os.path.size(self._body_filepath)
    
    def open(self):
        """
        Opens the body of this resource for reading, returning a file-like object.
        """
        self._ensure_has_body()
        return open(self._body_filepath, 'rb')
    
    def links(self):
        """
        Returns list of Links found in this resource.
        
        This method blocks while parsing the links.
        """
        return self.document_and_links()[1]
    
    def document_and_links(self) -> tuple[Optional[Document], list[Link], Optional[str]]:
        """
        Returns a 3-tuple containing:
        (1) if the resource is a document, the document, otherwise None;
        (2) a list of rewritable Links found in this resource.
        (3) a Content-Type value for the document, or None if unknown
        
        The HTML document can be reoutput by getting its str() representation.
        
        This method blocks while parsing the links.
        """
        from crystal.doc.css import parse_css_and_links
        from crystal.doc.generic import create_external_link
        from crystal.doc.html import parse_html_and_links
        from crystal.doc.json import parse_json_and_links
        from crystal.doc.xml import parse_xml_and_links
        
        # Extract links from HTML, if applicable
        (doc, links) = (None, [])
        content_type_with_options = None  # type: Optional[str]
        if self.is_html and self.has_body:
            with self.open() as body:
                doc_and_links = parse_html_and_links(body, self.declared_charset)
            if doc_and_links is not None:
                (doc, links) = doc_and_links
                content_type_with_options = 'text/html; charset=utf-8'
        elif self.is_css and self.has_body:
            with self.open() as body:
                body_bytes = body.read()
            (doc, links) = parse_css_and_links(body_bytes, self.declared_charset)
            content_type_with_options = 'text/css; charset=utf-8'
        elif self.is_json and self.has_body:
            with self.open() as body:
                doc_and_links = parse_json_and_links(body, self.declared_charset)
            if doc_and_links is not None:
                (doc, links) = doc_and_links
                content_type_with_options = 'application/json; charset=utf-8'
        elif self.is_xml and self.has_body:
            with self.open() as body:
                doc_and_links = parse_xml_and_links(body, self.declared_charset)
            if doc_and_links is not None:
                (doc, links) = doc_and_links
                content_type_with_options = 'text/xml; charset=utf-8'
        
        # Ignore links that should never be rewritten
        links = [link for link in links if not is_unrewritable_url(link.relative_url)]
        
        # Add pseudo-link for redirect, if applicable
        redirect_url = self.redirect_url
        if redirect_url is not None:
            links.append(create_external_link(redirect_url, self._redirect_title, 'Redirect', True))
        
        return (doc, links, content_type_with_options)
    
    # === Operations ===
    
    @property
    def is_http_304(self) -> bool:
        metadata = self.metadata  # cache
        return metadata is not None and metadata['status_code'] == 304
    
    def resolve_http_304(self) -> ResourceRevision:
        """
        If this revision is an HTTP 304 Not Modified which redirects to a
        valid known revision of the same resource, returns a new ResourceRevision
        representing the target revision plus various headers of the HTTP 304
        overlaid on top of it.
        
        Otherwise returns self (which could still be an HTTP 304).
        """
        if not self.is_http_304:
            return self
        
        target_etag = self._get_first_value_of_http_header('etag')
        if target_etag is None:
            # Target ETag missing
            return self  # is the original HTTP 304
        
        target_revision = self.resource.revision_for_etag().get(target_etag)
        if target_revision is None:
            # Target ETag did not correspond to known revision of resource
            return self  # is the original HTTP 304
        
        # Replace various headers in the target revision (from RFC 7232 §4.1)
        # with updated values for those headers from this HTTP 304 revision
        assert target_revision.metadata is not None
        new_metadata = copy.deepcopy(target_revision.metadata)
        for header_name in ['Cache-Control', 'Content-Location', 'Date', 'ETag', 'Expires', 'Vary']:
            header_value = self._get_first_value_of_http_header(header_name)
            if header_value is not None:
                # Set header_name = header_value in new_metadata, replacing any older value
                header_name_lower = header_name.lower()  # cache
                new_metadata['headers'] = [
                    (k, v)
                    for (k, v) in new_metadata['headers']
                    if k.lower() != header_name_lower
                ] + [(header_name, header_value)]
        
        return ResourceRevision._create_from_revision_and_new_metadata(target_revision, new_metadata)
    
    def delete(self):
        project = self.project
        
        body_filepath = self._body_filepath  # cache
        if os.path.exists(body_filepath):
            os.remove(body_filepath)
        
        if project.readonly:
            raise ProjectReadOnlyError()
        c = project._db.cursor()
        c.execute('delete from resource_revision where id=?', (self._id,))
        project._db.commit()
        self._id = None
    
    def __repr__(self):
        return "<ResourceRevision %s for '%s'>" % (self._id, self.resource.url)


class ResourceRevisionMetadata(TypedDict):
    http_version: int  # 10 for HTTP/1.0, 11 for HTTP/1.1
    status_code: int
    reason_phrase: str
    headers: list[tuple[str, str]]  # email.message.EmailMessage


class _PersistedError(Exception):
    """
    Wraps an exception loaded from persistent storage.
    """
    # TODO: Alter parameter order to be [type, message] instead,
    #       which prints out more nicely.
    def __init__(self, message, type):
        self.message = message
        self.type = type


ResourceGroupSource = Union['RootResource', 'ResourceGroup', None]


class ResourceGroup:
    """
    Groups resource whose url matches a particular pattern.
    Persisted and auto-saved.
    """
    
    def __init__(self, 
            project: Project, 
            name: str, 
            url_pattern: str, 
            _id: Optional[int]=None) -> None:
        """
        Arguments:
        * project -- associated `Project`.
        * name -- name of this group.
        * url_pattern -- url pattern matched by this group.
        """
        self.project = project
        self.name = name
        self.url_pattern = url_pattern
        self._url_pattern_re = ResourceGroup.create_re_for_url_pattern(url_pattern)
        self._source = None  # type: ResourceGroupSource
        self.listeners = []  # type: List[object]
        
        members = []
        for r in self.project.resources:
            if self.contains_url(r.url):
                members.append(r)
        self._members = members
        
        if project._loading:
            self._id = _id
        else:
            if project.readonly:
                raise ProjectReadOnlyError()
            c = project._db.cursor()
            c.execute('insert into resource_group (name, url_pattern) values (?, ?)', (name, url_pattern))
            project._db.commit()
            self._id = c.lastrowid
        project._resource_groups.append(self)
    
    def _init_source(self, source: ResourceGroupSource) -> None:
        self._source = source
    
    def delete(self) -> None:
        """
        Deletes this resource group.
        If it is referenced as a source, it will be replaced with None.
        """
        for rg in self.project.resource_groups:
            if rg.source == self:
                rg.source = None
        
        if self.project.readonly:
            raise ProjectReadOnlyError()
        c = self.project._db.cursor()
        c.execute('delete from resource_group where id=?', (self._id,))
        self.project._db.commit()
        self._id = None
        
        self.project._resource_groups.remove(self)
    
    def _get_source(self) -> ResourceGroupSource:
        """
        The "source" of this resource group.
        
        If the source of a resource group is set, the user asserts that downloading
        the source will reveal all of the members of this group. Thus a group's source
        acts as the source of its members.
        """
        return self._source
    def _set_source(self, value: ResourceGroupSource) -> None:
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
        c = self.project._db.cursor()
        c.execute('update resource_group set source_type=?, source_id=? where id=?', (source_type, source_id, self._id))
        self.project._db.commit()
        
        self._source = value
    source = cast(ResourceGroupSource, property(_get_source, _set_source))
    
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
        patstr = patstr.replace(r'$**$', r'.*')
        patstr = patstr.replace(r'$*$', r'[^/?=&]*')
        patstr = patstr.replace(r'$#$', r'[0-9]+')
        patstr = patstr.replace(r'$@$', r'[a-zA-Z]+')
        
        return re.compile(r'^' + patstr + r'$')
    
    def __contains__(self, resource: Resource) -> bool:
        return resource in self._members
    
    def contains_url(self, resource_url: str) -> bool:
        return self._url_pattern_re.match(resource_url) is not None
    
    @property
    def members(self) -> List[Resource]:
        return self._members
    
    # Called when a new Resource is created after the project has loaded
    def _resource_did_instantiate(self, resource: Resource) -> None:
        if self.contains_url(resource.url):
            self._members.append(resource)
            
            for lis in self.listeners:
                if hasattr(lis, 'group_did_add_member'):
                    lis.group_did_add_member(self, resource)  # type: ignore[attr-defined]
    
    def _resource_did_alter_url(self, 
            resource: Resource, old_url: str, new_url: str) -> None:
        if self.contains_url(old_url):
            self._members.remove(resource)
        if self.contains_url(new_url):
            self._members.append(resource)
    
    def _resource_did_delete(self, resource: Resource) -> None:
        if resource in self._members:
            self._members.remove(resource)
    
    def download(self, needs_result: bool=False) -> None:
        """
        Downloads this group asynchronously.
        
        A top-level Task will be created internally to display the progress.
        """
        if needs_result:
            raise ValueError('Download task for a group never has a result')
        task = self.create_download_task(needs_result=needs_result)
        self.project.add_task(task)
    
    def create_download_task(self, needs_result: bool=False) -> DownloadResourceGroupTask:
        """
        Creates a Task to download this resource group.
        
        The caller is responsible for adding the returned Task as the child of an
        appropriate parent task so that the UI displays it.
        """
        if needs_result:
            raise ValueError('Download task for a group never has a result')
        if self.source is None:
            raise ValueError('Cannot download a group that lacks a source.')
        
        from crystal.task import DownloadResourceGroupTask
        return DownloadResourceGroupTask(self)
    
    def update_membership(self):
        """
        Updates the membership of this group asynchronously.
        
        A top-level Task will be created internally to display the progress.
        """
        if self.source is None:
            raise ValueError('Cannot update members of a group that lacks a source.')
        
        from crystal.task import UpdateResourceGroupMembersTask
        task = UpdateResourceGroupMembersTask(self)
        self.project.add_task(task)

    def __repr__(self):
        return 'ResourceGroup(%s,%s)' % (repr(self.name), repr(self.url_pattern))


def _is_ascii(s: str) -> bool:
    assert isinstance(s, str)
    try:
        s.encode('ascii')
    except UnicodeEncodeError:
        return False
    else:
        return True
