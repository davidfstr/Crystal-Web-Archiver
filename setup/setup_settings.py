# Locate and import crystal, modifying sys.path if necessary
try:
    import crystal
except ImportError:
    import os
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
    import crystal

from crystal import APP_NAME, APP_COPYRIGHT_STRING, __version__


# Settings
APP_NAME = APP_NAME  # reexport
VERSION_STRING = __version__
COPYRIGHT_STRING = APP_COPYRIGHT_STRING
