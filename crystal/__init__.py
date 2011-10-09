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
    
    def __init__(self, path, primary_domain=None):
        """
        Loads a project from the specified filepath, or creates a new one if none is found.
        
        Arguments:
        path -- Path to a directory (ideally with the `FILE_EXTENSION` extension)
                from which the project is to be loaded.
        primary_domain -- Absolute URL string that the majority of URLs will be relative to.
                          URLs displayed in the UI will be converted to be relative to this
                          URL whenever possible.
        """
        
        self.path = path
        self.primary_domain = primary_domain
        
        if os.path.exists(path):
            # Load from existing project
            self._db = sqlite3.connect(os.path.join(path, self._DB_FILENAME))
        else:
            # Create new project
            os.mkdir(path)
            os.mkdir(os.path.join(path, self._BLOBS_DIRNAME))
            self._db = sqlite3.connect(os.path.join(path, self._DB_FILENAME))
