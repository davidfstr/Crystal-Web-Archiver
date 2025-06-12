"""
Persistent data model.

Unless otherwise specified, all changes to models are auto-saved.

Model objects may only be manipulated on the foreground thread.
Callers that attempt to do otherwise may get thrown `ProgrammingError`s.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import Future
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
    CancelLoadUrls, CancelOpenProject, DummyLoadUrlsProgressListener,
    DummyOpenProjectProgressListener, LoadUrlsProgressListener,
    OpenProjectProgressListener, VetoUpgradeProject,
)
from crystal.util import gio, http_date, xcgi, xshutil
from crystal.util.bulkheads import (
    capture_crashes_to_bulkhead_arg as capture_crashes_to_task_arg,
)
from crystal.util.bulkheads import capture_crashes_to_stderr, run_bulkhead_call
from crystal.util.db import (
    DatabaseConnection, DatabaseCursor, get_column_names_of_table,
    get_index_names, is_no_such_column_error_for,
)
from crystal.util.ellipsis import Ellipsis, EllipsisType
from crystal.util.listenable import ListenableMixin
from crystal.util.profile import create_profiling_context, warn_if_slow
from crystal.util.progress import DevNullFile
from crystal.util.ssd import is_ssd
from crystal.util.test_mode import tests_are_running
from crystal.util.urls import is_unrewritable_url, requote_uri
from crystal.util.windows_attrib import set_windows_file_attrib
from crystal.util.xbisect import bisect_key_right
from crystal.util.xcollections.ordereddict import as_ordereddict
from crystal.util.xcollections.sortedlist import BLACK_HOLE_SORTED_LIST
from crystal.util.xdatetime import datetime_is_aware
from crystal.util.xgc import gc_disabled
from crystal.util.xos import is_linux, is_mac_os, is_windows
from crystal.util.xsqlite3 import sqlite_has_json_support
from crystal.util.xthreading import (
    bg_affinity, bg_call_later, fg_affinity, fg_call_and_wait, fg_call_later,
    is_foreground_thread,
)
import datetime
import json
import math
import mimetypes
import os
import pathlib
import re
from re import Pattern
import shutil
from sortedcontainers import SortedList
import sqlite3
import sys
from tempfile import NamedTemporaryFile
from textwrap import dedent
import threading
from tqdm import tqdm
import traceback
from typing import (
    Any, BinaryIO, cast, Dict, Generic, List, Literal, Optional, Self, Tuple,
    TYPE_CHECKING, TypedDict, TypeVar, Union,
)
from typing_extensions import deprecated, override
from urllib.parse import quote as url_quote
from urllib.parse import urlparse, urlunparse
from weakref import WeakValueDictionary

if TYPE_CHECKING:
    from crystal.doc.generic import Document, Link
    from crystal.doc.html import HtmlParserType
    from crystal.task import (
        DownloadResourceBodyTask, DownloadResourceGroupTask,
        DownloadResourceTask, Task,
    )


# Whether to collect profiling information about Project._apply_migrations().
# 
# When True, a 'migrate_revisions.prof' file is written to the current directory
# after all projects have been closed. Such a file can be converted
# into a visual flamegraph using the "flameprof" PyPI module,
# or analyzed using the built-in "pstats" module.
_PROFILE_MIGRATE_REVISIONS = False


_OptionalStr = TypeVar('_OptionalStr', bound=Optional[str])
_TK = TypeVar('_TK', bound='Task')


class Project(ListenableMixin):
    """
    Groups together a set of resources that are downloaded and any associated settings.
    Persisted and auto-saved.
    """
    
    FILE_EXTENSION = '.crystalproj'
    OPENER_FILE_EXTENSION = '.crystalopen'
    
    # Project structure constants
    _DB_FILENAME = 'database.sqlite'
    _LATEST_SUPPORTED_MAJOR_VERSION = 2
    _REVISIONS_DIRNAME = 'revisions'
    _IN_PROGRESS_REVISIONS_DIRNAME = 'revisions.inprogress'
    _TEMPORARY_DIRNAME = 'tmp'
    _OPENER_DEFAULT_FILENAME = 'OPEN ME' + OPENER_FILE_EXTENSION
    _OPENER_DEFAULT_CONTENT = b'CrOp'  # Crystal Opener, as a FourCC
    _README_FILENAME = 'README.txt'
    # Define README.txt which explains what a .crystalproj is to a user that
    # does not have Crystal installed.
    # 
    # NOTE: Use Windows-style CRLF line endings, assuming that most text editors
    #       in Linux and macOS are more tolerant of foreign newline sequences
    #       than those in Windows.
    _README_DEFAULT_CONTENT = dedent(
        '''
        This .crystalproj directory is a Crystal Project, which contains one or more
        downloaded websites and associated web pages.

        You can view the websites in this project by installing Crystal from
        https://dafoster.net/projects/crystal-web-archiver/ and double-clicking the
        "OPEN ME" file in this directory.

        To avoid damaging the downloaded websites, please do not rename, move, or
        delete any files in this directory.
        '''.lstrip('\n')
    ).replace('\n', '\r\n')
    _DESKTOP_INI_FILENAME = 'desktop.ini'
    # Define desktop.ini file for Windows that:
    # - Defines icon for the .crystalproj directory
    # - Defines tooltip for the .crystalproj directory
    # - Associates directory with the "crystalproj" Directory Class in registry,
    #   which defines which .exe to open it with
    # 
    # References:
    # - https://learn.microsoft.com/en-us/windows/win32/shell/how-to-customize-folders-with-desktop-ini
    # - https://learn.microsoft.com/en-us/windows/win32/shell/how-to-implement-custom-verbs-for-folders-through-desktop-ini
    # 
    # NOTE: Use Windows-style CRLF line endings because this is a Windows-specific file
    _DESKTOP_INI_CONTENT = dedent(
        r'''
        [.ShellClassInfo]
        DirectoryClass=crystalproj
        ConfirmFileOp=0
        IconFile=icons\docicon.ico
        IconIndex=0
        InfoTip=Crystal Project
        '''.lstrip('\n')
    ).replace('\n', '\r\n')
    _ICONS_DIRNAME = 'icons'
    
    _MAX_REVISION_ID = (2 ** 60) - 1  # for projects with major version >= 2
    
    # NOTE: Only changed when tests are running
    _last_opened_project: Project | None=None
    _report_progress_at_maximum_resolution: bool=False
    
    # === Load ===
    
    @fg_affinity
    def __init__(self,
            path: str,
            progress_listener: OpenProjectProgressListener | None=None,
            load_urls_progress_listener: LoadUrlsProgressListener | None=None,
            *, readonly: bool=False) -> None:
        """
        Loads a project from the specified itempath, or creates a new one if none is found.
        
        Arguments:
        * path -- 
            path to a project directory (ending with `FILE_EXTENSION`)
            or to a project opener (ending with `OPENER_FILE_EXTENSION`).
        
        Raises:
        * FileNotFoundError --
            if readonly is True and no project already exists at the specified path
        * ProjectFormatError -- if the project at the specified path is invalid
        * ProjectTooNewError -- 
            if the project is a version newer than this version of Crystal can open safely
        * CancelOpenProject
        """
        super().__init__()
        
        if progress_listener is None:
            progress_listener = DummyOpenProjectProgressListener()
        if load_urls_progress_listener is None:
            load_urls_progress_listener = DummyLoadUrlsProgressListener()
        self._load_urls_progress_listener = load_urls_progress_listener
        
        # Remove any trailing slash from the path
        (head, tail) = os.path.split(path)
        if len(tail) == 0:
            path = head  # reinterpret
        
        # Normalize path
        normalized_path = self._normalize_project_path(path)  # reinterpret
        if normalized_path is None:
            raise ProjectFormatError(f'Project does not end with {self.FILE_EXTENSION}')
        path = normalized_path  # reinterpret
        
        self.path = path
        
        self._properties = dict()               # type: Dict[str, Optional[str]]
        self._resource_for_url = WeakValueDictionary()  # type: Union[WeakValueDictionary[str, Resource], OrderedDict[str, Resource]]
        self._resource_for_id = WeakValueDictionary()   # type: Union[WeakValueDictionary[int, Resource], OrderedDict[int, Resource]]
        self._sorted_resource_urls = None       # type: Optional[SortedList[str]]
        self._root_resources = OrderedDict()    # type: Dict[Resource, RootResource]
        self._resource_groups = []              # type: List[ResourceGroup]
        self._readonly = True  # will reinitialize after database is located
        
        self._min_fetch_date = None  # type: Optional[datetime.datetime]
        
        progress_listener.opening_project()
        
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
                os.mkdir(os.path.join(path, self._REVISIONS_DIRNAME))
                
                # TODO: Consider let _apply_migrations() define the rest of the
                #       project structure, rather than duplicating logic here
                os.mkdir(os.path.join(path, self._TEMPORARY_DIRNAME))
                with open(os.path.join(path, self._OPENER_DEFAULT_FILENAME), 'wb') as f:
                    f.write(self._OPENER_DEFAULT_CONTENT)
                with open(os.path.join(self.path, self._README_FILENAME), 'w', newline='') as tf:
                    tf.write(self._README_DEFAULT_CONTENT)
                with open(os.path.join(self.path, self._DESKTOP_INI_FILENAME), 'w', newline='') as tf:
                    tf.write(self._DESKTOP_INI_CONTENT)
                os.mkdir(os.path.join(path, self._ICONS_DIRNAME))
                with resources_.open_binary('docicon.ico') as src_file:
                    with open(os.path.join(path, self._ICONS_DIRNAME, 'docicon.ico'), 'wb') as dst_file:
                        shutil.copyfileobj(src_file, dst_file)
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
            db = sqlite3.connect(
                'file:' + url_quote(db_filepath) + db_connect_query,
                uri=True)
            
            try:
                self._database_is_on_ssd = is_ssd(db_filepath)
            except Exception:
                # NOTE: Specially check for unexpected errors because SSD detection
                #       is somewhat brittle and I don't want errors to completely
                #       block opening a project
                print(
                    '*** Unexpected error while checking whether project database is on SSD',
                    file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                
                self._database_is_on_ssd = False  # conservative
            
            self._readonly = readonly or not can_write_db
            self._db = DatabaseConnection(db, lambda: self.readonly)
            try:
                # Enable use of REGEXP operator and regexp() function
                db.create_function('regexp', 2, lambda x, y: re.search(x, y) is not None)
                
                c = self._db.cursor()
                
                # Create new project content, if missing
                if create:
                    self._create(c, self._db)
                
                # Load from existing project
                # NOTE: Don't provide detailed feedback when creating a project initially
                load_progress_listener = (
                    progress_listener if not create
                    else DummyOpenProjectProgressListener()
                )
                self._load(c, self._db, load_progress_listener)
            except:
                self.close()
                raise
        finally:
            self._loading = False
        
        # Hold on to the root task and scheduler
        import crystal.task
        self.root_task = crystal.task.RootTask()
        crystal.task.start_schedule_forever(self.root_task)
        
        # Define initial configuration
        self._request_cookie = None  # type: Optional[str]
        
        self._check_url_collection_invariants()
        
        # Export reference to self, if running tests
        if tests_are_running():
            Project._last_opened_project = self
    
    # --- Load: Validity ---
    
    @classmethod
    def is_valid(cls, path: str) -> bool:
        """
        Returns whether there appears to be a minimally valid project
        at the specified path.
        """
        normalized_path = cls._normalize_project_path(path)
        if normalized_path is None:
            return False
        try:
            Project._ensure_valid(normalized_path)
        except ProjectFormatError:
            return False
        else:
            return True
    
    @classmethod
    def _normalize_project_path(cls, path: str) -> str | None:
        if os.path.exists(path):
            # Try to alter existing path to point to item ending with FILE_EXTENSION
            if path.endswith(cls.FILE_EXTENSION):
                return path
            elif path.endswith(cls.OPENER_FILE_EXTENSION):
                parent_itempath = os.path.dirname(path)
                if parent_itempath.endswith(cls.FILE_EXTENSION):
                    return parent_itempath
        else:
            # Ensure new path ends with FILE_EXTENSION
            if path.endswith(cls.FILE_EXTENSION):
                return path
            else:
                return path + cls.FILE_EXTENSION
        return None  # invalid
    
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
        
        revision_dirpath = os.path.join(path, Project._REVISIONS_DIRNAME)
        if not os.path.isdir(revision_dirpath):
            raise ProjectFormatError(f'Project is missing revisions directory: {revision_dirpath}')
    
    # --- Load: Migrations ---
    
    def _apply_migrations(self,
            c: DatabaseCursor,
            commit: Callable[[], None],
            progress_listener: OpenProjectProgressListener) -> None:
        """
        Upgrades this project's directory structure and database schema
        to the latest version.
        
        Raises:
        * ProjectReadOnlyError
        * CancelOpenProject
        """
        # Add missing database columns and indexes
        if True:
            index_names = get_index_names(c)  # cache
            
            # Add resource_group.do_not_download column if missing
            if 'do_not_download' not in get_column_names_of_table(c, 'resource_group'):
                progress_listener.upgrading_project('Adding do-not-download status to resource groups...')
                c.execute('alter table resource_group add column do_not_download integer not null default 0')
            
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
            
            commit()
        
        # Add missing directory structures
        if True:
            # Add temporary directory if missing
            tmp_dirpath = os.path.join(self.path, self._TEMPORARY_DIRNAME)
            if not os.path.exists(tmp_dirpath):
                os.mkdir(tmp_dirpath)
            
            # Add opener and README if missing
            if not any([n for n in os.listdir(self.path) if n.endswith(self.OPENER_FILE_EXTENSION)]):
                # Add missing opener
                with open(os.path.join(self.path, self._OPENER_DEFAULT_FILENAME), 'wb') as f:
                    f.write(self._OPENER_DEFAULT_CONTENT)
                
                # Add README if not already there
                readme_filepath = os.path.join(self.path, self._README_FILENAME)
                if not os.path.exists(readme_filepath):
                    with open(readme_filepath, 'w', newline='') as tf:
                        tf.write(self._README_DEFAULT_CONTENT)
            
            # Add Windows desktop.ini and icon for .crystalproj if missing
            desktop_ini_filepath = os.path.join(self.path, self._DESKTOP_INI_FILENAME)
            if not os.path.exists(desktop_ini_filepath):
                with open(desktop_ini_filepath, 'w', newline='') as tf:
                    tf.write(self._DESKTOP_INI_CONTENT)
                
                icons_dirpath = os.path.join(self.path, self._ICONS_DIRNAME)
                if not os.path.exists(icons_dirpath):
                    os.mkdir(icons_dirpath)
                    
                    with resources_.open_binary('docicon.ico') as src_file:
                        with open(os.path.join(icons_dirpath, 'docicon.ico'), 'wb') as dst_file:
                            shutil.copyfileobj(src_file, dst_file)
            
            # Add Linux icon for .crystalproj if missing
            if True:
                # GNOME: Define icon in GIO database
                if is_linux():
                    did_set_gio_icon = False
                    
                    # GNOME Files (AKA Nautilus)
                    try:
                        gio.set(self.path, 'metadata::custom-icon-name', 'crystalproj')
                    except gio.GioNotAvailable:
                        pass
                    except gio.UnrecognizedGioAttributeError:
                        # For example Kubuntu 22 does not recognize this attribute
                        pass
                    else:
                        did_set_gio_icon = True
                    
                    # GNOME Desktop Items Shell Extension
                    # 
                    # HACK: Must also set icon location as a brittle absolute path
                    #       because Desktop Items doesn't understand the
                    #       'metadata::custom-icon-name' GIO attribute.
                    crystalproj_png_icon_url = pathlib.Path(
                        resources_.get_filepath('docicon.png')
                    ).as_uri()
                    try:
                        gio.set(self.path, 'metadata::custom-icon', crystalproj_png_icon_url)
                    except gio.GioNotAvailable:
                        pass
                    except gio.UnrecognizedGioAttributeError:
                        # For example Kubuntu 22 does not recognize this attribute
                        pass
                    else:
                        did_set_gio_icon = True
                    
                    # Touch .crystalproj so that GNOME Files (AKA Nautilus)
                    # observes the icon change
                    if did_set_gio_icon:
                        pathlib.Path(self.path).touch()
                
                # KDE: Define icon in .directory file
                dot_directory_filepath = os.path.join(self.path, '.directory')
                if not os.path.exists(dot_directory_filepath):
                    with open(dot_directory_filepath, 'w') as tf:
                        tf.write('[Desktop Entry]\nIcon=crystalproj\n')
            
            # Set Windows-specific file attributes, if not already done
            if is_windows():
                # Mark .crystalproj as System,
                # so that icon defined by desktop.ini is used
                set_windows_file_attrib(self.path, ['+s'])
                
                # Mark desktop.ini as Hidden & System
                set_windows_file_attrib(desktop_ini_filepath, ['+h', '+s'])
                
                # Mark .directory as Hidden
                set_windows_file_attrib(dot_directory_filepath, ['+h'])
        
        # Apply major version migrations
        if True:
            # Get the project's major version
            major_version = self._get_major_version(c)
            
            # Upgrade major version 1 -> 2
            if major_version == 1:
                revisions_dirpath = os.path.join(
                    self.path, self._REVISIONS_DIRNAME)  # cache
                ip_revisions_dirpath = os.path.join(
                    self.path, self._IN_PROGRESS_REVISIONS_DIRNAME)  # cache
                tmp_revisions_dirpath = os.path.join(
                    self.path, self._TEMPORARY_DIRNAME, self._REVISIONS_DIRNAME)  # cache
                
                # Ensure old revisions directory exists
                assert os.path.isdir(revisions_dirpath)
                
                # 1. Confirm want to migrate now
                # 2. Create new revisions directory
                def will_upgrade_revisions(approx_revision_count: int) -> None:
                    """
                    Raises:
                    * VetoUpgradeProject
                    * CancelOpenProject
                    """
                    migration_was_in_progress = os.path.isdir(ip_revisions_dirpath)  # capture
                    
                    if approx_revision_count > Project._MAX_REVISION_ID:
                        assert not migration_was_in_progress
                        
                        # Veto the migration automatically because it would fail
                        # due to inability to migrate revisions with very high IDs
                        raise VetoUpgradeProject()
                    
                    try:
                        progress_listener.will_upgrade_revisions(
                            approx_revision_count,
                            can_veto=not migration_was_in_progress)
                    except VetoUpgradeProject:
                        if migration_was_in_progress:
                            raise AssertionError('Cannot veto migration that was in progress')
                        raise
                    except CancelOpenProject:
                        raise
                    
                    # Create new revisions directory
                    if not migration_was_in_progress:
                        os.mkdir(ip_revisions_dirpath)
                
                # Move revisions to appropriate locations in new revisions directory
                os_path_sep = os.path.sep  # cache
                last_new_revision_parent_relpath = None  # type: Optional[str]
                def migrate_revision(row: tuple) -> None:
                    (id,) = row
                    old_revision_filepath = (
                        revisions_dirpath + os_path_sep +
                        str(id)
                    )
                    
                    new_revision_filepath_parts = f'{id:015x}'
                    if len(new_revision_filepath_parts) != 15:
                        # NOTE: Raising an AssertionError rather than a
                        #       ProjectHasTooManyRevisionsError because
                        #       will_upgrade_revisions() should have detected
                        #       this case early and not permitted the upgrade
                        #       to continue
                        raise AssertionError(
                            'Revision ID {id} is too high to migrate to the '
                            'major version 2 project format')
                    new_revision_parent_relpath = (
                        new_revision_filepath_parts[0:3] + os_path_sep +
                        new_revision_filepath_parts[3:6] + os_path_sep +
                        new_revision_filepath_parts[6:9] + os_path_sep +
                        new_revision_filepath_parts[9:12]
                    )
                    new_revision_filepath = (
                        ip_revisions_dirpath + os_path_sep + 
                        new_revision_parent_relpath + os_path_sep +
                        new_revision_filepath_parts[12:15]
                    )
                    
                    # Create parent directory for new location if needed
                    # 
                    # NOTE: Avoids extra calls to os.makedirs() when easy to
                    #       prove that there's no work to be done
                    nonlocal last_new_revision_parent_relpath
                    if new_revision_parent_relpath != last_new_revision_parent_relpath:
                        new_revision_parent_dirpath = \
                            ip_revisions_dirpath + os_path_sep + new_revision_parent_relpath
                        os.makedirs(new_revision_parent_dirpath, exist_ok=True)
                        last_new_revision_parent_relpath = new_revision_parent_relpath
                    
                    # Move revision from old location to new location
                    try:
                        os.rename(old_revision_filepath, new_revision_filepath)
                    except FileNotFoundError:
                        # Either:
                        # 1. Revision has already been moved from old location to new location
                        #    (if this migration is being resumed from an earlier canceled migration)
                        # 2. Revision was missing in old location before, and will be missing in new location.
                        pass
                # TODO: Dump profiling context immediately upon exit of context
                #       rather then waiting to program to exit
                with create_profiling_context(
                        'migrate_revisions.prof', enabled=_PROFILE_MIGRATE_REVISIONS):
                    try:
                        self._process_table_rows(
                            c,
                            # NOTE: The following query to approximate row count is
                            #       significantly faster than the exact query
                            #       ('select count(1) from resource_revision') because it
                            #       does not require a full table scan.
                            'select id from resource_revision order by id desc limit 1',
                            'select id from resource_revision order by id asc',
                            migrate_revision,
                            will_upgrade_revisions,
                            progress_listener.upgrading_revision,
                            progress_listener.did_upgrade_revisions)
                    except CancelOpenProject:
                        raise
                    except VetoUpgradeProject:
                        pass
                    else:
                        # Move aside old revisions directory and queue it for deletion
                        os.rename(revisions_dirpath, tmp_revisions_dirpath)
                        
                        # Move new revisions directory to final location
                        os.rename(ip_revisions_dirpath, revisions_dirpath)
                        
                        # Commit upgrade
                        major_version = 2
                        self._set_major_version(major_version, c, commit)
            
            # At latest major version 2
            if major_version == 2:
                # Nothing to do
                pass
            assert self._LATEST_SUPPORTED_MAJOR_VERSION == 2
    
    @staticmethod
    def _get_major_version(c: DatabaseCursor) -> int:
        rows = list(c.execute(
            'select value from project_property where name = ?',
            ('major_version',)))
        if len(rows) == 0:
            major_version = 1
        else:
            [(major_version_str,)] = rows
            major_version = int(major_version_str)
        return major_version
    
    @staticmethod
    def _set_major_version(major_version: int, c: DatabaseCursor, commit: Callable[[], None]) -> None:
        c.execute(
            'insert or replace into project_property (name, value) values (?, ?)',
            ('major_version', major_version))
        commit()
    
    # --- Load: Create & Load ---
    
    def _create(self, c: DatabaseCursor, db: DatabaseConnection) -> None:
        c.execute('create table project_property (name text unique not null, value text)')
        c.execute('create table resource (id integer primary key, url text unique not null)')
        c.execute('create table root_resource (id integer primary key, name text not null, resource_id integer unique not null, foreign key (resource_id) references resource(id))')
        c.execute('create table resource_group (id integer primary key, name text not null, url_pattern text not null, source_type text, source_id integer)')
        c.execute('create table resource_revision (id integer primary key, resource_id integer not null, request_cookie text, error text not null, metadata text not null)')
        c.execute('create index resource_revision__resource_id on resource_revision (resource_id)')
        
        # (Define indexes later in _apply_migrations())
        
        # Set property values
        if True:
            # Define major version for new projects, for Crystal >1.6.0
            self._set_major_version(2, c, db.commit)
            
            # Define default HTML parser for new projects, for Crystal >1.5.0
            self.html_parser_type = 'lxml'
    
    def _load(self,
            c: DatabaseCursor,
            db: DatabaseConnection,
            progress_listener: OpenProjectProgressListener) -> None:
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
            self._apply_migrations(c, db.commit, progress_listener)
        
        # Ensure major version is recognized
        major_version = self._get_major_version(c)
        if major_version > self._LATEST_SUPPORTED_MAJOR_VERSION:
            raise ProjectTooNewError(
                f'Project has major version {major_version} but this '
                f'version of Crystal only knows how to open projects '
                f'with major version {self._LATEST_SUPPORTED_MAJOR_VERSION} '
                f'or less')
        
        # Cleanup any temporary files from last session (unless is readonly)
        if not self.readonly:
            tmp_dirpath = os.path.join(self.path, self._TEMPORARY_DIRNAME)
            if os.path.exists(tmp_dirpath):
                for tmp_filename in os.listdir(tmp_dirpath):
                    tmp_filepath = os.path.join(tmp_dirpath, tmp_filename)
                    if os.path.isfile(tmp_filepath):
                        os.remove(tmp_filepath)
                    else:
                        shutil.rmtree(tmp_filepath)
        
        # Load project properties
        for (name, value) in c.execute('select name, value from project_property'):
            self._set_property(name, value)
        
        # Load RootResources
        [(root_resource_count,)] = c.execute('select count(1) from root_resource')
        progress_listener.loading_root_resources(root_resource_count)
        for (name, resource_id, id) in c.execute('select name, resource_id, id from root_resource'):
            resource = self._get_resource_with_id(resource_id)
            if resource is None:
                raise ProjectFormatError(f'RootResource {id} references Resource {resource_id} which does not exist')
            RootResource(self, name, resource, _id=id)
        
        # Load ResourceGroups
        [(resource_group_count,)] = c.execute('select count(1) from resource_group')
        progress_listener.loading_resource_groups(resource_group_count)
        group_2_source = {}
        do_not_download_column = (
            'do_not_download' if 'do_not_download' in get_column_names_of_table(c, 'resource_group')
            else '0'  # default value for do_not_download column
        )
        for (index, (name, url_pattern, source_type, source_id, do_not_download, id)) in enumerate(c.execute(
                f'select name, url_pattern, source_type, source_id, {do_not_download_column}, id from resource_group')):
            group = ResourceGroup(self, name, url_pattern, source=Ellipsis, do_not_download=do_not_download, _id=id)
            group_2_source[group] = (source_type, source_id)
        for (group, (source_type, source_id)) in group_2_source.items():
            if source_type is None:
                source_obj = None  # type: ResourceGroupSource
            elif source_type == 'root_resource':
                source_obj = self._get_root_resource_with_id(source_id)
            elif source_type == 'resource_group':
                source_obj = self._get_resource_group_with_id(source_id)
            else:
                raise ProjectFormatError('Resource group {} has invalid source type "{}".'.format(group._id, source_type))
            group.init_source(source_obj)
        
        # (ResourceRevisions are loaded on demand)
    
    # --- Load: Utility ---
    
    @staticmethod
    def _process_table_rows(
            c: DatabaseCursor,
            approx_row_count_query: str,
            rows_query: str,
            process_row_func: Callable[[tuple], None],
            report_approx_row_count_func: Callable[[int], None],
            report_processing_row_func: Callable[[int, float], None],
            report_did_process_rows_func: Callable[[int], None],
            ) -> None:
        TARGET_MAX_DELAY_BETWEEN_REPORTS = 1.0  # seconds
        
        rows = list(c.execute(approx_row_count_query))
        if len(rows) == 1:
            [(approx_row_count,)] = rows
        else:
            assert len(rows) == 0
            approx_row_count = 0
        report_approx_row_count_func(approx_row_count)  # may raise
        
        # NOTE: Initialize before initializing ProgressBar
        index = 0
        
        # Configure tqdm to efficiently report process approximately every
        # TARGET_MAX_DELAY_BETWEEN_REPORTS seconds
        with Project._ProcessTableRows_ProgressBar(
            report_processing_row_func=report_processing_row_func,
            index_func=lambda: index,
            initial=0,
            total=approx_row_count,
            mininterval=(
                TARGET_MAX_DELAY_BETWEEN_REPORTS
                if not Project._report_progress_at_maximum_resolution
                else 0
            ),
            miniters=(
                None  # dynamic
                if not Project._report_progress_at_maximum_resolution
                else 0
            ),
            file=DevNullFile(),
        ) as progress_bar:
            row_count = 0
            with gc_disabled():  # don't garbage collect while allocating many objects
                for (index, row) in enumerate(c.execute(rows_query)):
                    progress_bar.update()
                    process_row_func(row)  # may raise
                    row_count += 1
        
        report_did_process_rows_func(row_count)  # may raise
    
    class _ProcessTableRows_ProgressBar(tqdm):
        def __init__(self,
                *, report_processing_row_func: Callable[[int, float], None],
                index_func: Callable[[], int],
                **kwargs) -> None:
            self._report_processing_row_func = report_processing_row_func
            self._index_func = index_func
            
            self._initializing = True
            super().__init__(**kwargs)
            self._initializing = False
        
        @override
        def refresh(self, nolock=False, lock_args=None):
            return super().refresh(nolock=True, lock_args=lock_args)
        
        @override
        def display(self, *args, **kwargs) -> None:
            if not self._initializing:
                self._report_processing_row_func(
                    self._index_func(),
                    self.miniters
                )  # may raise
    
    # === Properties ===
    
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
    
    def _get_property(self, name: str, default: _OptionalStr) -> str | _OptionalStr:
        return self._properties.get(name) or default
    def _set_property(self, name: str, value: str | None) -> None:
        if not self._loading:
            if self._properties.get(name) == value:
                return
            if self.readonly:
                raise ProjectReadOnlyError()
            c = self._db.cursor()
            c.execute('insert or replace into project_property (name, value) values (?, ?)', (name, value))
            self._db.commit()
        self._properties[name] = value
    def _delete_property(self, name: str) -> None:
        if not self._loading:
            if name not in self._properties:
                return
            if self.readonly:
                raise ProjectReadOnlyError()
            c = self._db.cursor()
            c.execute('delete from project_property where name=?', (name,))
            self._db.commit()
        del self._properties[name]
    
    @property
    def major_version(self) -> int:
        """
        Major version of this project.
        
        Crystal will refuse to open a project with a later major version than
        it knows how to read, with a ProjectTooNewError.
        
        Crystal will permit opening projects with a major version that is
        older than the latest supported major version, even without upgrading
        the project's version, because the project may be stored on a read-only
        volume such as a DVD, CD, or BluRay disc.
        """
        return int(self._get_property('major_version', '1'))
    
    def _get_default_url_prefix(self) -> str | None:
        """
        URL prefix for the majority of this project's resource URLs.
        The UI will display resources under this prefix as relative URLs.
        """
        return self._get_property('default_url_prefix', None)
    def _set_default_url_prefix(self, value: str | None) -> None:
        self._set_property('default_url_prefix', value)
    default_url_prefix = cast(Optional[str], property(_get_default_url_prefix, _set_default_url_prefix))
    
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
    
    def _get_html_parser_type(self) -> HtmlParserType:
        value = self._get_property(
            'html_parser_type',
            # Default HTML parser for classic projects from Crystal <=1.5.0
            'html_parser')
        from crystal.doc.html import HTML_PARSER_TYPE_CHOICES
        if value not in HTML_PARSER_TYPE_CHOICES:
            raise ValueError(f'Project requests HTML parser of unknown type: {value}')
        return cast('HtmlParserType', value)
    def _set_html_parser_type(self, value: HtmlParserType) -> None:
        from crystal.doc.html import HTML_PARSER_TYPE_CHOICES
        if value not in HTML_PARSER_TYPE_CHOICES:
            raise ValueError(f'Unknown type of HTML parser: {value}')
        self._set_property('html_parser_type', value)
    html_parser_type = property(_get_html_parser_type, _set_html_parser_type, doc=
        """
        The type of parser used for parsing links from HTML documents.
        """)
    
    def _get_request_cookie(self) -> str | None:
        return self._request_cookie
    def _set_request_cookie(self, request_cookie: str | None) -> None:
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
    
    def request_cookies_in_use(self, *, most_recent_first: bool=True) -> list[str]:
        """
        Returns all distinct Cookie HTTP header values used by revisions in this project.
        """
        ordering = 'desc' if most_recent_first else 'asc'
        
        c = self._db.cursor()
        return [
            rc for (rc,) in
            c.execute(f'select distinct request_cookie from resource_revision where request_cookie is not null order by id {ordering}')
        ]
    
    def _get_min_fetch_date(self) -> datetime.datetime | None:
        return self._min_fetch_date
    def _set_min_fetch_date(self, min_fetch_date: datetime.datetime | None) -> None:
        if min_fetch_date is not None:
            if not datetime_is_aware(min_fetch_date):
                raise ValueError('Expected an aware datetime (with a UTC offset)')
        self._min_fetch_date = min_fetch_date
        if not self._loading:
            from crystal.task import (
                ASSUME_RESOURCES_DOWNLOADED_IN_SESSION_WILL_ALWAYS_REMAIN_FRESH,
            )
            if ASSUME_RESOURCES_DOWNLOADED_IN_SESSION_WILL_ALWAYS_REMAIN_FRESH:
                for r in self._materialized_resources:
                    r.already_downloaded_this_session = False
            for lis in self.listeners:
                if hasattr(lis, 'min_fetch_date_did_change'):
                    run_bulkhead_call(lis.min_fetch_date_did_change)  # type: ignore[attr-defined]
    min_fetch_date = property(_get_min_fetch_date, _set_min_fetch_date, doc=
        """
        If non-None then any resource fetched <= this datetime
        will be considered stale and subject to being redownloaded.
        
        This property is configured only for the current session
        and is not persisted.
        """)
    
    # === Load URLs ===
    
    def load_urls(self, *, force: bool=False) -> None:
        """
        Loads all URLs and Resources in the project, if needed, to speed up calls to 
        Project.{resources_matching_pattern, urls_matching_pattern}.
        
        Raises:
        * CancelLoadUrls
        """
        if not force:
            if self._database_is_on_ssd:
                return
        
        if self._did_load_urls:
            return
        
        progress_listener = self._load_urls_progress_listener   # cache
        try:
            # Load Resources
            resources = []
            old_resource_for_url = self._resource_for_url  # cache
            def loading_resource(index: int, resources_per_second: float) -> None:
                assert progress_listener is not None
                progress_listener.loading_resource(index)
            def load_resource(row: tuple) -> None:
                (url, id) = row
                # NOTE: Reuse existing Resource object if available
                resource = old_resource_for_url.get(url)
                if resource is None:
                    resource = Resource(self, url, _id=id)
                resources.append(resource)
            # NOTE: May raise CancelLoadUrls if user cancels
            self._process_table_rows(
                self._db.cursor(),
                # NOTE: The following query to approximate row count is
                #       significantly faster than the exact query
                #       ('select count(1) from resource') because it
                #       does not require a full table scan.
                'select id from resource order by id desc limit 1',
                # TODO: Consider add 'order by id asc'
                'select url, id from resource',
                load_resource,
                progress_listener.will_load_resources,
                loading_resource,
                progress_listener.did_load_resources)
            
            # Index Resources
            progress_listener.indexing_resources()
            self._resource_for_url = as_ordereddict({r.url: r for r in resources})  # replace
            self._resource_for_id = as_ordereddict({r._id: r for r in resources})  # replace
            self._sorted_resource_urls = SortedList([r.url for r in resources])
            self._check_url_collection_invariants()
        finally:
            progress_listener.reset()
    
    @property
    def _did_load_urls(self) -> bool:
        """
        Whether all URLs and Resources in the project have actually been loaded
        by a prior call to load_urls().
        """
        return self._sorted_resource_urls is not None
    
    
    @fg_affinity
    def _check_url_collection_invariants(self) -> None:
        """
        Checks that all internal collections tracking URLs and Resources
        appear to be in sync, raising if not.
        
        Operations that make bulk modifications to a project's collection of
        resources should call this method.
        
        Runtime complexity: O(1)
        """
        INCONSISTENT_URL_COLLECTIONS = 'Project URL collections are inconsistent with each other'
        
        count1 = len(self._resource_for_url)
        count2 = len(self._resource_for_id)
        if self._sorted_resource_urls is None:
            assert count1 == count2, INCONSISTENT_URL_COLLECTIONS
        else:
            count3 = len(self._sorted_resource_urls)
            assert count1 == count2 == count3, INCONSISTENT_URL_COLLECTIONS
    
    @fg_affinity
    def resources_matching_pattern(self,
            url_pattern_re: re.Pattern,
            literal_prefix: str,
            ) -> list[Resource]:
        """
        Returns all Resources in the project whose URL matches the specified
        regular expression and literal prefix, in the order they were created.
        
        Raises:
        * CancelLoadUrls
        """
        if '*' in literal_prefix:
            raise ValueError('literal_prefix may not contain an *')
        
        self.load_urls()
        if self._did_load_urls:
            assert self._sorted_resource_urls is not None
            
            self._check_url_collection_invariants()
            
            sorted_resource_urls = self._sorted_resource_urls  # cache
            resource_for_url = self._resource_for_url  # cache
            
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
        else:
            # NOTE: The following calculation is equivalent to
            #           members = [r for r in self.resources if url_pattern_re.fullmatch(r.url) is not None]
            #       but runs faster on average,
            #       in O(log(r) + s + g*log(g)) time rather than O(r) time, where
            #           r = (# of Resources in Project),
            #           s = (# of Resources in Project matching the literal prefix), and
            #           g = (# of Resources in the resulting group).
            c = self._db.cursor()
            member_data = c.execute(
                'select id, url from resource where url glob ? and url regexp ? order by id',
                (literal_prefix + '*', url_pattern_re.pattern)
            )
            return self._materialize_resources(member_data)
    
    def _materialize_resources(self, resources_data: Iterator[tuple[int, str]]) -> list[Resource]:
        resources = []
        resource_for_id = self._resource_for_id  # cache
        resource_for_url = self._resource_for_url  # cache
        sorted_resource_urls = self._sorted_resource_urls or BLACK_HOLE_SORTED_LIST  # cache
        for (id, url) in resources_data:
            resource = resource_for_id.get(id)
            if resource is None:
                resource = Resource(self, url, _id=id)
                resource_for_url[url] = resource
                resource_for_id[id] = resource
                sorted_resource_urls.add(url)
            resources.append(resource)
        
        self._check_url_collection_invariants()
        
        return resources
    
    @fg_affinity
    def urls_matching_pattern(self,
            url_pattern_re: re.Pattern,
            literal_prefix: str,
            limit: int | None=None,
            ) -> tuple[list[str], int]:
        """
        Returns all resource URLs in the project which match the specified
        regular expression and literal prefix, ordered by URL value.
        
        If limit is not None than at most `limit` URLs will be returned.
        
        Also returns the number of matching URLs if limit is None,
        or an upper bound on the number of matching URLs if limit is not None.
        
        Raises:
        * CancelLoadUrls
        """
        if '*' in literal_prefix:
            raise ValueError('literal_prefix may not contain an *')
        
        self.load_urls()
        if self._did_load_urls:
            assert self._sorted_resource_urls is not None
            
            self._check_url_collection_invariants()
            
            sorted_resource_urls = self._sorted_resource_urls  # cache
            
            member_urls = []
            start_index = sorted_resource_urls.bisect_left(literal_prefix)
            for cur_url in sorted_resource_urls.islice(start=start_index):
                if not cur_url.startswith(literal_prefix):
                    break
                if url_pattern_re.fullmatch(cur_url):
                    member_urls.append(cur_url)
                    if limit is not None and len(member_urls) == limit:
                        break
            
            if limit is None or len(member_urls) < limit:
                return (member_urls, len(member_urls))
            else:
                end_index = bisect_key_right(
                    sorted_resource_urls,  # type: ignore[misc]
                    literal_prefix,
                    order_preserving_key=lambda url: url[:len(literal_prefix)])  # type: ignore[index]
                
                approx_member_count = end_index - start_index + 1
                return (member_urls, approx_member_count)
        else:
            # NOTE: When limit is None, the following calculation is equivalent to
            #           members = sorted([r.url for r in self.resources if url_pattern_re.fullmatch(r.url) is not None])
            #       but runs faster on average,
            #       in O(log(r) + s) time rather than O(r) time, where
            #           r = (# of Resources in Project) and
            #           s = (# of Resources in Project matching the literal prefix).
            c = self._db.cursor()
            if limit is None:
                member_urls = [url for (url,) in c.execute(
                    'select url from resource where url glob ? and url regexp ? order by url',
                    (literal_prefix + '*', url_pattern_re.pattern)
                )]
                return (member_urls, len(member_urls))
            else:
                member_urls = [url for (url,) in c.execute(
                    'select url from resource where url glob ? and url regexp ? order by url limit ?',
                    (literal_prefix + '*', url_pattern_re.pattern, limit + 1)
                )]
                if len(member_urls) <= limit:
                    return (member_urls, len(member_urls))
                else:
                    [(approx_member_count,)] = c.execute(
                        'select count(1) from resource where url glob ?',
                        (literal_prefix + '*',)
                    )
                    return (member_urls[:-1], approx_member_count)
    
    # === Children ===
    
    @property
    def resources(self) -> Iterable[Resource]:
        """
        Returns all Resources in the project in the order they were created.
        
        Raises:
        * CancelLoadUrls
        """
        self.load_urls()
        if self._did_load_urls:
            return self._resource_for_url.values()
        else:
            # TODO: Alter implementation to load resources one page at a time
            #       rather than all at once, so that this method can be used
            #       on projects with very many resources
            c = self._db.cursor()
            resources_data = c.execute('select id, url from resource order by id')
            return self._materialize_resources(resources_data)
    
    @property
    def _materialized_resources(self) -> Iterable[Resource]:
        return self._resource_for_id.values()
    
    @fg_affinity
    def get_resource(self, url: str) -> Resource | None:
        """Returns the `Resource` with the specified URL or None if no such resource exists."""
        
        if self._did_load_urls:
            return self._resource_for_url.get(url)
        
        # Lookup/materialize Resource
        resource = self._resource_for_url.get(url)
        if resource is not None:
            return resource
        c = self._db.cursor()
        rows = list(c.execute('select id from resource where url = ?', (url,)))
        if len(rows) == 0:
            return None
        else:
            [(id,)] = rows
            
            resource = Resource(self, url, _id=id)
            self._resource_for_url[url] = resource
            self._resource_for_id[id] = resource
            if self._sorted_resource_urls is not None:
                self._sorted_resource_urls.add(url)
            self._check_url_collection_invariants()
            
            return resource
    
    # Private to crystal.model classes
    @fg_affinity
    def _get_resource_with_id(self, id: int) -> Resource | None:
        """Returns the `Resource` with the specified ID or None if no such resource exists."""
        
        if self._did_load_urls:
            return self._resource_for_id.get(id)
        
        # Lookup/materialize Resource
        resource = self._resource_for_id.get(id)
        if resource is not None:
            return resource
        c = self._db.cursor()
        rows = list(c.execute('select url from resource where id = ?', (id,)))
        if len(rows) == 0:
            return None
        else:
            [(url,)] = rows
            
            resource = Resource(self, url, _id=id)
            self._resource_for_id[id] = resource
            self._resource_for_url[url] = resource
            if self._sorted_resource_urls is not None:
                self._sorted_resource_urls.add(url)
            self._check_url_collection_invariants()
            
            return resource
    
    @property
    def root_resources(self) -> Iterable[RootResource]:
        """Returns all RootResources in the project in the order they were created."""
        return self._root_resources.values()
    
    def get_root_resource(self, resource: Resource) -> RootResource | None:
        """Returns the `RootResource` with the specified `Resource` or None if none exists."""
        return self._root_resources.get(resource, None)
    
    def _get_root_resource_with_id(self, root_resource_id) -> RootResource | None:
        """Returns the `RootResource` with the specified ID or None if no such root resource exists."""
        # PERF: O(n) when it could be O(1), where n = # of RootResources
        return next((rr for rr in self._root_resources.values() if rr._id == root_resource_id), None)
    
    def _get_root_resource_with_name(self, name) -> RootResource | None:
        """Returns the `RootResource` with the specified name or None if no such root resource exists."""
        # PERF: O(n) when it could be O(1), where n = # of RootResources
        return next((rr for rr in self._root_resources.values() if rr.name == name), None)
    
    @property
    def resource_groups(self) -> Iterable[ResourceGroup]:
        """Returns all ResourceGroups in the project in the order they were created."""
        return self._resource_groups
    
    def get_resource_group(self, name: str) -> ResourceGroup | None:
        """Returns the `ResourceGroup` with the specified name or None if no such resource exists."""
        # PERF: O(n) when it could be O(1), where n = # of ResourceGroups
        return next((rg for rg in self._resource_groups if rg.name == name), None)
    
    def _get_resource_group_with_id(self, resource_group_id) -> ResourceGroup | None:
        """Returns the `ResourceGroup` with the specified ID or None if no such resource exists."""
        # PERF: O(n) when it could be O(1), where n = # of ResourceGroups
        return next((rg for rg in self._resource_groups if rg._id == resource_group_id), None)
    
    # NOTE: Used by tests
    def _revision_count(self) -> int:
        c = self._db.cursor()
        [(revision_count,)] = c.execute('select count(1) from resource_revision')
        return revision_count
    
    # === Tasks ===
    
    def add_task(self, task: Task) -> None:
        """
        Schedules the specified top-level task for execution.
        
        The specified task is allowed to already be complete.
        
        Raises:
        * ProjectClosedError -- if this project is closed
        """
        task_was_complete = task.complete  # capture
        self.root_task.append_child(task, already_complete_ok=True)
        if task_was_complete:
            self.root_task.child_task_did_complete(task)
    
    @fg_affinity
    def hibernate_tasks(self) -> None:
        """
        Saves the state of any running tasks.
        
        Raises:
        * ProjectReadOnlyError
        """
        from crystal.task import (
            DownloadResourceGroupTask, DownloadResourceTask,
        )
        
        if self.readonly:
            raise ProjectReadOnlyError()
        
        hibernated_tasks = []
        for task in self.root_task.children:
            if task.complete:
                # Do not attempt to preserve completed tasks
                continue
            if isinstance(task, DownloadResourceTask):
                hibernated_tasks.append({
                    'type': 'DownloadResourceTask',
                    'resource_id': str(task.resource._id),
                })
            elif isinstance(task, DownloadResourceGroupTask):
                hibernated_tasks.append({
                    'type': 'DownloadResourceGroupTask',
                    'group_id': str(task.group._id),
                })
            else:
                # Do not attempt to preserve other kinds of tasks
                pass
        
        # Save the last_downloaded_member of all ResourceGroups
        # because enables DownloadResourceGroupTasks to be resumed
        # precisely after last member that was downloaded
        hibernated_groups = {
            str(rg._id): {
                'last_downloaded_member_id':
                    str(rg.last_downloaded_member._id)
                    if rg.last_downloaded_member is not None
                    else None
            }
            for rg in self.resource_groups
        }
        
        hibernated_project = {
            'tasks': hibernated_tasks,
            'groups': hibernated_groups,
        }
        
        hibernated_project_str = json.dumps(hibernated_project)
        
        if len(hibernated_tasks) == 0:
            # Keep no property in the database if no tasks
            # to minimize the number of persisted database IDs
            self._delete_property('hibernated_state')
        else:
            self._set_property('hibernated_state', hibernated_project_str)
    
    @fg_affinity
    def unhibernate_tasks(self, confirm_func: Callable[[], bool] | None=None) -> None:
        """
        Restores the state of any running tasks.
        
        `confirm_func` (if provided) will be called if there are any
        running tasks to restore, to confirm they should be restored
        (which may involve loading the project URLs).
        
        Raises:
        * ProjectReadOnlyError
        """
        from crystal.task import (
            DownloadResourceGroupTask, DownloadResourceTask,
        )
        
        if self.readonly:
            raise ProjectReadOnlyError()
        if len(self.root_task.children) != 0:
            raise ValueError('Expected no running tasks in project')
        
        hibernated_project_str = self._get_property('hibernated_state', default=None)
        if hibernated_project_str is None:
            return
        
        hibernated_project = json.loads(hibernated_project_str)
        
        hibernated_tasks = hibernated_project['tasks']
        if len(hibernated_tasks) == 0:
            return
        if confirm_func is not None and not confirm_func():
            return
        
        # Show progress dialog in advance if may need to load many project URLs
        try:
            self.load_urls()
        except CancelLoadUrls:
            return
        
        # Restore the last_downloaded_member of all ResourceGroups,
        # before restoring DownloadResourceGroupTasks
        for (rg_id_str, hibernated_group) in hibernated_project['groups'].items():
            rg = self._get_resource_group_with_id(int(rg_id_str))
            if rg is None:
                # ResourceGroup no longer exists. Ignore restoring this group.
                continue
            
            last_downloaded_member_id_str = hibernated_group['last_downloaded_member_id']
            if last_downloaded_member_id_str is None:
                last_downloaded_member = None
            else:
                last_downloaded_member_id = int(last_downloaded_member_id_str)
                last_downloaded_member = self._get_resource_with_id(last_downloaded_member_id)
                if last_downloaded_member is None:
                    # Resource no longer exists. Ignore restoring this group.
                    continue
            
            # Restore last_downloaded_member
            if last_downloaded_member is not None:
                members_already_downloaded = []
                for m in rg.members:
                    members_already_downloaded.append(m)
                    if m == last_downloaded_member:
                        break
                else:
                    # Member not found. Ignore restoring this group.
                    continue
                
                for m in members_already_downloaded:
                    m.already_downloaded_this_session = True
            rg.last_downloaded_member = last_downloaded_member
        
        # Restore tasks
        tasks = []  # type: List[Task]
        for hibernated_task in hibernated_tasks:
            if hibernated_task['type'] == 'DownloadResourceTask':
                r = self._get_resource_with_id(int(hibernated_task['resource_id']))
                if r is None:
                    # Resource no longer exists. Ignore related download.
                    continue
                tasks.append(DownloadResourceTask(r, needs_result=False))
            elif hibernated_task['type'] == 'DownloadResourceGroupTask':
                rg = self._get_resource_group_with_id(int(hibernated_task['group_id']))
                if rg is None:
                    # ResourceGroup no longer exists. Ignore related download.
                    continue
                tasks.append(DownloadResourceGroupTask(rg))
            else:
                raise ValueError('Unknown task type: ' + hibernated_task['type'])
        for t in tasks:
            self.add_task(t)
    
    # === Events: Resource Lifecycle ===
    
    # Called when a new Resource is created after the project has loaded
    def _resource_did_instantiate(self, resource: Resource) -> None:
        # Notify resource groups (which are like hardwired listeners)
        for rg in self.resource_groups:
            rg._resource_did_instantiate(resource)
        
        # Notify normal listeners
        for lis in self.listeners:
            if hasattr(lis, 'resource_did_instantiate'):
                run_bulkhead_call(lis.resource_did_instantiate, resource)  # type: ignore[attr-defined]
    
    def _resource_did_alter_url(self, 
            resource: Resource, old_url: str, new_url: str) -> None:
        # Update URL collections
        if True:
            del self._resource_for_url[old_url]
            self._resource_for_url[new_url] = resource
            
            if self._sorted_resource_urls is not None:
                self._sorted_resource_urls.remove(old_url)
                self._sorted_resource_urls.add(new_url)
            
            self._check_url_collection_invariants()
        
        # Notify resource groups (which are like hardwired listeners)
        for rg in self.resource_groups:
            rg._resource_did_alter_url(resource, old_url, new_url)
    
    def _resource_will_delete(self, resource: Resource) -> None:
        # Update URL collections
        del self._resource_for_url[resource.url]
        del self._resource_for_id[resource._id]
        if self._sorted_resource_urls is not None:
            self._sorted_resource_urls.remove(resource.url)
        self._check_url_collection_invariants()
        
        # Notify resource groups (which are like hardwired listeners)
        for rg in self.resource_groups:
            rg._resource_will_delete(resource)
    
    # === Events: Resource Revision Lifecycle ===
    
    # Called when a new ResourceRevision is created after the project has loaded
    def _resource_revision_did_instantiate(self, revision: ResourceRevision) -> None:
        # Notify normal listeners
        for lis in self.listeners:
            if hasattr(lis, 'resource_revision_did_instantiate'):
                run_bulkhead_call(lis.resource_revision_did_instantiate, revision)  # type: ignore[attr-defined]
    
    # === Events: Root Resource Lifecycle ===
    
    # Called when a new RootResource is created after the project has loaded
    def _root_resource_did_instantiate(self, root_resource: RootResource) -> None:
        # Notify normal listeners
        for lis in self.listeners:
            if hasattr(lis, 'root_resource_did_instantiate'):
                run_bulkhead_call(lis.root_resource_did_instantiate, root_resource)  # type: ignore[attr-defined]
    
    def _root_resource_did_forget(self, root_resource: RootResource) -> None:
        # Notify normal listeners
        for lis in self.listeners:
            if hasattr(lis, 'root_resource_did_forget'):
                run_bulkhead_call(lis.root_resource_did_forget, root_resource)  # type: ignore[attr-defined]
    
    # === Events: Resource Group Lifecycle ===
    
    # Called when a new ResourceGroup is created after the project has loaded
    def _resource_group_did_instantiate(self, group: ResourceGroup) -> None:
        # Notify normal listeners
        for lis in self.listeners:
            if hasattr(lis, 'resource_group_did_instantiate'):
                run_bulkhead_call(lis.resource_group_did_instantiate, group)  # type: ignore[attr-defined]
    
    def _resource_group_did_change_do_not_download(self, group: ResourceGroup) -> None:
        # Notify normal listeners
        for lis in self.listeners:
            if hasattr(lis, 'resource_group_did_change_do_not_download'):
                run_bulkhead_call(lis.resource_group_did_change_do_not_download, group)  # type: ignore[attr-defined]
    
    def _resource_group_did_forget(self, group: ResourceGroup) -> None:
        # Notify normal listeners
        for lis in self.listeners:
            if hasattr(lis, 'resource_group_did_forget'):
                run_bulkhead_call(lis.resource_group_did_forget, group)  # type: ignore[attr-defined]
    
    # === Close ===
    
    def close(self) -> None:
        # Stop scheduler thread soon
        if hasattr(self, 'root_task'):
            self.root_task.interrupt()
            # (TODO: Actually wait for the scheduler thread to exit
            #        in a deterministic fashion, rather than relying on 
            #        garbage collection to clean up objects.)
        
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
        if tests_are_running():
            if Project._last_opened_project is self:
                Project._last_opened_project = None
    
    # === Context Manager ===
    
    def __enter__(self) -> Self:
        return self
    
    def __exit__(self, exc_type, exc_value, exc_traceback) -> None:
        self.close()


class CrossProjectReferenceError(Exception):
    pass


class ProjectFormatError(Exception):
    """The on-disk format of a Project is corrupted in some way."""


class ProjectTooNewError(Exception):
    """
    The project has a greater major version than this version of Crystal
    knows how to open safely.
    """


class ProjectReadOnlyError(Exception):
    pass


class ProjectClosedError(Exception):
    pass


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
            _id: Union[None, int, Literal["__defer__"]]=None,
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
        
        self = object.__new__(cls)
        self.project = project
        self._url = normalized_url
        self._download_body_task_ref = None
        self._download_task_ref = None
        self._download_task_noresult_ref = None
        self._already_downloaded_this_session = False
        self._definitely_has_no_revisions = False
        
        creating = _id is None  # capture
        if creating:
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
        self._id = id
        
        if creating:
            project = self.project  # cache
            
            # Record self in Project
            project._resource_for_url[self._url] = self
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
    
    # === Init (Many) ===
    
    @staticmethod
    @fg_affinity
    def bulk_create(
            project: Project,
            urls: list[str],
            origin_url: str,
            ) -> list[Resource]:
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
            new_r._finish_init(id, creating=True)
        
        # Return the set of Resources that were created,
        # which may be shorter than the list of URLs to create that were provided
        return list(resource_for_new_url.values())
    
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
    
    # === Operations: Download ===
    
    def download_body(self) -> Future[ResourceRevision]:
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
        if created:
            if not task.complete:
                self.project.add_task(task)
        return task.future
    
    # Soft Deprecated: Use get_or_create_download_body_task() instead,
    # which clarifies that an existing task may be returned.
    def create_download_body_task(self) -> DownloadResourceBodyTask:
        (task, _) = self.get_or_create_download_body_task()
        return task
    
    def get_or_create_download_body_task(self) -> Tuple[DownloadResourceBodyTask, bool]:
        """
        Gets/creates a Task to download this resource's body.
        
        The caller is responsible for adding a returned created Task as the child of an
        appropriate parent task so that the UI displays it.
        
        This task is never complete immediately after initialization.
        """
        def task_factory() -> DownloadResourceBodyTask:
            from crystal.task import DownloadResourceBodyTask
            return DownloadResourceBodyTask(self)
        if self._download_body_task_ref is None:
            self._download_body_task_ref = _WeakTaskRef()
        return self._get_task_or_create(self._download_body_task_ref, task_factory)
    
    def download(self, *, wait_for_embedded: bool=False, needs_result: bool=True, is_embedded: bool=False) -> Future[ResourceRevision]:
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
        (task, created) = self.get_or_create_download_task(
            needs_result=needs_result, is_embedded=is_embedded)
        if created:
            if not task.complete:
                self.project.add_task(task)
        return task.get_future(wait_for_embedded)
    
    # Soft Deprecated: Use get_or_create_download_task() instead,
    # which clarifies that an existing task may be returned.
    def create_download_task(self, *args, **kwargs) -> DownloadResourceTask:
        (task, _) = self.get_or_create_download_task(*args, **kwargs)
        return task
    
    def get_or_create_download_task(self, *, needs_result: bool=True, is_embedded: bool=False) -> Tuple[DownloadResourceTask, bool]:
        """
        Gets/creates a Task to download this resource and all its embedded resources.
        Returns the task and whether it was created.
        
        The caller is responsible for adding a returned created Task as the child of an
        appropriate parent task so that the UI displays it.
        
        This task may be complete immediately after initialization.
        """
        def task_factory() -> DownloadResourceTask:
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
        
        c = self.project._db.cursor()
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
        
        if project.get_resource(new_url) is not None:
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
        
        project._resource_will_delete(self)
        
        # Delete Resource itself
        c = project._db.cursor()
        c.execute('delete from resource where id=?', (self._id,))
        project._db.commit()
        self._id = None  # type: ignore[assignment]  # intentionally leave exploding None
    
    # === Utility ===
    
    def __repr__(self):
        return "Resource({})".format(repr(self.url))


class RootResource:
    """
    Represents a resource whose existence is manually defined by the user.
    Persisted and auto-saved.
    """
    project: Project
    _name: str
    _resource: Resource
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
        * CrossProjectReferenceError -- if `resource` belongs to a different project.
        * RootResource.AlreadyExists -- 
            if there is already a `RootResource` associated with the specified resource.
        * ProjectReadOnlyError
        """
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
                c = project._db.cursor()
                c.execute('insert into root_resource (name, resource_id) values (?, ?)', (name, resource._id))
                project._db.commit()
                self._id = c.lastrowid
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
        
        self.project._root_resource_did_forget(self)
    
    # === Properties ===
    
    def _get_name(self) -> str:
        """Name of this root resource. Possibly ''."""
        return self._name
    @fg_affinity
    def _set_name(self, name: str) -> None:
        if self._name == name:
            return
        
        if self.project.readonly:
            raise ProjectReadOnlyError()
        c = self.project._db.cursor()
        c.execute('update root_resource set name=? where id=?', (
            name,
            self._id,))
        self.project._db.commit()
        
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
        Creates a task to download this root resource.
        
        This task may be complete immediately after initialization.
        """
        # TODO: Create the underlying task with the full RootResource
        #       so that the correct subtitle is displayed.
        return self.resource.create_download_task(needs_result=needs_result, is_embedded=False)
    
    # === Utility ===
    
    def __repr__(self):
        return "RootResource({},{})".format(repr(self.name), repr(self.resource.url))
    
    class AlreadyExists(Exception):
        """
        Raised when an attempt is made to create a new `RootResource` for a `Resource`
        that is already associated with an existing `RootResource`.
        """


class ResourceRevision:
    """
    A downloaded revision of a `Resource`. Immutable.
    Persisted. Loaded on demand.
    """
    resource: Resource
    request_cookie: str | None
    error: Exception | None
    metadata: ResourceRevisionMetadata | None
    _id: int | None  # None if deleted
    has_body: bool
    
    # === Init ===
    
    # NOTE: This method is not used by the UI at this time.
    #       It is intended only to be used by shell programs.
    @staticmethod
    def create_from_revision(
            resource: Resource,
            revision: ResourceRevision
            ) -> ResourceRevision:
        """
        Creates a new revision whose contents is copied from a different revision
        (which is likely in a different project).
        
        Raises:
        * ProjectHasTooManyRevisionsError
        * Exception -- if could not write revision to disk
        """
        if revision.error is not None:
            return ResourceRevision.create_from_error(resource, revision.error)
        else:
            with revision.open() as f:
                return ResourceRevision.create_from_response(
                    resource,
                    revision.metadata,
                    f,
                    revision.request_cookie)
    
    @staticmethod
    def create_from_error(
            resource: Resource,
            error: Exception,
            request_cookie: str | None=None
            ) -> ResourceRevision:
        """
        Creates a new revision that encapsulates the error encountered when fetching the revision.
        
        Raises:
        * ProjectHasTooManyRevisionsError
        * Exception -- if could not write revision to disk
        """
        return ResourceRevision._create_from_stream(
            resource,
            request_cookie=request_cookie,
            error=error)
    
    @staticmethod
    def create_from_response(
            resource: Resource,
            metadata: ResourceRevisionMetadata | None,
            body_stream: BinaryIO,
            request_cookie: str | None=None
            ) -> ResourceRevision:
        """
        Creates a new revision with the specified metadata and body.
        
        The passed body stream will be read synchronously until EOF,
        so it is recommended that this method be invoked on a background thread.
        
        Arguments:
        * resource -- resource that this is a revision of.
        * metadata -- JSON-encodable dictionary of resource metadata.
        * body_stream -- file-like object containing the revision body.
        
        Raises:
        * ProjectHasTooManyRevisionsError
        * Exception -- if could not read revision from stream or write to disk
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
                        http_date.format(datetime.datetime.now(datetime.UTC))
                    ])
            
            return ResourceRevision._create_from_stream(
                resource,
                request_cookie=request_cookie,
                metadata=metadata,
                body_stream=body_stream)
        except ProjectHasTooManyRevisionsError:
            raise
        except Exception as e:
            return ResourceRevision.create_from_error(resource, e, request_cookie)
    
    @staticmethod
    def _create_from_stream(
            resource: Resource,
            *, request_cookie: str | None=None,
            error: Exception | None=None,
            metadata: ResourceRevisionMetadata | None=None,
            body_stream: BinaryIO | None=None
            ) -> ResourceRevision:
        """
        Creates a new revision.
        
        See also:
        * ResourceRevision.create_from_error()
        * ResourceRevision.create_from_response()
        
        Raises:
        * ProjectHasTooManyRevisionsError
        * Exception -- if could not read revision from stream or write to disk
        """
        self = ResourceRevision()
        self.resource = resource
        self.request_cookie = request_cookie
        self.error = error
        self.metadata = metadata
        self._id = None  # not yet created
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
        
        row_create_attempted_event = threading.Event()
        callable_exc_info = None
        
        # Asynchronously:
        # 1. Create the ResourceRevision row in the database
        # 2. Get the database ID
        @capture_crashes_to_stderr
        def fg_task() -> None:
            nonlocal callable_exc_info
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
                row_create_attempted_event.set()
        # NOTE: Use profile=False because no obvious further optimizations exist
        fg_call_later(fg_task, profile=False)
        
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
            row_create_attempted_event.wait()
            row_created_ok = self._id is not None
            
            if body_file is not None:
                try:
                    if body_file_downloaded_ok and row_created_ok:
                        # Move body file to its final filename
                        # NOTE: May raise ProjectHasTooManyRevisionsError
                        revision_filepath = self._body_filepath
                        try:
                            os.rename(body_file.name, revision_filepath)
                        except FileNotFoundError:  # probably missing parent directory
                            os.makedirs(os.path.dirname(revision_filepath), exist_ok=True)
                            os.rename(body_file.name, revision_filepath)
                    else:
                        # Remove body file
                        os.remove(body_file.name)
                except:
                    body_file_downloaded_ok = False
                    raise
                finally:
                    if not body_file_downloaded_ok and row_created_ok:
                        # Rollback database commit
                        def fg_task() -> None:
                            if project.readonly:
                                raise ProjectReadOnlyError()
                            c = project._db.cursor()
                            c.execute('delete from resource_revision where id=?', (self._id,))
                            project._db.commit()
                        # NOTE: Use profile=False because no obvious further optimizations exist
                        fg_call_and_wait(fg_task, profile=False)
            
            # Reraise callable's exception, if applicable
            if callable_exc_info is not None:
                exc_info = callable_exc_info
                assert exc_info[1] is not None
                raise exc_info[1].with_traceback(exc_info[2])
        
        if not project._loading:
            project._resource_revision_did_instantiate(self)
        
        return self
    
    @staticmethod
    def _create_unsaved_from_revision_and_new_metadata(
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
            request_cookie: str | None,
            error: Exception | None,
            metadata: ResourceRevisionMetadata | None,
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
    @fg_affinity
    def load(project: Project, id: int) -> ResourceRevision | None:
        """
        Loads the existing revision with the specified ID,
        or returns None if no such revision exists.
        """
        # Fetch the revision's resource URL
        c = project._db.cursor()
        rows = list(c.execute(
            f'select '
                f'resource_id from resource_revision '
                f'where resource_revision.id=?',
            (id,)
        ))
        if len(rows) == 0:
            return None
        [(resource_id)] = rows
        
        # Get the resource by URL from memory
        r = project._get_resource_with_id(resource_id)
        assert r is not None
        
        # Load all of the resource's revisions
        rrs = r.revisions()
        
        # Find the specific revision that was requested
        for rr in rrs:
            if rr._id == id:
                return rr
        raise AssertionError()
    
    @classmethod
    def _encode_error(cls, error: Exception | None) -> str:
        return json.dumps(cls._encode_error_dict(error))
    
    @staticmethod
    def _encode_error_dict(error: Exception | None) -> Optional[DownloadErrorDict]:
        if error is None:
            error_dict = None
        elif isinstance(error, _PersistedError):
            error_dict = DownloadErrorDict({
                'type': error.type,
                'message': error.message,
            })
        else:
            error_dict = DownloadErrorDict({
                'type': type(error).__name__,
                'message': str(error),
            })
        return error_dict
    
    @staticmethod
    def _encode_metadata(metadata: ResourceRevisionMetadata | None) -> str:
        return json.dumps(metadata)
    
    @staticmethod
    def _decode_error(db_error: str) -> Exception | None:
        error_dict = json.loads(db_error)
        if error_dict is None:
            return None
        else:
            return _PersistedError(error_dict['message'], error_dict['type'])
    
    @staticmethod
    def _decode_metadata(db_metadata: str) -> ResourceRevisionMetadata | None:
        return json.loads(db_metadata)
    
    # === Properties ===
    
    @property
    def project(self) -> Project:
        return self.resource.project
    
    @property
    def _url(self) -> str:
        return self.resource.url
    
    @property
    def error_dict(self) -> Optional[DownloadErrorDict]:
        return self._encode_error_dict(self.error)
    
    def _ensure_has_body(self) -> None:
        """
        Raises:
        * NoRevisionBodyError
        """
        if not self.has_body:
            raise NoRevisionBodyError(self)
    
    @property
    def _body_filepath(self) -> str:
        """
        Raises:
        * ProjectHasTooManyRevisionsError --
            if this revision's in-memory ID is higher than what the 
            project format supports on disk
        """
        if self._id is None:
            raise RevisionDeletedError()
        
        major_version = self.project.major_version
        if major_version >= 2:
            os_path_sep = os.path.sep  # cache
            
            revision_relpath_parts = f'{self._id:015x}'
            if len(revision_relpath_parts) != 15:
                assert self._id > Project._MAX_REVISION_ID
                raise ProjectHasTooManyRevisionsError(
                    f'Revision ID {id} is too high to store in the '
                    'major version 2 project format')
            revision_relpath = (
                revision_relpath_parts[0:3] + os_path_sep +
                revision_relpath_parts[3:6] + os_path_sep +
                revision_relpath_parts[6:9] + os_path_sep +
                revision_relpath_parts[9:12] + os_path_sep +
                revision_relpath_parts[12:15]
            )
        elif major_version == 1:
            revision_relpath = str(self._id)
        else:
            raise AssertionError()
        
        return os.path.join(
            self.project.path, Project._REVISIONS_DIRNAME, revision_relpath)
    
    # === Metadata ===
    
    @property
    def is_http(self) -> bool:
        """Returns whether this resource was fetched using HTTP."""
        # HTTP resources are presently the only ones with metadata
        return self.metadata is not None
    
    @property
    def status_code(self) -> int | None:
        if self.metadata is None:
            return None
        else:
            return self.metadata['status_code']
    
    @property
    def is_redirect(self) -> bool:
        """Returns whether this resource is a redirect."""
        return self.metadata is not None and (self.metadata['status_code'] // 100) == 3
    
    def _get_first_value_of_http_header(self, name: str) -> str | None:
        return self._get_first_value_of_http_header_in_metadata(name, self.metadata)
    
    @staticmethod
    def _get_first_value_of_http_header_in_metadata(
            name: str,
            metadata: ResourceRevisionMetadata | None,
            ) -> str | None:
        name = name.lower()  # reinterpret
        if metadata is None:
            return None
        for (cur_name, cur_value) in metadata['headers']:
            if name == cur_name.lower():
                return cur_value
        return None
    
    @property
    def redirect_url(self) -> str | None:
        """
        Returns the resource to which this resource redirects,
        or None if it cannot be determined or this is not a redirect.
        """
        if self.is_redirect:
            return self._get_first_value_of_http_header('location')
        else:
            return None
    
    @property
    def _redirect_title(self) -> str | None:
        if self.is_redirect:
            metadata = self.metadata  # cache
            if metadata is None:
                return None
            return '{} {}'.format(metadata['status_code'], metadata['reason_phrase'])
        else:
            return None
    
    @property
    def declared_content_type_with_options(self) -> str | None:  # ex: 'text/html; charset=utf-8'
        if self.is_http:
            return self._get_first_value_of_http_header('content-type')
        else:
            return None
    
    @property
    def declared_content_type(self) -> str | None:  # ex: 'text/html'
        """Returns the MIME content type declared for this resource, or None if not declared."""
        content_type_with_options = self.declared_content_type_with_options
        if content_type_with_options is None:
            return None
        else:
            (content_type, content_type_options) = xcgi.parse_header(content_type_with_options)
            return content_type
    
    @property
    def declared_charset(self) -> str | None:  # ex: 'utf-8'
        """Returns the charset declared for this resource, or None if not declared."""
        content_type_with_options = self.declared_content_type_with_options
        if content_type_with_options is None:
            return None
        else:
            (content_type, content_type_options) = xcgi.parse_header(content_type_with_options)
            return content_type_options.get('charset')
    
    @property
    def content_type(self) -> str | None:  # ex: 'utf-8'
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
        return self.content_type in (
            # https://www.rfc-editor.org/rfc/rfc3023#section-3.1
            'text/xml',
            # https://www.rfc-editor.org/rfc/rfc3023#section-3.2
            'application/xml',
            # https://www.rssboard.org/rss-mime-type-application.txt
            'application/rss+xml',
            # https://www.rfc-editor.org/rfc/rfc4287
            'application/atom+xml',
        )
    
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
    def date(self) -> datetime.datetime | None:
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
            return date.replace(tzinfo=datetime.UTC)
    
    @property
    def age(self) -> int | None:
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
    def date_plus_age(self) -> datetime.datetime | None:
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
    def etag(self) -> str | None:
        return self._get_first_value_of_http_header('etag')
    
    # === Staleness ===
    
    @property
    def is_stale(self) -> bool:
        resource = self.resource
        project = resource.project
        
        if project.request_cookie_applies_to(resource.url) and project.request_cookie is not None:
            if self.request_cookie != project.request_cookie:
                return True
        if project.min_fetch_date is not None:
            # TODO: Consider storing the fetch date explicitly
            #       rather than trying to derive it from the 
            #       Date and Age HTTP headers
            fetch_date = self.date_plus_age  # cache
            if (fetch_date is not None and 
                    fetch_date <= project.min_fetch_date):
                return True
        return False
    
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
        
        If this revision is an error then returns an empty list.
        
        Raises:
        * NoRevisionBodyError
        * RevisionBodyMissingError
        """
        return self.document_and_links()[1]
    
    def document_and_links(self) -> tuple[Document | None, list[Link], str | None]:
        """
        Returns a 3-tuple containing:
        (1) if this revision is a document, the document, otherwise None;
        (2) a list of rewritable Links found in this revision.
        (3) a Content-Type value for the document, or None if unknown
        
        The HTML document can be reoutput by getting its str() representation.
        
        This method blocks while parsing the links.
        
        If this revision is an error then returns a None document and
        an empty list of links.
        
        Raises:
        * NoRevisionBodyError
        * RevisionBodyMissingError
        """
        
        # Extract links from HTML, if applicable
        doc: Document | None
        links: list[Link]
        (doc, links) = (None, [])
        content_type_with_options = None  # type: Optional[str]
        if self.is_html and self.has_body:
            with self.open() as body:
                doc_and_links = parse_html_and_links(
                    body, self.declared_charset, self.project.html_parser_type)
            if doc_and_links is not None:
                (doc, links) = doc_and_links
                content_type_with_options = 'text/html; charset=utf-8'
                
                # Add implicit link to default favicon
                # if no explicit favicon specified and path is /
                if urlparse(self._url).path == '/':
                    has_explicit_favicon_link = False
                    for link in links:
                        if link.type_title == FAVICON_TYPE_TITLE:
                            has_explicit_favicon_link = True
                            break
                    
                    if not has_explicit_favicon_link:
                        # Insert implicit favicon link
                        if isinstance(doc, HtmlDocument):
                            # Try insert read-write favicon link
                            favicon_link = doc.try_insert_favicon_link('/favicon.ico')
                        else:
                            favicon_link = None
                        if favicon_link is None:
                            # Insert read-only favicon link
                            favicon_link = create_external_link(
                                '/favicon.ico', FAVICON_TYPE_TITLE, None, True)
                        assert favicon_link is not None
                        links.append(favicon_link)
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
            links.append(create_external_link(redirect_url, 'Redirect', redirect_title, True))
        
        # Allow plugins to postprocess results
        url = self.resource.url  # cache
        for postprocess_document_and_links in (
                plugins_minbaker.postprocess_document_and_links,
                ):
            (doc, links) = postprocess_document_and_links(url, doc, links)
        
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
        
        return ResourceRevision._create_unsaved_from_revision_and_new_metadata(
            target_revision, new_metadata)
    
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
        return "<ResourceRevision {} for '{}'>".format(self._id, self.resource.url)
    
    def __str__(self) -> str:
        return f'Revision {self._id} for URL {self.resource.url}'


class DownloadErrorDict(TypedDict):
    type: str
    message: str


class RevisionDeletedError(ValueError):
    pass


class ProjectHasTooManyRevisionsError(Exception):
    pass


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


class ResourceGroup(ListenableMixin):
    """
    Groups resource whose url matches a particular pattern.
    Persisted and auto-saved.
    """
    
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
        """
        super().__init__()
        
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
            self._id = _id
            
            self._source = source
        else:
            if project.readonly:
                raise ProjectReadOnlyError()
            c = project._db.cursor()
            c.execute('insert into resource_group (name, url_pattern, do_not_download) values (?, ?, ?)', (name, url_pattern, do_not_download))
            project._db.commit()
            self._id = c.lastrowid
            
            if source is Ellipsis:
                raise ValueError()
            # NOTE: Performs 1 database query to update above database row
            self.source = source
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
        
        self.project._resource_group_did_forget(self)
    
    # === Properties ===
    
    def _get_name(self) -> str:
        """Name of this resource group. Possibly ''."""
        return self._name
    def _set_name(self, name: str) -> None:
        if self._name == name:
            return
        
        if self.project.readonly:
            raise ProjectReadOnlyError()
        c = self.project._db.cursor()
        c.execute('update resource_group set name=? where id=?', (
            name,
            self._id,))
        self.project._db.commit()
        
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
        """
        if isinstance(self._source, EllipsisType):
            raise ValueError('Expected ResourceGroup.init_source() to have been already called')
        return self._source
    def _set_source(self, value: ResourceGroupSource) -> None:
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
        c = self.project._db.cursor()
        c.execute('update resource_group set source_type=?, source_id=? where id=?', (source_type, source_id, self._id))
        self.project._db.commit()
        
        self._source = value
    source = cast(ResourceGroupSource, property(_get_source, _set_source))
    
    def _get_do_not_download(self) -> bool:
        return self._do_not_download
    def _set_do_not_download(self, value: bool) -> None:
        if self._do_not_download == value:
            return
        
        if self.project.readonly:
            raise ProjectReadOnlyError()
        c = self.project._db.cursor()
        c.execute('update resource_group set do_not_download=? where id=?', (value, self._id))
        self.project._db.commit()
        
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
        
        This task may be complete immediately after initialization.
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


def _is_ascii(s: str) -> bool:
    assert isinstance(s, str)
    try:
        s.encode('ascii')
    except UnicodeEncodeError:
        return False
    else:
        return True
