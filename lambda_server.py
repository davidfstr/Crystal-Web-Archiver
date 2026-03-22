"""
HTTP server entry point for Crystal's Lambda container with Lambda Web Adapter.

Lambda Web Adapter (LWA) proxies Lambda invocations to this HTTP server,
streaming responses back to the caller. This lifts the 6 MB buffered-response
size limit imposed by non-streaming Lambda Function URLs.

Usage:
    Set CRYSTAL_PROJECT_URL to the S3 URL of a .crystalproj:
        CRYSTAL_PROJECT_URL=s3://my-bucket/My Site.crystalproj

    See Dockerfile.lambda for how this file is used in the container.

    Credentials come from the Lambda execution role (boto3 credential chain).
"""

import os
import threading

# Gather inputs
_project_url = os.environ['CRYSTAL_PROJECT_URL']
_PORT = int(os.environ.get('PORT', '8080'))

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

# Open project
from crystal.model import Project
_project = Project(_project_url, readonly=True)

# Start serving
from crystal.server import ProjectServer
ProjectServer(
    _project,
    port=_PORT,
    host='',
)
