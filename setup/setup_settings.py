# Locate and import crystal, modifying sys.path if necessary
try:
    import crystal
except ImportError:
    import os
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
    import crystal

from crystal import __version__
import datetime

APP_NAME = 'Crystal'
VERSION_STRING = __version__
COPYRIGHT_STRING = f'Copyright © 2011-{datetime.date.today().year} David Foster. Licensed under PolyForm NC 1.0.0'
