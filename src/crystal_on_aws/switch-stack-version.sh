#!/usr/bin/env bash
# Switches a Crystal CloudFormation stack to use a different image source.
#
# Prerequisites:
#   - AWS CLI installed and configured (aws configure, or env vars)
#
# Usage:
#   src/crystal_on_aws/switch-stack-version.sh <stack-name>                     Switch to private ECR (locally-built)
#   src/crystal_on_aws/switch-stack-version.sh <stack-name> --public --dev      Switch to public ECR dev tag
#   src/crystal_on_aws/switch-stack-version.sh <stack-name> --public --release  Switch to public ECR latest tag
#
# Options:
#   --public    Target the public ECR repository (public.ecr.aws)
#               instead of the private one. Requires --dev or --release.
#   --dev       Use the "dev" tag. Requires --public.
#   --release   Use the "latest" tag. Requires --public.
#
# Environment variables (optional overrides):
#   PRIVATE_ECR_REPO   Full private ECR repository URI (without tag)
#   PUBLIC_ECR_REPO    Full public ECR repository URI (without tag)
#   AWS_REGION         AWS region for CloudFormation

set -euo pipefail

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

STACK_NAME=''
USE_PUBLIC=false
USE_DEV=false
USE_RELEASE=false

for arg in "$@"; do
    case "${arg}" in
        --public)  USE_PUBLIC=true ;;
        --dev)     USE_DEV=true ;;
        --release) USE_RELEASE=true ;;
        -*)
            echo "ERROR: Unknown option: ${arg}"
            echo "Usage: $0 <stack-name> [--public (--dev | --release)]"
            exit 1
            ;;
        *)
            if [[ -z "${STACK_NAME}" ]]; then
                STACK_NAME="${arg}"
            else
                echo "ERROR: Unexpected argument: ${arg}"
                echo "Usage: $0 <stack-name> [--public (--dev | --release)]"
                exit 1
            fi
            ;;
    esac
done

if [[ -z "${STACK_NAME}" ]]; then
    echo "ERROR: Missing required argument: <stack-name>"
    echo "Usage: $0 <stack-name> [--public (--dev | --release)]"
    exit 1
fi

# Validate option combinations
if ${USE_DEV} && ${USE_RELEASE}; then
    echo "ERROR: --dev and --release are mutually exclusive."
    exit 1
fi
if ${USE_PUBLIC} && ! ${USE_DEV} && ! ${USE_RELEASE}; then
    echo "ERROR: --public requires --dev or --release."
    exit 1
fi
if (${USE_DEV} || ${USE_RELEASE}) && ! ${USE_PUBLIC}; then
    echo "ERROR: --dev and --release require --public."
    exit 1
fi

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Resolve AWS region: explicit env var > AWS profile/config > error.
if [[ -z "${AWS_REGION:-}" ]]; then
    AWS_REGION="$(aws configure get region 2>/dev/null || true)"
fi
if [[ -z "${AWS_REGION:-}" ]]; then
    echo "ERROR: Could not determine AWS region."
    echo "Set AWS_REGION, or configure a region with: aws configure [--profile <name>]"
    exit 1
fi

# Private ECR repository (default target)
if [[ -z "${PRIVATE_ECR_REPO:-}" ]]; then
    ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
    PRIVATE_ECR_REPO="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/crystal-on-aws"
fi

# Public ECR repository
PUBLIC_ECR_REPO="${PUBLIC_ECR_REPO:-public.ecr.aws/g0h6z3c9/crystal-on-aws}"

# Determine the new ImageUri
if ${USE_PUBLIC}; then
    if ${USE_DEV}; then
        NEW_IMAGE_URI="${PUBLIC_ECR_REPO}:dev"
    else
        NEW_IMAGE_URI="${PUBLIC_ECR_REPO}:latest"
    fi
else
    NEW_IMAGE_URI="${PRIVATE_ECR_REPO}:latest"
fi

REFRESH_TOKEN="$(date -u +%Y%m%dT%H%M%SZ)"

echo "Stack:              ${STACK_NAME}"
echo "New ImageUri:       ${NEW_IMAGE_URI}"
echo "ImageRefreshToken:  ${REFRESH_TOKEN}"

# ---------------------------------------------------------------------------
# Update the CloudFormation stack
# ---------------------------------------------------------------------------

echo ""
echo "==> Building parameter list for stack: ${STACK_NAME}..."

# Build --parameters list: new values for ImageUri and ImageRefreshToken,
# UsePreviousValue for every other parameter.
PARAM_KEYS="$(
    aws cloudformation describe-stacks \
        --stack-name "${STACK_NAME}" \
        --region "${AWS_REGION}" \
        --query 'Stacks[0].Parameters[].ParameterKey' \
        --output text
)"

PARAMS=()
for KEY in ${PARAM_KEYS}; do
    case "${KEY}" in
        ImageUri)
            PARAMS+=("ParameterKey=ImageUri,ParameterValue=${NEW_IMAGE_URI}")
            ;;
        ImageRefreshToken)
            PARAMS+=("ParameterKey=ImageRefreshToken,ParameterValue=${REFRESH_TOKEN}")
            ;;
        *)
            PARAMS+=("ParameterKey=${KEY},UsePreviousValue=true")
            ;;
    esac
done

echo "==> Updating stack: ${STACK_NAME}..."
aws cloudformation update-stack \
    --stack-name "${STACK_NAME}" \
    --use-previous-template \
    --parameters "${PARAMS[@]}" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "${AWS_REGION}" \
    --no-cli-pager > /dev/null

echo "==> Waiting for stack update: ${STACK_NAME}..."
aws cloudformation wait stack-update-complete \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}"
echo "    ${STACK_NAME}: update complete."

# ---------------------------------------------------------------------------
# Print the site URLs from stack Outputs
# ---------------------------------------------------------------------------
echo ""

SITE_URL1="$(
    aws cloudformation describe-stacks \
        --stack-name "${STACK_NAME}" \
        --region "${AWS_REGION}" \
        --query 'Stacks[0].Outputs[?OutputKey==`SiteUrl1`].OutputValue' \
        --output text 2>/dev/null || true
)"
SITE_URL2="$(
    aws cloudformation describe-stacks \
        --stack-name "${STACK_NAME}" \
        --region "${AWS_REGION}" \
        --query 'Stacks[0].Outputs[?OutputKey==`SiteUrl2`].OutputValue' \
        --output text 2>/dev/null || true
)"

if [[ -n "${SITE_URL1}" && "${SITE_URL1}" != "None" ]]; then
    echo "    - SiteUrl1: ${SITE_URL1}"
fi
if [[ -n "${SITE_URL2}" && "${SITE_URL2}" != "None" && "${SITE_URL2}" != "" ]]; then
    echo "    - SiteUrl2: ${SITE_URL2}"
fi

echo ""
echo "==> Done."
