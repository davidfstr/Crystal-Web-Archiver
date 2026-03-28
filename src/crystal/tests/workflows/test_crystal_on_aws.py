"""
Tests for the "Crystal on AWS" deployment infrastructure.

These tests validate the CloudFormation template, Launch Stack buttons,
custom domain scripts, and the release procedure against live AWS resources.

Unlike test_lambda_function.py (which tests Crystal's Lambda serving logic
locally via Docker), these tests verify that the published deployment
artifacts work correctly in a real AWS environment.
"""

from unittest import skip


# === Tests: Launch Stack Buttons ===

@skip('not yet implemented')
def test_launch_stack_button_for_stable_version_on_crystal_on_aws_works() -> None:
    # Verify the "Stable" Launch Stack URL in doc/wiki/Crystal-on-AWS.md:
    # - The templateURL points to an S3-hosted CloudFormation template that exists
    # - The template can be used to create a stack (validates against CloudFormation)
    # - The stack creates successfully with a test ProjectS3Url
    # - The resulting Function URL serves the archived site
    pass


@skip('not yet implemented')
def test_launch_stack_button_for_dev_version_on_crystal_on_aws_works() -> None:
    # Verify the "Dev" Launch Stack URL in doc/wiki/Crystal-on-AWS.md:
    # - The templateURL points to an S3-hosted CloudFormation template that exists
    # - The template can be used to create a stack (validates against CloudFormation)
    # - The stack creates successfully with a test ProjectS3Url
    # - The resulting Function URL serves the archived site
    pass


# === Tests: Custom Domain Scripts ===

@skip('not yet implemented')
def test_custom_domain_add_works_in_aws_cloudshell() -> None:
    # Verify that custom-domain-add.sh works when run against a deployed stack:
    # - The script can be fetched via the curl URL documented in the wiki
    # - Given a deployed Crystal stack and a test domain,
    #   the script creates a CloudFront distribution and ACM certificate
    # - After completion, the custom domain serves the archived site
    pass


@skip('not yet implemented')
def test_custom_domain_remove_works_in_aws_cloudshell() -> None:
    # Verify that custom-domain-remove.sh works when run against a deployed stack:
    # - The script can be fetched via the curl URL documented in the wiki
    # - Given a stack with a custom domain previously added,
    #   the script removes the CloudFront distribution and ACM certificate
    # - After completion, the custom domain no longer resolves
    #   and the stack's CustomDomainHost parameter is cleared
    pass


# === Tests: Password Protection ===

@skip('not yet implemented')
def test_given_username_and_password_are_defined_then_crystal_configured_to_require_basic_auth_for_all_requests() -> None:
    # Verify that the CloudFormation template accepts Username and Password
    # parameters and correctly sets the CRYSTAL_SERVER_CREDENTIAL env var
    # on the Lambda function when both are provided
    pass


# === Tests: Release Procedure ===

@skip('not yet implemented')
def test_crystal_release_procedure_updates_stable_cloudformation_template_and_image_for_crystal_on_aws() -> None:
    # Verify that the release steps documented in doc/wiki/Releasing.md
    # correctly update the "Crystal on AWS" artifacts:
    # - deploy-image.sh --public --release builds and pushes the container image
    #   to public ECR with both a version tag and "latest"
    # - deploy-cf-template.sh --public --release updates the stable CloudFormation template in S3
    # - A new stack created with the stable template picks up the new image
    pass
