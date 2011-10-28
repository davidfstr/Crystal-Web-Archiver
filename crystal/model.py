"""
Persistent data model.

Unless otherwise specified, all changes to models are auto-saved.
[TODO: Encapsulate read-only properties.]
"""

from collections import OrderedDict
import mimetypes
import os
import re
import sqlite3

class Project(object):
    """
    Groups together a set of resources that are downloaded and any associated settings.
    Persisted and auto-saved.
    """
    
    FILE_EXTENSION = '.crystalproj'
    
    # Project structure constants
    _DB_FILENAME = 'database.sqlite'
    _BLOBS_DIRNAME = 'blobs'
    
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
            else:
                # Create new project
                os.mkdir(path)
                os.mkdir(os.path.join(path, self._BLOBS_DIRNAME))
                self._db = sqlite3.connect(os.path.join(path, self._DB_FILENAME))
                
                c = self._db.cursor()
                c.execute('create table project_property (name text unique not null, value text not null)')
                c.execute('create table resource (id integer primary key, url text unique not null)')
                c.execute('create table root_resource (id integer primary key, name text not null, resource_id integer unique not null, foreign key (resource_id) references resource(id))')
                c.execute('create table resource_group (id integer primary key, name text not null, url_pattern text not null)')
        finally:
            self._loading = False
    
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
    
    def find_root_resource(self, resource):
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

class CrossProjectReferenceError(Exception):
    pass

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
    def downloadable(self):
        try:
            from crystal.download import ResourceRequest
            ResourceRequest.create(self.url)
            return True
        except Exception:
            return False
    
    # TODO: Define download() method that fetches the resource itself,
    #       plus any other "embedded" resources it links to.
    
    def download_self(self):
        """
        Returns a `Task` that yields a `ResourceRevision`.
        [TODO: If this resource is up-to-date, yields the default revision immediately.]
        """
        from crystal.download import ResourceDownloadTask
        return ResourceDownloadTask(self)
    
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
    A downloaded revision of a `Resource`.
    [TODO: Persisted and auto-saved.]
    """
    
    def __init__(self, error=None, metadata=None, body_stream=None):
        if not ((error is None) != (body_stream is None)):
            raise ValueError('Must specify either "error" or "body_stream" argument.')
        self.error = error
        self.metadata = metadata
        if body_stream:
            try:
                # TODO: Not a great idea to read a response directly into memory.
                #       This should be streamed to disk.
                self._body = body_stream.read() # TODO: finalize internal representation
            finally:
                body_stream.close()
        else:
            self._body = None
    
    @property
    def is_http(self):
        """Returns whether this resource was fetched using HTTP."""
        from crystal.download import HttpResourceResponseMetadata
        return self.metadata and isinstance(self.metadata, HttpResourceResponseMetadata)
    
    @property
    def is_redirect(self):
        """Returns whether this resource is a redirect."""
        return self.is_http and (self.metadata.status_code / 100) == 3
    
    def _get_first_value_of_http_header(self, name):
        for (cur_name, cur_value) in self.metadata.headers:
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
            return '%s %s' % (self.metadata.status_code, self.metadata.reason_phrase)
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
        return mimetypes.guess_type(self.url)
    
    @property
    def is_html(self):
        """Returns whether this resource is HTML."""
        return self.content_type == 'text/html'
    
    def links(self):
        """Returns list of `Link`s found in this resource."""
        # Extract links from HTML, if applicable
        from crystal.html import parse_links, Link
        links = parse_links(self._body) if self.is_html else []
        
        # Add pseudo-link for redirect, if applicable
        redirect_url = self.redirect_url
        if redirect_url is not None:
            links.append(Link(redirect_url, self._redirect_title, 'Redirect', True))
        
        return links

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
