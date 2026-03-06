"""
Fake boto3 package directory for testing S3Filesystem without real AWS access.

The boto3/ and botocore/ subdirectories contain fake implementations of the
real boto3 and botocore packages.

Call install() to load those fakes into sys.modules so that any subsequent
`import boto3` / `import botocore` picks up the fakes instead of the real ones.
"""

from collections.abc import Callable
import sys


_FAKE_MODULE_NAMES = ['botocore', 'botocore.exceptions', 'boto3']


def install() -> Callable[[], None]:
    """
    Load the fake boto3/botocore modules directly into sys.modules.

    Wires the fake subpackages of this package into sys.modules under the real
    module names so that any subsequent `import boto3` / `import botocore`
    picks up the fakes.

    Returns an uninstall() callable that removes the fakes from sys.modules and
    restores whatever modules were there before install() was called.
    """
    # NOTE: Uses static imports so that py2exe's import tracer includes these
    #       modules in the frozen bundle.
    from crystal.tests.util.fake_boto3 import botocore as fake_botocore
    from crystal.tests.util.fake_boto3.botocore import exceptions as fake_botocore_exceptions
    from crystal.tests.util.fake_boto3 import boto3 as fake_boto3_mod

    # Save and remove any existing modules with these names
    saved_modules = {
        k: sys.modules.pop(k)
        for k in _FAKE_MODULE_NAMES
        if k in sys.modules
    }

    # Wire fakes into sys.modules under the real (short) module names
    sys.modules['botocore'] = fake_botocore
    sys.modules['botocore.exceptions'] = fake_botocore_exceptions
    sys.modules['boto3'] = fake_boto3_mod

    def uninstall() -> None:
        for k in _FAKE_MODULE_NAMES:
            sys.modules.pop(k, None)
        sys.modules.update(saved_modules)
    return uninstall
