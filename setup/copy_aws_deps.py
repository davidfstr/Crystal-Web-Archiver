"""
Copies AWS S3 dependencies (botocore, boto3, s3transfer, jmespath) into dist/lib/.

botocore and boto3 must be copied as full package directories (rather than
bundled into the py2exe zip) because they derive their data directory paths
from __file__ at runtime:

    # botocore/__init__.py
    BOTOCORE_ROOT = os.path.dirname(os.path.abspath(__file__))

    # botocore/loaders.py
    BUILTIN_DATA_PATH = os.path.join(BOTOCORE_ROOT, 'data')

When bundled inside py2exe's zip, __file__ resolves to a path inside the zip
rather than a real directory, so botocore.loaders cannot open endpoints.json
or any other data file. Placing the packages on disk as real directories fixes
this.

Only S3-related data files are kept (saves ~15 MB vs. copying everything):
- botocore/data/: keeps endpoints.json, partitions.json,
  sdk-default-configuration.json, _retry.json, and the s3/ service directory.
- boto3/data/: keeps only the s3/ service directory.

How to re-determine which data files are required
--------------------------------------------------
If botocore or boto3 is updated and the required data files change, the
following snippet can be used to discover which files are actually loaded
at runtime when creating an S3 client:

    import botocore, botocore.loaders as bl, os

    original_load = bl.JSONFileLoader.load_file
    loaded = set()
    bl.JSONFileLoader.load_file = lambda self, p: (loaded.add(p), original_load(self, p))[1]

    import boto3
    boto3.client('s3', region_name='us-east-1',
                 aws_access_key_id='x', aws_secret_access_key='x')

    data_root = os.path.join(botocore.BOTOCORE_ROOT, 'data')
    b3_root   = os.path.join(boto3.__path__[0], 'data')
    for f in sorted(loaded):
        if data_root in f:
            print(os.path.relpath(f, data_root))
        elif b3_root in f:
            print('[boto3]', os.path.relpath(f, b3_root))
        else:
            print(f)
"""

import os
import shutil


DIST_LIB = os.path.join('dist', 'lib')


def _copy_package(src: str, dst: str) -> None:
    shutil.copytree(src, dst)


def _prune_data_dir(data_dst: str, keep: set) -> None:
    """Remove all service subdirectories from a package's data/ dir except those in keep."""
    for entry in os.listdir(data_dst):
        entry_path = os.path.join(data_dst, entry)
        if os.path.isdir(entry_path) and entry not in keep:
            shutil.rmtree(entry_path)


# --- botocore (S3 data only) ---
import botocore  # noqa: E402
print('Copying botocore (S3 data only)...')
botocore_dst = os.path.join(DIST_LIB, 'botocore')
_copy_package(botocore.__path__[0], botocore_dst)
_prune_data_dir(
    os.path.join(botocore_dst, 'data'),
    keep={'s3', 'endpoints.json', 'partitions.json',
          'sdk-default-configuration.json', '_retry.json'},
)

# --- boto3 (S3 data only) ---
import boto3  # noqa: E402
print('Copying boto3 (S3 data only)...')
boto3_dst = os.path.join(DIST_LIB, 'boto3')
_copy_package(boto3.__path__[0], boto3_dst)
_prune_data_dir(
    os.path.join(boto3_dst, 'data'),
    keep={'s3'},
)

# --- s3transfer (no data directory, bundled in full) ---
import s3transfer  # noqa: E402
print('Copying s3transfer...')
_copy_package(s3transfer.__path__[0], os.path.join(DIST_LIB, 's3transfer'))

# --- jmespath (no data directory, bundled in full) ---
import jmespath  # noqa: E402
print('Copying jmespath...')
_copy_package(jmespath.__path__[0], os.path.join(DIST_LIB, 'jmespath'))
