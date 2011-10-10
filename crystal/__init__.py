# --------------------------------------------------------------------------------------------------
# Model

from collections import OrderedDict
import os
import sqlite3
import urllib2

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
    
    def download_body(self):
        """
        Returns a `Task` that yields a `ResourceRevision`.
        [TODO: If this resource is up-to-date, yields the default revision immediately.]
        """
        return _ResourceBodyDownloadTask(self)
    
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

class _ResourceBodyDownloadTask(object): # TODO: extend from Task base class, once it is defined
    def __init__(self, resource):
        self._resource = resource
        
        self.title = 'Downloading: %s' % (resource.url,)
        self.subtitle = 'Queued.'
        self.subtasks = []
    
    def __call__(self):
        """Synchronously runs this task."""
        request = None
        try:
            # TODO: Migrate to httplib instead of urllib2, so that exact request headers can be saved
            #       and redirections can be handled directly. Note that non-HTTP(S) URLs such as FTP
            #       should still be handled. And don't forget to get a nice exception for unsupported
            #       URI schemes (such as mailto).
            self.subtitle = 'Waiting for response...'
            request = urllib2.Request('http://www.themanime.org/')
            response_body_stream = urllib2.urlopen(request) # may raise URLError
            
            # TODO: Provide incremental feedback such as '7 KB of 15 KB'
            self.subtitle = 'Receiving response...'
            response_body = response_body_stream.read() # may raise IOError
            
            return ResourceRevision(request=request, response_body=response_body)
        except Exception as e:
            return ResourceRevision(download_error=e, request=request)
    
    @property
    def subtitle(self):
        return self._subtitle
    
    @subtitle.setter
    def subtitle(self, value):
        # TODO: Display updates in GUI instead of CLI
        print '-> %s' % (value,)
        self._subtitle = value

class ResourceRevision(object):
    """
    A downloaded revision of a `Resource`.
    Stores all information needed to reperform the request exactly as originally done.
    [TODO: Persisted and auto-saved.]
    """
    
    def __init__(self, download_error=None, request=None, response_body=None):
        if not ((download_error is None) != (response_body is None)):
            raise ValueError('Must specify either "download_error" or "response_body" argument.')
        self.download_error = download_error
        self._request = request             # TODO: finalize internal representation
        self._response_body = response_body # TODO: finalize internal representation

# --------------------------------------------------------------------------------------------------
# HTML

from BeautifulSoup import BeautifulSoup
import re

class LinkParser(object):
    _any_re = re.compile(r'.*')
    
    @staticmethod
    def parse(html_bytes):
        """
        Parses and returns a list of `Link`s in the specified HTML bytestring.
        """
        # TODO: Pass in the hinted Content-Encoding HTTP header, if available,
        #       to assist in determining the correct text encoding
        try:
            html = BeautifulSoup(html_bytes)
        except Exception as e:
            # TODO: Return the underlying exception as a warning
            return []
        
        tags_with_src = html.findAll(LinkParser._any_re, src=LinkParser._any_re)
        tags_with_href = html.findAll(LinkParser._any_re, href=LinkParser._any_re)
        
        links = []
        for tag in tags_with_src:
            # TODO: Need to resolve URLs to be absolute
            url = tag['src']
            if tag.name == 'img':
                title = LinkParser._get_image_tag_title(tag)
                links.append(Link(url, title, 'Image', True))
            elif tag.name == 'frame':
                title = tag['name'] if 'name' in tag.attrMap else None
                links.append(Link(url, title, 'Frame', True))
            elif tag.name == 'input' and 'type' in tag.attrMap and tag['type'] == 'image':
                title = LinkParser._get_image_tag_title(tag)
                links.append(Link(url, title, 'Form Image', True))
            else:
                title = None
                links.append(Link(url, title, 'Unknown Embedded (%s)' % (tag.name,), True))
        for tag in tags_with_href:
            # TODO: Need to resolve URLs to be absolute
            url = tag['href']
            if tag.name == 'a':
                title = tag.string
                links.append(Link(url, title, 'Link', False))
            elif tag.name == 'link' and (
                    ('rel' in tag.attrMap and tag['rel'] == 'stylesheet') or (
                     'type' in tag.attrMap and tag['type'] == 'text/css') or (
                     url.endswith('.css'))):
                title = None
                links.append(Link(url, title, 'Stylesheet', True))
            else:
                title = None
                links.append(Link(url, title, 'Unknown (%s)' % (tag.name,), False))
        
        return links
    
    @staticmethod
    def _get_image_tag_title(tag):
        if 'alt' in tag.attrMap:
            return tag['alt']
        elif 'title' in tag.attrMap:
            return tag['title']
        else:
            return None

class Link(object):
    def __init__(self, url, title, type_title, embedded):
        """
        Arguments:
        url - URL or URI referenced by this link.
        title - displayed title for this link, or None.
        type_title - displayed title for this link's type.
        embedded - whether this link refers to an embedded resource.
        """
        if url is None or type_title is None or embedded not in (True, False):
            raise ValueError
        self.url = url
        self.title = title
        self.type_title = type_title
        self.embedded = embedded
    
    def __repr__(self):
        return 'Link(%s,%s,%s,%s)' % (repr(self.url), repr(self.title), repr(self.type_title), repr(self.embedded))
