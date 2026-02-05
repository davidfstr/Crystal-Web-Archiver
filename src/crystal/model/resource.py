from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Generator, Iterable, Iterator, Sequence
from concurrent.futures import Future
from contextlib import closing, contextmanager
import copy
from crystal import resources as resources_
from crystal.doc.css import parse_css_and_links
from crystal.doc.generic import create_external_link
from crystal.doc.html import parse_html_and_links
from crystal.doc.html.soup import FAVICON_TYPE_TITLE, HtmlDocument
from crystal.doc.json import parse_json_and_links
from crystal.doc.xml import parse_xml_and_links
from crystal.model.util import resolve_proxy
from crystal.plugins import minimalist_baker as plugins_minbaker
from crystal.plugins import phpbb as plugins_phpbb
from crystal.plugins import substack as plugins_substack
from crystal.plugins import wordpress as plugins_wordpress
from crystal.progress import (
    CancelLoadUrls, CancelOpenProject, CancelSaveAs, DummyLoadUrlsProgressListener,
    DummyOpenProjectProgressListener, LoadUrlsProgressListener,
    OpenProjectProgressListener, SaveAsProgressListener, VetoUpgradeProject,
)
from crystal.util import gio, http_date, xcgi, xshutil
from crystal.util.bulkheads import (
    capture_crashes_to_bulkhead_arg as capture_crashes_to_task_arg,
)
from crystal.util.bulkheads import capture_crashes_to_stderr, run_bulkhead_call
from crystal.util.db import (
    DatabaseConnection, DatabaseCursor, get_column_names_of_table,
    get_index_names, get_table_names, is_no_such_column_error_for,
)
from crystal.util.ellipsis import Ellipsis, EllipsisType
from crystal.util.filesystem import rename_and_flush, flush_renames_in_directory
from crystal.util.listenable import ListenableMixin
from crystal.util.profile import create_profiling_context, warn_if_slow
from crystal.util.progress import DevNullFile
from crystal.util.ssd import is_ssd
from crystal.util.test_mode import tests_are_running
from crystal.util.thread_debug import get_thread_stack
from crystal.app_preferences import app_prefs
from crystal.util.urls import is_unrewritable_url, requote_uri
from crystal.util.windows_attrib import set_windows_file_attrib
from crystal.util.xappdirs import user_untitled_projects_dir
from crystal.util.xbisect import bisect_key_right
from crystal.util.xcollections.ordereddict import as_ordereddict
from crystal.util.xcollections.sortedlist import BLACK_HOLE_SORTED_LIST
from crystal.util.xdatetime import datetime_is_aware
from crystal.util.xshutil import walkzip
from crystal.util.xsqlite3 import random_choices_from_table_ids
from crystal.util.xgc import gc_disabled
from crystal.util.xos import is_linux, is_mac_os, is_windows
from crystal.util.xsqlite3 import is_database_read_only_error, sqlite_has_json_support
from crystal.util.xthreading import (
    SwitchToThread, bg_affinity, bg_call_later, fg_affinity, fg_call_and_wait, fg_call_later, fg_wait_for,
    is_foreground_thread, start_thread_switching_coroutine,
)
import datetime
from enum import Enum
import errno
import itertools
import json
import math
import mimetypes
import os
import pathlib
import re
from re import Pattern
from send2trash import send2trash, TrashPermissionError
import shutil
from shutil import COPY_BUFSIZE  # type: ignore[attr-defined]  # private API
from sortedcontainers import SortedList
import sqlite3
import sys
import tempfile
from tempfile import mkdtemp, NamedTemporaryFile
from textwrap import dedent
import threading
import time
from tqdm import tqdm
import traceback
from typing import (
    Any, BinaryIO, cast, Dict, Generic, IO, List, Literal, Optional, Self, Tuple,
    TYPE_CHECKING, TypedDict, TypeAlias, TypeVar, Union,
)
from typing_extensions import deprecated, override
from urllib.parse import quote as url_quote
from urllib.parse import urlparse, urlunparse
import uuid
import warnings
from weakref import WeakValueDictionary

