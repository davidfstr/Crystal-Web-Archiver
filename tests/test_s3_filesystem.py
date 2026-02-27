from crystal.filesystem import S3Filesystem
import pytest


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
