"""
Fake boto3 module for testing S3Filesystem without real AWS access.

Activated by setting CRYSTAL_FAKE_S3_ROOT environment variable to a directory
with the structure:
    $CRYSTAL_FAKE_S3_ROOT/
        <region>/
            <bucket>/
                <key_prefix>/
                    <files...>

Only supports the (readonly S3) functionality used by S3Filesystem.
Attempting to use other functionality raises NotImplementedError.
"""

import io
import os
from typing import TypeAlias


def _FAKE_S3_ROOT() -> str:
    root = os.environ.get('CRYSTAL_FAKE_S3_ROOT', '')
    if not root:
        raise RuntimeError(
            'Fake boto3 module requires CRYSTAL_FAKE_S3_ROOT environment variable'
        )
    return root


def client(service_name, *, region_name=None, aws_access_key_id=None, aws_secret_access_key=None):
    if service_name != 's3':
        raise NotImplementedError(f'Fake boto3 only supports s3, not {service_name!r}')
    has_credentials = (
        aws_access_key_id is not None or
        os.environ.get('AWS_ACCESS_KEY_ID') is not None
    )
    invalid_credentials = (
        os.environ.get('CRYSTAL_FAKE_S3_INVALID_CREDENTIALS') == '1'
    )
    return _FakeS3Client(
        region_name=region_name,
        has_credentials=has_credentials,
        invalid_credentials=invalid_credentials,
    )

# ('<region>', 'GET', 's3://<bucket>/<key>') or 
# ('<region>', 'HEAD', 's3://<bucket>/<key>')
HttpRequestToS3: TypeAlias = tuple[str, str, str]

class _FakeS3Client:
    # Class-global log of simulated HTTP requests.
    #
    # Tests can clear this list and then inspect it after performing operations.
    http_requests: list[HttpRequestToS3] = []

    # Class-global mapping of bucket name -> correct region.
    # 
    # When the client's region doesn't match, simulates the 4-request
    # region-discovery pattern that real boto3 performs.
    # Buckets not in this dict are assumed to be in whatever region the client was created with.
    CORRECT_REGION_FOR_BUCKET: dict[str, str] = {}

    def __init__(self, *, region_name=None, has_credentials=True, invalid_credentials=False):
        self._region_name = region_name or 'us-east-1'
        self._has_credentials = has_credentials
        self._invalid_credentials = invalid_credentials
    
    # === Utility ===

    def _check_credentials(self, operation_name: str) -> None:
        if not self._has_credentials:
            from botocore.exceptions import NoCredentialsError
            raise NoCredentialsError()
        if self._invalid_credentials:
            from botocore.exceptions import ClientError
            raise ClientError(
                {
                    'Error': {
                        'Code': 'InvalidClientTokenId',
                        'Message': 'The security token included in the request is invalid.',
                    },
                    'ResponseMetadata': {'HTTPStatusCode': 403},
                },
                operation_name,
            )

    def _resolve_path(self, bucket, key):
        return os.path.join(_FAKE_S3_ROOT(), self._region_name, bucket, key)

    def _simulate_region_discovery(self, http_method: str, bucket: str, key: str) -> None:
        """
        Simulates the HTTP request pattern that real boto3 performs
        when the client's region doesn't match the bucket's correct region.

        When the region is wrong, real boto3 makes 4 HTTP requests:
        1. <METHOD> /<key> to wrong region -> 400
        2. HEAD / (HeadBucket) to wrong region -> 400 (discovers correct region)
        3. HEAD / (HeadBucket) to correct region -> 200
        4. <METHOD> /<key> to correct region -> 200
        Then boto3 internally corrects the client's region for future requests.

        When the region is already correct, only 1 HTTP request is made:
        1. <METHOD> /<key> to correct region -> 200
        """
        correct_region = self.CORRECT_REGION_FOR_BUCKET.get(bucket)
        wrong_region = self._region_name
        s3_url = f's3://{bucket}/{key}'
        if correct_region is not None and correct_region != wrong_region:
            # Wrong region: simulate the 4-request discovery pattern
            _FakeS3Client.http_requests.append((wrong_region, http_method, s3_url))   # 1. original request -> 400
            _FakeS3Client.http_requests.append((wrong_region, 'HEAD', f's3://{bucket}/'))  # 2. HeadBucket wrong region -> 400
            _FakeS3Client.http_requests.append((correct_region, 'HEAD', f's3://{bucket}/'))  # 3. HeadBucket correct region -> 200
            _FakeS3Client.http_requests.append((correct_region, http_method, s3_url))  # 4. retry with correct region -> 200
            # Correct the region for future requests on this client
            self._region_name = correct_region
        else:
            # Correct region: just 1 request
            _FakeS3Client.http_requests.append((self._region_name, http_method, s3_url))

    # === API ===
    
    def get_object(self, *, Bucket, Key, Range=None):
        self._check_credentials('GetObject')
        self._simulate_region_discovery('GET', Bucket, Key)
        filepath = self._resolve_path(Bucket, Key)
        if not os.path.isfile(filepath):
            from botocore.exceptions import ClientError
            raise ClientError(
                {
                    'Error': {'Code': 'NoSuchKey', 'Message': 'The specified key does not exist.'},
                    'ResponseMetadata': {'HTTPStatusCode': 404},
                },
                'GetObject',
            )

        data = open(filepath, 'rb').read()
        if Range is not None:
            data = _apply_range(data, Range)

        return {
            'Body': io.BytesIO(data),
            'ContentLength': len(data),
        }

    def head_object(self, *, Bucket, Key):
        self._check_credentials('HeadObject')
        self._simulate_region_discovery('HEAD', Bucket, Key)
        filepath = self._resolve_path(Bucket, Key)
        if not os.path.isfile(filepath):
            from botocore.exceptions import ClientError
            raise ClientError(
                {
                    'Error': {'Code': 'NoSuchKey', 'Message': 'The specified key does not exist.'},
                    'ResponseMetadata': {'HTTPStatusCode': 404},
                },
                'HeadObject',
            )

        return {
            'ContentLength': os.path.getsize(filepath),
        }

    def __getattr__(self, name):
        raise NotImplementedError(
            f'Fake boto3 S3 client does not support {name!r}'
        )


class Session:
    """
    Fake boto3.Session for testing.

    Supports:
    - available_profiles property (configured via CRYSTAL_FAKE_S3_PROFILES env var,
      a comma-separated list of profile names)
    - client() method for creating S3 clients
    """
    def __init__(self, *, profile_name=None):
        self._profile_name = profile_name

    @property
    def available_profiles(self):
        profiles_str = os.environ.get('CRYSTAL_FAKE_S3_PROFILES', '')
        if not profiles_str:
            return []
        return profiles_str.split(',')

    def client(self, service_name, *, region_name=None):
        return client(service_name, region_name=region_name)


def _apply_range(data, range_header):
    """Parse an HTTP Range header value and return the corresponding byte slice."""
    range_str = range_header.removeprefix('bytes=')
    if range_str.startswith('-'):
        # Suffix range: last N bytes
        n = int(range_str)
        return data[n:]
    else:
        parts = range_str.split('-')
        start = int(parts[0])
        end = int(parts[1])
        return data[start:end + 1]
