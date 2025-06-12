# Copied from Python 3.10's site.py and _sitebuiltins.py module,
# because these modules aren't available in frozen .app or .exe bundles

import builtins
import os
import sys

# ------------------------------------------------------------------------------
# site.py

def setquit():
    """Define new builtins 'quit' and 'exit'.

    These are objects which make the interpreter exit when called.
    The repr of each object contains a hint at how it works.

    """
    if os.sep == '\\':
        eof = 'Ctrl-Z plus Return'
    else:
        eof = 'Ctrl-D (i.e. EOF)'

    builtins.quit = Quitter('quit', eof)
    builtins.exit = Quitter('exit', eof)


def sethelper():
    builtins.help = _Helper()


# ------------------------------------------------------------------------------
# _sitebuiltins.py

class Quitter:
    def __init__(self, name, eof):
        self.name = name
        self.eof = eof
    def __repr__(self):
        return 'Use {}() or {} to exit'.format(self.name, self.eof)
    def __call__(self, code=None):
        # Shells like IDLE catch the SystemExit, but listen when their
        # stdin wrapper is closed.
        try:
            sys.stdin.close()
        except:
            pass
        raise SystemExit(code)


class _Helper:
    """Define the builtin 'help'.

    This is a wrapper around pydoc.help that provides a helpful message
    when 'help' is typed at the Python interactive prompt.

    Calling help() at the Python prompt starts an interactive help session.
    Calling help(thing) prints help for the python object 'thing'.
    """

    def __repr__(self):
        return "Type help() for interactive help, " \
               "or help(object) for help about object."
    def __call__(self, *args, **kwds):
        import pydoc
        return pydoc.help(*args, **kwds)


# ------------------------------------------------------------------------------
