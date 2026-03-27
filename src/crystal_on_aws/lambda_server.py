"""
HTTP server entry point for Crystal's Lambda container with Lambda Web Adapter.

Lambda Web Adapter (LWA) proxies Lambda invocations to this HTTP server,
streaming responses back to the caller. This lifts the 6 MB buffered-response
size limit imposed by non-streaming Lambda Function URLs.

Usage:
    Set CRYSTAL_PROJECT_URL to the S3 URL of a .crystalproj:
        CRYSTAL_PROJECT_URL=s3://my-bucket/My Site.crystalproj

    See src/crystal_on_aws/Dockerfile.lambda for how this file is used in the container.

    Credentials come from the Lambda execution role (boto3 credential chain).
"""

import os
import threading

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

# Try to: Gather inputs. Open project.
_project_error = None  # type: Exception | None
try:
    # Gather inputs
    _port = int(os.environ.get('PORT', '8080'))
    try:
        _project_url = os.environ['CRYSTAL_PROJECT_URL']
    except KeyError:
        raise ValueError(
            'CRYSTAL_PROJECT_URL environment variable is not configured for the Crystal lambda function. '
            'Set it to an s3:// URL.'
        )
    
    # Open project
    from crystal.model import Project, ProjectMissingOrIncompleteError
    try:
        _project: Project | None = Project(_project_url, readonly=True)
    except ProjectMissingOrIncompleteError:
        # Default error message is understandable in this Lambda context
        raise
    except PermissionError as e:
        from crystal.filesystem import S3Filesystem
        if S3Filesystem.recognizes_path(_project_url):
            try:
                (bucket_name, key, _) = S3Filesystem.parse_url(_project_url)
            except ValueError:
                pass
            else:
                raise PermissionError(
                    f'{e} '
                    f'Ensure the project exists at "{_project_url}" and '
                    f'the Crystal lambda function has the "s3:GetObject" permission '
                    f'to resource "arn:aws:s3:::{bucket_name}/{key.removesuffix("/")}/*" '
                    f'and the "s3:ListBucket" permission '
                    f'to resource "arn:aws:s3:::{bucket_name}".'
                )
        
        # Fallback to original PermissionError message
        raise
except Exception as e:
    # Log traceback to lambda log
    import traceback
    traceback.print_exc()
    
    _project = None
    _project_error = e
else:
    _project_error = None

# Start serving
if _project is not None:
    from crystal.server import ProjectServer
    ProjectServer(
        _project,
        port=_port,
        host='',
    )
else:
    # Serve an Internal Server Error page for all requests
    from crystal.server.special_pages import internal_server_error_html
    from html import escape as _html_escape
    _error_page_bytes = internal_server_error_html(
        error_type_html=_html_escape(type(_project_error).__name__),
        error_message_html=_html_escape(str(_project_error)),
    ).encode('utf-8')

    from crystal import resources
    from crystal.server import _RequestHandler
    from http.server import HTTPServer, BaseHTTPRequestHandler
    class _ErrorHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            _RequestHandler._strip_trailing_empty_query(self)
            
            # Handle: Health check
            if self.path == '/_/crystal/health':
                _RequestHandler._serve_health_check_response(self)
                return

            # Handle: Crystal static resources
            if self.path.startswith('/_/crystal/resources/'):
                _RequestHandler._handle_static_resource(self)
                return

            self.send_response(500)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(_error_page_bytes)))
            self.end_headers()
            self.wfile.write(_error_page_bytes)

        do_POST = do_GET
        do_HEAD = do_GET
    _server = HTTPServer(('', _port), _ErrorHandler)
    _server.serve_forever()
