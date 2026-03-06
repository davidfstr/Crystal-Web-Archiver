"""
Unit tests for the S3Filesystem class.
"""

from crystal.filesystem import S3Filesystem
import pytest


# === Test: join ===

def test_s3_filesystem_join_child() -> None:
    fs = S3Filesystem()

    result = fs.join('s3://my-bucket/Archive?region=us-east-2', 'mysite.crystalproj')

    assert result == 's3://my-bucket/Archive/mysite.crystalproj?region=us-east-2'


def test_s3_filesystem_join_multiple_children() -> None:
    fs = S3Filesystem()

    result = fs.join('s3://my-bucket/a?region=us-east-2', 'b', 'c')

    assert result == 's3://my-bucket/a/b/c?region=us-east-2'


def test_s3_filesystem_join_from_bucket_root() -> None:
    fs = S3Filesystem()

    result = fs.join('s3://my-bucket/?region=us-east-2', 'Archive')

    assert result == 's3://my-bucket/Archive?region=us-east-2'


def test_s3_filesystem_join_when_name_contains_slash_then_raises_value_error() -> None:
    fs = S3Filesystem()

    with pytest.raises(ValueError):
        fs.join('s3://my-bucket/Archive?region=us-east-2', 'a/b')


def test_s3_filesystem_join_when_name_is_empty_then_raises_value_error() -> None:
    fs = S3Filesystem()

    with pytest.raises(ValueError):
        fs.join('s3://my-bucket/Archive?region=us-east-2', '')


def test_s3_filesystem_join_when_name_is_parent_dir_then_raises_value_error() -> None:
    fs = S3Filesystem()

    with pytest.raises(ValueError):
        fs.join('s3://my-bucket/Archive?region=us-east-2', '..')


def test_s3_filesystem_join_when_name_is_current_dir_then_raises_value_error() -> None:
    fs = S3Filesystem()

    with pytest.raises(ValueError):
        fs.join('s3://my-bucket/Archive?region=us-east-2', '.')


def test_s3_filesystem_join_when_parent_has_trailing_slash_then_raises_value_error() -> None:
    fs = S3Filesystem()

    with pytest.raises(ValueError):
        fs.join('s3://my-bucket/Archive/?region=us-east-2', 'child')


# === Test: split ===

def test_s3_filesystem_split_nested_path() -> None:
    fs = S3Filesystem()

    (parent, name) = fs.split('s3://my-bucket/Archive/mysite.crystalproj?region=us-east-2')

    assert parent == 's3://my-bucket/Archive?region=us-east-2'
    assert name == 'mysite.crystalproj'


def test_s3_filesystem_split_top_level_path() -> None:
    fs = S3Filesystem()

    (parent, name) = fs.split('s3://my-bucket/Archive?region=us-east-2')

    assert parent == 's3://my-bucket/?region=us-east-2'
    assert name == 'Archive'


def test_s3_filesystem_split_with_root_ok() -> None:
    fs = S3Filesystem()
    root_url = 's3://my-bucket/?region=us-east-2'

    (parent, name) = fs.split(root_url, root_ok=True)

    assert parent == root_url
    assert name == ''


def test_s3_filesystem_split_at_root_without_root_ok_raises_value_error() -> None:
    fs = S3Filesystem()

    with pytest.raises(ValueError):
        fs.split('s3://my-bucket/?region=us-east-2')


# === Test: open: Validate Arguments ===

def test_s3_filesystem_open_when_invalid_mode_then_raises_value_error() -> None:
    fs = S3Filesystem()

    with pytest.raises(ValueError):
        fs.open('s3://my-bucket/some-key?region=us-east-2', 'w')  # type: ignore[arg-type]


def test_s3_filesystem_open_when_negative_start_with_end_then_raises_value_error() -> None:
    fs = S3Filesystem()

    with pytest.raises(ValueError):
        fs.open('s3://my-bucket/some-key?region=us-east-2', 'rb', start=-5, end=10)


def test_s3_filesystem_open_when_nonnegative_start_without_end_then_raises_value_error() -> None:
    fs = S3Filesystem()

    with pytest.raises(ValueError):
        fs.open('s3://my-bucket/some-key?region=us-east-2', 'rb', start=0)


def test_s3_filesystem_open_when_start_greater_than_end_then_raises_value_error() -> None:
    fs = S3Filesystem()

    with pytest.raises(ValueError):
        fs.open('s3://my-bucket/some-key?region=us-east-2', 'rb', start=10, end=5)



# === Test: split_credentials_if_present ===

def test_when_split_credentials_if_present_and_url_has_credentials_then_returns_credentials_and_plain_url() -> None:
    secret_url = 's3://AKIA_TEST:abc%2B123@my-bucket/MG.crystalproj?region=us-east-2'

    (credentials, plain_url) = S3Filesystem.split_credentials_if_present(secret_url)

    assert credentials is not None
    assert credentials.access_key_id == 'AKIA_TEST'
    assert credentials.secret_access_key == 'abc+123'
    assert plain_url == 's3://my-bucket/MG.crystalproj?region=us-east-2'


def test_when_split_credentials_if_present_and_url_has_no_credentials_then_returns_none_credentials_and_plain_url() -> None:
    plain_url = 's3://my-bucket/MG.crystalproj?region=us-east-2'

    (credentials, result_url) = S3Filesystem.split_credentials_if_present(plain_url)

    assert credentials is None
    assert result_url == plain_url


def test_when_split_credentials_if_present_and_url_has_partial_credentials_then_raises_value_error() -> None:
    partial_secret_url = 's3://AKIA_TEST@my-bucket/MG.crystalproj?region=us-east-2'

    with pytest.raises(ValueError):
        S3Filesystem.split_credentials_if_present(partial_secret_url)


# === Test: parse_url ===

def test_when_parse_url_and_url_has_embedded_credentials_then_raises_value_error() -> None:
    secret_url = 's3://AKIA_TEST:secret@my-bucket/MG.crystalproj?region=us-east-2'

    with pytest.raises(ValueError):
        S3Filesystem.parse_url(secret_url, allow_credentials=False)
