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


class _FakeS3Client:
    def __init__(self, *, region_name=None, has_credentials=True, invalid_credentials=False):
        self._region_name = region_name or 'us-east-1'
        self._has_credentials = has_credentials
        self._invalid_credentials = invalid_credentials

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

    def get_object(self, *, Bucket, Key, Range=None):
        self._check_credentials('GetObject')
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
