"""
Persistent data model.

Unless otherwise specified, all changes to models are auto-saved.
[TODO: Encapsulate read-only properties.]

Model objects may only be manipulated on the foreground thread.
Callers that attempt to do otherwise may get thrown `ProgrammingError`s.
"""

from collections import OrderedDict
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import urllib2
from xfutures import Future
from xthreading import bg_call_later, fg_call_and_wait

class Project(object):
    """
    Groups together a set of resources that are downloaded and any associated settings.
    Persisted and auto-saved.
    """
    
    FILE_EXTENSION = '.crystalproj'
    
    # Project structure constants
    _DB_FILENAME = 'database.sqlite'
    _RESOURCE_REVISION_DIRNAME = 'resource_revision_body'
    
    def __init__(self, path):
        """
        Loads a project from the specified filepath, or creates a new one if none is found.
        
        Arguments:
        path -- path to a directory (ideally with the `FILE_EXTENSION` extension)
                from which the project is to be loaded.
        """
        self.path = path
        
        self._properties = dict()               # <key, value>
        self._resources = OrderedDict()         # <url, Resource>
        self._root_resources = OrderedDict()    # <Resource, RootResource>
        self._resource_groups = []              # <ResourceGroup>
        
        self._loading = True
        try:
            if os.path.exists(path):
                # Load from existing project
                self._db = sqlite3.connect(os.path.join(path, self._DB_FILENAME))
                
                c = self._db.cursor()
                for (name, value) in c.execute('select name, value from project_property'):
                    self._set_property(name, value)
                for (url, id) in c.execute('select url, id from resource'):
                    Resource(self, url, _id=id)
                for (name, resource_id, id) in c.execute('select name, resource_id, id from root_resource'):
                    resource = [r for r in self._resources.values() if r._id == resource_id][0] # PERF
                    RootResource(self, name, resource, _id=id)
                for (name, url_pattern, id) in c.execute('select name, url_pattern, id from resource_group'):
                    ResourceGroup(self, name, url_pattern, _id=id)
                # (ResourceRevisions are loaded on demand)
            else:
                # Create new project
                os.mkdir(path)
                os.mkdir(os.path.join(path, self._RESOURCE_REVISION_DIRNAME))
                self._db = sqlite3.connect(os.path.join(path, self._DB_FILENAME))
                
                c = self._db.cursor()
                c.execute('create table project_property (name text unique not null, value text not null)')
                c.execute('create table resource (id integer primary key, url text unique not null)')
                c.execute('create table root_resource (id integer primary key, name text not null, resource_id integer unique not null, foreign key (resource_id) references resource(id))')
                c.execute('create table resource_group (id integer primary key, name text not null, url_pattern text not null)')
                c.execute('create table resource_revision (id integer primary key, resource_id integer not null, error text not null, metadata text not null)')
                e.execute('create index resource_revision__resource_id on resource_revision (resource_id)')
        finally:
            self._loading = False
        
        # Hold on to the root task and scheduler
        from crystal.task import RootTask, start_schedule_forever
        self.root_task = RootTask()
        start_schedule_forever(self.root_task)
    
    def _get_property(self, name, default):
        return self._properties.get(name, default)
    def _set_property(self, name, value):
        if not self._loading:
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
    
    @property
    def resources(self):
        return self._resources.values()
    
    @property
    def root_resources(self):
        return self._root_resources.values()
    
    def get_resource(self, url):
        """Returns the `Resource` with the specified URL or None if no such resource is recognized."""
        return self._resources.get(url, None)
    
    def get_root_resource(self, resource):
        """Returns the `RootResource` with the specified `Resource` or None if none exists."""
        return self._root_resources.get(resource, None)
    
    @property
    def resource_groups(self):
        return self._resource_groups
    
    def get_resource_group(self, name):
        for rg in self._resource_groups:
            if rg.name == name:
                return rg
        return None
    
    def add_task(self, task):
        """
        Schedules the specified top-level task for execution, if not already done.
        """
        if task not in self.root_task.children:
            self.root_task.append_child(task)

class CrossProjectReferenceError(Exception):
    pass

class _WeakTaskRef(object):
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

