#!/usr/bin/env bash
# Builds the Crystal Lambda container image and deploys it to AWS Lambda.
#
# Prerequisites:
#   - Docker installed and running
#   - AWS CLI installed and configured (aws configure, or env vars)
#   - An ECR repository already created (see "One-time setup" below)
#   - A Lambda function already created pointing at the ECR image
#     (see "One-time setup" below)
#
# Usage:
#   ./deploy-lambda.sh
#
# Configuration (edit variables below or export them before running):
#   LAMBDA_FUNCTION_NAME   Name of the Lambda function to update
#   ECR_REPO               Full ECR repository URI (without tag)
#   AWS_REGION             AWS region for ECR and Lambda
#   IMAGE_TAG              Docker image tag (default: "latest")
#
# One-time setup (run once before first deploy):
#
#   1. Create an ECR repository:
#        aws ecr create-repository --repository-name crystal-lambda
#
#   2. Create a Lambda execution role:
#
#      a. Create the role with a trust policy that allows Lambda to assume it:
#           aws iam create-role \
#             --role-name crystal-lambda-role \
#             --assume-role-policy-document '{
#               "Version": "2012-10-17",
#               "Statement": [{
#                 "Effect": "Allow",
#                 "Principal": { "Service": "lambda.amazonaws.com" },
#                 "Action": "sts:AssumeRole"
#               }]
#             }'
#
#      b. Attach AWS's managed policy for basic Lambda logging to CloudWatch:
#           aws iam attach-role-policy \
#             --role-name crystal-lambda-role \
#             --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
#
#      c. Grant S3 read access to your project bucket (replace my-bucket):
#           aws iam put-role-policy \
#             --role-name crystal-lambda-role \
#             --policy-name crystal-s3-read \
#             --policy-document '{
#               "Version": "2012-10-17",
#               "Statement": [{
#                 "Effect": "Allow",
#                 "Action": ["s3:GetObject", "s3:HeadObject"],
#                 "Resource": "arn:aws:s3:::my-bucket/*"
#               }]
#             }'
#
#      d. Get the role ARN for use in the next step:
#           aws iam get-role \
#             --role-name crystal-lambda-role \
#             --query Role.Arn --output text
#           # → arn:aws:iam::<ACCOUNT_ID>:role/crystal-lambda-role
#
#   3. Build and push the initial image to ECR (Lambda requires the image to
#      exist before the function can be created):
#        ./deploy-lambda.sh
#      NOTE: This will fail at the final "Updating Lambda function" step
#            because the function does not exist yet — that is expected.
#            The image will be in ECR after this step regardless.
#
#   4. Create the Lambda function (container image type):
#        ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
#        AWS_REGION="$(aws configure get region 2>/dev/null || true)"
#        aws lambda create-function \
#          --function-name crystal-lambda \
#          --package-type Image \
#          --code ImageUri=${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/crystal-lambda:latest \
#          --role arn:aws:iam::${ACCOUNT_ID}:role/crystal-lambda-role \
#          --memory-size 512 \
#          --timeout 30 \
#          --environment 'Variables={CRYSTAL_PROJECT_URL=s3://my-bucket/My Site.crystalproj}'
#
#   5. Expose the function via a Function URL (simplest; no extra charge):
#        aws lambda add-permission \
#          --function-name crystal-lambda \
#          --statement-id FunctionURLAllowPublicAccess \
#          --action lambda:InvokeFunctionUrl \
#          --principal '*' \
#          --function-url-auth-type NONE
#        aws lambda create-function-url-config \
#          --function-name crystal-lambda \
#          --auth-type NONE
#      Or expose via API Gateway if you prefer.
#
# Subsequent deploys:
#   Just re-run this script.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LAMBDA_FUNCTION_NAME="${LAMBDA_FUNCTION_NAME:-crystal-lambda}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

# Resolve AWS region: explicit env var > AWS profile/config > error.
# `aws configure get region` respects AWS_PROFILE and ~/.aws/config.
if [[ -z "${AWS_REGION:-}" ]]; then
    AWS_REGION="$(aws configure get region 2>/dev/null || true)"
fi
if [[ -z "${AWS_REGION:-}" ]]; then
    echo "ERROR: Could not determine AWS region."
    echo "Set AWS_REGION, or configure a region with: aws configure [--profile <name>]"
    exit 1
fi

# Derive ECR repository URI from the AWS account ID if not set explicitly.
if [[ -z "${ECR_REPO:-}" ]]; then
    ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
    ECR_REPO="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/crystal-lambda"
fi

FULL_IMAGE="${ECR_REPO}:${IMAGE_TAG}"

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

echo "==> Building container image..."
# NOTE: --provenance=false prevents Docker BuildKit (used by Docker Desktop on
# Apple Silicon) from adding OCI attestation metadata that turns the image into
# a manifest list. Lambda requires a plain Docker v2 manifest, not a manifest
# list, and will reject the image with "media type is not supported" otherwise.
docker build \
    --platform linux/amd64 \
    --provenance=false \
    -f Dockerfile.lambda \
    -t "${FULL_IMAGE}" \
    .

# ---------------------------------------------------------------------------
# Push to ECR
# ---------------------------------------------------------------------------

echo "==> Authenticating with ECR..."
aws ecr get-login-password --region "${AWS_REGION}" \
    | docker login \
        --username AWS \
        --password-stdin \
        "${ECR_REPO%%/*}"

echo "==> Pushing image to ECR: ${FULL_IMAGE}"
docker push "${FULL_IMAGE}"

# ---------------------------------------------------------------------------
# Deploy to Lambda
# ---------------------------------------------------------------------------

echo "==> Updating Lambda function: ${LAMBDA_FUNCTION_NAME}"
aws lambda update-function-code \
    --function-name "${LAMBDA_FUNCTION_NAME}" \
    --image-uri "${FULL_IMAGE}" \
    --region "${AWS_REGION}" \
    --no-cli-pager > /dev/null

echo ""
echo "==> Waiting for update to complete..."
aws lambda wait function-updated \
    --function-name "${LAMBDA_FUNCTION_NAME}" \
    --region "${AWS_REGION}"

# Print the Function URL if one exists.
FUNCTION_URL="$(
    aws lambda get-function-url-config \
        --function-name "${LAMBDA_FUNCTION_NAME}" \
        --region "${AWS_REGION}" \
        --query FunctionUrl \
        --output text 2>/dev/null || true
)"
if [[ -n "${FUNCTION_URL}" ]]; then
    echo ""
    echo "==> Deployed. Function URL: ${FUNCTION_URL}"
else
    echo "==> Deployed."
fi
