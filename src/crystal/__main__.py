"""
The startup module of Crystal, which is designated as the initial module
that runs when Crystal is launched.

Trampolines to the main module at crystal.main.

The startup module and the main module are kept separate because app
packages like py2app and py2exe treat the startup module slightly
differently than a regular module, so it's best not to put too much
functionality in the startup module. Known differences:
* py2app --
    Relocates the startup module from its original location at /crystal/__main__.py
    to just /__main__.py, so it's more difficult to patch in automated tests.
* py2exe --
    The startup module has no __file__ defined in its globals() and 
    doesn't appear to be patchable at all by automated tests.
"""

from crystal.main import main

if __name__ == '__main__':
    main()
