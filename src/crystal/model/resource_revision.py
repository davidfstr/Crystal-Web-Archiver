from __future__ import annotations

from contextlib import closing
import copy
from crystal.doc.css import parse_css_and_links
from crystal.doc.generic import create_external_link
from crystal.doc.html import parse_html_and_links
from crystal.doc.html.soup import FAVICON_TYPE_TITLE, HtmlDocument
from crystal.doc.json import parse_json_and_links
from crystal.doc.xml import parse_xml_and_links
from crystal.plugins import minimalist_baker as plugins_minbaker
from crystal.util import http_date, xcgi, xshutil
from crystal.util.bulkheads import capture_crashes_to_stderr
from crystal.util.filesystem import rename_and_flush
from crystal.util.urls import is_unrewritable_url
from crystal.util.xthreading import (
    fg_affinity, fg_call_and_wait, fg_call_later,
)
import datetime
import json
import mimetypes
import os
from shutil import COPY_BUFSIZE  # type: ignore[attr-defined]  # private API
import sys
from tempfile import NamedTemporaryFile
import threading
from typing import (
    BinaryIO, IO, Optional, TYPE_CHECKING, TypedDict,
)
from urllib.parse import urlparse

if TYPE_CHECKING:
    from crystal.doc.generic import Document, Link
    from crystal.model.project import Project
    from crystal.model.resource import Resource


