"""
Tests for serving an archived Crystal project via the Lambda handler.
"""

from contextlib import contextmanager
from collections.abc import Iterator
from crystal.tests.util.asserts import assertIn, assertRegex
from crystal.tests.util.server import extracted_project
from crystal.tests.util import xtempfile
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import time
from unittest import skip, SkipTest
import urllib.error
import urllib.request


# === Constants ===

_DOCKER_IMAGE_NAME = 'crystal-lambda-test'

_LAMBDA_RUNTIME_API_PATH = '/2015-03-31/functions/function/invocations'

# How long to wait for the Lambda container to become ready
_CONTAINER_STARTUP_TIMEOUT = 60.0  # seconds; first build can be slow
_CONTAINER_READY_POLL_INTERVAL = 0.5  # seconds


# === Tests ===

def test_can_fetch_html_page_from_crystal_running_as_lambda_function() -> None:
    with _lambda_container_serving_xkcd_project() as container_url:
        # Fetch the xkcd home page via the Lambda runtime API,
        # simulating a request from an HTTPS Lambda Function URL.
        # The archive URL path format is /_/<scheme>/<host>/<path>
        response = _invoke_lambda(container_url, path='/_/https/xkcd.com/', headers={
            'host': 'example.execute-api.us-east-1.on.aws',
            'x-forwarded-proto': 'https',
        })

        assert response['statusCode'] == 200, (
            f'Expected 200, got {response["statusCode"]}'
        )

        body = response['body']

        # Verify the page has the expected title
        title_match = re.search(r'<title>([^<]*)</title>', body)
        assert title_match is not None, 'Page has no <title> tag'
        assertIn('xkcd', title_match.group(1))

        # Verify the page links to an xkcd comic image
        assertRegex(body, r'imgs\.xkcd\.com')

        # Verify links use https:// (not http://), since we sent
        # X-Forwarded-Proto: https. This covers the scenario in:
        # test_links_in_html_page_fetched_from_https_lambda_function_are_https_links
        assert 'http://example.execute-api' not in body, (
            'Page contains http:// links but should use https:// '
            'when X-Forwarded-Proto is https'
        )
        # Verify at least one https link is present in the rewritten content
        assertRegex(body, r'https://example\.execute-api')

        # Verify the home page references a known archived comic image,
        # then fetch it and verify it is a valid PNG.
        # This covers the scenario in:
        # test_can_fetch_image_from_crystal_running_as_lambda_function
        assertIn('imgs.xkcd.com/comics/air_gap', body)
        img_path = '/_/https/imgs.xkcd.com/comics/air_gap.png'
        img_response = _invoke_lambda(container_url, path=img_path, headers={
            'host': 'example.execute-api.us-east-1.on.aws',
            'x-forwarded-proto': 'https',
        })
        assert 'statusCode' in img_response, (
            f'Unexpected response format for image {img_path!r}: '
            f'{json.dumps(img_response, indent=2)}'
        )
        assert img_response['statusCode'] == 200, (
            f'Expected 200 for image, got {img_response["statusCode"]}'
        )
        assert img_response.get('isBase64Encoded') is True, (
            'Image response should be base64-encoded'
        )
        img_bytes = base64.b64decode(img_response['body'])
        # PNG files start with an 8-byte signature
        _PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
        assert img_bytes[:8] == _PNG_SIGNATURE, (
            f'Expected PNG signature, got {img_bytes[:8]!r}'
        )

        # Fetch a URL that is NOT in the archive and verify a 404 response.
        # This covers the scenario in:
        # test_can_fetch_404_error_page_from_crystal_running_as_lambda_function
        missing_path = '/_/https/example.com/does-not-exist'
        missing_response = _invoke_lambda(container_url, path=missing_path, headers={
            'host': 'example.execute-api.us-east-1.on.aws',
            'x-forwarded-proto': 'https',
        })
        assert 'statusCode' in missing_response, (
            f'Unexpected response format for 404 request {missing_path!r}: '
            f'{json.dumps(missing_response, indent=2)}'
        )
        assert missing_response['statusCode'] == 404, (
            f'Expected 404, got {missing_response["statusCode"]}'
        )


@skip('covered by: test_can_fetch_html_page_from_crystal_running_as_lambda_function')
async def test_links_in_html_page_fetched_from_https_lambda_function_are_https_links() -> None:
    pass


@skip('covered by: test_can_fetch_html_page_from_crystal_running_as_lambda_function')
def test_can_fetch_image_from_crystal_running_as_lambda_function() -> None:
    pass


@skip('covered by: test_can_fetch_html_page_from_crystal_running_as_lambda_function')
def test_can_fetch_404_error_page_from_crystal_running_as_lambda_function() -> None:
    pass


# === Utility: Docker Container ===