class Resource(object):
    """
    Represents an entity, potentially downloadable.
    Either created manually or discovered through a link from another resource.
    Persisted and auto-saved.
    """
    
    def __new__(cls, project, url, _id=None):
        """
        Looks up an existing resource with the specified URL or creates a new
        one if no preexisting resource matches.
        
        Arguments:
        project -- associated `Project`.
        url -- absolute URL to this resource (ex: http), or a URI (ex: mailto).
        """
        
        if url in project._resources:
            return project._resources[url]
        else:
            self = object.__new__(cls)
            self.project = project
            self.url = url
            self.download_body_task_ref = _WeakTaskRef()
            self.download_task_ref = _WeakTaskRef()
            
            if project._loading:
                self._id = _id
            else:
                c = project._db.cursor()
                c.execute('insert into resource (url) values (?)', (url,))
                project._db.commit()
                self._id = c.lastrowid
            project._resources[url] = self
            return self
    
    @property
    def resource(self):
        """
        Returns self.
        
        This property is useful when a Resource and a RootResource are used in the same
        context. Both Resource and RootResource have a 'resource' property that returns
        the underlying resource.
        """
        return self
    
    @property
    def downloadable(self):
        try:
            from crystal.download import ResourceRequest
            ResourceRequest.create(self.url)
            return True
        except urllib2.URLError:
            return False
    
    def download_body(self):
        """
        Returns a Future<ResourceRevision> that downloads (if necessary) and returns an
        up-to-date version of this resource's body.
        
        The returned Future may invoke its callbacks on any thread.
        
        If it is necessary to perform a download, a top-level Task will be created
        internally to perform the download and display the progress.
        """
        if self.up_to_date():
            # Already up-to-date
            revision = self.default_revision()
            if revision is None:
                raise AssertionError('Up-to-date resource should have a default revision.')
            
            future = Future()
            future.set_result(revision)
            return future
        
        task = self.try_create_download_body_task()
        if task is None:
            raise AssertionError('Failed to create download-body task for up-to-date Resource.')
        self.project.add_task(task)
        return task.future
    
    def try_create_download_body_task(self):
        """
        Creates a Task to download this resource's body, if it is not already up-to-date.
        If a such a Task already exists, the preexisting Task will be returned instead of creating a new one.
        If this resource is already up-to-date, None will be returned.
        
        The caller is responsible for adding the returned Task as the child of an
        appropriate parent task so that the UI displays it.
        """
        def task_factory():
            if self.up_to_date():
                return None
            
            from crystal.task import DownloadResourceBodyTask
            return DownloadResourceBodyTask(self)
        return self._get_task_or_create(self.download_body_task_ref, task_factory)
    
    def download(self):
        """
        Returns a Future<ResourceRevision> that downloads (if necessary) and returns an
        up-to-date version of this resource's body. If a download is performed, all
        embedded resources will be downloaded as well.
        
        The returned Future may invoke its callbacks on any thread.
        
        If it is necessary to perform a download, a top-level Task will be created
        internally to perform the download and display the progress.
        """
        task = self._create_download_task()
        self.project.add_task(task)
        return task.future
    
    def _create_download_task(self):
        def task_factory():
            from crystal.task import DownloadResourceTask
            return DownloadResourceTask(self)
        return self._get_task_or_create(self.download_task_ref, task_factory)
    
    def _get_task_or_create(self, task_ref, task_factory):
        if task_ref.task is not None:
            return task_ref.task
        
        task = task_factory()
        task_ref.task = task
        return task
    
    # TODO: This should ideally be a cheap operation, not requiring a database hit.
    #       Convert to property once this "cheapening" has been done.
    def up_to_date(self):
        """
        Returns whether this resource is "up-to-date".
        
        An "up-to-date" resource is one that whose most recent local revision is estimated
        to be the same (in content) as the remote version at the time of invocation.
        """
        # NOTE: Presently there is a hard-coded assumption that remote resources never change.
        #       Therefore a downloaded revision is always considered "up-to-date".
        #       This will likely require reconfiguring by the user in the future.
        return self.has_any_revisions()
    
    # TODO: This should ideally be a cheap operation, not requiring a database hit.
    #       Convert to property once this "cheapening" has been done.
    def has_any_revisions(self):
        """
        Returns whether any revisions of this resource have been downloaded.
        """
        c = self.project._db.cursor()
        c.execute('select 1 from resource_revision where resource_id=? limit 1', (self._id,))
        return c.fetchone() is not None
    
    def default_revision(self):
        """
        Loads and returns the "default" revision of this resource, which is the revision
        that will be displayed when this resource is served or exported.
        
        If no revisions of this resource have been downloaded, None is returned.
        """
        default_revision_singleton = self.revisions(_query_suffix=' order by id desc limit 1')
        return default_revision_singleton[0] if len(default_revision_singleton) == 1 else None
    
    def revisions(self, _query_suffix=''):
        """
        Loads and returns a list of `ResourceRevision`s downloaded for this resource.
        If no such revisions exist, an empty list is returned.
        """
        RR = ResourceRevision
        
        revs = []
        c = self.project._db.cursor()
        query = 'select error, metadata, id from resource_revision where resource_id=?%s' % _query_suffix
        for (error, metadata, id) in c.execute(query, (self._id,)):
            revs.append(ResourceRevision._load(self, RR._decode_error(error), RR._decode_metadata(metadata), _id=id))
        return revs
    
    def __repr__(self):
        return "Resource(%s)" % (repr(self.url),)