if TYPE_CHECKING:
    from crystal.doc.generic import Document, Link
    from crystal.doc.html import HtmlParserType
    from crystal.task import (
        DownloadResourceBodyTask, DownloadResourceGroupTask,
        DownloadResourceTask, RootTask, Task,
    )
    from crystal.model.project import Project
    from crystal.model.resource_revision import ResourceRevision

# ------------------------------------------------------------------------------
# Constants + Type Utilities

_TK = TypeVar('_TK', bound='Task')


# ------------------------------------------------------------------------------
# Resource

class _WeakTaskRef(Generic[_TK]):
    """
    Holds a reference to a Task until that task completes.
    """
    # Optimize per-instance memory use, since there may be very many
    # _WeakTaskRef objects, because there may be very many Resource objects
    # which each contain _WeakTaskRef instances
    __slots__ = ('_task',)
    
    def __init__(self, task: _TK | None=None) -> None:
        self._task = None
        self.task = task
    
    def _get_task(self) -> _TK | None:
        return self._task
    def _set_task(self, value: _TK | None) -> None:
        if value is not None and value.complete:
            # Do not hold reference to an already completed task
            value = None  # reinterpret
        if self._task:
            self._task.listeners.remove(self)
        self._task = value
        if self._task:
            self._task.listeners.append(self)
    task = property(_get_task, _set_task)
    
    @capture_crashes_to_task_arg
    def task_did_complete(self, task: Task) -> None:
        self.task = None
    
    def __repr__(self) -> str:
        return f'<_WeakTaskRef to {self._task!r} at {hex(id(self))}>'


