from collections.abc import Iterator
from contextlib import contextmanager
from crystal.filesystem.local import (
    flush_renames_in_directory as _flush_renames_in_directory,
    open_nonexclusive,
    replace_destination_locked as _replace_destination_locked,
    RENAME_SUFFIX,
)
from dataclasses import dataclass
from functools import lru_cache
import os
import os.path
import pathlib
import shutil
import threading
from typing import BinaryIO, ClassVar, Literal, NamedTuple, TypeAlias, assert_never
import urllib.parse


Filesystem: TypeAlias = 'LocalFilesystem | S3Filesystem'
"""
A supported filesystem type.

Use instead of _AbstractFilesystem so that exhaustiveness checking
can be performed by typecheckers on code like `if isinstance(X, FooFilesystem): ...`.

See alsp:
- _AbstractFilesystem
"""


class FilesystemPath(NamedTuple):
    """
    A (Filesystem, path) bundle, which is convenient to pass between functions because
    I/O can only be done on a path through a Filesystem instance.
    
    Supports destructuring via:
        fs_path: FilesystemPath = ...
        (fs, path) = fs_path
    """
    fs: Filesystem
    path: str


class _AbstractFilesystem:
    """
    Interface for manipulating files & directories in a filesystem.
    
    Designed originally to support only the intersection of operations
    that make sense for LocalFilesystem and S3Filesystem.
    
    Subclasses - notably LocalFilesystem - may support additional operations
    not in this abstract interface.
    """
    
    # === Filesystem API ===
    
    @classmethod
    def recognizes_path(cls, path: str) -> bool:
        """
        Whether this Filesystem subclass is responsible for manipulating
        paths in the format matching the specified path.
        """
        raise NotImplementedError()

    def join(self, /, parent_dirpath: str, *itemnames: str) -> str:
        raise NotImplementedError()

    def split(self, /, itempath: str, *, root_ok: bool = False) -> tuple[str, str]:
        raise NotImplementedError()

    def dirname(self, /, path: str) -> str:
        return self.split(path)[0]

    def basename(self, /, path: str) -> str:
        return self.split(path)[1]
    
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
    """
    Interface for manipulating files/directories on the local computer filesystem.
    
    Directories exist as concrete entities in this filesystem type. Therefore:
    - It is necessary to "create the parent directory" of a file before
      it is created. See makedirs().
    """
    
    # === Filesystem API ===
    
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
        * OSError -- if some other kind of I/O error occurs
        """
        return os.path.getsize(path)

    # === LocalFilesystem API ===

    W_OK: ClassVar[int] = os.W_OK

    @property
    def sep(self) -> str:
        return os.path.sep

    def exists(self, path: str) -> bool:
        """
        Raises:
        * OSError
        """
        return os.path.exists(path)

    def isfile(self, path: str) -> bool:
        """
        Raises:
        * OSError
        """
        return os.path.isfile(path)

    def isdir(self, path: str) -> bool:
        """
        Raises:
        * OSError
        """
        return os.path.isdir(path)

    def access(self, path: str, mode: int) -> bool:
        """
        Raises:
        * OSError
        """
        return os.access(path, mode)
    
    def touch(self, path: str) -> None:
        """
        Raises:
        * OSError
        """
        pathlib.Path(path).touch()

    def listdir(self, path: str) -> list[str]:
        """
        Raises:
        * FileNotFoundError
        * OSError
        """
        return os.listdir(path)

    def walk(self,
            top: str,
            *, topdown: bool = True,
            ) -> Iterator[tuple[str, list[str], list[str]]]:
        """
        Raises:
        * OSError
        """
        return os.walk(top, topdown=topdown)

    def mkdir(self, path: str) -> None:
        """
        Raises:
        * FileExistsError
        * OSError
        """
        os.mkdir(path)

    # TODO: Remove exist_ok and assume it is always True,
    #       because all callers at the time of writing specify exist_ok=True.
    def makedirs(self, path: str, exist_ok: bool = False) -> None:
        """
        Raises:
        * OSError
        """
        os.makedirs(path, exist_ok=exist_ok)

    def rename(self, src: str, dst: str) -> None:
        """
        Renames/move an item to a different name/path that is assumed to not exist, atomically.
        
        If the destination itempath DOES actually exist then this function
        behaves differently depending on the operating system.
        See os.rename() documentation for details.
        
        Raises:
        * OSError
        """
        os.rename(src, dst)

    def flush_renames_in_directory(self, parent_dirpath: str) -> None:
        """
        Ensures that all renames of files to locations directly within the
        specified parent directory are flushed to disk.

        Raises:
        * OSError
        """
        _flush_renames_in_directory(parent_dirpath)

    def replace_and_flush(self, src: str, dst: str, *, nonatomic_ok: bool = False) -> None:
        """
        Renames/move an item to a different name/path that is assumed may exist,
        replacing the destination itempath, atomically.
        
        If the destination itempath does not actually exist then this function
        also succeeds.
        
        Raises:
        * OSError
        """
        from crystal.filesystem.local import replace_and_flush as _replace_and_flush
        _replace_and_flush(src, dst, nonatomic_ok=nonatomic_ok)

    @contextmanager
    def replace_destination_locked(self, dst_filepath: str) -> Iterator[None]:
        """
        Context in which either
        (1) a non-atomic replace_and_flush() operation or
        (2) a repair of one, is allowed.
        """
        with _replace_destination_locked(dst_filepath):
            yield

    def remove(self, path: str) -> None:
        """
        Raises:
        * FileNotFoundError
        * OSError
        """
        os.remove(path)

    def rmtree(self, path: str, *, ignore_errors: bool = False) -> None:
        """
        Raises:
        * OSError
        """
        shutil.rmtree(path, ignore_errors=ignore_errors)

    def send2trash(self, path: str) -> None:
        """
        Raises:
        * TrashPermissionError
        * OSError
        """
        from send2trash import send2trash as _send2trash
        _send2trash(path)

    def copystat(self, src: str, dst: str) -> None:
        """
        Raises:
        * OSError
        """
        shutil.copystat(src, dst)
    
    def as_uri(self, path: str) -> str:
        return pathlib.Path(path).as_uri()


class S3Filesystem(_AbstractFilesystem):
    """
    Interface for manipulating files/directories on the S3 object storage system.
    
    Note that "directories" aren't a true concrete entity in S3.
    A "directory" exists only insofar as there is a file key with a nested path. Thus:
    - There is no need to "create the parent directory" of a file that is about
      to be created. There is no makedirs() command.
    - Queries like "does X directory exist" are not supported.
    """
    _MAX_CACHED_S3_CLIENTS = 4
    
    def __init__(self, credentials: 'Credentials | ProfileCredentials | None' = None) -> None:
        self._credentials = credentials
        
        self._s3_client_cache_lock = threading.Lock()
        # NOTE: _bucket_name is used in the cache key for @lru_cache
        def _create_cached(_bucket_name: str, region_hint: str):
            return self._create_s3_client(region_hint)
        self._s3_client_cache = lru_cache(maxsize=self._MAX_CACHED_S3_CLIENTS)(_create_cached)

    # === Filesystem API ===
    
    @classmethod
    def recognizes_path(cls, path: str) -> bool:
        return path.startswith('s3://')
    
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

        (bucket, key, region_hint) = self.parse_url(path)
        s3_client = self._get_or_create_s3_client(bucket, region_hint)
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
        import botocore.exceptions

        (bucket, key, region_hint) = self.parse_url(path)
        s3_client = self._get_or_create_s3_client(bucket, region_hint)
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
    
    # === S3Filesystem API ===

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
            raise ValueError(f'Not a valid S3 URL')

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
        if not bucket_name:
            # NOTE: Do NOT include secret_url in the output because it
            #       might contain secret credentials
            raise ValueError(f'Invalid S3 URL bucket')

        region = parsed.region
        # NOTE: If no ?region=R is specified in the URL, parse_s3_url()
        #       will fallback to "us-east-1" as a default region rather
        #       then returning a blank or None region
        assert region

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
            raise ValueError(f'Not a valid S3 URL: {path}')

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

        region_hint = parsed.region
        # TODO: Is the exception below reachable?
        #       I suspect parse_s3_url() *always* returns a region, 
        #       even if it infers the default region (us-east-1).
        if region_hint is None or region_hint == '':
            raise ValueError(f'S3 URL must include exactly one region: {path!r}')

        return (bucket_name, parsed.key, region_hint)

    @classmethod
    def format_url(cls,
            bucket_name: str,
            key: str,
            region: str,
            ) -> str:
        return f's3://{bucket_name}/{key}?region={region}'
    
    # === Utility ===

    def _get_or_create_s3_client(self, bucket_name: str, region_hint: str):
        """
        Returns a cached boto3 S3 client for the given bucket,
        creating one if necessary.

        Caches up to _MAX_CACHED_S3_CLIENTS clients 
        (one per unique (bucket_name, region_hint) pair),
        evicting the least-recently-used one when the cache is full.
        """
        with self._s3_client_cache_lock:
            return self._s3_client_cache(bucket_name, region_hint)

    def _create_s3_client(self, region: str):
        """Creates a boto3 S3 client using this filesystem's credentials."""
        import boto3
        
        if isinstance(self._credentials, S3Filesystem.ProfileCredentials):
            session = boto3.Session(profile_name=self._credentials.profile_name)
            return session.client('s3', region_name=region)
        elif isinstance(self._credentials, S3Filesystem.Credentials):
            return boto3.client(
                's3',
                aws_access_key_id=self._credentials.access_key_id,
                aws_secret_access_key=self._credentials.secret_access_key,
                region_name=region)
        elif self._credentials is None:
            return boto3.client('s3', region_name=region)
        else:
            assert_never(self._credentials)

    # === Credentials ===

    @dataclass
    class Credentials:
        access_key_id: str
        secret_access_key: str

    @dataclass
    class ProfileCredentials:
        profile_name: str