@contextmanager
def _lambda_container_serving_xkcd_project() -> Iterator[str]:
    """
    Build the Lambda Docker image, start a container serving the xkcd test
    project via fake S3, and yield the container's base URL.

    Cleans up the container on exit.
    """
    _ensure_docker_available()

    s3_bucket = 'test-bucket'
    s3_key_prefix = 'Archive/TestProject.crystalproj'
    s3_region = 'us-east-1'
    s3_url = f's3://{s3_bucket}/{s3_key_prefix}/?region={s3_region}'

    with extracted_project('testdata_xkcd.crystalproj.zip') as project_dirpath, \
            _fake_s3_root(
                project_dirpath,
                region=s3_region,
                bucket=s3_bucket,
                key_prefix=s3_key_prefix,
            ) as fake_s3_root:

        _build_lambda_image()

        host_port = _find_free_port()

        container_id = subprocess.check_output([
            'docker', 'run', '-d', '--rm',
            '--platform', 'linux/amd64',
            '-p', f'{host_port}:8080',
            '-v', f'{fake_s3_root}:/fake_s3:ro',
            '-e', f'CRYSTAL_PROJECT_URL={s3_url}',
            '-e', 'CRYSTAL_FAKE_S3_ROOT=/fake_s3',
            '-e', 'AWS_ACCESS_KEY_ID=fake-access-key',
            '-e', 'AWS_SECRET_ACCESS_KEY=fake-secret-key',
            '-e', f'AWS_DEFAULT_REGION={s3_region}',
            _DOCKER_IMAGE_NAME,
        ], text=True).strip()

        container_url = f'http://localhost:{host_port}'
        try:
            _wait_for_container_ready(container_url, container_id)
            yield container_url
        finally:
            subprocess.run(
                ['docker', 'kill', container_id],
                capture_output=True,
            )


def _build_lambda_image() -> None:
    """Build the Lambda Docker image from Dockerfile.lambda."""
    project_root = _get_project_root()
    subprocess.check_call(
        [
            'docker', 'build',
            '--platform', 'linux/amd64',
            '--provenance=false',
            '-f', 'Dockerfile.lambda',
            '-t', _DOCKER_IMAGE_NAME,
            '.',
        ],
        cwd=project_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_container_ready(container_url: str, container_id: str) -> None:
    """
    Poll the Lambda runtime API until it responds, or raise if the
    container exits or the timeout is reached.
    """
    deadline = time.monotonic() + _CONTAINER_STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        # Check that the container is still running
        result = subprocess.run(
            ['docker', 'inspect', '-f', '{{.State.Running}}', container_id],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or result.stdout.strip() != 'true':
            logs = subprocess.run(
                ['docker', 'logs', container_id],
                capture_output=True, text=True,
            )
            raise AssertionError(
                f'Lambda container exited unexpectedly.\n'
                f'stdout: {logs.stdout[-2000:]}\n'
                f'stderr: {logs.stderr[-2000:]}'
            )

        # Try to connect to the runtime API
        try:
            _invoke_lambda(container_url, path='/')
            return  # container is ready
        except (ConnectionRefusedError, urllib.error.URLError, OSError):
            time.sleep(_CONTAINER_READY_POLL_INTERVAL)

    logs = subprocess.run(
        ['docker', 'logs', container_id],
        capture_output=True, text=True,
    )
    raise AssertionError(
        f'Lambda container did not become ready within {_CONTAINER_STARTUP_TIMEOUT}s\n'
        f'stdout: {logs.stdout[-2000:]}\n'
        f'stderr: {logs.stderr[-2000:]}'
    )


# === Utility: Lambda Invocation ===

def _invoke_lambda(container_url: str, *, path: str, headers: dict[str, str] | None = None) -> dict:
    """
    Send a simulated HTTP GET request to the Lambda runtime API
    and return the parsed response dict.
    """
    if headers is None:
        headers = {}

    event = {
        'requestContext': {
            'http': {
                'method': 'GET',
            },
        },
        'rawPath': path,
        'rawQueryString': '',
        'headers': headers,
    }

    request = urllib.request.Request(
        f'{container_url}{_LAMBDA_RUNTIME_API_PATH}',
        data=json.dumps(event).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=30.0) as resp:
        return json.loads(resp.read().decode('utf-8'))


# === Utility: Fake S3 ===

@contextmanager
def _fake_s3_root(
        project_dirpath: str,
        *, region: str,
        bucket: str,
        key_prefix: str,
        ) -> Iterator[str]:
    """
    Create a fake S3 root directory that maps region/bucket/key_prefix
    to the given project_dirpath by copying the project data.

    Returns the fake S3 root path.
    """
    with xtempfile.TemporaryDirectory() as tmpdir:
        fake_s3_root = os.path.join(tmpdir, 'fake_s3_root')

        dest_path = os.path.normpath(os.path.join(fake_s3_root, region, bucket, key_prefix))
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        shutil.copytree(project_dirpath, dest_path)

        yield fake_s3_root


# === Utility: General ===

def _ensure_docker_available() -> None:
    """Skip the test if Docker is not available or cannot run Linux containers."""
    try:
        result = subprocess.run(
            ['docker', 'info'],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        raise SkipTest('Docker is not installed')
    if result.returncode != 0:
        raise SkipTest('Docker daemon is not running')

    # On Windows GitHub Actions runners, Docker only supports Windows
    # containers. Building a Linux-based image would fail with exit code 125.
    info = result.stdout
    if 'OSType: windows' in info:
        raise SkipTest('Docker is in Windows containers mode; Linux containers required')


def _find_free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _get_project_root() -> str:
    """Return the root directory of the Crystal project (where Dockerfile.lambda lives)."""
    # Walk up from this file until we find Dockerfile.lambda
    d = os.path.dirname(__file__)
    for _ in range(10):
        if os.path.exists(os.path.join(d, 'Dockerfile.lambda')):
            return d
        d = os.path.dirname(d)
    raise RuntimeError('Cannot find project root (Dockerfile.lambda)')