class RootResource(object):
    """
    Represents a resource whose existence is manually defined by the user.
    Persisted and auto-saved.
    """
    
    def __new__(cls, project, name, resource, _id=None):
        """
        Creates a new root resource.
        
        Arguments:
        project -- associated `Project`.
        name -- display name.
        resource -- `Resource`.
        
        Raises:
        CrossProjectReferenceError -- if `resource` belongs to a different project.
        RootResource.AlreadyExists -- if there is already a `RootResource` associated
                                      with the specified resource.
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
                c = project._db.cursor()
                c.execute('insert into root_resource (name, resource_id) values (?, ?)', (name, resource._id))
                project._db.commit()
                self._id = c.lastrowid
            project._root_resources[resource] = self
            return self
    
    def delete(self):
        c = self.project._db.cursor()
        c.execute('delete from root_resource where resource_id=?', (self.resource._id,))
        self.project._db.commit()
        self._id = None
        
        del self.project._root_resources[self.resource]
    
    @property
    def url(self):
        return self.resource.url
    
    def __repr__(self):
        return "RootResource(%s,%s)" % (repr(self.name), repr(self.resource.url))
    
    class AlreadyExists(Exception):
        """
        Raised when an attempt is made to create a new `RootResource` for a `Resource`
        that is already associated with an existing `RootResource`.
        """
        pass

class ResourceRevision(object):
    """
    A downloaded revision of a `Resource`. Immutable.
    Persisted. Loaded on demand.
    """
    
    @staticmethod
    def create_from_error(resource, error):
        """
        Creates a revision that encapsulates the error encountered when fetching the revision.
        
        Threadsafe.
        """
        return ResourceRevision._create(resource, error=error)
    
    @staticmethod
    def create_from_response(resource, metadata, body_stream):
        """
        Creates a revision with the specified metadata and body.
        
        Threadsafe. The passed body stream will be read synchronously until EOF,
        so it is recommended that this method be invoked on a background thread.
        
        Arguments:
        resource -- resource that this is a revision of.
        metadata -- JSON-encodable dictionary of resource metadata.
        body_stream -- file-like object containing the revision body.
        """
        try:
            return ResourceRevision._create(resource, metadata=metadata, body_stream=body_stream)
        except Exception as e:
            return ResourceRevision.create_from_error(resource, e)
    
    @staticmethod
    def _create(resource, error=None, metadata=None, body_stream=None):
        self = ResourceRevision()
        self.resource = resource
        self.error = error
        self.metadata = metadata
        # (self._id computed below)
        self.has_body = body_stream is not None
        
        project = self.project
        
        # Need to do this first to get the database ID
        def fg_task():
            RR = ResourceRevision
            
            c = project._db.cursor()
            c.execute('insert into resource_revision (resource_id, error, metadata) values (?, ?, ?)', (resource._id, RR._encode_error(error), RR._encode_metadata(metadata)))
            project._db.commit()
            self._id = c.lastrowid
        fg_call_and_wait(fg_task)
        
        if body_stream:
            try:
                body_filepath = os.path.join(project.path, Project._RESOURCE_REVISION_DIRNAME, str(self._id))
                with open(body_filepath, 'wb') as body_file:
                    shutil.copyfileobj(body_stream, body_file)
            except:
                # Rollback database commit
                def fg_task():
                    c = project._db.cursor()
                    c.execute('delete from resource_revision where id=?', (self._id,))
                    project._db.commit()
                fg_call_and_wait(fg_task)
                raise
        
        return self
    
    @staticmethod
    def _load(resource, error, metadata, _id):
        self = ResourceRevision()
        self.resource = resource
        self.error = error
        self.metadata = metadata
        self._id = _id
        self.has_body = os.path.exists(self._body_filepath)
        return self
    
    @staticmethod
    def _encode_error(error):
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
                'message': error.message if hasattr(error, 'message') else None,
            }
        return json.dumps(error_dict)
    
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
    
    @property
    def project(self):
        return self.resource.project
    
    @property
    def _url(self):
        return self.resource.url
    
    def _ensure_has_body(self):
        if not self.has_body:
            raise ValueError('Resource has no body.')
    
    @property
    def _body_filepath(self):
        return os.path.join(self.project.path, Project._RESOURCE_REVISION_DIRNAME, str(self._id))
    
    @property
    def is_http(self):
        """Returns whether this resource was fetched using HTTP."""
        # HTTP resources are presently the only ones with metadata
        return self.metadata is not None
    
    @property
    def is_redirect(self):
        """Returns whether this resource is a redirect."""
        return self.is_http and (self.metadata['status_code'] / 100) == 3
    
    def _get_first_value_of_http_header(self, name):
        for (cur_name, cur_value) in self.metadata['headers']:
            if name == cur_name:
                return cur_value
        return None
    
    @property
    def redirect_url(self):
        """
        Returns the resource to which this resource redirects,
        or None if it cannot be determined or this is not a redirect.
        """
        if self.is_redirect:
            return self._get_first_value_of_http_header('location')
        else:
            return None
    
    @property
    def _redirect_title(self):
        if self.is_redirect:
            return '%s %s' % (self.metadata['status_code'], self.metadata['reason_phrase'])
        else:
            return None
    
    @property
    def declared_content_type(self):
        """Returns the MIME content type declared for this resource, or None if not declared."""
        if self.is_http:
            content_type_with_parameters = self._get_first_value_of_http_header('content-type')
            if content_type_with_parameters is None:
                return None
            else:
                # Remove RFC 2045 parameters, if present
                return content_type_with_parameters.split(';')[0].strip()
        else:
            return None
    
    @property
    def content_type(self):
        """Returns the MIME content type declared or guessed for this resource, or None if unknown."""
        declared = self.declared_content_type
        if declared is not None:
            return declared
        return mimetypes.guess_type(self._url)
    
    @property
    def is_html(self):
        """Returns whether this resource is HTML."""
        return self.content_type == 'text/html'
    
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
        """
        return self.html_and_links()[1]
    
    def html_and_links(self):
        """
        Returns a 2-tuple containing:
        (1) if the resource is HTML, the HTML document, otherwise None;
        (2) a list of Links found in this resource.
        
        The HTML document can be reoutput by getting its str() representation.
        """
        from crystal.html import parse_html_and_links, Link
        
        # Extract links from HTML, if applicable
        if not self.is_html or not self.has_body:
            (html, links) = (None, [])
        else:
            with self.open() as body:
                (html, links) = parse_html_and_links(body, self.declared_content_type)
        
        # Add pseudo-link for redirect, if applicable
        redirect_url = self.redirect_url
        if redirect_url is not None:
            links.append(Link.create_external(redirect_url, self._redirect_title, 'Redirect', True))
        
        return (html, links)
    
    def __repr__(self):
        return "<ResourceRevision %s for '%s'>" % (self._id, self.resource.url)

class _PersistedError(Exception):
    """
    Wraps an exception loaded from persistent storage.
    """
    def __init__(self, message, type):
        self.message = message
        self.type = type

class ResourceGroup(object):
    """
    Groups resource whose url matches a particular pattern.
    Persisted and auto-saved.
    """
    
    def __init__(self, project, name, url_pattern, _id=None):
        """
        Arguments:
        project -- associated `Project`.
        name -- name of this group.
        url_pattern -- url pattern matched by this group.
        """
        self.project = project
        self.name = name
        self.url_pattern = url_pattern
        self._url_pattern_re = ResourceGroup._url_pattern_to_re(url_pattern)
        
        if project._loading:
            self._id = _id
        else:
            c = project._db.cursor()
            c.execute('insert into resource_group (name, url_pattern) values (?, ?)', (name, url_pattern))
            project._db.commit()
            self._id = c.lastrowid
        project._resource_groups.append(self)
    
    @staticmethod
    def _url_pattern_to_re(url_pattern):
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
    
    def __contains__(self, resource):
        return self._url_pattern_re.match(resource.url) is not None
