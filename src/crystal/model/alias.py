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


# ------------------------------------------------------------------------------
# Alias

class Alias:
    """
    An Alias causes URLs with a particular Source URL Prefix to be considered
    equivalent to the URL with the prefix replaced with a Target URL Prefix.
    
    In particular any links to URLs matching the Source URL Prefix of an Alias
    will be rewritten to point to the equivalent URL with the Target URL Prefix.
    
    An alias's target can be marked as External, meaning that it points to a
    live URL on the internet rather than to a downloaded URL in the project.
    
    Persisted and auto-saved.
    """
    project: Project
    _source_url_prefix: str
    _target_url_prefix: str
    _target_is_external: bool
    _id: int | None  # or None if deleted
    
    # === Init ===
    
    @fg_affinity
    def __init__(self,
            project: Project,
            source_url_prefix: str,
            target_url_prefix: str,
            *, target_is_external: bool = False,
            _id: int | None = None) -> None:
        """
        Creates a new alias.
        
        Arguments:
        * project -- associated `Project`.
        * source_url_prefix -- source URL prefix. Must end in '/'.
        * target_url_prefix -- target URL prefix. Must end in '/'.
        * target_is_external -- whether target is external to the project.
        
        Raises:
        * ProjectReadOnlyError
        * Alias.AlreadyExists --
            if there is already an `Alias` with specified `source_url_prefix`.
        * ValueError --
            if `source_url_prefix` or `target_url_prefix` do not end in slash (/).
        * sqlite3.DatabaseError --
            if a database error occurred, preventing the creation of the new Alias.
        """
        project = _resolve_proxy(project)  # type: ignore[assignment]
        if not isinstance(project, Project):
            raise TypeError()
        if not isinstance(source_url_prefix, str):
            raise TypeError()
        if not isinstance(target_url_prefix, str):
            raise TypeError()
        if not isinstance(target_is_external, bool):
            raise TypeError()
        
        # Validate that URL prefixes end in slash
        if not source_url_prefix.endswith('/'):
            raise ValueError('source_url_prefix must end in slash (/)')
        if not target_url_prefix.endswith('/'):
            raise ValueError('target_url_prefix must end in slash (/)')
        
        # Check for duplicate source_url_prefix
        if not project._loading:
            if project.get_alias(source_url_prefix) is not None:
                raise Alias.AlreadyExists(
                    f'Alias with source_url_prefix {source_url_prefix!r} already exists')        
        
        self.project = project
        self._source_url_prefix = source_url_prefix
        self._target_url_prefix = target_url_prefix
        self._target_is_external = target_is_external
        
        if project._loading:
            assert _id is not None
            self._id = _id
        else:
            if project.readonly:
                raise ProjectReadOnlyError()
            with project._db, closing(project._db.cursor()) as c:
                c.execute(
                    'insert into alias (source_url_prefix, target_url_prefix, target_is_external) values (?, ?, ?)',
                    (source_url_prefix, target_url_prefix, int(target_is_external)))
                self._id = c.lastrowid
        project._aliases.append(self)
        
        # Notify listeners if not loading
        if not project._loading:
            project._alias_did_instantiate(self)
    
    # === Delete ===
    
    @fg_affinity
    def delete(self) -> None:
        """
        Deletes this alias.
        
        Raises:
        * ProjectReadOnlyError
        * sqlite3.DatabaseError --
            if the delete fully failed due to a database error
        """
        if self.project.readonly:
            raise ProjectReadOnlyError()
        with self.project._db, closing(self.project._db.cursor()) as c:
            c.execute('delete from alias where id=?', (self._id,))
        self._id = None
        
        self.project._aliases.remove(self)
        
        self.project._alias_did_forget(self)
    
    # === Properties ===
    
    @property
    def source_url_prefix(self) -> str:
        """Source URL prefix. Always ends in '/'."""
        return self._source_url_prefix
    
    def _get_target_url_prefix(self) -> str:
        """
        Target URL prefix. Always ends in '/'.
        
        Setter Raises:
        * sqlite3.DatabaseError
        """
        return self._target_url_prefix
    @fg_affinity
    def _set_target_url_prefix(self, target_url_prefix: str) -> None:
        if not target_url_prefix.endswith('/'):
            raise ValueError('target_url_prefix must end in slash (/)')
        if self._target_url_prefix == target_url_prefix:
            return
        
        if self.project.readonly:
            raise ProjectReadOnlyError()
        with self.project._db, closing(self.project._db.cursor()) as c:
            c.execute('update alias set target_url_prefix=? where id=?', (
                target_url_prefix,
                self._id,))
        
        self._target_url_prefix = target_url_prefix
        
        self.project._alias_did_change(self)
    target_url_prefix = cast(str, property(_get_target_url_prefix, _set_target_url_prefix))
    
    def _get_target_is_external(self) -> bool:
        """Whether target is external to the project."""
        return self._target_is_external
    @fg_affinity
    def _set_target_is_external(self, target_is_external: bool) -> None:
        if not isinstance(target_is_external, bool):
            raise TypeError()
        if self._target_is_external == target_is_external:
            return
        
        if self.project.readonly:
            raise ProjectReadOnlyError()
        with self.project._db, closing(self.project._db.cursor()) as c:
            c.execute('update alias set target_is_external=? where id=?', (
                int(target_is_external),
                self._id,))
        
        self._target_is_external = target_is_external
        
        self.project._alias_did_change(self)
    target_is_external = cast(bool, property(_get_target_is_external, _set_target_is_external))
    
    # === External URLs ===
    
    @staticmethod
    def format_external_url(external_url: str) -> str:
        """
        Given an external URL (pointing to a live resource on the internet),
        returns the corresponding archive URL that should be used internally
        within the project to represent this external resource.
        
        Example:
        >>> Alias.format_external_url('https://example.com/page')
        'crystal://external/https://example.com/page'
        """
        return f'crystal://external/{external_url}'
    
    @staticmethod
    def parse_external_url(archive_url: str) -> str | None:
        """
        Given an archive URL, returns the corresponding external URL if the
        archive URL represents an external resource, or None otherwise.
        
        Example:
        >>> Alias.parse_external_url('crystal://external/https://example.com/page')
        'https://example.com/page'
        >>> Alias.parse_external_url('https://example.com/page')
        None
        """
        prefix = 'crystal://external/'
        if archive_url.startswith(prefix):
            return archive_url[len(prefix):]
        else:
            return None
    
    @staticmethod
    def format_external_url_for_display(external_url: str) -> str:
        return f'🌐 {external_url}'
    
    # === Utility ===
    
    def __repr__(self):
        if self.target_is_external:
            return f'Alias({self.source_url_prefix!r}, {self.target_url_prefix!r}, target_is_external={True!r})'
        else:
            return f'Alias({self.source_url_prefix!r}, {self.target_url_prefix!r})'
    
    class AlreadyExists(Exception):
        """
        Raised when an attempt is made to create a new `Alias` with a
        `source_url_prefix` that is already used by an existing `Alias`.
        """
        pass


# ------------------------------------------------------------------------------
