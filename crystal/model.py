"""
Persistent data model.

Unless otherwise specified, all changes to models are auto-saved.
[TODO: Encapsulate read-only properties.]
"""

from collections import OrderedDict
import os
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
        
        self._resources = OrderedDict()         # <url, Resource>
        self._root_resources = OrderedDict()    # <Resource, RootResource>
        
        self._loading = True
        try:
            if os.path.exists(path):
                # Load from existing project
                self._db = sqlite3.connect(os.path.join(path, self._DB_FILENAME))
                
                c = self._db.cursor()
                for (url, id) in c.execute('select url, id from resource'):
                    Resource(self, url, _id=id)
                for (name, resource_id, id) in c.execute('select name, resource_id, id from root_resource'):
                    resource = [r for r in self._resources.values() if r._id == resource_id][0] # PERF
                    RootResource(self, name, resource, _id=id)
            else:
                # Create new project
                os.mkdir(path)
                os.mkdir(os.path.join(path, self._BLOBS_DIRNAME))
                self._db = sqlite3.connect(os.path.join(path, self._DB_FILENAME))
                
                c = self._db.cursor()
                c.execute('create table resource (id integer primary key, url text unique not null)')
                c.execute('create table root_resource (id integer primary key, name text not null, resource_id integer unique not null, foreign key (resource_id) references resource(id))')
        finally:
            self._loading = False
    
    @property
    def resources(self):
        return self._resources.values()
    
    @property
    def root_resources(self):
        return self._root_resources.values()

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
    Stores all information needed to reperform the request exactly as originally done.
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
        from crystal.download import HttpResourceResponseMetadata
        return self.metadata and isinstance(self.metadata, HttpResourceResponseMetadata)
    
    @property
    def is_redirect(self):
        return self.is_http and (self.metadata.status_code / 100) == 3
    
    @property
    def redirect_url(self):
        if self.is_redirect:
            return self.metadata.header_dict.get('location', [None])[0]
        else:
            return None