"""
AWS Lambda entrypoint for serving an archived Crystal project via HTTP.

Usage:
    Set the CRYSTAL_PROJECT_URL environment variable to the S3 URL of a
    .crystalproj, e.g.:
        s3://my-bucket/My Site.crystalproj

    Configure the Lambda function's handler to: lambda_handler.handler

    Grant the Lambda execution role s3:GetObject on the bucket.

    The project is opened read-only at cold-start and reused across
    warm invocations. POST endpoints that would mutate the project will
    fail naturally with a ProjectReadOnlyError.

Limitations:
    TODO: Lambda responses are capped at 6 MB (Function URL) or ~10 MB
          (API Gateway). Add support for Lambda response streaming to lift
          this restriction for large archived resources.
"""

import base64
import io
import os
import threading
from typing import Any, cast, TYPE_CHECKING

if TYPE_CHECKING:
    from socket import socket

# ------------------------------------------------------------------------------
# Cold start (runs once per Lambda container instance)

# Gather inputs
_project_url = os.environ['CRYSTAL_PROJECT_URL']

# Enable headless mode before anything tries to import wx or call fg_call_later.
from crystal.util.headless import set_headless_mode
set_headless_mode(True)

# Make this thread act as both the foreground thread (satisfying @fg_affinity
# and fg_call_and_wait) and a background thread (satisfying @bg_affinity via
# single-threaded mode).
from crystal.util.xthreading import set_foreground_thread, set_single_threaded_mode
set_foreground_thread(threading.current_thread())
set_single_threaded_mode(True)

# Install boto3 fake if CRYSTAL_FAKE_S3_ROOT is set (used by tests)
if os.environ.get('CRYSTAL_FAKE_S3_ROOT'):
    from crystal.tests.util.fake_boto3 import install as install_fake_boto3
    install_fake_boto3()

# Open project and configure persistent server
from crystal.model import Project
from crystal.server import _HttpServer, _RequestHandler
_project = Project(_project_url, readonly=True)
_server = _HttpServer.create_without_address(
    _project,
    verbosity='normal',
    stdout=None
)


# ------------------------------------------------------------------------------
# Lambda handler

def handler(event: dict, context: Any) -> dict:
    """
    AWS Lambda handler function.

    Translates the incoming Lambda event into a raw HTTP request, runs it
    through Crystal's _RequestHandler (the same logic used by ProjectServer),
    and returns the response as a Lambda response dict.
    """
    request_bytes = _build_http_request(event)
    mock_socket = _MockSocket(request_bytes)
    client_address = ('lambda', 0)

    # Constructing _RequestHandler calls setup() then handle() then finish(),
    # which drives the full GET/POST request/response cycle synchronously.
    _RequestHandler(
        cast('socket', mock_socket),
        client_address,
        _server,
    )

    return _parse_http_response(mock_socket.response_bytes)


# === Lambda event <-> raw HTTP translation ===

def _build_http_request(event: dict) -> bytes:
    """
    Convert a Lambda Function URL / API Gateway v2 payload format event into
    a raw HTTP/1.1 request byte string suitable for feeding to
    BaseHTTPRequestHandler via a BytesIO rfile.
    """
    http_ctx = event.get('requestContext', {}).get('http', {})
    method = http_ctx.get('method', 'GET')

    path = event.get('rawPath', '/')
    qs = event.get('rawQueryString', '')
    if qs:
        path = path + '?' + qs

    header_lines = [f'{method} {path} HTTP/1.1']
    for (key, value) in (event.get('headers') or {}).items():
        header_lines.append(f'{key}: {value}')
    header = '\r\n'.join(header_lines) + '\r\n\r\n'

    raw_body = event.get('body') or ''
    if isinstance(raw_body, str):
        body: bytes = raw_body.encode('utf-8')
    else:
        body = raw_body
    if event.get('isBase64Encoded'):
        body = base64.b64decode(body)

    return header.encode('latin-1') + body


def _parse_http_response(raw: bytes) -> dict:
    """
    Parse a raw HTTP response produced by BaseHTTPRequestHandler into a
    Lambda response dict (API Gateway v2 / Function URL format).
    """
    separator = b'\r\n\r\n'
    sep_idx = raw.find(separator)
    if sep_idx == -1:
        # Malformed response
        return {
            'statusCode': 502,
            'headers': {'content-type': 'text/plain'},
            'body': 'Malformed response from handler',
        }

    header = raw[:sep_idx].decode('latin-1')
    body = raw[sep_idx + len(separator):]

    header_lines = header.split('\r\n')
    status_line = header_lines[0]
    # Status line: "HTTP/1.x 200 OK"
    parts = status_line.split(' ', 2)
    status_code = int(parts[1]) if len(parts) >= 2 else 200

    headers: dict[str, str] = {}
    for line in header_lines[1:]:
        if ': ' in line:
            (key, _, value) = line.partition(': ')
            headers[key.lower()] = value

    content_type = headers.get('content-type', '')
    is_text = (
        content_type.startswith('text/')
        or 'json' in content_type
        or 'javascript' in content_type
        or 'xml' in content_type
        or 'svg' in content_type
    )
    if is_text:
        return {
            'statusCode': status_code,
            'headers': headers,
            'body': body.decode('utf-8', errors='replace'),
            'isBase64Encoded': False,
        }
    else:
        return {
            'statusCode': status_code,
            'headers': headers,
            'body': base64.b64encode(body).decode('ascii'),
            'isBase64Encoded': True,
        }


# === MockSocket ===

class _MockSocket:
    """
    Simulates a socket for BaseHTTPRequestHandler / StreamRequestHandler.

    StreamRequestHandler.setup() uses the socket to create rfile/wfile:
      - makefile('rb', ...)  -> readable stream (the HTTP request bytes)
      - _SocketWriter wraps the socket and calls sendall() for writes

    _RequestHandler.send_revision_body() calls sendfile() directly on the
    socket for efficient body transfer.
    """

    def __init__(self, request_bytes: bytes) -> None:
        self._rfile = io.BytesIO(request_bytes)
        self._wbuf = io.BytesIO()

    # Called by StreamRequestHandler.setup() to build rfile
    def makefile(self, mode: str, buffering: int = -1) -> io.BytesIO:
        return self._rfile

    # Called by _SocketWriter (the wfile) on every write
    def sendall(self, data: bytes) -> None:
        self._wbuf.write(data)

    # Called by _RequestHandler.send_revision_body() for efficient body copy
    def sendfile(
            self,
            file: Any,
            offset: int = 0,
            count: int | None = None,
            ) -> int:
        if offset > 0:
            file.seek(offset)
        data = file.read(count) if count is not None else file.read()
        self._wbuf.write(data)
        return len(data)

    # StreamRequestHandler.setup() calls settimeout() when _RequestHandler.timeout is set
    def settimeout(self, timeout: float | None) -> None:
        pass  # no-op; Lambda invocations have their own timeout

    # StreamRequestHandler.setup() calls setsockopt() when disable_nagle_algorithm is True
    def setsockopt(self, level: int, optname: int, value: int) -> None:
        pass  # no-op; not a real TCP socket

    def fileno(self) -> int:
        # _SocketWriter.fileno() is called when wfile.fileno() is needed.
        # Return -1 to signal that no real file descriptor exists.
        return -1

    @property
    def response_bytes(self) -> bytes:
        return self._wbuf.getvalue()


# ------------------------------------------------------------------------------
