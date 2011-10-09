from collections import OrderedDict
import os
import sqlite3

class Project(object):
    """
    Groups together a set of resources that are downloaded and any associated settings.
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
        
        self._resources = OrderedDict()
        
        self._loading = True
        try:
            if os.path.exists(path):
                # Load from existing project
                self._db = sqlite3.connect(os.path.join(path, self._DB_FILENAME))
                
                c = self._db.cursor()
                c.execute('select url from resource')
                for (url,) in c:
                    Resource(self, url)
            else:
                # Create new project
                os.mkdir(path)
                os.mkdir(os.path.join(path, self._BLOBS_DIRNAME))
                self._db = sqlite3.connect(os.path.join(path, self._DB_FILENAME))
                
                c.execute('create table resource (id integer primary key, url text)')
        finally:
            self._loading = False

class Resource(object):
    def __new__(cls, project, url):
        """
        Arguments:
        url -- absolute URL to this resource (ex: http), or a URI (ex: mailto).
        """
        
        if url in project._resources:
            return project._resources[url]
        else:
            self = object.__new__(cls)
            self.project = project
            self.url = url
            
            if not project._loading:
                c = project._db.cursor()
                c.execute('insert into resource (url) values (?)', (url,))
                project._db.commit()
            project._resources[url] = self
            return self