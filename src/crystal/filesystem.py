# TODO: Rename crystal.util.filesystem -> local_filesystem
from crystal.util.filesystem import open_nonexclusive
from dataclasses import dataclass
import os.path
from typing import BinaryIO, Literal, TypeAlias
import urllib.parse


# A supported filesystem type.
# 
# Use instead of _AbstractFilesystem so that exhaustiveness checking
# can be performed by typecheckers on code like `if isinstance(X, FooFilesystem): ...`.
Filesystem: TypeAlias = 'LocalFilesystem | S3Filesystem'


class _AbstractFilesystem:
    @classmethod
    def recognizes_path(cls, path: str) -> bool:
        raise NotImplementedError()
    
    def join(self, /, parent_dirpath: str, *itemnames: str) -> str:
        raise NotImplementedError()
    
    def split(self, /, itempath: str, *, root_ok: bool = False) -> tuple[str, str]:
        raise NotImplementedError()
    
    def open(self, path: str, mode: Literal['rb']) -> BinaryIO:
        """
        Opens the specified file for reading.
        
        Raises:
        * FileNotFoundError -- if no file exists at `path`
        * PermissionError -- if you are not authorized to access `path`
        * Exception -- if some other kind of I/O error occurs
        """
        raise NotImplementedError()
    
    def getsize(self, path: str) -> int:
        """
        Returns the size of the specified file.
        
        Raises:
        * FileNotFoundError -- if no file exists at `path`
        * PermissionError -- if you are not authorized to access `path`
        * Exception -- if some other kind of I/O error occurs
        """
        raise NotImplementedError()


class LocalFilesystem(_AbstractFilesystem):
    @classmethod
    def recognizes_path(cls, path: str) -> bool:
        return not S3Filesystem.recognizes_path(path)
    
    def join(self, /, parent_dirpath: str, *itemnames: str) -> str:
        # Validate inputs
        if parent_dirpath.endswith(os.path.sep):
            raise ValueError(f'Trailing directory separator not allowed: {parent_dirpath!r}')
        for n in itemnames:
            if os.path.sep in n:
                raise ValueError(f'Not a valid file/directory name: {n!r}')
            if n == '':
                raise ValueError(f'Empty file/directory name not allowed: {n!r}')
            if n == os.path.pardir or n == os.path.curdir:
                raise ValueError(f'Special file/directory name not allowed: {n!r}')
        
        # Join
        return os.path.join(parent_dirpath, *itemnames)
    
    def split(self, /, itempath: str, *, root_ok: bool = False) -> tuple[str, str]:
        (parent_dirpath, itemname) = os.path.split(itempath)
        if itemname == '' and not root_ok:
            raise ValueError(f'Cannot split path at root: {itempath!r}')
        return (parent_dirpath, itemname)
    
    def open(self, path: str, mode: Literal['rb']) -> BinaryIO:
        """
        Opens the specified file for reading.
        
        Raises:
        * FileNotFoundError -- if no file exists at `path`
        * PermissionError -- if you are not authorized to access `path`
        * OSError -- if some other kind of I/O error occurs
        """
        return open_nonexclusive(path, mode)
    
    def getsize(self, path: str) -> int:
        """
        Returns the size of the specified file.
        
        Raises:
        * FileNotFoundError -- if no file exists at `path`
        * PermissionError -- if you are not authorized to access `path`
        * IOError -- if some other kind of I/O error occurs
        """
        return os.path.getsize(path)


