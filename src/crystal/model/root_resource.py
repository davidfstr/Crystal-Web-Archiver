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
        pass


# ------------------------------------------------------------------------------