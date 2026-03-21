"""
Top-level AWS Lambda entrypoint trampoline.

Configure the Lambda function's handler to: lambda_handler.handler

All logic lives in crystal.server.lambda_handler.
"""

from crystal.server.lambda_handler import handler  # noqa: F401