class S3Filesystem(_AbstractFilesystem):
    """
    Interface for manipulating files/directories on the S3 object storage system.
    
    Note that "directories" aren't a true concrete entity in S3.
    A "directory" exists only insofar as there is a file key with a nested path. Thus:
    - There is no need to "create the parent directory" of a file that is about
      to be created. There is no makedirs() command.
    - Queries like "does X directory exist" are not supported.
    """
    def __init__(self, credentials: 'Credentials | None' = None) -> None:
        try:
            import boto3
            import s3_parse_url
        except ImportError:
            raise ImportError(
                'S3 support for Crystal is not installed. '
                'Try "poetry install --with=s3".'
            )
        self._credentials = credentials
    
    @classmethod
    def recognizes_path(cls, path: str) -> bool:
        return path.startswith('s3://')
    
    @classmethod
    def split_credentials_if_present(cls, secret_url: str) -> 'tuple[Credentials | None, str]':
        """
        Splits an s3:// URL into (optional_credentials, plain_url).

        The returned plain_url never contains embedded credentials.
        """
        from s3_parse_url import parse_s3_url

        try:
            parsed = parse_s3_url(secret_url)
        except Exception:
            # NOTE: Do NOT include secret_url in the output because it
            #       might contain secret credentials
            raise ValueError(f'Not an S3 URL')

        access_key_id = parsed.access_key_id
        if access_key_id is None:
            secret_access_key = None
        else:
            try:
                secret_access_key = parsed.secret_access_key
            except TypeError:
                # s3_parse_url may internally store a missing secret as None,
                # and its property accessor attempts to unquote(None).
                secret_access_key = None

        if (access_key_id is None) != (secret_access_key is None):
            # NOTE: Do NOT include secret_url in the output because it
            #       might contain secret credentials
            raise ValueError(
                f'S3 URL has access key ID or secret access key but not both'
            )

        bucket_name = parsed.bucket_name
        if bucket_name == '':
            # NOTE: Do NOT include secret_url in the output because it
            #       might contain secret credentials
            raise ValueError(f'Invalid S3 URL bucket')

        region = parsed.region
        if region is None or region == '':
            # NOTE: Do NOT include secret_url in the output because it
            #       might contain secret credentials
            raise ValueError(f'S3 URL must include exactly one region')

        plain_url = cls.format_url(bucket_name, parsed.key, region)
        if access_key_id is None:
            credentials = None
        else:
            assert secret_access_key is not None
            credentials = cls.Credentials(
                access_key_id,
                urllib.parse.unquote(secret_access_key),
            )
        return (credentials, plain_url)
    
    @classmethod
    def parse_url(cls,
            path: str,
            *,
            allow_credentials: bool = False,
            ) -> tuple[str, str, str]:
        from s3_parse_url import parse_s3_url

        try:
            parsed = parse_s3_url(path)
        except Exception:
            raise ValueError(f'Not an S3 URL: {path}')

        access_key_id = parsed.access_key_id
        if access_key_id is None:
            secret_access_key = None
        else:
            try:
                secret_access_key = parsed.secret_access_key
            except TypeError:
                # s3_parse_url may internally store a missing secret as None,
                # and its property accessor attempts to unquote(None).
                secret_access_key = None

        if allow_credentials:
            if access_key_id is None or secret_access_key is None:
                raise ValueError(
                    f'S3 URL is missing embedded credentials: {path!r}'
                )
        else:
            if access_key_id is not None:
                raise ValueError(
                    f'S3 URL must not contain embedded credentials: {path!r}'
                )

        bucket_name = parsed.bucket_name
        if bucket_name == '':
            raise ValueError(f'Invalid S3 URL bucket: {path!r}')

        region = parsed.region
        if region is None or region == '':
            raise ValueError(f'S3 URL must include exactly one region: {path!r}')

        return (bucket_name, parsed.key, region)

    @classmethod
    def format_url(cls,
            bucket_name: str,
            key: str,
            region: str,
            ) -> str:
        return f's3://{bucket_name}/{key}?region={region}'

    def join(self, /, parent_dirpath: str, *itemnames: str) -> str:
        # Validate inputs
        for n in itemnames:
            if '/' in n:
                raise ValueError(f'Not a valid file/directory name: {n!r}')
            if n == '':
                raise ValueError(f'Empty file/directory name not allowed: {n!r}')
            if n == '..' or n == '.':
                raise ValueError(f'Special file/directory name not allowed: {n!r}')
        (bucket_name, parent_key, region) = self.parse_url(
            parent_dirpath,
        )
        if parent_key.endswith('/'):
            raise ValueError(f'Trailing directory separator not allowed: {parent_dirpath!r}')
        
        # Join
        if parent_key == '':
            new_key = '/'.join(itemnames)
        else:
            new_key = parent_key + '/' + '/'.join(itemnames)
        return self.format_url(bucket_name, new_key, region)
    
    def split(self, /, itempath: str, *, root_ok: bool = False) -> tuple[str, str]:
        (bucket_name, key, region) = self.parse_url(
            itempath,
        )
        
        if key == '':
            if root_ok:
                return (itempath, '')
            else:
                raise ValueError(f'Cannot split path at root: {itempath!r}')
        if '/' in key:
            (parent_key, itemname) = key.rsplit('/', 1)
        else:
            (parent_key, itemname) = ('', key)
        parent_s3_url_str = self.format_url(bucket_name, parent_key, region)
        return (parent_s3_url_str, itemname)
    
    def open(self,
            path: str,
            mode: Literal['rb'],
            *, start: int | None = None,
            end: int | None = None,
            ) -> BinaryIO:
        """
        Opens the specified file for reading.
        
        Supports opening specific byte ranges with the `start` and `end` arguments:
        - If neither `start` nor `end` are provided, opens the entire file.
        - If `start` is negative, opens the last abs(start) bytes.
        - If `start` is non-negative and `end` is provided,
          opens the byte range start to end (inclusive).
        
        Raises:
        * ValueError -- 
            if `path` is not a valid s3:// URL;
            if `path` contains embedded credentials;
            if `start` and `end` form an invalid range (start > end);
            if `mode` is not valid
        * FileNotFoundError -- if no file exists at `path`
        * PermissionError -- if you are not authorized to access `path`
        * botocore.exceptions.BotoCoreError -- if some other kind of I/O error occurs
        """
        import boto3
        import botocore.exceptions
        
        if mode != 'rb':
            raise ValueError(f'Invalid mode: {mode!r}')
        
        if start is None:
            range_header = None
        elif start < 0:
            if end is not None:
                raise ValueError(f'Invalid range: {start}-{end}')
            range_header = f'bytes={start}'
        else:
            if end is None or not (start <= end):
                raise ValueError(f'Invalid range: {start}-{end}')
            range_header = f'bytes={start}-{end}'

        (bucket, key, region) = self.parse_url(path)
        if self._credentials is None:
            s3_client = boto3.client('s3', region_name=region)
        else:
            s3_client = boto3.client(
                's3',
                aws_access_key_id=self._credentials.access_key_id,
                aws_secret_access_key=self._credentials.secret_access_key,
                region_name=region,
            )
        try:
            if range_header is None:
                resp = s3_client.get_object(Bucket=bucket, Key=key)
            else:
                resp = s3_client.get_object(Bucket=bucket, Key=key, Range=range_header)
        except botocore.exceptions.ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            http_status_code = e.response.get('ResponseMetadata', {}).get('HTTPStatusCode')

            # NoSuchKey, NoSuchBucket, no such region, etc
            if http_status_code == 404:
                raise FileNotFoundError(
                    f'No such key or bucket: {f"s3://{bucket}/{key}"!r}'
                ) from e
            # AccessDenied, InvalidAccessKeyId, SignatureDoesNotMatch, etc
            elif http_status_code == 403:
                raise PermissionError(str(e)) from e
            # InvalidRange
            elif http_status_code == 416:
                # The `start` >= the object's byte size
                # TODO: Parse `e.response['ResponseMetadata']['HTTPHeaders']['content-range']`,
                #       in the format "bytes */123456" to extract the object's byte size
                #       and return that in a structured exception type
                raise
            # SlowDown
            elif error_code == 'SlowDown':
                # TODO: Raise a structured exception for this condition which I suspect
                #       is common enough that clients may want to handle specially
                raise
            else:
                raise
        return resp['Body']

    def getsize(self, path: str) -> int:
        """
        Returns the size of the specified file.
        
        Raises:
        * ValueError -- if `path` is not a valid plain s3:// URL
          (must not contain embedded credentials)
        * FileNotFoundError -- if no file exists at `path`
        * PermissionError -- if you are not authorized to access `path`
        * botocore.exceptions.BotoCoreError -- if some other kind of I/O error occurs
        """
        import boto3
        import botocore.exceptions

        (bucket, key, region) = self.parse_url(path)
        if self._credentials is None:
            s3_client = boto3.client('s3', region_name=region)
        else:
            s3_client = boto3.client(
                's3',
                aws_access_key_id=self._credentials.access_key_id,
                aws_secret_access_key=self._credentials.secret_access_key,
                region_name=region,
            )
        try:
            resp = s3_client.head_object(Bucket=bucket, Key=key)
        except botocore.exceptions.ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            http_status_code = e.response.get('ResponseMetadata', {}).get('HTTPStatusCode')

            # NoSuchKey, NoSuchBucket, no such region, etc
            if http_status_code == 404:
                raise FileNotFoundError(
                    f'No such key or bucket: {f"s3://{bucket}/{key}"!r}'
                ) from e
            # 403, AccessDenied, InvalidAccessKeyId, SignatureDoesNotMatch, etc
            elif http_status_code == 403:
                # ex: 'An error occurred (403) when calling the HeadObject operation: Forbidden'
                #     when credentials are valid but disabled on the IAM account
                raise PermissionError(str(e)) from e
            # SlowDown
            elif error_code == 'SlowDown':
                # TODO: Raise a structured exception for this condition which I suspect
                #       is common enough that clients may want to handle specially
                raise
            else:
                raise
        return resp['ContentLength']
    
    # === Credentials ===
    
    @dataclass
    class Credentials:
        access_key_id: str
        secret_access_key: str