class Resource:
    """
    Represents an entity, potentially downloadable.
    Either created manually or discovered through a link from another resource.
    Persisted and auto-saved.
    
    It is always possible to create a Resource (in memory) even if
    its project is read-only. If/when the project transitions to
    writable, any unsaved resources will be saved to disk.
    """
    # Special IDs, all < 0
    _DEFER_ID = -1  # type: Literal[-1]
    _DELETED_ID = -2  # type: Literal[-2]
    _UNSAVED_ID = -3  # type: Literal[-3]
    _EXTERNAL_ID = -4  # type: Literal[-4]
    
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
        
        # Necessary to support weak references to Resource objects
        '__weakref__',
    )
    
    project: Project
    _url: str
    _download_body_task_ref: Optional[_WeakTaskRef[DownloadResourceBodyTask]]
    _download_task_ref: Optional[_WeakTaskRef[DownloadResourceTask]]
    _download_task_noresult_ref: Optional[_WeakTaskRef[DownloadResourceTask]]
    _already_downloaded_this_session: bool
    _definitely_has_no_revisions: bool
    _id: int  # or None if not finished initializing or deleted
    
    # === Init (One) ===
    
    @fg_affinity
    def __new__(cls, 
            project: Project,
            url: str,
            _id: Union[None, int]=None,
            *, _external_ok: bool=False,
            ) -> Resource:
        """
        Looks up an existing resource with the specified URL or creates a new
        one if no preexisting resource matches.
        
        Note that returned Resource will have a *normalized* URL which may
        differ from the exact URL specified in this constructor.
        
        It is always possible to create a Resource (in memory) even if
        its project is read-only. If/when the project transitions to
        writable, any unsaved resources will be saved to disk.
        
        Arguments:
        * project -- associated `Project`.
        * url -- absolute URL to this resource (ex: http), or a URI (ex: mailto).
        
        Raises:
        * sqlite3.DatabaseError --
            if a database error occurred, preventing the creation of the new Resource.
        """
        from crystal.model.alias import Alias
        
        # Private API:
        # * _id --
        #     - If _id is None then any existing resource in the database
        #       matching the specified URL will be used. If no matching resource
        #       is found then a new Resource will be created in the database.
        #       The resulting Resource will always have an _id pointing to
        #       a Resource in the database.
        #     - If not (_id < 0) then it points to an existing Resource in the
        #       database with the specified ID.
        #     - If _id == Resource._DEFER_ID, and there is no existing resource
        #       corresponding to the URL in the project, the returned Resource
        #       will not have a valid ID and report _is_finished_initializing() == False.
        #       The caller will then be responsible for populating the ID later
        #       using _finish_init().
        #     - If _id == Resource._EXTERNAL_ID, then the caller is signaling
        #       an explicit intent to create an external URL.
        #     - No other values for _id are valid.
        # * _external_ok --
        #     - whether the caller is prepared for the possibility
        #       that the specified URL corresponds to an external URL.
        #       In that circumstance the returned Resource will have
        #       (external_url is not None) and the caller should check
        #       for that condition to do any special handling required.
        
        if _id is None or _id == Resource._DEFER_ID:
            url_alternatives = cls.resource_url_alternatives(project, url)
            
            # Find first matching existing alternative URL, to provide
            # backward compatibility with older projects that use less-normalized
            # forms of the original URL
            # 
            # TODO: Optimize this to use a Project.get_first_matching_resource()
            #       method that performs at most a single bulk DB query
            for urla in url_alternatives:
                resource = project.get_resource(urla)
                if resource is not None:
                    return resource
            
            normalized_url = url_alternatives[-1]
        else:
            # Always use original URL if loading from saved resource
            normalized_url = url
        del url  # prevent accidental usage later
        
        # Ensure that if an external URL is used then the caller opts-in
        # to handling that possibility, so that they aren't created unintentionally
        is_external = Alias.parse_external_url(normalized_url) is not None
        if is_external:
            if not _external_ok:
                raise ValueError(
                    f'Cannot create Resource with external URL {normalized_url!r} '
                    f'unless caller signals it supports that possibility '
                    f'using _external_ok=True')
            if not (_id is None or _id < 0):  # non-special ID
                raise ValueError(
                    f'Cannot create Resource with external URL {normalized_url!r} '
                    f'with in-database id={_id}.')
            _id = Resource._EXTERNAL_ID  # reinterpret
        
        self = object.__new__(cls)
        self.project = resolve_proxy(project)  # type: ignore[assignment]
        self._url = normalized_url
        self._download_body_task_ref = None
        self._download_task_ref = None
        self._download_task_noresult_ref = None
        self._already_downloaded_this_session = False
        self._definitely_has_no_revisions = False
        
        creating = _id is None  # capture
        if creating:
            if project.readonly:
                _id = Resource._UNSAVED_ID
            else:
                with project._db, closing(project._db.cursor()) as c:
                    c.execute('insert into resource (url) values (?)', (normalized_url,))
                    assert c.lastrowid is not None
                    _id = c.lastrowid  # capture
            
            # Can't have revisions because it was just created this session
            self._definitely_has_no_revisions = True
        
        if _id == Resource._EXTERNAL_ID:
            # External resources are in-memory only and never have revisions
            self._definitely_has_no_revisions = True
        
        if _id == Resource._DEFER_ID:
            self._id = None  # type: ignore[assignment]  # intentionally leave exploding None
        else:
            assert isinstance(_id, int)
            self._finish_init(_id, creating)  # sets self._id
        
        return self
    
    @property
    def _is_finished_initializing(self) -> bool:
        return self._id is not None
    
    @fg_affinity
    def _finish_init(self, id: int, creating: bool) -> None:
        """
        Finishes initializing a Resource that was created with
        Resource(..., _id=Resource._DEFER_ID).
        
        Arguments:
        * creating -- whether this resource is being created and did not exist in the database
        """
        # Private API:
        # - id may be _UNSAVED_ID or _EXTERNAL_ID
        self._id = id
        
        if creating:
            project = self.project  # cache
            
            if id == Resource._EXTERNAL_ID:
                # External resources are in-memory only, not saved to project
                pass
            else:
                # Record self in Project
                project._resource_for_url[self._url] = self
                if id == Resource._UNSAVED_ID:
                    project._unsaved_resources.append(self)
                else:
                    assert id >= 0  # not any other kind of special ID
                    project._resource_for_id[id] = self
                if project._sorted_resource_urls is not None:
                    project._sorted_resource_urls.add(self._url)
                # NOTE: Don't check invariants here to save a little performance,
                #       since this method (_finish_init) is called very many times
                #project._check_url_collection_invariants()
            
            # Notify listeners that self did instantiate
            project._resource_did_instantiate(self)
        else:
            # Record self in Project
            # (Caller is responsible for updating Project._resource_for_url)
            # (Caller is responsible for updating Project._resource_for_id)
            # (Caller is responsible for updating Project._sorted_resource_urls)
            pass
    
    def _finish_save(self, id: int) -> None:
        """
        Finishes saving a Resource that was created with
        _finish_init(id=Resource._UNSAVED_ID).
        
        The caller is responsible for removing this Resource
        from project._unsaved_resources.
        """
        assert id >= 0  # not a special ID
        assert self._id == Resource._UNSAVED_ID
        
        project = self.project  # cache
        
        self._id = id
        # NOTE: Don't actually run assertion for improved performance
        #assert self._url in project._resource_for_url
        project._resource_for_id[id] = self
        # NOTE: Don't actually run assertion for improved performance
        #assert self._url in project._sorted_resource_urls
    
    # === Init (Many) ===
    
    @classmethod
    def bulk_get_or_create(cls,
            project: Project,
            urls: list[str],
            origin_url: str,
            *, _external_ok: bool=False,
            ) -> list[Resource]:
        """
        Get or creates several Resources for the specified list of URLs, in bulk.
        Returns the set of Resources that were looked up or created.
        
        Note that the list of Resources returned may be shorter than the
        input list of URLs because some of the input URLs may be normalized to
        the same output URL.
        
        Note that the list of Resources returned are not guaranteed to be
        ordered in any particular way.
        
        It is always possible to create a Resource (in memory) even if
        its project is read-only. If/when the project transitions to
        writable, any unsaved resources will be saved to disk.
        
        Arguments:
        * project -- associated `Project`.
        * urls -- absolute URLs.
        * origin_url -- origin URL from which `urls` were obtained. Used for debugging.
        
        Raises:
        * sqlite3.DatabaseError --
            if a database error occurred, preventing the lookup/creation of any Resources.
        """
        # Private API:
        # * _external_ok --
        #     - whether the caller is prepared for the possibility
        #       that any of the specified URLs correspond to an external URL.
        #       In that circumstance the returned list
        #       may contain one or more Resources where
        #       (external_url is not None) and the caller should check
        #       for that condition to do any special handling required.
        
        (already_created, created) = cls._bulk_get_or_create(
            project, urls, origin_url,
            _external_ok=_external_ok,
        )
        return already_created + created
    
    @classmethod
    @deprecated('Use Resource.bulk_get_or_create() instead')
    def bulk_create(cls,
            project: Project,
            urls: list[str],
            origin_url: str,
            ) -> list[Resource]:
        """
        Creates several Resources for the specified list of URLs, in bulk.
        Returns the set of Resources that were created. Already existing
        resources corresponding to input URLs will be ignored and not returned.
        
        Note that the list of Resources returned may be shorter than the
        input list of URLs because some of the input URLs may be normalized to
        the same output URL.
        
        Note that the list of Resources returned are not guaranteed to be
        ordered in any particular way.
        
        It is always possible to create a Resource (in memory) even if
        its project is read-only. If/when the project transitions to
        writable, any unsaved resources will be saved to disk.
        
        Arguments:
        * project -- associated `Project`.
        * urls -- absolute URLs.
        * origin_url -- origin URL from which `urls` were obtained. Used for debugging.
        
        Raises:
        * sqlite3.DatabaseError --
            if a database error occurred, preventing the lookup/creation of any Resources.
        """
        (_, created) = cls._bulk_get_or_create(
            project, urls, origin_url,
            # NOTE: _external_ok=True is always safe in this context because
            #       any created Resources with an external URL won't be exposed
            #       to the caller. Therefore the caller cannot observe such
            #       Resources and does not need any special handling for them.
            _external_ok=True,
        )
        return created
    
    @classmethod
    @fg_affinity
    def _bulk_get_or_create(cls,
            project: Project,
            urls: list[str],
            origin_url: str,
            *, _external_ok: bool=False,
            ) -> tuple[list[Resource], list[Resource]]:
        """
        Raises:
        * sqlite3.DatabaseError --
            if a database error occurred, preventing the lookup/creation of any Resources.
        """
        # Private API:
        # * _external_ok --
        #     - whether the caller is prepared for the possibility
        #       that any of the specified URLs correspond to an external URL.
        #       In that circumstance the returned list of
        #       `resources_already_created` may contain one or more Resources where
        #       (external_url is not None) and the caller should check
        #       for that condition to do any special handling required.
        
        # 1. Create Resources in memory initially, deferring any database INSERTs
        # 2. Identify new resources that need to be inserted in the database
        resource_for_new_url = OrderedDict()  # type: Dict[str, Resource]
        resources_already_created = []
        for url in urls:
            # Get/create Resource in memory and normalize its URL
            new_r = Resource(project, url, _id=Resource._DEFER_ID, _external_ok=_external_ok)
            if new_r.external_url is not None:
                # Report external URLs which exist only in memory as being "already created"
                resources_already_created.append(new_r)
            else:
                if new_r._is_finished_initializing:
                    # Resource with normalized URL already existed in memory
                    resources_already_created.append(new_r)
                else:
                    # Resource with normalized URL needs to be created in database
                    if new_r.url in resource_for_new_url:
                        # Resource with normalized URL is already scheduled to be created in database
                        pass
                    else:
                        # Schedule resource with normalized URL to be created in database
                        resource_for_new_url[new_r.url] = new_r
        
        if len(resource_for_new_url) > 0:
            if project.readonly:
                # Defer until project becomes writable:
                # Insert resources into the database
                ids = itertools.repeat(Resource._UNSAVED_ID)  # type: Iterable[int]
            else:
                # Insert resources into the database
                ids = cls._bulk_create_resource_ids_for_urls(
                    project,
                    list(resource_for_new_url.keys()),
                    origin_url,
                )
            
            # Populate the ID of each Resource in memory (possibly _UNSAVED_ID),
            # and finish initializing each Resource (by recording it
            # in the Project and notifying listeners of instantiation)
            for (new_r, id) in zip(resource_for_new_url.values(), ids):
                new_r._finish_init(id, creating=True)
        
        # Return the set of Resources that were looked up or created
        return (resources_already_created, list(resource_for_new_url.values()))
    
    @staticmethod
    def _bulk_create_resource_ids_for_urls(
            project: Project,
            normalized_urls: list[str],
            origin_url: str | None,
            ) -> list[int]:
        """
        Raises:
        * sqlite3.DatabaseError --
            if a database error occurred, preventing the creation of any ids.
        """
        from crystal.task import PROFILE_RECORD_LINKS
        
        # Create many Resource rows in database with a single bulk INSERT,
        # to optimize performance, retrieving the IDs of the inserted rows
        if origin_url is None:
            message = lambda: f'{len(normalized_urls)} links'
        else:
            message = lambda: f'{len(normalized_urls)} links from {origin_url!r}'
        insert_context = warn_if_slow('Inserting links', max_duration=1.0, message=message, enabled=PROFILE_RECORD_LINKS)
        commit_context = warn_if_slow('Committing links', max_duration=1.0, message=message, enabled=PROFILE_RECORD_LINKS)
        with project._db(commit_context=commit_context):
            with insert_context:
                with closing(project._db.cursor()) as c:
                    placeholders = ','.join(['(?)'] * len(normalized_urls))
                    rows = list(c.execute(
                        f'insert into resource (url) values {placeholders} returning id',
                        normalized_urls)
                    )  # type: List[Tuple[int]]
        return [id for (id,) in rows]
    
    # === Properties ===
    
    @staticmethod
    def resource_url_alternatives(project: Project, url: str) -> list[str]:
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
        
        For more information, see the covering test module:
        - test_url_normalization.py
        """
        from crystal.model.alias import Alias
        
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
        else:
            new_url = urlunparse(url_parts)
        del url_parts  # prevent accidental future use
        
        # Allow plugins to normalize URLs further
        old_url = new_url
        for normalize_url in (
                plugins_minbaker.normalize_url,
                plugins_phpbb.normalize_url,
                plugins_substack.normalize_url,
                plugins_wordpress.normalize_url,
                ):
            try:
                new_url = normalize_url(old_url)
            except Exception:  # ignore errors
                new_url = old_url
            else:
                if new_url != old_url:
                    alternatives.append(new_url)
                    old_url = new_url  # reinterpret
        
        # Apply user-defined alias-based normalization,
        # after all other normalizations
        old_url = new_url
        for alias in project.aliases:
            if not old_url.startswith(alias.source_url_prefix):
                continue
            
            # Replace source prefix with target prefix
            new_url = alias.target_url_prefix + old_url[len(alias.source_url_prefix):]
            
            # If target is external, format as external URL
            if alias.target_is_external:
                new_url = Alias.format_external_url(new_url)
            
            if new_url != old_url:
                alternatives.append(new_url)
                old_url = new_url  # reinterpret
            
            # Only apply the first matching alias
            break
        
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
    
    @property
    def external_url(self) -> str | None:
        """
        If this Resource points to live URL on the internet external to the project,
        returns what that external URL is. Otherwise returns None.
        """
        from crystal.model.alias import Alias
        
        if self._id != Resource._EXTERNAL_ID:
            return None
        external_url = Alias.parse_external_url(self._url)
        assert external_url is not None
        return external_url
    
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
    
    # === Operations: Download ===
    
    def download_body(self, *, interactive: bool=False) -> Future[ResourceRevision]:
        """
        Returns a Future[ResourceRevision] that downloads (if necessary) and returns an
        up-to-date version of this resource's body.
        
        The returned Future may invoke its callbacks on any thread.
        
        A top-level Task will be created internally to display the progress.
        
        Raises:
        * ProjectClosedError --
            If the project is closed.
        
        Future Raises:
        * CannotDownloadWhenProjectReadOnlyError --
            If resource is not already downloaded and project is read-only.
        * ProjectFreeSpaceTooLowError --
            If the project does not have enough free disk space to safely
            download more resources.
        * ProjectHasTooManyRevisionsError
        """
        (task, created) = self.get_or_create_download_body_task()
        self._schedule_task_at_top_level_if_created_or_interactive(task, created, interactive)
        return task.future
    
    # Soft Deprecated: Use get_or_create_download_body_task() instead,
    # which clarifies that an existing task may be returned.
    def create_download_body_task(self) -> DownloadResourceBodyTask:
        """
        Gets/creates a Task to download this resource's body.
        
        The caller is responsible for adding a returned created Task as the child of an
        appropriate parent task so that the UI displays it.
        
        A created task is never complete immediately after initialization,
        however a looked up task may be complete.
        """
        (task, _) = self.get_or_create_download_body_task()
        return task
    
    def get_or_create_download_body_task(self) -> Tuple[DownloadResourceBodyTask, bool]:
        """
        Gets/creates a Task to download this resource's body.
        
        The caller is responsible for adding a returned created Task as the child of an
        appropriate parent task so that the UI displays it.
        
        A created task is never complete immediately after initialization,
        however a looked up task may be complete.
        """
        def task_factory() -> DownloadResourceBodyTask:
            from crystal.task import DownloadResourceBodyTask
            return DownloadResourceBodyTask(self)
        if self._download_body_task_ref is None:
            self._download_body_task_ref = _WeakTaskRef()
        return self._get_task_or_create(self._download_body_task_ref, task_factory)
    
    def download(self, *, wait_for_embedded: bool=False, **kwargs) -> Future[ResourceRevision]:
        """
        Same as download_with_task() but returns a Future[ResourceRevision]
        instead of a DownloadResourceTask.
        
        The returned Future may invoke its callbacks on any thread.
        
        By default the returned future waits only for the resource itself
        to finish downloading but not for any embedded resources to finish
        downloading. Pass wait_for_embedded=True if you also want to wait
        for embedded resources.
        
        See documentation for download_with_task() to see the supported kwargs.
        """
        task = self.download_with_task(**kwargs)
        return task.get_future(wait_for_embedded)
    
    def download_with_task(self,
            *, needs_result: bool=True,
            is_embedded: bool=False,
            interactive: bool=False,
            ) -> DownloadResourceTask:
        """
        Returns a DownloadResourceTask that downloads (if necessary) and returns an
        up-to-date version of this resource's body. If a download is performed, all
        embedded resources will be downloaded as well.
        
        If needs_result=False then the caller is declaring that it does
        not need and will ignore the result of the returned future,
        which enables additional optimizations.
        
        Raises:
        * ProjectClosedError --
            If the project is closed.
        
        Future Raises:
        * CannotDownloadWhenProjectReadOnlyError --
            If resource is not already downloaded and project is read-only.
        * ProjectFreeSpaceTooLowError --
            If the project does not have enough free disk space to safely
            download more resources.
        * ProjectHasTooManyRevisionsError
        """
        if interactive:
            # Assume optimistically that resource is embedded so that
            # it downloads without inserting any artificial delays
            is_embedded = True  # reinterpret
        
        (task, created) = self.get_or_create_download_task(
            needs_result=needs_result, is_embedded=is_embedded)
        self._schedule_task_at_top_level_if_created_or_interactive(task, created, interactive)
        return task
    
    # TODO: Consider extract this interactive-related logic to the Task class
    #       to improve encapsulation of task._interactive.
    def _schedule_task_at_top_level_if_created_or_interactive(self,
            task: Task,
            created: bool,
            interactive: bool,
            ) -> None:
        from crystal.task import DownloadResourceTask, DownloadResourceBodyTask
        
        # 1. If task was just created, schedule it at the root of the task tree
        # 2. If task should be interactive priority, mark it as such, and
        #    (re)schedule it as a top-level task
        if interactive and not task._interactive:
            assert isinstance(task, (DownloadResourceTask, DownloadResourceBodyTask)), (
                # Don't allow big tasks like DownloadResourceGroup to be scheduled
                # with interactive=True priority to avoid hammering origin servers
                # with requests.
                'Only small tasks are intended to support interactive=True priority'
            )
            task._interactive = True
        if created or (interactive and task not in self._top_level_tasks()):
            if not task.complete:
                self.project.add_task(task)
    
    def _top_level_tasks(self) -> Sequence[Task]:
        if is_foreground_thread():
            return self.project.root_task.children
        else:
            return list(self.project.root_task.children_unsynchronized)  # clone a snapshot
    
    # Soft Deprecated: Use get_or_create_download_task() instead,
    # which clarifies that an existing task may be returned.
    def create_download_task(self, *args, **kwargs) -> DownloadResourceTask:
        """
        Gets/creates a Task to download this resource and all its embedded resources.
        Returns the task.
        
        The caller is responsible for adding a returned created Task as the child of an
        appropriate parent task so that the UI displays it.
        
        A created task may be complete immediately after initialization,
        and a looked up task may be complete.
        """
        (task, _) = self.get_or_create_download_task(*args, **kwargs)
        return task
    
    def get_download_task(self,
            *, needs_result: bool=True,
            ) -> DownloadResourceTask | None:
        """
        Gets an existing Task to download this resource and all its embedded resources,
        or None if no such task exists.
        
        A looked up task may be complete.
        """
        try:
            (task, created) = self.get_or_create_download_task(
                needs_result=needs_result,
                _get_only=True,
            )
        except _TaskNotFoundException:
            return None
        else:
            assert not created
            return task
    
    def get_or_create_download_task(self,
            *, needs_result: bool=True,
            is_embedded: bool=False,
            _get_only: bool=False,
            ) -> Tuple[DownloadResourceTask, bool]:
        """
        Gets/creates a Task to download this resource and all its embedded resources.
        Returns the task and whether it was created.
        
        The caller is responsible for adding a returned created Task as the child of an
        appropriate parent task so that the UI displays it.
        
        A created task may be complete immediately after initialization,
        and a looked up task may be complete.
        """
        if _get_only:
            def task_factory() -> DownloadResourceTask:
                raise _TaskNotFoundException()
        else:
            def task_factory() -> DownloadResourceTask:
                from crystal.task import DownloadResourceTask
                return DownloadResourceTask(self, needs_result=needs_result, is_embedded=is_embedded)
        if needs_result:
            if self._download_task_ref is None:
                self._download_task_ref = _WeakTaskRef()
            task_ref = self._download_task_ref
        else:
            if self._download_task_ref is not None:
                task_ref = self._download_task_ref
            else:
                if self._download_task_noresult_ref is None:
                    self._download_task_noresult_ref = _WeakTaskRef()
                task_ref = self._download_task_noresult_ref
        return self._get_task_or_create(task_ref, task_factory)
    
    def _get_task_or_create(self,
            task_ref: _WeakTaskRef,
            task_factory: Callable[[], _TK]
            ) -> tuple[_TK, bool]:
        """
        Gets/creates a task.
        Returns the task and whether it was created.
        """
        if task_ref.task is not None:
            return (task_ref.task, False)
        else:
            task = task_factory()
            task_ref.task = task
            return (task, True)
    
    # === Revisions ===
    
    @fg_affinity
    def has_any_revisions(self) -> bool:
        """
        Returns whether any revisions of this resource have been downloaded.
        """
        if self._definitely_has_no_revisions:
            return False
        
        with closing(self.project._db.cursor()) as c:
            c.execute('select 1 from resource_revision where resource_id=? limit 1', (self._id,))
            return c.fetchone() is not None
    
    @fg_affinity
    def default_revision(self, *, stale_ok: bool=True) -> ResourceRevision | None:
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
                if not revision.is_stale:
                    return revision
        return None
    
    @fg_affinity
    def revisions(self, *, reversed: bool=False) -> Iterable[ResourceRevision]:
        """
        Loads and returns a list of `ResourceRevision`s downloaded for this resource.
        If no such revisions exist, an empty list is returned.
        
        Revisions will be returned in the order they were downloaded,
        from least-recent to most-recent.
        """
        from crystal.model.resource_revision import ResourceRevision
        
        if self._definitely_has_no_revisions:
            return
        
        RR = ResourceRevision
        
        ordering = 'asc' if not reversed else 'desc'
        
        with closing(self.project._db.cursor()) as c:
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
    
    @fg_affinity
    def revision_for_etag(self) -> dict[str, ResourceRevision]:
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
        
        Raises:
        * ProjectReadOnlyError
        """
        new_url = self.normalized_url
        if new_url == self._url:
            return True
        return self._try_alter_url(new_url)
    
    def _try_alter_url(self, new_url: str) -> bool:
        """
        Tries to alter this resource's URL to new specified URL,
        unless there is already an existing resource with that URL.
        
        Raises:
        * ProjectReadOnlyError
        """
        from crystal.model.project import ProjectReadOnlyError
        
        project = self.project  # cache
        
        if project.get_resource(new_url) is not None:
            return False
        
        if project.readonly:
            raise ProjectReadOnlyError()
        with project._db, closing(project._db.cursor()) as c:
            c.execute('update resource set url=? where id=?', (new_url, self._id,))
        
        old_url = self._url  # capture
        self._url = new_url
        
        project._resource_did_alter_url(self, old_url, new_url)
        
        return True
    
    # NOTE: Only used from a Python REPL at the moment
    def delete(self) -> None:
        """
        Deletes this resource, including any related revisions.
        
        Raises:
        * ProjectReadOnlyError
        * ValueError -- if this resource is referenced by a RootResource
        * sqlite3.DatabaseError, OSError --
            if the delete partially/fully failed, leaving behind zero or more revisions
        """
        from crystal.model.project import ProjectReadOnlyError
        
        project = self.project
        
        if project.readonly:
            raise ProjectReadOnlyError()
        
        # Ensure not referenced by a RootResource
        with closing(project._db.cursor()) as c:
            root_resource_ids = [
                id
                for (id,) in 
                c.execute('select id from root_resource where resource_id=?', (self._id,))
            ]
        if len(root_resource_ids) > 0:
            raise ValueError(f'Cannot delete {self!r} referenced by RootResource {root_resource_ids!r}')
        
        # Delete ResourceRevision children
        # NOTE: If any revision fails to delete, the remaining revisions will be
        #       left intact. In particular the most-recently downloaded revisions,
        #       including the default_revision(), will be left intact, which
        #       is what most users of Resource care about.
        for rev in list(self.revisions()):
            rev.delete()
        
        project._resource_will_delete(self)
        
        # Delete Resource itself
        with project._db, closing(project._db.cursor()) as c:
            c.execute('delete from resource where id=?', (self._id,))
        self._id = Resource._DELETED_ID
    
    # === Utility ===
    
    def __repr__(self):
        return 'Resource({})'.format(repr(self.url))


class _TaskNotFoundException(Exception):
    pass


# ------------------------------------------------------------------------------
# Utility

def _is_ascii(s: str) -> bool:
    assert isinstance(s, str)
    try:
        s.encode('ascii')
    except UnicodeEncodeError:
        return False
    else:
        return True


# ------------------------------------------------------------------------------

