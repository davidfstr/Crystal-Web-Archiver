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
    get_index_names,
    is_no_such_column_error_for,
)
from crystal.util.profile import warn_if_slow
from crystal.util.urls import is_unrewritable_url, requote_uri
from crystal.util.xbisect import bisect_key_right
from crystal.util.xdatetime import datetime_is_aware
from crystal.util.xfutures import Future
from crystal.util.xgc import gc_disabled
from crystal.util import xshutil
from crystal.util.xsqlite3 import sqlite_has_json_support
from crystal.util.xthreading import bg_call_later, fg_call_and_wait, fg_call_later
import cgi
import datetime
import json
import math
import mimetypes
import os
import re
import shutil
from sortedcontainers import SortedList
import sqlite3
import sys
from tempfile import NamedTemporaryFile
import threading
import time
from typing import (
    Any, BinaryIO, Callable, cast, Dict, Iterable, List, Literal, Optional, Pattern,
    TYPE_CHECKING, Tuple, TypedDict, Union
)
from urllib.parse import urlparse, urlunparse

if TYPE_CHECKING:
    from crystal.doc.generic import Document, Link
    from crystal.doc.html import HtmlParserType
    from crystal.server import ProjectServer
    from crystal.task import (
        DownloadResourceTask, DownloadResourceBodyTask,
        DownloadResourceGroupTask, Task,
    )


