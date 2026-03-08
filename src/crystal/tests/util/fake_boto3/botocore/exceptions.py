"""
Fake botocore.exceptions module for testing S3Filesystem without real AWS access.
"""


class BotoCoreError(Exception):
    pass


class ClientError(BotoCoreError):
    def __init__(self, error_response, operation_name):
        self.response = error_response
        self.operation_name = operation_name
        msg = (
            f'An error occurred ({error_response["Error"]["Code"]}) '
            f'when calling the {operation_name} operation: '
            f'{error_response["Error"].get("Message", "Unknown")}'
        )
        super().__init__(msg)


class NoCredentialsError(BotoCoreError):
    def __init__(self):
        super().__init__('Unable to locate credentials')
