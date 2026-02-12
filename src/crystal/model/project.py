from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Generator, Iterable, Iterator
from concurrent.futures import Future
from contextlib import closing, contextmanager
from crystal import resources as resources_
from crystal.model.alias import Alias
from crystal.model.resource import Resource
from crystal.model.resource_group import ResourceGroup, ResourceGroupSource
from crystal.model.resource_revision import (
    NoRevisionBodyError, ResourceRevision,
)
from crystal.model.root_resource import RootResource
from crystal.progress import (
    CancelLoadUrls, CancelOpenProject, DummyLoadUrlsProgressListener, DummyOpenProjectProgressListener,
    LoadUrlsProgressListener, OpenProjectProgressListener,
    SaveAsProgressListener, VetoUpgradeProject,
)
from crystal.util import gio
from crystal.util.bulkheads import capture_crashes_to_stderr, run_bulkhead_call
from crystal.util.db import (
    DatabaseConnection, DatabaseCursor, get_column_names_of_table,
    get_index_names, get_table_names, is_no_such_column_error_for,
)
from crystal.util.ellipsis import Ellipsis
from crystal.util.filesystem import replace_and_flush, flush_renames_in_directory
from crystal.util.listenable import ListenableMixin
from crystal.util.profile import create_profiling_context
from crystal.util.progress import DevNullFile
from crystal.util.ssd import is_ssd
from crystal.util.test_mode import tests_are_running
from crystal.util.thread_debug import get_thread_stack
from crystal.app_preferences import app_prefs
from crystal.util.windows_attrib import set_windows_file_attrib
from crystal.util.xappdirs import user_untitled_projects_dir
from crystal.util.xbisect import bisect_key_right
from crystal.util.xcollections.ordereddict import as_ordereddict
from crystal.util.xcollections.sortedlist import BLACK_HOLE_SORTED_LIST
from crystal.util.xdatetime import datetime_is_aware
from crystal.util.xshutil import walkzip
from crystal.util.xsqlite3 import random_choices_from_table_ids
from crystal.util.xgc import gc_disabled
from crystal.util.xos import is_linux, is_windows
from crystal.util.xsqlite3 import is_database_read_only_error, sqlite_has_json_support
from crystal.util.xthreading import (
    SwitchToThread, bg_affinity, bg_call_later, fg_affinity, fg_wait_for, start_thread_switching_coroutine,
)
import datetime
from enum import Enum
import json
import math
import os
import pathlib
import re
from send2trash import send2trash, TrashPermissionError
import shutil
from shutil import COPY_BUFSIZE  # type: ignore[attr-defined]  # private API
from sortedcontainers import SortedList
import sqlite3
import sys
import tempfile
from textwrap import dedent
import time
from tqdm import tqdm
import traceback
from typing import (
    Any, cast, Dict, Literal, List, Optional, Self, Tuple, TYPE_CHECKING, TypeAlias, TypeVar, Union,
)
from typing_extensions import override
import threading
from urllib.parse import quote as url_quote
import uuid
from weakref import WeakValueDictionary

if TYPE_CHECKING:
    from crystal.doc.html import HtmlParserType
    from crystal.task import (
        RootTask, Task,
    )


# ------------------------------------------------------------------------------
# Constants + Type Utilities

# Whether to collect profiling information about Project._apply_migrations().
# 
# When True, a 'migrate_revisions.prof' file is written to the current directory
# after all projects have been closed. Such a file can be converted
# into a visual flamegraph using the "flameprof" PyPI module,
# or analyzed using the built-in "pstats" module.
_PROFILE_MIGRATE_REVISIONS = False


_OptionalStr = TypeVar('_OptionalStr', bound=Optional[str])


# ------------------------------------------------------------------------------
# Project

class _Missing(Enum):
    VALUE = 1


EntityTitleFormat: TypeAlias = Literal['url_name', 'name_url']