class Project:
    """
    Groups together a set of resources that are downloaded and any associated settings.
    Persisted and auto-saved.
    """
    
    FILE_EXTENSION = '.crystalproj'
    
    # Project structure constants
    _DB_FILENAME = 'database.sqlite'
    _RESOURCE_REVISION_DIRNAME = 'revisions'
    _TEMPORARY_DIRNAME = 'tmp'
    
    # NOTE: Only tracked when tests are running
    _last_opened_project: Optional[Project]=None  # static
    
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
        
        Raises:
        * FileNotFoundError --
            if readonly is True and no project already exists at the specified path.
        * CancelOpenProject
        """
        if progress_listener is None:
            progress_listener = DummyOpenProjectProgressListener()
        
        # Remove any trailing slash from the path
        (head, tail) = os.path.split(path)
        if len(tail) == 0:
            path = head  # reinterpret
        
        self.path = path
        self.listeners = []  # type: List[object]
        
        self._properties = dict()               # type: Dict[str, str]
        self._resources = OrderedDict()         # type: Dict[str, Resource]
        self._sorted_resource_urls = SortedList()  # type: SortedList[str]
        self._root_resources = OrderedDict()    # type: Dict[Resource, RootResource]
        self._resource_groups = []              # type: List[ResourceGroup]
        self._readonly = True  # will reinitialize after database is located
        
        self._min_fetch_date = None  # type: Optional[datetime.datetime]
        
        progress_listener.opening_project(os.path.basename(path))
        
        self._loading = True
        try:
            create = not os.path.exists(path)
            if create and readonly:
                # Can't create a project if cannot write to disk
                raise FileNotFoundError(f'Cannot create new project at {path!r} when readonly=True')
            
            # Create/verify project structure
            if create:
                # Create new project structure, minus database file
                os.mkdir(path)
                os.mkdir(os.path.join(path, self._RESOURCE_REVISION_DIRNAME))
                os.mkdir(os.path.join(path, self._TEMPORARY_DIRNAME))
            else:
                # Ensure existing project structure looks OK
                Project._ensure_valid(path)
            
            # Open database
            db_filepath = os.path.join(path, self._DB_FILENAME)  # cache
            can_write_db = (
                # Can write to *.crystalproj
                # (is not Locked on macOS, is not on read-only volume)
                os.access(path, os.W_OK) and (
                    not os.path.exists(db_filepath) or
                    # Can write to database
                    # (is not Locked on macOS, is not Read Only on Windows, is not on read-only volume)
                    os.access(db_filepath, os.W_OK)
                )
            )
            db_connect_query = (
                '?immutable=1'
                if not can_write_db
                else (
                    '?mode=ro'
                    if readonly
                    else ''
                )
            )
            db = sqlite3.connect('file:' + db_filepath + db_connect_query, uri=True)
            
            self._readonly = readonly or not can_write_db
            self._db = DatabaseConnection(db, lambda: self.readonly)
            
            c = self._db.cursor()
            
            # Create new project content, if missing
            if create:
                c.execute('create table project_property (name text unique not null, value text)')
                c.execute('create table resource (id integer primary key, url text unique not null)')
                c.execute('create table root_resource (id integer primary key, name text not null, resource_id integer unique not null, foreign key (resource_id) references resource(id))')
                c.execute('create table resource_group (id integer primary key, name text not null, url_pattern text not null, source_type text, source_id integer)')
                c.execute('create table resource_revision (id integer primary key, resource_id integer not null, request_cookie text, error text not null, metadata text not null)')
                c.execute('create index resource_revision__resource_id on resource_revision (resource_id)')
                
                # Default HTML parser for new projects, for Crystal >1.5.0
                self.html_parser_type = 'lxml'
            
            # Load from existing project
            if True:
                # Prefer Write Ahead Log (WAL) mode for higher performance
                if not self.readonly:
                    [(new_journal_mode,)] = c.execute('pragma journal_mode = wal')
                    if new_journal_mode != 'wal':
                        print(
                            '*** Unable to open database in WAL mode. '
                                'Downloads may be slower.',
                            file=sys.stderr)
                
                # Upgrade database schema to latest version (unless is readonly)
                if not self.readonly:
                    self._apply_migrations(c, progress_listener)
                
                # Cleanup any temporary files from last session (unless is readonly)
                if not self.readonly:
                    tmp_dirpath = os.path.join(self.path, self._TEMPORARY_DIRNAME)
                    assert os.path.exists(tmp_dirpath)
                    for tmp_filename in os.listdir(tmp_dirpath):
                        tmp_filepath = os.path.join(tmp_dirpath, tmp_filename)
                        if os.path.isfile(tmp_filepath):
                            os.remove(tmp_filepath)
                
                # Load project properties
                for (name, value) in c.execute('select name, value from project_property'):
                    self._set_property(name, value)
                
                # Load Resources
                # 
                # NOTE: The following query to approximate row count is
                #       significantly faster than the exact query
                #       ('select count(1) from resource') because it
                #       does not require a full table scan.
                resources = []
                if True:
                    rows = list(c.execute('select id from resource order by id desc limit 1'))
                    if len(rows) == 1:
                        [(approx_resource_count,)] = rows
                    else:
                        assert len(rows) == 0
                        approx_resource_count = 0
                    progress_listener.will_load_resources(approx_resource_count)
                    
                    batch_size = max(500, approx_resource_count // 100)
                    next_index_to_report = 0
                    time_of_last_report = time.time()
                    TARGET_MAX_DELAY_BETWEEN_REPORTS = 1.0
                    SPEEDUP_FACTOR_WHEN_REPORTING_TOO_SLOWLY = 0.8  # <1.0, >=0.0, smaller is faster
                    resource_count = 0
                    with gc_disabled():  # don't garbage collect while allocating many objects
                        for (index, (url, id)) in enumerate(c.execute('select url, id from resource')):
                            if index == next_index_to_report:
                                time_of_cur_report = time.time()  # capture
                                progress_listener.loading_resource(index)
                                
                                if (time_of_cur_report - time_of_last_report) > TARGET_MAX_DELAY_BETWEEN_REPORTS:
                                    batch_size = max(int(batch_size * SPEEDUP_FACTOR_WHEN_REPORTING_TOO_SLOWLY), 1)
                                time_of_last_report = time_of_cur_report
                                
                                next_index_to_report += batch_size
                            # Create Resource
                            resources.append(Resource(self, url, _id=id))
                            resource_count += 1
                    if resource_count != 0:
                        progress_listener.loading_resource(resource_count - 1)
                    
                    progress_listener.did_load_resources(resource_count)
                
                # Index Resources (to load RootResources and ResourceGroups faster)
                progress_listener.indexing_resources()
                self._resources = {r.url: r for r in resources}
                self._sorted_resource_urls.update(self._resources.keys())
                resource_for_id = {r._id: r for r in resources}
                del resources  # garbage collect early
                
                # Load RootResources
                [(root_resource_count,)] = c.execute('select count(1) from root_resource')
                progress_listener.loading_root_resources(root_resource_count)
                for (name, resource_id, id) in c.execute('select name, resource_id, id from root_resource'):
                    resource = resource_for_id[resource_id]
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
        finally:
            self._loading = False
        
        # Hold on to the root task and scheduler
        import crystal.task
        self.root_task = crystal.task.RootTask()
        crystal.task.start_schedule_forever(self.root_task)
        
        # Define initial configuration
        self._request_cookie = None  # type: Optional[str]
        
        # Export reference to self, if running tests
        if os.environ.get('CRYSTAL_RUNNING_TESTS', 'False') == 'True':
            Project._last_opened_project = self
    
    @staticmethod
    def is_valid(path: str) -> bool:
        try:
            Project._ensure_valid(path)
        except ProjectFormatError:
            return False
        else:
            return True
    
    @staticmethod
    def _ensure_valid(path: str) -> None:
        """
        Raises:
        * ProjectFormatError -- if the project at the specified path is invalid
        """
        if not os.path.isdir(path):
            raise ProjectFormatError(f'Project is missing outermost directory: {path}')
        
        db_filepath = os.path.join(path, Project._DB_FILENAME)
        if not os.path.isfile(db_filepath):
            raise ProjectFormatError(f'Project is missing database: {db_filepath}')
        
        revision_dirpath = os.path.join(path, Project._RESOURCE_REVISION_DIRNAME)
        if not os.path.isdir(revision_dirpath):
            raise ProjectFormatError(f'Project is missing revisions directory: {revision_dirpath}')
    
    def _apply_migrations(self,
            c: DatabaseCursor,
            progress_listener: OpenProjectProgressListener) -> None:
        """
        Upgrades this project's database schema to the latest version.
        
        Raises:
        * ProjectReadOnlyError
        """
        index_names = get_index_names(c)  # cache
        
        # Add resource_revision.request_cookie column if missing
        if 'request_cookie' not in get_column_names_of_table(c, 'resource_revision'):
            progress_listener.upgrading_project('Adding cookies to revisions...')
            c.execute('alter table resource_revision add column request_cookie text')
        
        # Add resource_revision__error_not_null index if missing
        if 'resource_revision__error_not_null' not in index_names:
            progress_listener.upgrading_project('Indexing revisions with errors...')
            c.execute(
                'create index resource_revision__error_not_null on resource_revision '
                '(id, resource_id) '
                'where error != "null"')
        
        # Add resource_revision__request_cookie_not_null index if missing
        if 'resource_revision__request_cookie_not_null' not in index_names:
            progress_listener.upgrading_project('Indexing revisions with cookies...')
            c.execute(
                'create index resource_revision__request_cookie_not_null on resource_revision '
                '(id, request_cookie) '
                'where request_cookie is not null')
        
        # Add resource_revision__status_code index if missing
        if 'resource_revision__status_code' not in index_names and sqlite_has_json_support():
            progress_listener.upgrading_project('Indexing revisions by status code...')
            c.execute(
                'create index resource_revision__status_code on resource_revision '
                '(json_extract(metadata, "$.status_code"), resource_id) '
                'where json_extract(metadata, "$.status_code") != 200')
        
        # Add temporary directory if missing
        tmp_dirpath = os.path.join(self.path, self._TEMPORARY_DIRNAME)
        if not os.path.exists(tmp_dirpath):
            os.mkdir(tmp_dirpath)
    
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
            if self._properties.get(name) == value:
                return
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
    
    def _get_html_parser_type(self) -> 'HtmlParserType':
        value = self._get_property(
            'html_parser_type',
            # Default HTML parser for classic projects from Crystal <=1.5.0
            'html_parser')
        from crystal.doc.html import HTML_PARSER_TYPE_CHOICES
        if value not in HTML_PARSER_TYPE_CHOICES:
            raise ValueError(f'Project requests HTML parser of unknown type: {value}')
        return cast('HtmlParserType', value)
    def _set_html_parser_type(self, value: 'HtmlParserType') -> None:
        from crystal.doc.html import HTML_PARSER_TYPE_CHOICES
        if value not in HTML_PARSER_TYPE_CHOICES:
            raise ValueError(f'Unknown type of HTML parser: {value}')
        self._set_property('html_parser_type', value)
    html_parser_type = property(_get_html_parser_type, _set_html_parser_type, doc=
        """
        The type of parser used for parsing links from HTML documents.
        """)
    
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
            from crystal.task import ASSUME_RESOURCES_DOWNLOADED_IN_SESSION_WILL_ALWAYS_REMAIN_FRESH
            if ASSUME_RESOURCES_DOWNLOADED_IN_SESSION_WILL_ALWAYS_REMAIN_FRESH:
                for r in self.resources:
                    r.already_downloaded_this_session = False
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
        """Returns all Resources in the project in the order they were created."""
        return self._resources.values()
    
    def get_resource(self, url: str) -> Optional[Resource]:
        """Returns the `Resource` with the specified URL or None if no such resource exists."""
        return self._resources.get(url, None)
    
    def resources_matching_pattern(self,
            url_pattern_re: re.Pattern,
            literal_prefix: str,
            ) -> List[Resource]:
        """
        Returns all Resources in the project whose URL matches the specified
        regular expression and literal prefix, in the order they were created.
        """
        sorted_resource_urls = self._sorted_resource_urls  # cache
        resource_for_url = self._resources  # cache
        
        # NOTE: The following calculation is equivalent to
        #           members = [r for r in self.resources if url_pattern_re.fullmatch(r.url) is not None]
        #       but runs faster on average,
        #       in O(log(r) + s + g*log(g)) time rather than O(r) time, where
        #           r = (# of Resources in Project),
        #           s = (# of Resources in Project matching the literal prefix), and
        #           g = (# of Resources in the resulting group).
        members = []
        start_index = sorted_resource_urls.bisect_left(literal_prefix)
        for cur_url in sorted_resource_urls.islice(start=start_index):
            if not cur_url.startswith(literal_prefix):
                break
            if url_pattern_re.fullmatch(cur_url):
                r = resource_for_url[cur_url]
                members.append(r)
        members.sort(key=lambda r: r._id)
        return members
    
    def urls_matching_pattern(self,
            url_pattern_re: re.Pattern,
            literal_prefix: str,
            limit: Optional[int]=None,
            ) -> Tuple[List[str], int]:
        """
        Returns all resource URLs in the project which match the specified
        regular expression and literal prefix, ordered by URL value.
        
        If limit is not None than at most `limit` URLs will be returned.
        
        Also returns the number of matching URLs if limit is None,
        or an upper bound on the number of matching URLs if limit is not None.
        """
        sorted_resource_urls = self._sorted_resource_urls  # cache
        
        # NOTE: When limit is None, the following calculation is equivalent to
        #           members = sorted([r.url for r in self.resources if url_pattern_re.fullmatch(r.url) is not None])
        #       but runs faster on average,
        #       in O(log(r) + s) time rather than O(r) time, where
        #           r = (# of Resources in Project) and
        #           s = (# of Resources in Project matching the literal prefix).
        member_urls = []
        start_index = sorted_resource_urls.bisect_left(literal_prefix)
        for cur_url in sorted_resource_urls.islice(start=start_index):
            if not cur_url.startswith(literal_prefix):
                break
            if url_pattern_re.fullmatch(cur_url):
                member_urls.append(cur_url)
                if limit is not None and len(member_urls) == limit:
                    break
        if limit is None:
            return (member_urls, len(member_urls))
        else:
            end_index = bisect_key_right(
                sorted_resource_urls,  # type: ignore[misc]
                literal_prefix,
                order_preserving_key=lambda url: url[:len(literal_prefix)])  # type: ignore[index]
            
            approx_member_count = end_index - start_index + 1
            return (member_urls, approx_member_count)
    
    @property
    def root_resources(self) -> Iterable[RootResource]:
        """Returns all RootResources in the project in the order they were created."""
        return self._root_resources.values()
    
    def get_root_resource(self, resource: Resource) -> Optional[RootResource]:
        """Returns the `RootResource` with the specified `Resource` or None if none exists."""
        return self._root_resources.get(resource, None)
    
    def _get_root_resource_with_id(self, root_resource_id):
        """Returns the `RootResource` with the specified ID or None if no such root resource exists."""
        # PERF: O(n) when it could be O(1), where n = # of RootResources
        return next((rr for rr in self._root_resources.values() if rr._id == root_resource_id), None)
    
    def _get_root_resource_with_name(self, name):
        """Returns the `RootResource` with the specified name or None if no such root resource exists."""
        # PERF: O(n) when it could be O(1), where n = # of RootResources
        return next((rr for rr in self._root_resources.values() if rr.name == name), None)
    
    @property
    def resource_groups(self) -> Iterable[ResourceGroup]:
        """Returns all ResourceGroups in the project in the order they were created."""
        return self._resource_groups
    
    def get_resource_group(self, name: str) -> Optional[ResourceGroup]:
        """Returns the `ResourceGroup` with the specified name or None if no such resource exists."""
        # PERF: O(n) when it could be O(1), where n = # of ResourceGroups
        return next((rg for rg in self._resource_groups if rg.name == name), None)
    
    def _get_resource_group_with_id(self, resource_group_id):
        """Returns the `ResourceGroup` with the specified ID or None if no such resource exists."""
        # PERF: O(n) when it could be O(1), where n = # of ResourceGroups
        return next((rg for rg in self._resource_groups if rg._id == resource_group_id), None)
    
    # === Tasks ===
    
    def add_task(self, task: Task) -> None:
        """
        Schedules the specified top-level task for execution, if not already done.
        
        The specified task is allowed to already be complete.
        
        Raises:
        * ProjectClosedError -- if this project is closed
        """
        if task not in self.root_task.children:
            self.root_task.append_child(task, already_complete_ok=True)
            if task.complete:
                self.root_task.child_task_did_complete(task)
    
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
        
        self._sorted_resource_urls.remove(old_url)
        self._sorted_resource_urls.add(new_url)
        
        # Notify resource groups (which are like hardwired listeners)
        for rg in self.resource_groups:
            rg._resource_did_alter_url(resource, old_url, new_url)
    
    def _resource_did_delete(self, resource: Resource) -> None:
        del self._resources[resource.url]
        self._sorted_resource_urls.remove(resource.url)
        
        # Notify resource groups (which are like hardwired listeners)
        for rg in self.resource_groups:
            rg._resource_did_delete(resource)
    
    # Called when a new RootResource is created after the project has loaded
    def _root_resource_did_instantiate(self, root_resource: RootResource) -> None:
        # Notify normal listeners
        for lis in self.listeners:
            if hasattr(lis, 'root_resource_did_instantiate'):
                lis.root_resource_did_instantiate(root_resource)  # type: ignore[attr-defined]
    
    # Called when a new ResourceGroup is created after the project has loaded
    def _resource_group_did_instantiate(self, group: ResourceGroup) -> None:
        # Notify normal listeners
        for lis in self.listeners:
            if hasattr(lis, 'resource_group_did_instantiate'):
                lis.resource_group_did_instantiate(group)  # type: ignore[attr-defined]
    
    # === Close ===
    
    def close(self) -> None:
        self.root_task.close()
        
        # Disable Write Ahead Log (WAL) mode when closing database
        # in case the user decides to burn the project to read-only media,
        # as recommended by: https://www.sqlite.org/wal.html#readonly
        if not self.readonly:
            try:
                c = self._db.cursor()
                [(old_journal_mode,)] = c.execute('pragma journal_mode')
                if old_journal_mode == 'wal':
                    [(new_journal_mode,)] = c.execute('pragma journal_mode = delete')
                    if new_journal_mode != 'delete':
                        print(
                            '*** Unable to close database with WAL mode turned off. '
                                'Project may be slower to read if burned to read-only media.',
                            file=sys.stderr)
            except sqlite3.Error:
                # Ignore errors while closing database
                pass
        
        self._db.close()
        
        # Unexport reference to self, if running tests
        if os.environ.get('CRYSTAL_RUNNING_TESTS', 'False') == 'True':
            if Project._last_opened_project is self:
                Project._last_opened_project = None
    
    # === Context Manager ===
    
    def __enter__(self) -> Project:
        return self
    
    def __exit__(self, exc_type, exc_value, exc_traceback) -> None:
        self.close()


class CrossProjectReferenceError(Exception):
    pass


class ProjectFormatError(Exception):
    """The on-disk format of a Project is corrupted in some way."""
    pass


class ProjectReadOnlyError(Exception):
    pass


class ProjectClosedError(Exception):
    pass


class _WeakTaskRef:
    """
    Holds a reference to a Task until that task completes.
    """
    # Optimize per-instance memory use, since there may be very many
    # _WeakTaskRef objects, because there may be very many Resource objects
    # which each contain _WeakTaskRef instances
    __slots__ = ('_task',)
    
    def __init__(self, task: Optional[Task]=None) -> None:
        self._task = None
        self.task = task
    
    def _get_task(self) -> Optional[Task]:
        return self._task
    def _set_task(self, value: Optional[Task]) -> None:
        if self._task:
            self._task.listeners.remove(self)
        self._task = value
        if self._task:
            self._task.listeners.append(self)
    task = property(_get_task, _set_task)
    
    def task_did_complete(self, task: Task) -> None:
        self.task = None
    
    def __repr__(self) -> str:
        return f'_WeakTaskRef({self._task!r})'


class Resource:
    """
    Represents an entity, potentially downloadable.
    Either created manually or discovered through a link from another resource.
    Persisted and auto-saved.
    """
    _DEFER_ID = sys.intern('__defer__')  # type: Literal['__defer__']  # type: ignore[assignment]
    
    # Optimize per-instance memory use, since there may be very many Resource objects
    __slots__ = (
        'project',
        '_url',
        '_download_body_task_ref',
        '_download_task_ref',
        '_download_task_noresult_ref',
        '_already_downloaded_this_session',
        '_definitely_has_no_revisions',
        '_id',
    )
    
    project: Project
    _url: str
    _download_body_task_ref: Optional[_WeakTaskRef]
    _download_task_ref: Optional[_WeakTaskRef]
    _download_task_noresult_ref: Optional[_WeakTaskRef]
    _already_downloaded_this_session: bool
    _definitely_has_no_revisions: bool
    _id: int  # or None if not finished initializing or deleted
    
    # === Init (One) ===
    
    def __new__(cls, 
            project: Project,
            url: str,
            _id: 'Union[None, int, Literal["__defer__"]]'=None,
            ) -> Resource:
        """
        Looks up an existing resource with the specified URL or creates a new
        one if no preexisting resource matches.
        
        Note that returned Resource will have a *normalized* URL which may
        differ from the exact URL specified in this constructor.
        
        Arguments:
        * project -- associated `Project`.
        * url -- absolute URL to this resource (ex: http), or a URI (ex: mailto).
        """
        
        if _id is None or _id is Resource._DEFER_ID:
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
        self._download_body_task_ref = None
        self._download_task_ref = None
        self._download_task_noresult_ref = None
        self._already_downloaded_this_session = False
        self._definitely_has_no_revisions = False
        
        if _id is None:
            if project.readonly:
                raise ProjectReadOnlyError()
            c = project._db.cursor()
            c.execute('insert into resource (url) values (?)', (normalized_url,))
            project._db.commit()
            assert c.lastrowid is not None
            _id = c.lastrowid
            
            # Can't have revisions because it was just created this session
            self._definitely_has_no_revisions = True
        
        if _id is Resource._DEFER_ID:
            self._id = None  # type: ignore[assignment]  # intentionally leave exploding None
        else:
            assert isinstance(_id, int)
            self._finish_init(_id)  # sets self._id
        
        return self
    
    @property
    def _is_finished_initializing(self) -> bool:
        return self._id is not None
    
    def _finish_init(self, id: int) -> None:
        """
        Finishes initializing a Resource that was created with
        Resource(..., _id=Resource._DEFER_ID).
        """
        self._id = id
        
        project = self.project  # cache
        normalized_url = self._url  # cache
        
        # Record self in Project
        if not project._loading:
            project._resources[normalized_url] = self
            project._sorted_resource_urls.add(normalized_url)
        else:
            # (Caller is responsible for updating Project._resources)
            # (Caller is responsible for updating Project._sorted_resource_urls)
            pass
        
        # Notify listeners that self did instantiate
        if not project._loading:
            project._resource_did_instantiate(self)
    
    # === Init (Many) ===
    
    @staticmethod
    def bulk_create(
            project: Project,
            urls: List[str],
            origin_url: str,
            ) -> List[Resource]:
        """
        Creates several Resources for the specified list of URLs, in bulk.
        Returns the set of Resources created.
        
        Arguments:
        * project -- associated `Project`.
        * urls -- absolute URLs.
        * origin_url -- origin URL from which `urls` were obtained. Used for debugging.
        """
        from crystal.task import PROFILE_RECORD_LINKS
        
        # 1. Create Resources in memory initially, deferring any database INSERTs
        # 2. Identify new resources that need to be inserted in the database
        resource_for_new_url = OrderedDict()
        for url in urls:
            # Get/create Resource in memory and normalize its URL
            new_r = Resource(project, url, _id=Resource._DEFER_ID)
            if new_r._is_finished_initializing:
                # Resource with normalized URL already existed in memory
                pass
            else:
                # Resource with normalized URL needs to be created in database
                if new_r.url in resource_for_new_url:
                    # Resource with normalized URL is already scheduled to be created in database
                    pass
                else:
                    # Schedule resource with normalized URL to be created in database
                    resource_for_new_url[new_r.url] = new_r
        
        # If no resources need to be created in database, abort early
        if len(resource_for_new_url) == 0:
            return []
        
        # Create many Resource rows in database with a single bulk INSERT,
        # to optimize performance, retrieving the IDs of the inserted rows
        message = lambda: f'{len(resource_for_new_url)} links from {origin_url}'
        with warn_if_slow('Inserting links', max_duration=1.0, message=message, enabled=PROFILE_RECORD_LINKS):
            c = project._db.cursor()
            placeholders = ','.join(['(?)'] * len(resource_for_new_url))
            ids = list(c.execute(
                f'insert into resource (url) values {placeholders} returning id',
                list(resource_for_new_url.keys()))
            )  # type: List[Tuple[int]]
        with warn_if_slow('Committing links', max_duration=1.0, message=message, enabled=PROFILE_RECORD_LINKS):
            project._db.commit()  # end transaction
        
        # Populate the ID of each Resource in memory with each inserted row's ID,
        # and finish initializing each Resource (by recording it
        # in the Project and notifying listeners of instantiation)
        for (new_r, (id,)) in zip(resource_for_new_url.values(), ids):
            new_r._finish_init(id)
        
        # Return the set of Resources that were created,
        # which may be shorter than the list of URLs to create that were provided
        return list(resource_for_new_url.values())
    
    # === Properties ===
    
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
    
    def _get_already_downloaded_this_session(self) -> bool:
        return self._already_downloaded_this_session
    def _set_already_downloaded_this_session(self, value: bool) -> None:
        if self._already_downloaded_this_session == value:
            return
        if not value:
            # Invalidate any prior downloaded state
            self._download_body_task_ref = None
            self._download_task_ref = None
            self._download_task_noresult_ref = None
        self._already_downloaded_this_session = value
    already_downloaded_this_session = property(
        _get_already_downloaded_this_session,
        _set_already_downloaded_this_session)
    
    @property
    def definitely_has_no_revisions(self) -> bool:
        """
        Returns whether this Resource is known to have no ResourceRevisions.
        Even if this property is False it is still possible that this
        Resource has no ResourceRevisions.
        
        This property can be accessed from any thread (and not just the 
        foreground thread).
        
        Callers can use this property to avoid making unnecessary database
        queries for ResourceRevisions that definitely don't exist.
        """
        return self._definitely_has_no_revisions
    
    # === Download ===
    
    def download_body(self) -> 'Future[ResourceRevision]':
        """
        Returns a Future[ResourceRevision] that downloads (if necessary) and returns an
        up-to-date version of this resource's body.
        
        The returned Future may invoke its callbacks on any thread.
        
        A top-level Task will be created internally to display the progress.
        
        Future Raises:
        * CannotDownloadWhenProjectReadOnlyError --
            If resource is not already downloaded and project is read-only.
        * ProjectFreeSpaceTooLowError --
            If the project does not have enough free disk space to safely
            download more resources.
        * ProjectClosedError --
            If the project is closed.
        """
        task = self.create_download_body_task()
        if not task.complete:
            self.project.add_task(task)
        return task.future
    
    def create_download_body_task(self) -> 'DownloadResourceBodyTask':
        """
        Creates a Task to download this resource's body.
        
        The caller is responsible for adding the returned Task as the child of an
        appropriate parent task so that the UI displays it.
        
        This task is never complete immediately after initialization.
        """
        def task_factory() -> 'DownloadResourceBodyTask':
            from crystal.task import DownloadResourceBodyTask
            return DownloadResourceBodyTask(self)
        if self._download_body_task_ref is None:
            self._download_body_task_ref = _WeakTaskRef()
        return self._get_task_or_create(self._download_body_task_ref, task_factory)
    
    def download(self, *, wait_for_embedded: bool=False, needs_result: bool=True, is_embedded: bool=False) -> 'Future[ResourceRevision]':
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
        * ProjectFreeSpaceTooLowError --
            If the project does not have enough free disk space to safely
            download more resources.
        * ProjectClosedError --
            If the project is closed.
        """
        task = self.create_download_task(needs_result=needs_result, is_embedded=is_embedded)
        if not task.complete:
            self.project.add_task(task)
        return task.get_future(wait_for_embedded)
    
    def create_download_task(self, *, needs_result: bool=True, is_embedded: bool=False) -> 'DownloadResourceTask':
        """
        Creates a Task to download this resource and all its embedded resources.
        
        The caller is responsible for adding the returned Task as the child of an
        appropriate parent task so that the UI displays it.
        
        This task may be complete immediately after initialization.
        """
        def task_factory() -> 'DownloadResourceTask':
            from crystal.task import DownloadResourceTask
            return DownloadResourceTask(self, needs_result=needs_result, is_embedded=is_embedded)
        if needs_result:
            if self._download_task_ref is None:
                self._download_task_ref = _WeakTaskRef()
            task_ref = self._download_task_ref
        else:
            if self._download_task_noresult_ref is None:
                self._download_task_noresult_ref = _WeakTaskRef()
            task_ref = self._download_task_noresult_ref
        return self._get_task_or_create(
            task_ref,
            task_factory
        )
    
    def _get_task_or_create(self, task_ref: _WeakTaskRef, task_factory):
        if task_ref.task is not None:
            return task_ref.task
        
        task = task_factory()
        task_ref.task = task
        return task
    
    # === Revisions ===
    
    def has_any_revisions(self) -> bool:
        """
        Returns whether any revisions of this resource have been downloaded.
        """
        if self._definitely_has_no_revisions:
            return False
        
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
        if self._definitely_has_no_revisions:
            return None
        
        project = self.project  # cache
        
        reversed_revisions = self.revisions(
            reversed=True  # prioritize most recently downloaded
        )
        for revision in reversed_revisions:
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
    
    def revisions(self, *, reversed: bool=False) -> Iterable[ResourceRevision]:
        """
        Loads and returns a list of `ResourceRevision`s downloaded for this resource.
        If no such revisions exist, an empty list is returned.
        
        Revisions will be returned in the order they were downloaded,
        from least-recent to most-recent.
        """
        if self._definitely_has_no_revisions:
            return []
        
        RR = ResourceRevision
        
        ordering = 'asc' if not reversed else 'desc'
        
        c = self.project._db.cursor()
        try:
            rows = c.execute(
                f'select request_cookie, error, metadata, id '
                    f'from resource_revision where resource_id=? order by id {ordering}',
                (self._id,)
            )  # type: Iterable[Tuple[Any, Any, Any, Any]]
        except Exception as e:
            if is_no_such_column_error_for('request_cookie', e):
                # Fetch from <=1.2.0 database schema
                old_rows = c.execute(
                    f'select error, metadata, id '
                        f'from resource_revision where resource_id=? order by id {ordering}',
                    (self._id,)
                )  # type: Iterable[Tuple[Any, Any, Any]]
                rows = ((None, c0, c1, c2) for (c0, c1, c2) in old_rows)
            else:
                raise
        any_rows = False
        for (request_cookie, error, metadata, id) in rows:
            any_rows = True
            yield ResourceRevision._load_from_data(
                resource=self,
                request_cookie=request_cookie,
                error=RR._decode_error(error),
                metadata=RR._decode_metadata(metadata),
                id=id)
        
        if not any_rows:
            self._definitely_has_no_revisions = True
    
    def revision_for_etag(self) -> Dict[str, ResourceRevision]:
        """
        Returns a map of each known ETag to a matching ResourceRevision that is NOT an HTTP 304.
        """
        if self._definitely_has_no_revisions:
            return {}
        
        revision_for_etag = {}
        for revision in list(self.revisions()):
            if revision.is_http_304:
                continue
            etag = revision.etag
            if etag is not None:
                revision_for_etag[etag] = revision
        return revision_for_etag
    
    # === Operations (Advanced) ===
    
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
        
        if project.readonly:
            raise ProjectReadOnlyError()
        
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
        for rev in list(self.revisions()):
            rev.delete()
        
        # Delete Resource itself
        c = project._db.cursor()
        c.execute('delete from resource where id=?', (self._id,))
        project._db.commit()
        self._id = None  # type: ignore[assignment]  # intentionally leave exploding None
        
        project._resource_did_delete(self)
    
    # === Utility ===
    
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
    _id: int  # or None if deleted
    
    def __new__(cls, project: Project, name: str, resource: Resource, _id: Optional[int]=None) -> RootResource:
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
                assert _id is not None
                self._id = _id
            else:
                if project.readonly:
                    raise ProjectReadOnlyError()
                c = project._db.cursor()
                c.execute('insert into root_resource (name, resource_id) values (?, ?)', (name, resource._id))
                project._db.commit()
                self._id = c.lastrowid
            project._root_resources[resource] = self
            
            if not project._loading:
                project._root_resource_did_instantiate(self)
            
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
        self._id = None  # type: ignore[assignment]  # intentionally leave exploding None
        
        del self.project._root_resources[self.resource]
    
    @property
    def url(self) -> str:
        return self.resource.url
    
    # TODO: Create the underlying task with the full RootResource
    #       so that the correct subtitle is displayed.
    def download(self, *, needs_result: bool=True) -> Future[ResourceRevision]:
        return self.resource.download(needs_result=needs_result)
    
    def create_download_task(self, *, needs_result: bool=True) -> Task:
        """
        Creates a task to download this root resource.
        
        This task may be complete immediately after initialization.
        """
        # TODO: Create the underlying task with the full RootResource
        #       so that the correct subtitle is displayed.
        return self.resource.create_download_task(needs_result=needs_result, is_embedded=False)
    
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
    _id: int  # or None if deleted
    has_body: bool
    
    # === Init ===
    
    @staticmethod
    def create_from_error(
            resource: Resource,
            error: Exception,
            request_cookie: Optional[str]=None
            ) -> ResourceRevision:
        """
        Creates a new revision that encapsulates the error encountered when fetching the revision.
        """
        return ResourceRevision._create_from_stream(
            resource,
            request_cookie=request_cookie,
            error=error)
    
    @staticmethod
    def create_from_response(
            resource: Resource,
            metadata: Optional[ResourceRevisionMetadata],
            body_stream: BinaryIO,
            request_cookie: Optional[str]=None
            ) -> ResourceRevision:
        """
        Creates a new revision with the specified metadata and body.
        
        The passed body stream will be read synchronously until EOF,
        so it is recommended that this method be invoked on a background thread.
        
        Arguments:
        * resource -- resource that this is a revision of.
        * metadata -- JSON-encodable dictionary of resource metadata.
        * body_stream -- file-like object containing the revision body.
        """
        try:
            # If no HTTP Date header was returned by the origin server,
            # auto-populate it with the current datetime, as per RFC 7231 §7.1.1.2:
            # 
            # > A recipient with a clock that receives a response message without a
            # > Date header field MUST record the time it was received and append a
            # > corresponding Date header field to the message's header section if it
            # > is cached or forwarded downstream.
            if metadata is not None:
                date_str = ResourceRevision._get_first_value_of_http_header_in_metadata(
                    'date', metadata)
                if date_str is None:
                    metadata['headers'].append([
                        'Date',
                        http_date.format(datetime.datetime.now(datetime.timezone.utc))
                    ])
            
            return ResourceRevision._create_from_stream(
                resource,
                request_cookie=request_cookie,
                metadata=metadata,
                body_stream=body_stream)
        except Exception as e:
            return ResourceRevision.create_from_error(resource, e, request_cookie)
    
    @staticmethod
    def _create_from_stream(
            resource: Resource,
            *, request_cookie: Optional[str]=None,
            error: Optional[Exception]=None,
            metadata: Optional[ResourceRevisionMetadata]=None,
            body_stream: Optional[BinaryIO]=None
            ) -> ResourceRevision:
        """
        Creates a new revision.
        
        See also:
        * ResourceRevision.create_from_error()
        * ResourceRevision.create_from_response()
        """
        self = ResourceRevision()
        self.resource = resource
        self.request_cookie = request_cookie
        self.error = error
        self.metadata = metadata
        self._id = None  # type: ignore[assignment]  # not yet created
        self.has_body = body_stream is not None
        
        project = self.project
        
        # Associated Resource will have at least one ResourceRevision
        # 
        # NOTE: Set this bit BEFORE finishing the download.
        #       If we were to set the bit AFTER finishing the download
        #       then there would be a period of time between when the download
        #       finished and the bit was set where the value of the
        #       bit would be wrong. Avoid that scenario.
        resource._definitely_has_no_revisions = False
        
        condition = threading.Condition()
        callable_done = False
        callable_exc_info = None
        
        # Asynchronously:
        # 1. Create the ResourceRevision row in the database
        # 2. Get the database ID
        def fg_task() -> None:
            nonlocal callable_done, callable_exc_info
            try:
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
            except BaseException as e:
                callable_exc_info = sys.exc_info()
            finally:
                with condition:
                    callable_done = True
                    condition.notify()
        # NOTE: Use no_profile=True because no obvious further optimizations exist
        fg_call_later(fg_task, no_profile=True)
        
        body_file_downloaded_ok = False
        try:
            # Download the resource's body, if available
            if body_stream:
                with NamedTemporaryFile(
                        mode='wb',
                        suffix='.body',
                        dir=os.path.join(project.path, Project._TEMPORARY_DIRNAME),
                        delete=False) as body_file:
                    xshutil.copyfileobj_readinto(body_stream, body_file)
                body_file_downloaded_ok = True
            else:
                body_file = None
        finally:
            # Wait for ResourceRevision row to be created in database
            with condition:
                while not callable_done:
                    condition.wait()
            row_created_ok = self._id is not None
            
            if body_file is not None:
                try:
                    if body_file_downloaded_ok and row_created_ok:
                        # Move body file to its final filename
                        os.rename(
                            body_file.name,
                            os.path.join(project.path, Project._RESOURCE_REVISION_DIRNAME, str(self._id)))
                    else:
                        # Remove body file
                        os.remove(body_file.name)
                except:
                    body_file_downloaded_ok = False
                finally:
                    if not body_file_downloaded_ok and row_created_ok:
                        # Rollback database commit
                        def fg_task() -> None:
                            if project.readonly:
                                raise ProjectReadOnlyError()
                            c = project._db.cursor()
                            c.execute('delete from resource_revision where id=?', (self._id,))
                            project._db.commit()
                        # NOTE: Use no_profile=True because no obvious further optimizations exist
                        fg_call_and_wait(fg_task, no_profile=True)
            
            # Reraise callable's exception, if applicable
            if callable_exc_info is not None:
                exc_info = callable_exc_info
                assert exc_info[1] is not None
                raise exc_info[1].with_traceback(exc_info[2])
        
        if not project._loading:
            project._resource_revision_did_instantiate(self)
        
        return self
    
    @staticmethod
    def _create_from_revision_and_new_metadata(
            revision: ResourceRevision,
            metadata: ResourceRevisionMetadata
            ) -> ResourceRevision:
        """
        Creates an unsaved modified version of an existing revision
        with the specified new metadata.
        """
        self = ResourceRevision()
        self.resource = revision.resource
        self.request_cookie = revision.request_cookie
        self.error = revision.error
        self.metadata = metadata
        self._id = revision._id
        self.has_body = (self.error is None)
        return self
    
    @staticmethod
    def _load_from_data(
            resource: Resource,
            request_cookie: Optional[str],
            error: Optional[Exception],
            metadata: Optional[ResourceRevisionMetadata],
            id: int) -> ResourceRevision:
        """
        Loads an existing revision with data that has already been fetched
        from the project database.
        """
        self = ResourceRevision()
        self.resource = resource
        self.request_cookie = request_cookie
        self.error = error
        self.metadata = metadata
        self._id = id
        self.has_body = (self.error is None)
        return self
    
    # TODO: Optimize implementation to avoid unnecessarily loading all
    #       sibling revisions of the requested revision.
    @staticmethod
    def load(project: Project, id: int) -> Optional[ResourceRevision]:
        """
        Loads the existing revision with the specified ID,
        or returns None if no such revision exists.
        """
        # Fetch the revision's resource URL
        c = project._db.cursor()
        rows = list(c.execute(
            f'select '
                f'resource_id, resource.url as resource_url from resource_revision '
                f'left join resource on resource_revision.resource_id = resource.id '
                f'where resource_revision.id=?',
            (id,)
        ))
        if len(rows) == 0:
            return None
        [(resource_id, resource_url)] = rows
        
        # Get the resource by URL from memory
        r = project.get_resource(resource_url)
        assert r is not None
        
        # Load all of the resource's revisions
        rrs = r.revisions()
        
        # Find the specific revision that was requested
        for rr in rrs:
            if rr._id == id:
                return rr
        raise AssertionError()
    
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
        """
        Raises:
        * NoRevisionBodyError
        """
        if not self.has_body:
            raise NoRevisionBodyError(self)
    
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
        return self._get_first_value_of_http_header_in_metadata(name, self.metadata)
    
    @staticmethod
    def _get_first_value_of_http_header_in_metadata(
            name: str,
            metadata: Optional[ResourceRevisionMetadata],
            ) -> Optional[str]:
        name = name.lower()  # reinterpret
        if metadata is None:
            return None
        for (cur_name, cur_value) in metadata['headers']:
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
    def is_recognized_binary_type(self) -> bool:
        return self.content_type in [
            # https://www.iana.org/assignments/media-types/media-types.xhtml#application
            'application/gzip',  # .gz
            'application/java-archive',  # .jar
            'application/zip',  # .zip
            'application/vnd.rar',  # .rar; https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types
            'application/x-tar',  # .tar; https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types
            'application/x-7z-compressed',  # .7z; https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types
            
            # https://www.iana.org/assignments/media-types/media-types.xhtml#audio
            'audio/aac',
            'audio/mp4',
            'audio/mpeg',  # .mp3
            'audio/ogg',  # .oga
            'audio/opus',  # .opus
            'audio/vorbis',
            'audio/midi',  # https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types
            'audio/x-midi',  # https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types
            'audio/wav',  # https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types
            'audio/webm',  # https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types
            
            # https://www.iana.org/assignments/media-types/media-types.xhtml#font
            'font/otf',
            'font/ttf',
            'font/woff',
            'font/woff2',
            'application/vnd.ms-fontobject',  # .eot; https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types
            
            # https://www.iana.org/assignments/media-types/media-types.xhtml#image
            'image/apng',
            'image/bmp',
            'image/gif',
            'image/jpeg',
            'image/png',
            # (NOT: 'image/svg+xml',)
            'image/tiff',
            'image/webp',
            'image/vnd.microsoft.icon',  # .ico; https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types
            
            # https://www.iana.org/assignments/media-types/media-types.xhtml#video
            'video/mp4',
            'video/ogg',
            'video/quicktime',  # .mov
            'video/x-msvideo',  # .avi; https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types
            'video/mpeg',  # .mpg; https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types
            'video/webm',  # .webm; https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types/Common_types
        ]
    
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
    
    def size(self) -> int:
        """
        Returns the size of this resource's body.
        
        Raises:
        * NoRevisionBodyError
        * RevisionBodyMissingError
        """
        self._ensure_has_body()
        try:
            return os.path.getsize(self._body_filepath)
        except FileNotFoundError:
            raise RevisionBodyMissingError(self)
    
    def open(self) -> BinaryIO:
        """
        Opens the body of this resource for reading, returning a file-like object.
        
        Raises:
        * NoRevisionBodyError
        * RevisionBodyMissingError
        """
        self._ensure_has_body()
        try:
            return open(self._body_filepath, 'rb')
        except FileNotFoundError:
            raise RevisionBodyMissingError(self)
    
    def links(self) -> list[Link]:
        """
        Returns list of Links found in this resource.
        
        This method blocks while parsing the links.
        
        Raises:
        * NoRevisionBodyError
        * RevisionBodyMissingError
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
        
        Raises:
        * NoRevisionBodyError
        * RevisionBodyMissingError
        """
        from crystal.doc.css import parse_css_and_links
        from crystal.doc.generic import create_external_link
        from crystal.doc.html import parse_html_and_links
        from crystal.doc.json import parse_json_and_links
        from crystal.doc.xml import parse_xml_and_links
        
        # Extract links from HTML, if applicable
        (doc, links) = (None, [])  # type: tuple[Optional[Document], list[Link]]
        content_type_with_options = None  # type: Optional[str]
        if self.is_html and self.has_body:
            with self.open() as body:
                doc_and_links = parse_html_and_links(
                    body, self.declared_charset, self.project.html_parser_type)
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
            redirect_title = self._redirect_title
            assert redirect_title is not None
            links.append(create_external_link(redirect_url, redirect_title, 'Redirect', True))
        
        return (doc, links, content_type_with_options)
    
    # === Operations ===
    
    # NOTE: For testing purposes only.
    #       
    #       This is NOT part of the public API because ResourceRevisions are
    #       generally immutable after creation.
    def _alter_metadata(self,
            new_metadata: ResourceRevisionMetadata,
            *, ignore_readonly: bool=False
            ) -> None:
        project = self.project
        
        # Alter ResourceRevision's metadata in memory
        self.metadata = new_metadata
        
        # Alter ResourceRevision's metadata in database
        c = project._db.cursor()
        c.execute(
            'update resource_revision set metadata = ? where id = ?',
            (json.dumps(new_metadata), self._id),  # type: ignore[attr-defined]
            ignore_readonly=ignore_readonly)
        project._db.commit()
    
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
                    [k, v]
                    for (k, v) in new_metadata['headers']
                    if k.lower() != header_name_lower
                ] + [[header_name, header_value]]
        
        return ResourceRevision._create_from_revision_and_new_metadata(target_revision, new_metadata)
    
    def delete(self):
        project = self.project
        
        if project.readonly:
            raise ProjectReadOnlyError()
        
        body_filepath = self._body_filepath  # cache
        try:
            os.remove(body_filepath)
        except FileNotFoundError:
            # OK. The revision may have already been partially deleted outside of Crystal.
            pass
        
        c = project._db.cursor()
        c.execute('delete from resource_revision where id=?', (self._id,))
        project._db.commit()
        self._id = None  # type: ignore[assignment]  # intentionally leave exploding None
        
        self.resource.already_downloaded_this_session = False
    
    def __repr__(self) -> str:
        return "<ResourceRevision %s for '%s'>" % (self._id, self.resource.url)
    
    def __str__(self) -> str:
        return f'Revision {self._id} for URL {self.resource.url}'