# ------------------------------------------------------------------------------
# ResourceRevision

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
    
    _MAX_REVISION_ID_QUERY = 'select id from resource_revision order by id desc limit 1'
    
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
        * ProjectReadOnlyError
        * ProjectHasTooManyRevisionsError
        * sqlite3.DatabaseError, OSError -- 
            if could not read old revision from disk or write new revision to disk.
            
            If the error is related to disk disconnection, disk full, or other
            disk-wide permanent I/O error then it is possible that a
            ResourceRevision was partially saved to the database but not
            rolled back, left pointing to a missing revision body file.
            Attempting to read that revision's body later will result in
            a RevisionBodyMissingError, which callers are expected to handle
            gracefully.
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
        * ProjectReadOnlyError
        * ProjectHasTooManyRevisionsError
        * sqlite3.DatabaseError -- 
            if could not write revision to disk.
        """
        return ResourceRevision._create_from_stream(
            resource,
            request_cookie=request_cookie,
            error=error)
    
    @staticmethod
    def create_from_response(
            resource: Resource,
            metadata: ResourceRevisionMetadata | None,
            body_stream: IO[bytes],
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
        * ProjectReadOnlyError
        * ProjectHasTooManyRevisionsError
        * sqlite3.DatabaseError, OSError -- 
            if could not read from stream or write revision to disk.
            
            If the error is related to disk disconnection, disk full, or other
            disk-wide permanent I/O error then it is possible that a
            ResourceRevision was partially saved to the database but not
            rolled back, left pointing to a missing revision body file.
            Attempting to read that revision's body later will result in
            a RevisionBodyMissingError, which callers are expected to handle
            gracefully.
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
            body_stream: IO[bytes] | None=None
            ) -> ResourceRevision:
        """
        Creates a new revision.
        
        See also:
        * ResourceRevision.create_from_error()
        * ResourceRevision.create_from_response()
        
        Raises:
        * ProjectReadOnlyError
        * ProjectHasTooManyRevisionsError
        * sqlite3.DatabaseError, OSError -- 
            if could not read from stream or write revision to disk.
            
            If the error is related to disk disconnection, disk full, or other
            disk-wide permanent I/O error then it is possible that a
            ResourceRevision was partially saved to the database but not
            rolled back, left pointing to a missing revision body file.
            
            When the project is next reopened as writable, any such
            incomplete rollback is automatically repaired by detecting and
            deleting the last revision if its body file is missing and
            the filesystem is confirmed accessible.
            
            Attempting to read this revision's body later will result in
            a RevisionBodyMissingError, which callers are expected to handle
            gracefully.
        """
        from crystal.model.project import Project, ProjectReadOnlyError
        
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
        # 1. Create/commit the ResourceRevision row in the database
        # 2. Get the database ID
        @capture_crashes_to_stderr
        def fg_task() -> None:
            nonlocal callable_exc_info
            try:
                RR = ResourceRevision
                
                if project.readonly:
                    raise ProjectReadOnlyError()
                with project._db, closing(project._db.cursor()) as c:
                    c.execute(
                        'insert into resource_revision '
                            '(resource_id, request_cookie, error, metadata) values (?, ?, ?, ?)', 
                        (resource._id, request_cookie, RR._encode_error(error), RR._encode_metadata(metadata)))
                    assert c.lastrowid is not None
                    id = c.lastrowid  # capture
                self._id = id
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
                    
                    # Ensure data is flushed to stable storage
                    body_file.flush()
                    os.fsync(body_file.fileno())
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
                        # NOTE: May raise ProjectHasTooManyRevisionsError
                        revision_filepath = self._body_filepath
                        
                        # 1. Move body file to its final filename
                        # 2. Ensure rename is flushed to disk
                        try:
                            rename_and_flush(body_file.name, revision_filepath)
                        except FileNotFoundError:  # probably missing parent directory
                            os.makedirs(os.path.dirname(revision_filepath), exist_ok=True)
                            rename_and_flush(body_file.name, revision_filepath)
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
                            with project._db, closing(project._db.cursor()) as c:
                                c.execute('delete from resource_revision where id=?', (self._id,))
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
        
        Raises:
        * sqlite3.DatabaseError -- 
            if could not read revision metadata from disk.
        """
        # Fetch the revision's resource URL
        with closing(project._db.cursor()) as c:
            rows = list(c.execute(
                f'select '
                    f'resource_id from resource_revision '
                    f'where resource_revision.id=?',
                (id,)
            ))
        if len(rows) == 0:
            return None
        [(resource_id,)] = rows
        
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
        
        return self._body_filepath_with(
            project_path=self.project.path,
            major_version=self.project.major_version,
            revision_id=self._id)
    
    @staticmethod
    def _body_filepath_with(
            project_path: str,
            major_version: int,
            revision_id: int,
            ) -> str:
        """
        Raises:
        * ProjectHasTooManyRevisionsError --
            if this revision's in-memory ID is higher than what the 
            project format supports on disk
        """
        from crystal.model.project import Project
        
        if major_version >= 2:
            os_path_sep = os.path.sep  # cache
            
            revision_relpath_parts = f'{revision_id:015x}'
            if len(revision_relpath_parts) != 15:
                assert revision_id > Project._MAX_REVISION_ID
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
            revision_relpath = str(revision_id)
        else:
            raise AssertionError()
        
        return os.path.join(
            project_path, Project._REVISIONS_DIRNAME, revision_relpath)
    
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
        * OSError --
            if I/O error while reading revision body
        """
        from crystal.model.project import RevisionBodyMissingError
        
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
        * OSError --
            if I/O error while opening revision body
        """
        from crystal.model.project import RevisionBodyMissingError
        
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
        """
        Changes the metadata of this revision in place.
        
        ONLY FOR USE BY AUTOMATED TESTS.
        
        Raises:
        * sqlite3.DatabaseError -- 
            if could not write revision metadata to disk.
        """
        project = self.project
        
        # Alter ResourceRevision's metadata in memory
        self.metadata = new_metadata
        
        # Alter ResourceRevision's metadata in database
        with project._db, closing(project._db.cursor()) as c:
            c.execute(
                'update resource_revision set metadata = ? where id = ?',
                (json.dumps(new_metadata), self._id),  # type: ignore[attr-defined]
                ignore_readonly=ignore_readonly)
    
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
    
    def delete(self) -> None:
        """
        Deletes this revision.
        
        Raises:
        * ProjectReadOnlyError
        * sqlite3.DatabaseError --
            if the delete fully failed due to a database error
        * OSError -- 
            if the delete partially failed, leaving behind a revision body file
        """
        from crystal.model.project import ProjectReadOnlyError
        
        project = self.project
        body_filepath = self._body_filepath  # capture
        
        if project.readonly:
            raise ProjectReadOnlyError()
        
        # Delete revision's database row
        # NOTE: If crash occurs after database commit but before revision body
        #       is deleted, a dangling revision's body file will be left behind.
        #       That dangling file will occupy some disk space unnecessarily
        #       but shouldn't interfere with any future project operations.
        with project._db, closing(project._db.cursor()) as c:
            c.execute('delete from resource_revision where id=?', (self._id,))
        self._id = None  # type: ignore[assignment]  # intentionally leave exploding None
        
        self.resource.already_downloaded_this_session = False
        
        # Delete revision's body file
        try:
            os.remove(body_filepath)
        except FileNotFoundError:
            # OK. The revision may have already been partially deleted outside of Crystal.
            pass
    
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


# ------------------------------------------------------------------------------