class Project(ListenableMixin):
    """
    Groups together a set of resources that are downloaded and any associated settings.
    Persisted and auto-saved.
    """
    
    FILE_EXTENSION = '.crystalproj'
    PARTIAL_FILE_EXTENSION = '.crystalproj-partial'
    OPENER_FILE_EXTENSION = '.crystalopen'
    
    # Project structure constants
    _DB_FILENAME = 'database.sqlite'
    _LATEST_SUPPORTED_MAJOR_VERSION = 3
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
    
    # Other constants
    _SCHEDULER_JOIN_TIMEOUT = 5.0  # seconds
    
    # NOTE: Only changed when tests are running
    _last_opened_project: Project | None=None
    _report_progress_at_maximum_resolution: bool=False
    
    # === Load ===
    
    @fg_affinity
    def __init__(self,
            path: str | None=None,
            progress_listener: OpenProjectProgressListener | None=None,
            load_urls_progress_listener: LoadUrlsProgressListener | None=None,
            *, readonly: bool=False,
            is_untitled: bool=False,
            is_dirty: bool=False,
            ) -> None:
        """
        Loads a project from the specified itempath, or creates a new one if none is found.
        
        Arguments:
        * path -- 
            path to a project directory (ending with `FILE_EXTENSION`)
            or to a project opener (ending with `OPENER_FILE_EXTENSION`).
            Or None to create a new untitled project in a temporary directory.
        * progress_listener --
            receives progress updates while the project is being opened.
        * load_urls_progress_listener --
            receives progress updates while URLs are being loaded,
            even after the project has been opened.
        * readonly --
            whether to open the project in read-only mode.
            If True, the project must already exist at the specified path.
            Note that a project on read-only media (such as a DVD-R) will
            always be opened in read-only mode, regardless of this argument.
        * is_untitled --
            if True then the project is considered untitled even if it has a path.
            It is usually easier to pass None for `path` and let the constructor
            create a temporary directory for the path internally.
        * is_dirty --
            whether the project is considered immediately dirty

        Raises:
        * ProjectReadOnlyError --
            if a new project could not be created because the path is 
            on a read-only filesystem or a filesystem that SQLite cannot write to
        * ProjectFormatError -- if the project at the specified path is invalid
        * ProjectTooNewError -- 
            if the project is a version newer than this version of Crystal can open safely
        * CancelOpenProject
        * sqlite3.DatabaseError, OSError
        """
        super().__init__()
        
        cls = type(self)
        if progress_listener is None:
            progress_listener = DummyOpenProjectProgressListener()
        if load_urls_progress_listener is None:
            load_urls_progress_listener = DummyLoadUrlsProgressListener()
        self._load_urls_progress_listener = load_urls_progress_listener
        readonly_requested = readonly  # rename for clarity
        
        # If path is missing then prepare to create an untitled project
        if path is None:
            # Create an untitled project in a permanent but hidden directory
            untitled_projects_dir = user_untitled_projects_dir()
            assert os.path.exists(untitled_projects_dir)
            project_name = f'Untitled-{uuid.uuid4().hex[:8]}{Project.FILE_EXTENSION}'
            untitled_project_dirpath = os.path.join(untitled_projects_dir, project_name)
            assert not os.path.exists(untitled_project_dirpath)
            
            path = untitled_project_dirpath  # reinterpret
            is_untitled = True  # reinterpret
        
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
        
        self._closed = False
        self._readonly = True  # will reinitialize after database is located
        self._is_untitled = is_untitled
        self._is_dirty = is_dirty
        self._properties_loaded = False
        self._properties = dict()               # type: Dict[str, Optional[str]]
        self._resource_for_url = WeakValueDictionary()  # type: Union[WeakValueDictionary[str, Resource], OrderedDict[str, Resource]]
        self._resource_for_id = WeakValueDictionary()   # type: Union[WeakValueDictionary[int, Resource], OrderedDict[int, Resource]]
        self._unsaved_resources = []            # type: List[Resource]
        self._sorted_resource_urls = None       # type: Optional[SortedList[str]]
        self._root_resources = OrderedDict()    # type: Dict[Resource, RootResource]
        self._resource_groups = []              # type: List[ResourceGroup]
        self._aliases = []                      # type: List[Alias]
        
        self._min_fetch_date = None  # type: Optional[datetime.datetime]
        
        progress_listener.opening_project()
        
        create = not os.path.exists(path)
        if create and readonly_requested:
            # Can't create a project if cannot write to disk
            raise ProjectReadOnlyError(
                f'Cannot create new project at {path!r} when readonly=True')
        # NOTE: Currently used by MainWindow only. Omitting from public API for now.
        self._created_this_session = create
        
        self._loading = True
        try:
            # Create/verify project structure
            if create:
                cls._create_directory_structure(path)
            else:
                cls._ensure_directory_structure_valid(path)
            try:
                # NOTE: May raise ProjectReadOnlyError if the database cannot be opened as writable
                with cls._open_database_but_close_if_raises(path, readonly_requested, self._mark_dirty_if_untitled, expect_writable=create) as (
                            self._db, self._readonly, self._database_is_on_ssd):
                    # Create new project content, if missing
                    if create:
                        self._create()
                    
                    # Load from existing project
                    # NOTE: Don't provide detailed feedback when creating a project initially
                    load_progress_listener = (
                        progress_listener if not create
                        else DummyOpenProjectProgressListener()
                    )
                    self._load(load_progress_listener)
        
                    # Apply repairs
                    if not self.readonly:
                        self._repair_incomplete_rollback_of_resource_revision_create()
                        if self.major_version >= 3:
                            self._repair_missing_pack_of_resource_revision_create()
                    
                    # Reset dirty state after loading
                    self._is_dirty = is_dirty
            except:
                if create:
                    shutil.rmtree(path, ignore_errors=True)
                raise
        finally:
            self._loading = False
        
        self._start_scheduler()
        
        # Define initial configuration
        self._request_cookie = None  # type: Optional[str]
        
        self._check_url_collection_invariants()
        
        if is_untitled:
            app_prefs.unsaved_untitled_project_path = self.path
        
        # Export reference to self, if running tests
        if tests_are_running():
            Project._last_opened_project = self
    
    @classmethod
    def _create_directory_structure(cls, project_path: str) -> None:
        """
        Create a new project's directory structure, minus the database file.
        """
        os.mkdir(project_path)
        os.mkdir(os.path.join(project_path, cls._REVISIONS_DIRNAME))
        
        # TODO: Consider let _apply_migrations() define the rest of the
        #       project structure, rather than duplicating logic here
        os.mkdir(os.path.join(project_path, cls._TEMPORARY_DIRNAME))
        with open(os.path.join(project_path, cls._OPENER_DEFAULT_FILENAME), 'wb') as f:
            f.write(cls._OPENER_DEFAULT_CONTENT)
        with open(os.path.join(project_path, cls._README_FILENAME), 'w', newline='') as tf:
            tf.write(cls._README_DEFAULT_CONTENT)
        with open(os.path.join(project_path, cls._DESKTOP_INI_FILENAME), 'w', newline='') as tf:
            tf.write(cls._DESKTOP_INI_CONTENT)
        os.mkdir(os.path.join(project_path, cls._ICONS_DIRNAME))
        with resources_.open_binary('docicon.ico') as src_file:
            with open(os.path.join(project_path, cls._ICONS_DIRNAME, 'docicon.ico'), 'wb') as dst_file:
                shutil.copyfileobj(src_file, dst_file)
    
    @classmethod
    @contextmanager
    def _open_database_but_close_if_raises(
            cls,
            project_path: str,
            readonly_requested: bool,
            mark_dirty_func: Callable[[], None],
            expect_writable: bool
            ) -> Iterator[Tuple[DatabaseConnection, bool, bool]]:
        """
        Opens the project database before entering the context,
        but closes it if an exception is raised in the context.
        
        Yields (db, readonly_actual, database_is_on_ssd).

        Effects of this method are reversed by `_close_database()`.
        
        Raises:
        * ProjectReadOnlyError -- 
            if expect_writable is True but the project database cannot be opened as writable
        """
        
        # Open database
        db_filepath = os.path.join(project_path, cls._DB_FILENAME)  # cache
        can_write_db = (
            # Can write to *.crystalproj
            # (is not Locked on macOS, is not on read-only volume)
            os.access(project_path, os.W_OK) and (
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
                if readonly_requested
                else ''
            )
        )
        raw_db = sqlite3.connect(
            'file:' + url_quote(db_filepath) + db_connect_query,
            uri=True)
        
        try:
            database_is_on_ssd = is_ssd(db_filepath)
        except Exception:
            # NOTE: Specially check for unexpected errors because SSD detection
            #       is somewhat brittle and I don't want errors to completely
            #       block opening a project
            print(
                '*** Unexpected error while checking whether project database is on SSD',
                file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            
            database_is_on_ssd = False  # conservative
        
        readonly_actual = readonly_requested or not can_write_db
        db = DatabaseConnection(raw_db, readonly_actual, mark_dirty_func)
        try:
            # Enable use of REGEXP operator and regexp() function
            db.create_function('regexp', 2, lambda x, y: re.search(x, y) is not None)
            
            # Check whether the database is actually writable by SQLite.
            # Some remote filesystems (such as GVFS/SFTP) may support
            # creating a database file but not actually writing to it.
            if not readonly_actual:
                try:
                    with closing(db.cursor()) as c:
                        c.execute('pragma user_version = user_version')
                except Exception as e:
                    if is_database_read_only_error(e):
                        readonly_actual = True  # reinterpret
                    else:
                        raise
            
            if expect_writable and readonly_actual:
                raise ProjectReadOnlyError(
                    f'Cannot open project database as writable at {project_path!r}')
            
            # Prefer Write Ahead Log (WAL) mode for higher performance
            if not readonly_actual:
                with closing(db.cursor()) as c:
                    [(new_journal_mode,)] = c.execute('pragma journal_mode = wal')
                    if new_journal_mode != 'wal':
                        print(
                            '*** Unable to open database in WAL mode. '
                                'Downloads may be slower.',
                            file=sys.stderr)
            
            yield (db, readonly_actual, database_is_on_ssd)
        except:
            cls._close_database(db, readonly_actual)
            raise
    
    def _start_scheduler(self) -> None:
        """
        Starts the scheduler thread for this project.
        
        Effects of this method are reversed by `_stop_scheduler()`.
        """
        import crystal.task
        
        # Recreate the root task
        old_root_task = getattr(self, 'root_task', None)  # capture
        new_root_task = crystal.task.RootTask()
        self.root_task = new_root_task  # export
        
        # Notify listeners if this is a root task change (not initial creation)
        if old_root_task is not None:
            self._root_task_did_change(old_root_task, new_root_task)
        
        # Start the scheduler (after preparing everything else)
        self._scheduler_thread = (
            crystal.task.start_scheduler_thread(new_root_task)
        )  # type: threading.Thread | None
    
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
            Project._ensure_directory_structure_valid(normalized_path)
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
    def _ensure_directory_structure_valid(path: str) -> None:
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
            progress_listener: OpenProjectProgressListener) -> None:
        """
        Upgrades this project's directory structure and database schema
        to the latest version.
        
        The major version 1 -> 2 migration is resumable if cancelled or interrupted.
        Migration progress is periodically synced to disk (every ~4,096 revisions).
        
        Raises:
        * ProjectReadOnlyError
        * CancelOpenProject
        * sqlite3.DatabaseError, OSError
        """
        # Add missing database columns and indexes
        with self._db, closing(self._db.cursor()) as c:
            index_names = get_index_names(c)  # cache
            table_names = get_table_names(c)  # cache
            
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
            
            # Add alias table if missing
            if 'alias' not in table_names:
                progress_listener.upgrading_project('Adding aliases table...')
                c.execute('create table alias (id integer primary key, source_url_prefix text unique not null, target_url_prefix text not null, target_is_external integer not null default 0)')
        
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
            with self._db, closing(self._db.cursor()) as c:
                major_version = self._get_major_version(c)
            
            # Upgrade major version 1 -> 2
            if major_version == 1:
                self._migrate_v1_to_v2(progress_listener)
            
            # At major version 2
            if major_version == 2:
                # If did not finish commit of "Upgrade major version 1 -> 2",
                # resume the commit
                ip_revisions_dirpath = os.path.join(
                    self.path, self._IN_PROGRESS_REVISIONS_DIRNAME)  # cache
                if os.path.exists(ip_revisions_dirpath):
                    self._commit_migrate_v1_to_v2()

                # Nothing to do
                pass
            
            # At major version 3
            if major_version == 3:
                # Check if migration from v2 is in progress
                with self._db, closing(self._db.cursor()) as c:
                    major_version_old = self._get_major_version_old(c)
                if major_version_old == 2:
                    self._migrate_v2_to_v3(progress_listener)

            assert self._LATEST_SUPPORTED_MAJOR_VERSION == 3
    
    def _migrate_v1_to_v2(self,
            progress_listener: OpenProjectProgressListener,
            ) -> None:
        """
        Raises:
        * sqlite3.DatabaseError, OSError
        """
        revisions_dirpath = os.path.join(
            self.path, self._REVISIONS_DIRNAME)  # cache
        ip_revisions_dirpath = os.path.join(
            self.path, self._IN_PROGRESS_REVISIONS_DIRNAME)  # cache
        tmp_revisions_dirpath = os.path.join(
            self.path, self._TEMPORARY_DIRNAME, self._REVISIONS_DIRNAME)  # cache
        
        def calculate_new_revision_filepath(id: int) -> tuple[str, str]:
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
            return (new_revision_filepath, new_revision_parent_relpath)
        
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
            
            (new_revision_filepath, new_revision_parent_relpath) = \
                calculate_new_revision_filepath(id)
            
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
            
            if new_revision_filepath.endswith('fff'):
                # Flush all changes to leaf directory before moving
                # on to the next leaf directory
                flush_renames_in_directory(
                    os.path.dirname(new_revision_filepath)
                )
        # TODO: Dump profiling context immediately upon exit of context
        #       rather then waiting for program to exit
        with create_profiling_context(
                'migrate_revisions.prof', enabled=_PROFILE_MIGRATE_REVISIONS):
            try:
                with self._db, closing(self._db.cursor()) as c:
                    self._process_table_rows(
                        c,
                        # NOTE: The following query to approximate row count is
                        #       significantly faster than the exact query
                        #       ('select count(1) from resource_revision') because it
                        #       does not require a full table scan.
                        ResourceRevision._MAX_REVISION_ID_QUERY,
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
                # Locate last revision ID.
                # Flush all changes to its parent directory.
                with self._db, closing(self._db.cursor()) as c:
                    rows = list(c.execute(ResourceRevision._MAX_REVISION_ID_QUERY))
                if len(rows) == 1:
                    [(max_revision_id,)] = rows
                else:
                    [] = rows
                    max_revision_id = None
                if max_revision_id is not None:
                    (new_revision_filepath, _) = \
                        calculate_new_revision_filepath(max_revision_id)
                    flush_renames_in_directory(
                        os.path.dirname(new_revision_filepath)
                    )
                
                self._commit_migrate_v1_to_v2()
    
    def _commit_migrate_v1_to_v2(self) -> None:
        """
        Raises:
        * sqlite3.DatabaseError, OSError
        """
        with self._db, closing(self._db.cursor()) as c:
            assert self._get_major_version(c) in [1, 2]
        
        revisions_dirpath = os.path.join(
            self.path, self._REVISIONS_DIRNAME)  # cache
        ip_revisions_dirpath = os.path.join(
            self.path, self._IN_PROGRESS_REVISIONS_DIRNAME)  # cache
        tmp_revisions_dirpath = os.path.join(
            self.path, self._TEMPORARY_DIRNAME, self._REVISIONS_DIRNAME)  # cache
        
        # Start commit
        major_version = 2
        self._set_major_version(major_version, self._db)
        # (If crash happens between here and "Finish commit",
        #  reopening the project will resume the commit)
        
        # Move aside old revisions directory and queue it for deletion
        os.rename(revisions_dirpath, tmp_revisions_dirpath)
        
        # 1. Move new revisions directory to final location
        # 2. Finish commit
        replace_and_flush(ip_revisions_dirpath, revisions_dirpath)
    
    def _migrate_v2_to_v3(self,
            progress_listener: OpenProjectProgressListener,
            ) -> None:
        """
        Migrates a project from major version 2 (Hierarchical) to major version 3 (Pack16).

        Packs all existing hierarchical revision files into groups of 16 (pack zip files).
        Incomplete packs (fewer than 16 revisions) remain as individual files.

        Raises:
        * CancelOpenProject
        * sqlite3.DatabaseError, OSError
        """
        with self._db, closing(self._db.cursor()) as c:
            assert self._get_major_version(c) == 3
            assert self._get_major_version_old(c) == 2

        # Get max revision ID for progress reporting
        with self._db, closing(self._db.cursor()) as c:
            rows = list(c.execute(ResourceRevision._MAX_REVISION_ID_QUERY))
        if len(rows) == 1:
            [(max_revision_id,)] = rows
        else:
            max_revision_id = 0
        approx_revision_count = max_revision_id or 0

        # Report that migration is starting/resuming
        progress_listener.will_upgrade_revisions(
            approx_revision_count,
            # Disallow veto because migration already in progress
            can_veto=False,
        )  # may raise CancelOpenProject

        # Process complete packs: Scan pack groups 0-15, 16-31, 32-47, ...
        # NOTE: Safe to assert sync'ed with scheduler thread because that thread is not running.
        #       This thread has exclusive access to the project while it is being migrated.
        # HACK: Uses scheduler_thread_context(), which is intended for testing only
        from crystal.tests.util.tasks import scheduler_thread_context
        with scheduler_thread_context():
            start_time = time.monotonic()  # capture
            last_report_time = start_time
            pack_start_id = 0
            while True:
                pack_end_id = pack_start_id + 15
                if pack_end_id > max_revision_id:
                    # Incomplete last group. Leave as individual files.
                    break

                # Pack revisions [pack_start_id, pack_end_id], if not already done
                pack_filepath = ResourceRevision._body_pack_filepath_with(self.path, pack_end_id)
                if not os.path.exists(pack_filepath):
                    ResourceRevision._pack_revisions_for_id(
                        self, pack_end_id, project_major_version=3)
                pack_start_id += 16

                # Report progress approximately once per second
                current_time = time.monotonic()  # capture
                if current_time - last_report_time >= 1.0 or Project._report_progress_at_maximum_resolution:
                    elapsed = current_time - start_time
                    revisions_processed = pack_start_id
                    revisions_per_second = revisions_processed / elapsed if elapsed > 0 else 0.0
                    progress_listener.upgrading_revision(
                        revisions_processed,
                        revisions_per_second,
                    )  # may raise CancelOpenProject
                    last_report_time = current_time
            revisions_processed = pack_start_id

        # Migration complete. Remove migration marker.
        self._delete_major_version_old(self._db)

        progress_listener.did_upgrade_revisions(revisions_processed)

    def _repair_incomplete_rollback_of_resource_revision_create(self) -> None:
        """
        If the last revision was likely intended to be deleted by a
        failed rollback in ResourceRevision._create_from_stream,
        then delete it.
        
        Rationale for checking only the last revision:
        - Revisions are written with sequential IDs from the database.
        - A rollback which failed due to a permanent I/O failure (that prevented
          any further I/O operations on the project the last time it was opened)
          would have occurred during the most recent write operation
          (the revision with the highest ID).
            - Disk disconnection - especially for network filesystems - is a
              common case of a permanent I/O failure
        - Older revisions completed successfully or failed and were
          rolled back fully.
        
        Raises:
        * sqlite3.DatabaseError
        """
        
        # Locate last revision
        with self._db, closing(self._db.cursor()) as c:
            rows = list(c.execute(ResourceRevision._MAX_REVISION_ID_QUERY))
        if len(rows) == 1:
            [(max_revision_id,)] = rows
        else:
            # No max revision exists to repair
            return
        try:
            last_revision = ResourceRevision.load(self, max_revision_id)
        except Exception as e:
            # Database potentially corrupt?
            # Abort further repair attempts.
            return
        assert last_revision is not None
        
        # Check whether last revision's body is missing,
        # which could be the result of a failed rollback
        try:
            with last_revision.open() as f:
                # Body exists. No rollback was attempted.
                return
        except RevisionBodyMissingError:
            # Body is missing
            pass  # keep going
        except NoRevisionBodyError:
            # No body expected. No rollback could have been attempted.
            return
        except (OSError, IOError):
            # Database or filesystem potentially corrupt?
            # Abort further repair attempts.
            return
        
        # Check whether at least 3 other revisions have readable bodies.
        # If so then the last revision's body being missing is likely to
        # be legitimately orphaned by a failed rollback.
        with self._db, closing(self._db.cursor()) as c:
            rows = list(c.execute(
                'select id from resource_revision '
                    # NOTE: error == "null" filters out revisions where
                    #       no body is expected (i.e. has_body == False)
                    'where error == "null" and id < ? '
                    'order by id desc '
                    'limit 3',
                (max_revision_id,)
            ))
        if len(rows) < 3:
            # Not enough revisions to make a determination RE whether a rollback failed.
            # Be conservative and don't try to continue the rollback.
            return
        try:
            other_revisions = [ResourceRevision.load(self, id) for (id,) in rows]
        except Exception as e:
            # Database potentially corrupt?
            # Abort further repair attempts.
            return
        unreadable_body_count = 0
        for rev in other_revisions:
            assert rev is not None, 'Revision not found yet already verified to exist'
            assert rev.has_body, 'Revision not expecting a body should have been filtered out'
            try:
                with rev.open() as f:
                    # Body exists and is readable enough to successfully open
                    pass
            except RevisionBodyMissingError:
                # Body is missing
                unreadable_body_count += 1
            except NoRevisionBodyError:
                # No body expected
                raise AssertionError(
                    'Revision not expecting a body should have been filtered out')
            except (OSError, IOError):
                # Body is corrupted or inaccessible
                unreadable_body_count += 1
        if unreadable_body_count != 0:
            # Multiple revision bodies are unreadable
            # (the last one and at least one other) which suggests something
            # strange is going on, separate from a rollback failure.
            # Abort further repair attempts.
            # 
            # Likely causes:
            # - Revisions directory is on a temporarily-unmounted filesystem.
            #   All revision bodies are unreadable.
            # - Revisions directory is on a filesystem with intermittent
            #   availability (packet loss, flaky connection).
            #   Revision bodies are unreadable at random times.
            # - Multiple revisions have filesystem corruption.
            return
        else:
            # At least 3 other revision bodies are readable,
            # which is strong evidence that:
            # 1. The filesystem is mounted and accessible
            # 2. The filesystem does not have intermittent availability issues
            # 3. The last revision's missing body is unusual and likely
            #    related to a failed rollback when writing the most recent
            #    revision during the previous project session
            pass
        
        # Resume failed rollback of the last revision, by deleting it
        print(
            f'*** Cleaning up likely-orphaned revision {last_revision._id}. '
            'Missing body file. Probable rollback failure.',
            file=sys.stderr,
        )
        # Delete database row. Ignore the missing body file.
        # NOTE: Safe to assert sync'ed with scheduler thread because that thread is not running.
        #       This thread has exclusive access to the project while it is being created.
        # HACK: Uses scheduler_thread_context(), which is intended for testing only
        from crystal.tests.util.tasks import scheduler_thread_context
        with scheduler_thread_context():
            try:
                # NOTE: Safe to call because scheduler thread is not running
                #       and this thread has exclusive access to the project
                #       while it is being created
                last_revision._delete_now()
            except Exception as e:
                # Repair failed. Continue opening the project anyway.
                return
    
    def _repair_missing_pack_of_resource_revision_create(self) -> None:
        """
        Detects and completes any incomplete pack files on project open.

        This is a recovery mechanism for Pack16 format projects that may have
        had incomplete packs due to disk-full errors or crashes during previous sessions.

        Only applies to the highest-numbered pack that should exist based on the
        highest revision ID in the database.
        """
        # Locate last revision and related pack boundaries
        with self._db, closing(self._db.cursor()) as c:
            rows = list(c.execute(ResourceRevision._MAX_REVISION_ID_QUERY))
        if len(rows) == 1:
            [(max_revision_id,)] = rows
        else:
            # No max revision exists to repair
            return
        if (max_revision_id % 16) != 15:
            # No pack operation to repair
            return
        pack_base_id = max_revision_id - 15
        pack_end_id = max_revision_id
        
        # Check whether pack file is missing
        pack_filepath = ResourceRevision._body_pack_filepath_with(self.path, max_revision_id)
        if os.path.exists(pack_filepath):
            return
        
        # Check if there are any individual revision files that should be in the pack
        has_any_revision_files = False
        for rid in range(pack_base_id, pack_end_id + 1):
            hierarchical_body_filepath = ResourceRevision._body_filepath_with(self.path, 2, rid)
            if os.path.exists(hierarchical_body_filepath):
                has_any_revision_files = True
                break
        if not has_any_revision_files:
            # No individual files exist. Nothing to pack.
            return
        
        # Create the pack file from the individual revision files
        # NOTE: Safe to assert sync'ed with scheduler thread because that thread is not running.
        #       This thread has exclusive access to the project while it is being created.
        # HACK: Uses scheduler_thread_context(), which is intended for testing only
        from crystal.tests.util.tasks import scheduler_thread_context
        with scheduler_thread_context():
            ResourceRevision._pack_revisions_for_id(self, pack_end_id)
    
    # TODO: Consider accepting `db: DatabaseConnection` rather than `c: DatabaseCursor`
    @staticmethod
    def _get_major_version(c: DatabaseCursor | sqlite3.Cursor) -> int:
        """Gets the major version of a project, before the project's properties are loaded."""
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
    def _set_major_version(major_version: int, db: DatabaseConnection) -> None:
        """Sets the major version of a project, before the project's properties are loaded."""
        with db, closing(db.cursor()) as c:
            c.execute(
                'insert or replace into project_property (name, value) values (?, ?)',
                ('major_version', major_version))

    @staticmethod
    def _get_major_version_old(c: DatabaseCursor | sqlite3.Cursor) -> int | None:
        """
        Gets the major_version_old migration marker, or None if not set.

        This marker is set when a migration is in progress (e.g., v2 -> v3).
        It records the old major version before the migration started.
        """
        rows = list(c.execute(
            'select value from project_property where name = ?',
            ('major_version_old',)))
        if len(rows) == 0:
            return None
        [(value,)] = rows
        return int(value)

    @staticmethod
    def _set_major_version_old(major_version_old: int, db: DatabaseConnection) -> None:
        """Sets the major_version_old migration marker."""
        with db, closing(db.cursor()) as c:
            c.execute(
                'insert or replace into project_property (name, value) values (?, ?)',
                ('major_version_old', major_version_old))

    @staticmethod
    def _delete_major_version_old(db: DatabaseConnection) -> None:
        """Removes the major_version_old migration marker (signals migration complete)."""
        with db, closing(db.cursor()) as c:
            c.execute(
                'delete from project_property where name = ?',
                ('major_version_old',))

    # --- Load: Create & Load ---
    
    def _create(self) -> None:
        with self._db, closing(self._db.cursor()) as c:
            c.execute('create table project_property (name text unique not null, value text)')
            c.execute('create table resource (id integer primary key, url text unique not null)')
            # NOTE: Defines an FK constraint, but FK constraints aren't enforced in SQLite by default,
            #       and currently Crystal does not change the default.
            c.execute('create table root_resource (id integer primary key, name text not null, resource_id integer unique not null, foreign key (resource_id) references resource(id))')
            c.execute('create table resource_group (id integer primary key, name text not null, url_pattern text not null, source_type text, source_id integer)')
            # NOTE: Accidentally omits the FK constraint `foreign key (resource_id) references resource(id)`.
            #       - An FK constraint can't be added by an ALTER TABLE in SQLite -
            #         a (manual) complete table copy is required - which makes it
            #         difficult to migrate old projects to retroactively add one.
            #       - FK constraints aren't enforced in SQLite by default,
            #         and currently Crystal does not change the default.
            c.execute('create table resource_revision (id integer primary key, resource_id integer not null, request_cookie text, error text not null, metadata text not null)')
            c.execute('create table alias (id integer primary key, source_url_prefix text unique not null, target_url_prefix text not null, target_is_external integer not null default 0)')
            c.execute('create index resource_revision__resource_id on resource_revision (resource_id)')
        
        # (Define indexes later in _apply_migrations())
        
        # Set property values
        if True:
            # Define major version for new projects, for Crystal >1.6.0
            self._set_major_version(2, self._db)
            
            # Define default HTML parser for new projects, for Crystal >1.5.0
            self._set_html_parser_type('lxml', _change_while_loading=True)
    
    def _load(self,
            progress_listener: OpenProjectProgressListener) -> None:
        """
        Raises:
        * sqlite3.DatabaseError, OSError
        """
        
        # Upgrade database schema to latest version (unless is readonly)
        if not self.readonly:
            self._apply_migrations(progress_listener)
        
        # Ensure major version is recognized
        with self._db, closing(self._db.cursor()) as c:
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
        
        with self._db, closing(self._db.cursor()) as c:
            # Load project properties
            for (name, value) in c.execute('select name, value from project_property'):
                self._set_property(name, value)
            self._properties_loaded = True
            
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
            
            # Load Aliases
            table_names = get_table_names(c)
            if 'alias' in table_names:
                for (source_url_prefix, target_url_prefix, target_is_external, id) in c.execute(
                        'select source_url_prefix, target_url_prefix, target_is_external, id from alias order by id'):
                    Alias(self, source_url_prefix, target_url_prefix, target_is_external=bool(target_is_external), _id=id)
            
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
            [] = rows
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
    
    @property
    def is_untitled(self) -> bool:
        """
        Whether this project is untitled.
        
        A project is considered untitled if it was created in a temporary directory.
        """
        return self._is_untitled
    
    @property
    def is_dirty(self) -> bool:
        """
        Whether this project has been modified since it was last saved.
        
        A project is considered dirty if it is untitled and has been modified.
        """
        return self._is_dirty
    
    def _mark_dirty_if_untitled(self) -> None:
        """
        Marks this project as dirty if it is untitled.
        
        This method is called after any change is made to a project,
        automatically whenever a database write is performed,
        so that if it is an untitled project then it will later be saved to
        a permanent location.
        """
        if not self._is_untitled:
            return
        if self._is_dirty:
            return
        self._is_dirty = True
        
        for lis in self.listeners:
            if hasattr(lis, 'project_is_dirty_did_change'):
                run_bulkhead_call(lis.project_is_dirty_did_change)  # type: ignore[attr-defined]
    
    def _mark_clean_and_titled(self) -> None:
        """
        Marks this project as clean and titled.
        
        This method should be called after a project has been saved to a permanent location,
        so that it is no longer considered dirty.
        """
        if self._is_untitled:
            del app_prefs.unsaved_untitled_project_path
            self._is_untitled = False
        
        if self._is_dirty:
            self._is_dirty = False
            
            for lis in self.listeners:
                if hasattr(lis, 'project_is_dirty_did_change'):
                    run_bulkhead_call(lis.project_is_dirty_did_change)
    
    def _get_property(self, name: str, default: _OptionalStr) -> str | _OptionalStr:
        if not self._properties_loaded:
            if name == 'major_version':
                hint = ' Did you mean _get_major_version()?'
            else:
                hint = ''
            raise ValueError('Project properties are not yet loaded.' + hint)
        return self._properties.get(name) or default
    def _set_property(self, name: str, value: str | None, *, _change_while_loading: bool = False) -> None:
        if not self._loading or _change_while_loading:
            if self._properties.get(name) == value:
                return
            if self.readonly:
                raise ProjectReadOnlyError()
            with self._db, closing(self._db.cursor()) as c:
                c.execute('insert or replace into project_property (name, value) values (?, ?)', (name, value))
        self._properties[name] = value
    def _delete_property(self, name: str) -> None:
        if not self._loading:
            if name not in self._properties:
                return
            if self.readonly:
                raise ProjectReadOnlyError()
            with self._db, closing(self._db.cursor()) as c:
                c.execute('delete from project_property where name=?', (name,))
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
        
        See also:
        * _get_major_version -- Reads the major version before project properties are loaded
        * _set_major_version -- Writes the major version before project properties are loaded
        * _set_major_version_for_test -- Writes the major version, for tests
        """
        return int(self._get_property('major_version', '1'))

    def _set_major_version_for_test(self, version: int) -> None:
        """
        Sets the major version of this project.

        For testing purposes only.
        """
        self._set_property('major_version', str(version))

    def _set_major_version_old_for_test(self, version: int) -> None:
        """
        Sets the major_version_old migration marker of this project.

        For testing purposes only.
        """
        self._set_property('major_version_old', str(version))

    def _get_default_url_prefix(self) -> str | None:
        """
        URL prefix for the majority of this project's resource URLs.
        The UI will display resources under this prefix as relative URLs.
        """
        return self._get_property('default_url_prefix', None)
    def _set_default_url_prefix(self, value: str | None) -> None:
        self._set_property('default_url_prefix', value)
    default_url_prefix = cast(Optional[str], property(_get_default_url_prefix, _set_default_url_prefix))
    
    def _get_entity_title_format(self) -> EntityTitleFormat:
        value = self._get_property('entity_title_format', 'url_name')
        if value not in ('url_name', 'name_url'):
            # Replace unrecognized value with default value
            value = 'url_name'
        return value  # type: ignore[return-value]
    def _set_entity_title_format(self, value: EntityTitleFormat) -> None:
        if value not in ('url_name', 'name_url'):
            raise ValueError(f'Invalid entity_title_format: {value}')
        self._set_property('entity_title_format', value)
    entity_title_format = cast(EntityTitleFormat, property(
        _get_entity_title_format,
        _set_entity_title_format,
        doc="""Format for displaying entity titles in the Entity Tree."""))
    
    def get_display_url(self, url):
        """
        Returns a displayable version of the provided URL.
        
        - If the URL is an external URL (pointing to a live resource on the internet),
          it will be formatted with an icon prefix.
        - If the URL is not external and lies under the configured `default_url_prefix`, 
          that prefix will be stripped.
        """
        # Check if this is an external URL first
        if (external_url := Alias.parse_external_url(url)) is not None:
            return Alias.format_external_url_for_display(external_url)
        
        # Apply default URL prefix shortening for non-external URLs
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
    def _set_html_parser_type(self, value: HtmlParserType, *, _change_while_loading: bool=False) -> None:
        from crystal.doc.html import HTML_PARSER_TYPE_CHOICES
        if value not in HTML_PARSER_TYPE_CHOICES:
            raise ValueError(f'Unknown type of HTML parser: {value}')
        self._set_property('html_parser_type', value, _change_while_loading=_change_while_loading)
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
        
        with closing(self._db.cursor()) as c:
            try:
                return [
                    rc for (rc,) in
                    c.execute(f'select distinct request_cookie from resource_revision where request_cookie is not null order by id {ordering}')
                ]
            except Exception as e:
                if is_no_such_column_error_for('request_cookie', e):
                    # Fetch from <=1.2.0 database schema
                    return []
                else:
                    raise
    
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
            with closing(self._db.cursor()) as c:
                self._process_table_rows(
                    c,
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
        count2 = len(self._resource_for_id) + len(self._unsaved_resources)
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
            with closing(self._db.cursor()) as c:
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
            with closing(self._db.cursor()) as c:
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
            with closing(self._db.cursor()) as c:
                resources_data = c.execute('select id, url from resource order by id')
                return self._materialize_resources(resources_data)
    
    @property
    def _materialized_resources(self) -> Iterable[Resource]:
        """Returns all resource in the project that have been loaded into memory."""
        return self._resource_for_id.values()
    
    @fg_affinity
    def get_resource(self,
            # NOTE: "url" is NOT a keyword-only argument for backward compatibility
            url: str | _Missing = _Missing.VALUE,
            *, id: int | _Missing = _Missing.VALUE,
            ) -> Resource | None:
        """
        Returns the Resource with the specified URL or ID.
        Returns None if no matching resource exists.
        """
        if url != _Missing.VALUE:
            return self._get_resource_with_url(url)
        elif id != _Missing.VALUE:
            return self._get_resource_with_id(id)
        else:
            raise ValueError('Expected url or id to be specified')
    
    @fg_affinity
    def _get_resource_with_url(self, url: str) -> Resource | None:
        """
        Returns the Resource with the specified URL.
        Returns None if no such resource exists.
        """
        if self._did_load_urls:
            return self._resource_for_url.get(url)
        
        # Lookup/materialize Resource
        resource = self._resource_for_url.get(url)
        if resource is not None:
            return resource
        with closing(self._db.cursor()) as c:
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
    # Soft-deprecated: Use get_resource(id=...) instead.
    @fg_affinity
    def _get_resource_with_id(self, id: int) -> Resource | None:
        """
        Returns the Resource with the specified ID.
        Returns None if no such resource exists.
        """
        if self._did_load_urls:
            return self._resource_for_id.get(id)
        
        # Lookup/materialize Resource
        resource = self._resource_for_id.get(id)
        if resource is not None:
            return resource
        with closing(self._db.cursor()) as c:
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
    
    def get_root_resource(self,
            # NOTE: "resource" is NOT a keyword-only argument for backward compatibility
            resource: Resource | _Missing = _Missing.VALUE,
            *, id: int | _Missing = _Missing.VALUE,
            name: str | _Missing = _Missing.VALUE,
            url: str | _Missing = _Missing.VALUE,
            ) -> RootResource | None:
        """
        Returns the RootResource with the specified resource, ID, or name.
        Returns None if no matching root resource exists.
        """
        if resource != _Missing.VALUE:
            return self._root_resources.get(resource, None)
        elif id != _Missing.VALUE:
            # PERF: O(n) when it could be O(1), where n = # of RootResources
            for rr in self._root_resources.values():
                if rr._id == id:
                    return rr
            return None
        elif name != _Missing.VALUE:
            # PERF: O(n) when it could be O(1), where n = # of RootResources
            for rr in self._root_resources.values():
                if rr.name == name:
                    return rr
            return None
        elif url != _Missing.VALUE:
            r = self.get_resource(url)
            if r is None:
                return None
            return self.get_root_resource(r)
        else:
            raise ValueError('Expected resource, id, name, or url to be specified')
    
    # Soft-deprecated: Use get_root_resource(id=...) instead.
    def _get_root_resource_with_id(self, root_resource_id) -> RootResource | None:
        """Returns the `RootResource` with the specified ID or None if no such root resource exists."""
        return self.get_root_resource(id=root_resource_id)
    
    # Soft-deprecated: Use get_root_resource(name=...) instead.
    def _get_root_resource_with_name(self, name) -> RootResource | None:
        """Returns the `RootResource` with the specified name or None if no such root resource exists."""
        return self.get_root_resource(name=name)
    
    @property
    def resource_groups(self) -> Iterable[ResourceGroup]:
        """Returns all ResourceGroups in the project in the order they were created."""
        return self._resource_groups
    
    def get_resource_group(self,
            # NOTE: "name" is NOT a keyword-only argument for backward compatibility
            name: str | _Missing = _Missing.VALUE,
            *, url_pattern: str | _Missing = _Missing.VALUE,
            id: int | _Missing = _Missing.VALUE
            ) -> ResourceGroup | None:
        """
        Returns the ResourceGroup with the specified name, URL pattern, or ID.
        Returns None if no matching group exists.
        """
        if name != _Missing.VALUE:
            # PERF: O(n) when it could be O(1), where n = # of ResourceGroups
            for rg in self._resource_groups:
                if rg.name == name:
                    return rg
            return None
        elif url_pattern != _Missing.VALUE:
            # PERF: O(n) when it could be O(1), where n = # of ResourceGroups
            for rg in self._resource_groups:
                if rg.url_pattern == url_pattern:
                    return rg
            return None
        elif id != _Missing.VALUE:
            # PERF: O(n) when it could be O(1), where n = # of ResourceGroups
            for rg in self._resource_groups:
                if rg._id == id:
                    return rg
            return None
        else:
            raise ValueError('Expected name, url_pattern, or id to be specified')
    
    # Soft-deprecated: Use get_resource_group(id=...) instead.
    def _get_resource_group_with_id(self, resource_group_id) -> ResourceGroup | None:
        """Returns the ResourceGroup with the specified ID or None if no such group exists."""
        return self.get_resource_group(id=resource_group_id)
    
    @property
    def aliases(self) -> Iterable[Alias]:
        """Returns all Aliases in the project in the order they were created."""
        return self._aliases
    
    @fg_affinity
    def get_alias(self,
            source_url_prefix: str | _Missing = _Missing.VALUE,
            *, target_url_prefix: str | _Missing = _Missing.VALUE,
            id: int | _Missing = _Missing.VALUE,
            ) -> Alias | None:
        """
        Returns the Alias with the specified URL prefix or ID.
        Returns None if no matching alias exists.
        """
        if source_url_prefix != _Missing.VALUE:
            for existing_alias in self._aliases:
                if existing_alias.source_url_prefix == source_url_prefix:
                    return existing_alias
            return None
        elif target_url_prefix != _Missing.VALUE:
            for existing_alias in self._aliases:
                if existing_alias.target_url_prefix == target_url_prefix:
                    return existing_alias
            return None
        elif id != _Missing.VALUE:
            for existing_alias in self._aliases:
                if existing_alias._id == id:
                    return existing_alias
            return None
        else:
            raise ValueError('Expected source_url_prefix, target_url_prefix, or id to be specified')
    
    # NOTE: Used by tests
    def _revision_count(self) -> int:
        with closing(self._db.cursor()) as c:
            [(revision_count,)] = c.execute('select count(1) from resource_revision')
            return revision_count
    
    # === Tasks ===
    
    def add_task(self, task: Task) -> None:
        """
        Schedules the specified top-level task for execution,
        unless it is already complete.
        
        Can be called from any thread.
        
        Raises:
        * ProjectClosedError -- if this project is closed
        """
        if task.complete:
            # Do not schedule already complete tasks
            return
        self.root_task.append_child(task)
    
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
                tasks.append(DownloadResourceTask(
                    r,
                    needs_result=False,
                    ignore_already_downloaded_this_session=True))
            elif hibernated_task['type'] == 'DownloadResourceGroupTask':
                rg = self._get_resource_group_with_id(int(hibernated_task['group_id']))
                if rg is None:
                    # ResourceGroup no longer exists. Ignore related download.
                    continue
                tasks.append(DownloadResourceGroupTask(rg))
            else:
                raise ValueError('Unknown task type: ' + hibernated_task['type'])
        for t in tasks:
            assert not t.complete, (
                f'Unhibernated task is already complete '
                f'but was not complete when it was hibernated: {t!r}'
            )
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
    
    # === Events: Alias Lifecycle ===
    
    # Called when a new Alias is created after the project has loaded
    def _alias_did_instantiate(self, alias: Alias) -> None:
        # Notify normal listeners
        for lis in self.listeners:
            if hasattr(lis, 'alias_did_instantiate'):
                run_bulkhead_call(lis.alias_did_instantiate, alias)  # type: ignore[attr-defined]
    
    def _alias_did_change(self, alias: Alias) -> None:
        # Notify normal listeners
        for lis in self.listeners:
            if hasattr(lis, 'alias_did_change'):
                run_bulkhead_call(lis.alias_did_change, alias)  # type: ignore[attr-defined]
    
    def _alias_did_forget(self, alias: Alias) -> None:
        # Notify normal listeners
        for lis in self.listeners:
            if hasattr(lis, 'alias_did_forget'):
                run_bulkhead_call(lis.alias_did_forget, alias)  # type: ignore[attr-defined]
    
    # === Events: Root Task Lifecycle ===
    
    def _root_task_did_change(self, old_root_task: 'RootTask', new_root_task: 'RootTask') -> None:
        # Notify normal listeners
        for lis in self.listeners:
            if hasattr(lis, 'project_root_task_did_change'):
                run_bulkhead_call(lis.project_root_task_did_change, old_root_task, new_root_task)  # type: ignore[attr-defined]
    
    # === Save As ===
    
    @fg_affinity
    def save_as(self,
            new_path: str,
            progress_listener: Optional['SaveAsProgressListener'] = None
            ) -> Future[None]:
        """
        Saves this project to the specified path soon, which must not already exist.
        This project will be reopened at the new path.
        
        If a failure occurs when saving the new project this project will
        remain open at its original path.
        
        Raises in returned Future:
        * FileExistsError --
            if a file or directory exists at the specified path
        * ProjectReadOnlyError --
            the specified path is not writable
        * CancelSaveAs --
            if the user cancels the save operation
        """
        return start_thread_switching_coroutine(
            SwitchToThread.FOREGROUND,
            self._save_as_coro(new_path, progress_listener),
            capture_crashes_to_deco=None,
            uses_future_result=True
        )
    
    @fg_affinity
    def _save_as_coro(self,
            new_path: str, 
            progress_listener: Optional['SaveAsProgressListener'] = None
            ) -> Generator[SwitchToThread, None, None]:
        if os.path.exists(new_path):
            raise FileExistsError(
                f'Cannot save project to {new_path!r} because a file or '
                f'directory already exists at that path')
        
        if not new_path.endswith(Project.FILE_EXTENSION):
            raise ValueError(
                f'Cannot save project to {new_path!r} because it does not end with '
                f'the expected file extension {Project.FILE_EXTENSION!r}')
        new_partial_path = (
            new_path.removesuffix(Project.FILE_EXTENSION) +
            Project.PARTIAL_FILE_EXTENSION
        )
        
        old_path = self.path  # capture
        was_untitled = self._is_untitled  # capture
        
        # Save the current state of tasks
        if not self.readonly:
            self.hibernate_tasks()
        
        try:
            # - Stop and destroy tasks
            # - Stop scheduler
            # - Close database
            # NOTE: Failures during close may indicate that the in-memory
            #       Project state is somehow inconsistent. Thus when the
            #       recovery code below attempts to reopen using the same
            #       Project state it may fail again.
            self.close(capture_crashes=False, _will_reopen=True)
            
            # Reset session state that could affect how tasks are unhibernated
            for r in self._materialized_resources:
                r.already_downloaded_this_session = False
            
            # Move/copy the project directory to the new path.
            # - If the project is untitled, it will be renamed.
            # - If the project is titled, it will be copied.
            yield SwitchToThread.BACKGROUND
            try:
                if self._is_untitled:
                    # Move the project directory to the new path
                    try:
                        # Try atomic move first
                        os.rename(old_path, new_path)
                    except OSError:
                        # Try copy and delete if atomic move fails
                        
                        # Copy
                        self._copytree_of_project_with_progress(
                            old_path, new_partial_path, progress_listener)
                        os.rename(new_partial_path, new_path)
                        
                        # Delete
                        # (Later in this method,
                        #  at call to Project._delete_in_background)

                    self._is_untitled = False
                else:
                    # Copy the project directory to the new path
                    self._copytree_of_project_with_progress(
                        self.path, new_partial_path, progress_listener)
                    os.rename(new_partial_path, new_path)
            except:
                # Clean up partial copy if an error occurs
                if os.path.exists(new_partial_path):
                    try:
                        send2trash(new_partial_path)
                    except (TrashPermissionError, OSError, Exception):
                        # Give up. Leave the partial copy in place
                        # for the user to delete manually.
                        if tests_are_running():
                            print(
                                f'*** send2trash failed. Partial copy left at: {new_partial_path!r} '
                                f'Consider using _rmtree_fallback_for_send2trash().',
                                file=sys.stderr)
                
                raise
            
            # - Open database
            # - Start scheduler
            yield SwitchToThread.FOREGROUND
            self.path = new_path
            # NOTE: May change the readonly status of this Project
            self._reopen()
            
            # Restore the state of tasks
            if not self.readonly:
                self.unhibernate_tasks()
            
            # Bulk-save any unsaved resources, populating the resource IDs
            if not self.readonly and len(self._unsaved_resources) > 0:
                ids = Resource._bulk_create_resource_ids_for_urls(
                    self,
                    [r.url for r in self._unsaved_resources],
                    origin_url=None,  # multiple origins
                )
                for (r, id) in zip(self._unsaved_resources, ids, strict=True):
                    r._finish_save(id)
                self._unsaved_resources.clear()
                self._check_url_collection_invariants()
        except:
            # Try to reopen the project at the old path
            if os.path.exists(old_path):
                yield SwitchToThread.FOREGROUND
                self.path = old_path
                self._reopen()
                if not self.readonly:
                    self.unhibernate_tasks()
            
            raise
        else:
            self._mark_clean_and_titled()
            assert self._is_untitled == False
            assert self._is_dirty == False

            # Delete old project if it was untitled and is still present
            if was_untitled and os.path.exists(old_path):
                Project._delete_in_background(old_path)
    
    @staticmethod
    @bg_affinity
    def _copytree_of_project_with_progress(
            src_project_dirpath: str,
            dst_project_dirpath: str,
            progress_listener: 'SaveAsProgressListener | None' = None
            ) -> None:
        """
        Copies an entire directory tree to a new location with progress reporting.
        
        Raises:
        * CancelSaveAs -- if the user cancels the operation
        * ProjectFormatError -- if the project format appears to be invalid
        """
        # Sample size chosen to be large enough to provide a reasonable estimate
        # of project size without taking too much time to collect.
        # 
        # On a 5,400 RPM HDD:
        # - Find Sample Time: 7.14 seconds
        # - Size Sample Time: 8.04 seconds
        # 
        # On an SSD:
        # - Find Sample Time: 0.25 seconds
        # - Size Sample Time: 0.23 seconds
        REVISIONS_SAMPLE_SIZE = 256  # revisions
        
        # Ensure at least 1 report will be made during each 1-second interval
        TARGET_MAX_DELAY_BETWEEN_REPORTS = 0.5  # seconds
        
        if progress_listener is None:
            from crystal.progress import DummySaveAsProgressListener
            progress_listener = DummySaveAsProgressListener()
        
        # Calculate approximate size of project resource revision files
        approx_revision_count: int
        approx_revision_data_size: int
        if True:
            # 1. Count approximate number of revisions
            # 2. Get project major version
            # 3. Get IDs for random revision sample
            approx_revision_count: int  # type: ignore[no-redef]
            major_version: int
            random_revision_ids: list[int]
            db_filepath = os.path.join(src_project_dirpath, Project._DB_FILENAME)
            db_connect_query = '?mode=ro'
            db_raw = sqlite3.connect(
                'file:' + url_quote(db_filepath) + db_connect_query,
                uri=True)
            with db_raw, closing(db_raw.cursor()) as c:
                # NOTE: This is much faster than count(1)
                [(max_revision_id,)] = c.execute('select max(id) from resource_revision')
                approx_revision_count = max_revision_id or 0
                
                major_version = Project._get_major_version(c)
                
                # Estimate total size of all resource revisions
                progress_listener.calculating_total_size(
                    f'Sampling {REVISIONS_SAMPLE_SIZE:,} of about {approx_revision_count:,} revisions...')
                try:
                    random_revision_ids = random_choices_from_table_ids(
                        k=REVISIONS_SAMPLE_SIZE,
                        table_name='resource_revision',
                        c=c
                    )
                except IndexError:
                    # If the table is empty, size will be zero
                    random_revision_ids = []
            
            # Get sizes for random revision sample
            size_for_revision_id: dict[int, int] = {}
            progress_listener.calculating_total_size(f'Sizing sample of {REVISIONS_SAMPLE_SIZE:,} revisions...')
            for revision_id in random_revision_ids:
                if revision_id in size_for_revision_id:
                    continue
                revision_body_filepath = ResourceRevision._body_filepath_with(
                    project_path=src_project_dirpath,
                    major_version=major_version,
                    revision_id=revision_id)
                try:
                    size_for_revision_id[revision_id] = os.path.getsize(revision_body_filepath)
                except OSError:
                    # File doesn't exist or is inaccessible
                    continue
            if len(size_for_revision_id) == 0 and approx_revision_count > 0:
                raise ProjectFormatError(
                    f'Unable to locate any of {REVISIONS_SAMPLE_SIZE} resource revisions '
                    f'for project {src_project_dirpath!r}')
            
            # Estimate total size of all resource revisions based on the sample
            approx_revision_data_size = math.ceil(
                sum(size_for_revision_id.values()) * 
                approx_revision_count / REVISIONS_SAMPLE_SIZE
            )
        
        # Calculate total size of source project directory
        total_byte_count = 0
        total_file_count = 0
        progress_listener.calculating_total_size('Sizing remaining project files...')
        # NOTE: topdown=True is used to:
        #       (1) allow skipping the revisions directory and to
        #       (2) size the project database (which resides directly
        #           within the project directory) as early as possible
        for (parent_dirpath, dirnames, filenames) in os.walk(src_project_dirpath, topdown=True):
            # If the revisions directory is encountered, add its approximate size
            # and file count to the totals rather than walking into it
            if parent_dirpath == src_project_dirpath and Project._REVISIONS_DIRNAME in dirnames:
                total_byte_count += approx_revision_data_size
                total_file_count += approx_revision_count
                dirnames.remove(Project._REVISIONS_DIRNAME)
            
            for filename in filenames:
                filepath = os.path.join(parent_dirpath, filename)
                try:
                    # TODO: Access the os.DirEntry object from the os.scandir() call
                    #       used inside of os.walk() to avoid calls to os.path.getsize()
                    total_byte_count += os.path.getsize(filepath)
                    total_file_count += 1
                except OSError:
                    # File is inaccessible
                    continue
        progress_listener.total_size_calculated(total_file_count, total_byte_count)
        
        # Copy project directory contents, with progress reporting
        bytes_copied = 0
        files_copied = 0
        start_time = time.monotonic()  # capture
        last_report_time = start_time
        os.mkdir(dst_project_dirpath)
        for (src_parent_dirpath, dst_parent_dirpath, dirnames, filenames) in walkzip(
                src_project_dirpath, dst_project_dirpath, topdown=True):
            # Ensure files and directories are copied in a deterministic lexicographic order
            filenames.sort()
            dirnames.sort()

            # Copy files to the current destination directory
            for filename in filenames:
                src_filepath = os.path.join(src_parent_dirpath, filename)
                dst_filepath = os.path.join(dst_parent_dirpath, filename)
                
                # Copy the file
                with open(src_filepath, 'rb') as src_file, \
                        open(dst_filepath, 'wb') as dst_file:
                    # Copy in chunks to allow progress reporting
                    while True:
                        chunk = src_file.read(COPY_BUFSIZE)
                        if not chunk:
                            break
                        
                        dst_file.write(chunk)
                        bytes_copied += len(chunk)
                        
                        # Report progress, but not too frequently
                        current_time = time.monotonic()  # capture
                        if (current_time - last_report_time) >= TARGET_MAX_DELAY_BETWEEN_REPORTS:
                            elapsed = current_time - start_time
                            bytes_per_second = bytes_copied / elapsed if elapsed > 0 else 0
                            progress_listener.copying(
                                min(files_copied, total_file_count),
                                filename,
                                min(bytes_copied, total_byte_count),
                                bytes_per_second)
                            
                            last_report_time = current_time
                
                # Preserve file metadata
                try:
                    shutil.copystat(src_filepath, dst_filepath)
                except OSError:
                    # Some metadata might not be copyable, ignore errors
                    pass
                
                files_copied += 1
            
            # Create directories in the current destination directory
            for dirname in dirnames:
                dst_dirpath = os.path.join(dst_parent_dirpath, dirname)
                os.mkdir(dst_dirpath)
        
        # Final progress report
        if True:
            elapsed = time.monotonic() - start_time
            bytes_per_second = bytes_copied / elapsed if elapsed > 0 else 0
            progress_listener.copying(
                files_copied,
                '',  # Placeholder filename for final report
                min(bytes_copied, total_byte_count),
                bytes_per_second)
            
            progress_listener.did_copy_files()
    
    @staticmethod
    def _delete_in_background(old_path: str) -> None:
        # Try to send the project to the
        # OS temporary directory, where it will
        # be deleted when the computer restarts
        try:
            temp_dirpath = tempfile.gettempdir()
            old_path_in_temp = os.path.join(temp_dirpath, os.path.basename(old_path))
            if old_path_in_temp != old_path:
                os.rename(old_path, old_path_in_temp)
        except:
            # Give up
            pass
        else:
            old_path = old_path_in_temp  # reinterpret

        # Delete, on a best-effort basis, in the background
        # NOTE: If the delete fails or is interrupted the
        #       old path should be pointing to a 
        #       temporary directory that will eventually
        #       be cleaned up by the OS later.
        @capture_crashes_to_stderr
        def bg_delete_old_path() -> None:
            try:
                shutil.rmtree(old_path)
            except OSError:
                # Give up
                pass
        bg_call_later(
            bg_delete_old_path,
            name='Project.delete_in_background',
            daemon=True,
        )
    
    # === Close & Reopen ===
    
    @fg_affinity
    def close(self, *, capture_crashes: bool=True, _will_reopen: bool=False) -> None:
        """
        Closes this project soon, stopping any tasks and closing all files.
        
        By default this method captures any exceptions that occur internally
        since the caller doesn't usually have a realistic way to handle them.
        
        Effects of this method are reversed by `reopen()`.
        
        This method is prepared to operate on projects with corrupted state,
        since even corrupted projects will attempt to close themselves gracefully.
        
        It is safe to call this method multiple times, even after the project has closed.
        """
        if self._closed:
            # Already closed
            return
        
        try:
            guarded = (
                capture_crashes_to_stderr if capture_crashes else (lambda f: f)
            )
            @guarded
            def do_close() -> None:
                try:
                    self._stop_scheduler()
                finally:
                    try:
                        self._close_database(self._db, self.readonly)
                    finally:
                        try:
                            if self.is_untitled and not _will_reopen:
                                # Forget the untitled project during a normal close operation
                                # so that Crystal does not attempt to reopen it later
                                del app_prefs.unsaved_untitled_project_path
                                
                                try:
                                    # Try to send the untitled project to the trash,
                                    # where the user can easily recover it if they change
                                    # their mind about not saving it
                                    send2trash(self.path)
                                except:
                                    try:
                                        # Try to send the untitled project to the
                                        # OS temporary directory, where it will
                                        # be deleted when the computer restarts
                                        temp_dirpath = tempfile.gettempdir()
                                        os.rename(
                                            self.path,
                                            os.path.join(temp_dirpath, os.path.basename(self.path)))
                                    except:
                                        # Give up
                                        pass
                        finally:
                            # Unexport reference to self, if running tests
                            if tests_are_running():
                                if Project._last_opened_project is self:
                                    Project._last_opened_project = None
            do_close()
        finally:
            self._closed = True
    
    @fg_affinity
    def _stop_scheduler(self) -> None:
        """
        Stops the scheduler thread for this project.
        
        Is the inverse of `_start_scheduler()`.
        
        This method is prepared to operate on projects with corrupted state,
        since even corrupted projects will attempt to close themselves gracefully.
        
        Raises:
        * TimeoutError -- if the scheduler thread does not exit promptly within a timeout
        """
        # Stop scheduler thread soon
        if hasattr(self, 'root_task'):
            try:
                self.root_task.cancel_tree()
            finally:
                assert self.root_task._cancel_tree_soon, \
                    'Root task should be pending cancellation, even if cancel_tree() partially failed'
        
        # Wait for the scheduler thread to exit
        if hasattr(self, '_scheduler_thread') and self._scheduler_thread is not None:
            scheduler_thread = self._scheduler_thread  # capture
            def scheduler_thread_is_dead() -> bool:
                scheduler_thread.join(20 / 1000)  # 20 ms
                return not scheduler_thread.is_alive()
            try:
                fg_wait_for(
                    scheduler_thread_is_dead,
                    timeout=self._SCHEDULER_JOIN_TIMEOUT,
                    # No need to sleep additionally between polls because 
                    # scheduler_thread_is_dead() sleeps internally
                    poll_interval=0)
            except TimeoutError:
                tb = get_thread_stack(scheduler_thread)
                msg = f'Scheduler thread failed to stop within {self._SCHEDULER_JOIN_TIMEOUT} seconds.\n\n'
                if tb:
                    msg += f'Scheduler thread stack (possible deadlock):\n{tb}'
                else:
                    msg += 'Scheduler thread stack unavailable.'
                raise TimeoutError(msg)
            
            self._scheduler_thread = None
        
        # 1. Verify that all task references have been cleared
        # 2. Perform assertions last, which can raise
        if tests_are_running():
            for r in self._materialized_resources:
                for task_ref in [r._download_body_task_ref, r._download_task_ref, r._download_task_noresult_ref]:
                    if task_ref is not None and task_ref.task is not None:
                        if task_ref.task.complete:
                            # WeakTaskRef should never refer to a completed task
                            print(
                                f'*** Incomplete task cleanup: WeakTaskRef still refers to a task that was completed: '
                                f'{r=!r}, {task_ref=!r}', file=sys.stderr)
                        elif not task_ref.task.in_task_tree(self.root_task):
                            # WeakTaskRef should never refer to a task that is not in the task tree
                            print(
                                f'*** Incomplete task cleanup: WeakTaskRef refers to a task that is not in the task tree: '
                                f'{r=!r}, {task_ref=!r}', file=sys.stderr)
                        else:
                            # All tasks should be completed
                            print(
                                f'*** Incomplete task cleanup: Task in task tree was not completed: '
                                f'{r=!r}, {task_ref=!r}', file=sys.stderr)
    
    @staticmethod
    @fg_affinity
    def _close_database(db: DatabaseConnection, readonly: bool) -> None:
        """
        Closes the database for this project.
        
        Is the inverse of `_open_database_but_close_if_raises()`.
        
        This method is prepared to operate on projects with corrupted state,
        since even corrupted projects will attempt to close themselves gracefully.
        """
        # Disable Write Ahead Log (WAL) mode when closing database
        # in case the user decides to burn the project to read-only media,
        # as recommended by: https://www.sqlite.org/wal.html#readonly
        if not readonly:
            try:
                with closing(db.cursor()) as c:
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
        
        db.close()
    
    @fg_affinity
    def _reopen(self) -> None:
        """
        Reopens this project at self.path, attempting to open as writable.
        
        Is the inverse of `close()`, but does not restore the state of tasks.
        """
        try:
            cls = type(self)
            
            # Open database at the new path, attempting to open as writable
            old_readonly = self._readonly
            with cls._open_database_but_close_if_raises(self.path, False, self._mark_dirty_if_untitled, expect_writable=False) as (
                    self._db, new_readonly, self._database_is_on_ssd):
                if new_readonly != old_readonly:
                    self._readonly = new_readonly
                    
                    # Notify if readonly status changed
                    for lis in self.listeners:
                        if hasattr(lis, 'project_readonly_did_change'):
                            run_bulkhead_call(lis.project_readonly_did_change)
            
            # Start scheduler
            self._start_scheduler()
        except:
            # Clean up partially opened state
            self._closed = False  # allow close() to run
            # NOTE: _will_reopen=True suppresses cleanup related to closing untitled projects,
            #       because the caller is expected to call _reopen() again during
            #       its own error recovery.
            self.close(_will_reopen=True)
            assert self._closed
            
            raise
        else:
            # Successfully reopened
            self._closed = False
    
    # === Context Manager ===
    
    def __enter__(self) -> Self:
        return self
    
    def __exit__(self, *args) -> None:
        self.close()


class CrossProjectReferenceError(Exception):
    pass


class ProjectFormatError(Exception):
    """The on-disk format of a Project is corrupted in some way."""


class RevisionBodyMissingError(ProjectFormatError):
    def __init__(self, revision: ResourceRevision) -> None:
        super().__init__(
            f'{revision!s} is missing its body on disk. '
            f'Recommend delete and redownload it.')


class ProjectTooNewError(Exception):
    """
    The project has a greater major version than this version of Crystal
    knows how to open safely.
    """


class ProjectReadOnlyError(Exception):
    pass


class ProjectClosedError(Exception):
    pass


# ------------------------------------------------------------------------------