class NoRevisionBodyError(ValueError):
    """
    An operation was attempted on a ResourceRevision that only makes sense
    for revisions that have a body, and the targeted revision has no body.
    """
    def __init__(self, revision: ResourceRevision) -> None:
        super().__init__(f'{revision!s} has no body')


class RevisionBodyMissingError(ProjectFormatError):
    def __init__(self, revision: ResourceRevision) -> None:
        super().__init__(
            f'{revision!s} is missing its body on disk. '
            f'Recommend delete and redownload it.')


class ResourceRevisionMetadata(TypedDict):
    http_version: int  # 10 for HTTP/1.0, 11 for HTTP/1.1
    status_code: int
    reason_phrase: str
    # NOTE: Each element of headers is a 2-item (key, value) list
    headers: list[list[str]]  # email.message.EmailMessage


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
        
        self._members = project.resources_matching_pattern(
            url_pattern_re=self._url_pattern_re,
            literal_prefix=ResourceGroup.literal_prefix_for_url_pattern(url_pattern))
        
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
        
        if not project._loading:
            project._resource_group_did_instantiate(self)
    
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
        self._id = None  # type: ignore[assignment]  # intentionally leave exploding None
        
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
        
        This task may be complete immediately after initialization.
        """
        if needs_result:
            raise ValueError('Download task for a group never has a result')
        
        from crystal.task import DownloadResourceGroupTask
        return DownloadResourceGroupTask(self)
    
    def update_membership(self) -> None:
        """
        Updates the membership of this group asynchronously.
        
        A top-level Task will be created internally to display the progress.
        
        Raises:
        * ProjectClosedError -- If the project is closed.
        """
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
