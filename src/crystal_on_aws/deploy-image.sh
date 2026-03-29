#!/usr/bin/env bash
# Builds the Crystal container image and pushes it to ECR.
# Then refreshes any Lambda functions that were already using the
# same repository+tag that was just pushed.
#
# Prerequisites:
#   - Docker installed and running
#   - AWS CLI installed and configured (aws configure, or env vars)
#
# Usage:
#   src/crystal_on_aws/deploy-image.sh                     Push "latest" to private ECR
#   src/crystal_on_aws/deploy-image.sh --public --dev      Push "dev" to public ECR
#   src/crystal_on_aws/deploy-image.sh --public --release  Push "2.2.0" + "latest" to public ECR
#
# Options:
#   --public    Target the public ECR repository (public.ecr.aws)
#               instead of the private one. Requires --dev or --release.
#   --dev       Push with the "dev" tag. Requires --public.
#   --release   Push with the version tag (e.g. "2.2.0") and "latest".
#               Fails if the version tag already exists. Requires --public.
#
# Environment variables (optional overrides):
#   PRIVATE_ECR_REPO   Full private ECR repository URI (without tag)
#   PUBLIC_ECR_REPO    Full public ECR repository URI (without tag)
#   AWS_REGION         AWS region for private ECR and Lambda

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

USE_PUBLIC=false
USE_DEV=false
USE_RELEASE=false

for arg in "$@"; do
    case "${arg}" in
        --public)  USE_PUBLIC=true ;;
        --dev)     USE_DEV=true ;;
        --release) USE_RELEASE=true ;;
        *)
            echo "ERROR: Unknown option: ${arg}"
            echo "Usage: $0 [--public (--dev | --release)]"
            exit 1
            ;;
    esac
done

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

# Determine Crystal version from pyproject.toml
CRYSTAL_VERSION="$(grep -m1 '^version' "${REPO_ROOT}/pyproject.toml" | sed 's/.*"\(.*\)"/\1/')"

# Determine which repository and tag(s) to push
TAGS_TO_PUSH=()
if ${USE_PUBLIC}; then
    ECR_REPO="${PUBLIC_ECR_REPO}"
    if ${USE_DEV}; then
        TAGS_TO_PUSH=("dev")
    elif ${USE_RELEASE}; then
        TAGS_TO_PUSH=("${CRYSTAL_VERSION}" "latest")
    fi
else
    ECR_REPO="${PRIVATE_ECR_REPO}"
    TAGS_TO_PUSH=("latest")
fi

# Build the list of full image references (repo:tag)
FULL_IMAGES=()
for TAG in "${TAGS_TO_PUSH[@]}"; do
    FULL_IMAGES+=("${ECR_REPO}:${TAG}")
done

echo "Target repository: ${ECR_REPO}"
echo "Tags to push:      ${TAGS_TO_PUSH[*]}"
if ${USE_RELEASE}; then
    echo "Crystal version:   ${CRYSTAL_VERSION}"
fi

# ---------------------------------------------------------------------------
# Pre-flight: check that release tag does not already exist
# ---------------------------------------------------------------------------

if ${USE_RELEASE}; then
    echo ""
    echo "==> Checking that tag \"${CRYSTAL_VERSION}\" does not already exist..."
    EXISTING="$(
        aws ecr-public describe-images \
            --repository-name crystal-on-aws \
            --region us-east-1 \
            --query "imageDetails[?contains(imageTags, '${CRYSTAL_VERSION}')].imageTags" \
            --output text 2>/dev/null || true
    )"
    if [[ -n "${EXISTING}" ]]; then
        echo "ERROR: Tag \"${CRYSTAL_VERSION}\" already exists in public ECR."
        echo "Bump the version in pyproject.toml before running --release."
        exit 1
    fi
    echo "    Tag is available."
fi

# ---------------------------------------------------------------------------
# Authenticate with ECR (must happen before build, which pulls base images)
# ---------------------------------------------------------------------------

echo ""
if ${USE_PUBLIC}; then
    echo "==> Authenticating with public ECR..."
    aws ecr-public get-login-password --region us-east-1 \
        | docker login \
            --username AWS \
            --password-stdin \
            public.ecr.aws
else
    echo "==> Authenticating with private ECR..."
    aws ecr get-login-password --region "${AWS_REGION}" \
        | docker login \
            --username AWS \
            --password-stdin \
            "${ECR_REPO%%/*}"
fi

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

echo ""
echo "==> Building container image..."
# NOTE: --provenance=false prevents Docker BuildKit (used by Docker Desktop on
# Apple Silicon) from adding OCI attestation metadata that turns the image into
# a manifest list. Lambda requires a plain Docker v2 manifest, not a manifest
# list, and will reject the image with "media type is not supported" otherwise.
BUILD_TAG="${FULL_IMAGES[0]}"
docker build \
    --platform linux/amd64 \
    --provenance=false \
    -f src/crystal_on_aws/Dockerfile.lambda \
    -t "${BUILD_TAG}" \
    .

# Tag with any additional tags
for (( i=1; i<${#FULL_IMAGES[@]}; i++ )); do
    docker tag "${BUILD_TAG}" "${FULL_IMAGES[$i]}"
done

# ---------------------------------------------------------------------------
# Push to ECR
# ---------------------------------------------------------------------------

# For public ECR pushes we need the manifest digest so we can wait for CDN
# propagation before triggering the ImageCopierFunction (see below).
PUSHED_DIGEST=''  # sha256 of the first pushed image (public ECR only)

for IMG in "${FULL_IMAGES[@]}"; do
    echo "==> Pushing image: ${IMG}"
    if ${USE_PUBLIC}; then
        # Capture push output to a temp file while still streaming it to the user.
        PUSH_TMP="$(mktemp)"
        docker push "${IMG}" 2>&1 | tee "${PUSH_TMP}"
        if [[ -z "${PUSHED_DIGEST}" ]]; then
            PUSHED_DIGEST="$(grep -oE ': digest: sha256:[0-9a-f]+' "${PUSH_TMP}" | grep -oE 'sha256:[0-9a-f]+' | head -1)"
        fi
        rm -f "${PUSH_TMP}"
    else
        docker push "${IMG}"
    fi
done

# ---------------------------------------------------------------------------
# Refresh Lambda functions using the pushed image(s)
# ---------------------------------------------------------------------------

echo ""
echo "==> Finding Crystal Lambda functions (tagged crystal-lambda=true)..."
FUNCTION_ARNS="$(
    aws resourcegroupstaggingapi get-resources \
        --tag-filters Key=crystal-lambda,Values=true \
        --resource-type-filters lambda:function \
        --region "${AWS_REGION}" \
        --query 'ResourceTagMappingList[].ResourceARN' \
        --output text
)"

if [[ -z "${FUNCTION_ARNS}" ]]; then
    echo "    No tagged Lambda functions found in ${AWS_REGION}."
    echo ""
    echo "==> Done (image pushed, no Lambda functions to refresh)."
    exit 0
fi

# Build a set of full image references that were pushed, for matching.
# A Lambda function is refreshed only if its current image matches one
# of the pushed repo:tag combinations.
declare -A PUSHED_SET
for IMG in "${FULL_IMAGES[@]}"; do
    PUSHED_SET["${IMG}"]=1
done

# When pushing to public ECR, Lambda functions are updated via CF stack
# parameter (ImageRefreshToken). The IS_MIRROR detection below reads the
# CF stack's ImageUri parameter to find which stacks need updating.

UPDATED_COUNT=0
UPDATED_ARNS=()
declare -A STACKS_TO_UPDATE  # CF stack name -> 1

for ARN in ${FUNCTION_ARNS}; do
    FNAME="${ARN##*:function:}"

    # Get the function's current image URI (includes :tag or @digest)
    CURRENT_IMAGE="$(
        aws lambda get-function \
            --function-name "${FNAME}" \
            --region "${AWS_REGION}" \
            --query 'Code.ImageUri' \
            --output text 2>/dev/null || true
    )"

    # Check if the current image matches any of the pushed repo:tag combos
    SHOULD_UPDATE=false
    for IMG in "${FULL_IMAGES[@]}"; do
        if [[ "${CURRENT_IMAGE}" == "${IMG}" || "${CURRENT_IMAGE}" == "${IMG}@"* ]]; then
            SHOULD_UPDATE=true
            break
        fi
    done

    # Check if a CF stack manages this Lambda and its ImageUri parameter
    # matches one of the pushed public images.
    # NOTE: We check the stack parameter rather than the Lambda's current
    # Code.ImageUri, because the ImageCopierFunction now returns a digest URI
    # (e.g. ...crystal-on-aws@sha256:...) which doesn't match the mirror set.
    IS_MIRROR=false
    STACK_NAME_TMP=''
    STACK_IMAGE_URI=''
    if ! ${SHOULD_UPDATE} && ${USE_PUBLIC}; then
        STACK_NAME_TMP="$(
            aws lambda get-function \
                --function-name "${FNAME}" \
                --region "${AWS_REGION}" \
                --query 'Tags."aws:cloudformation:stack-name"' \
                --output text 2>/dev/null || true
        )"
        if [[ -n "${STACK_NAME_TMP}" && "${STACK_NAME_TMP}" != "None" ]]; then
            STACK_IMAGE_URI="$(
                aws cloudformation describe-stacks \
                    --stack-name "${STACK_NAME_TMP}" \
                    --region "${AWS_REGION}" \
                    --query 'Stacks[0].Parameters[?ParameterKey==`ImageUri`].ParameterValue' \
                    --output text 2>/dev/null || true
            )"
            for IMG in "${FULL_IMAGES[@]}"; do
                if [[ "${STACK_IMAGE_URI}" == "${IMG}" ]]; then
                    IS_MIRROR=true
                    break
                fi
            done
        fi
    fi

    if ${SHOULD_UPDATE}; then
        echo "==> Updating: ${FNAME} (was: ${CURRENT_IMAGE})"
        aws lambda update-function-code \
            --function-name "${FNAME}" \
            --image-uri "${CURRENT_IMAGE%%@*}" \
            --region "${AWS_REGION}" \
            --no-cli-pager > /dev/null
        UPDATED_ARNS+=("${ARN}")
        UPDATED_COUNT=$((UPDATED_COUNT + 1))
    elif ${IS_MIRROR}; then
        # Lambda uses a private mirror managed by CloudFormation.
        # STACK_NAME_TMP was already resolved during IS_MIRROR detection above.
        if [[ -n "${STACK_NAME_TMP}" && "${STACK_NAME_TMP}" != "None" ]]; then
            echo "==> Queuing CF stack update: ${STACK_NAME_TMP} (${FNAME} uses mirror ${STACK_IMAGE_URI})"
            STACKS_TO_UPDATE["${STACK_NAME_TMP}"]=1
            UPDATED_COUNT=$((UPDATED_COUNT + 1))
        else
            echo "    WARNING: ${FNAME} uses a private mirror image but has no CF stack tag. Skipping."
        fi
    else
        echo "    Skipping: ${FNAME} (uses ${CURRENT_IMAGE})"
    fi
done

if [[ ${UPDATED_COUNT} -eq 0 ]]; then
    echo ""
    echo "==> Done (image pushed, no Lambda functions matched)."
    exit 0
fi

# Wait for updates to complete, then print Function URLs.
for ARN in "${UPDATED_ARNS[@]}"; do
    FNAME="${ARN##*:function:}"
    echo ""
    echo "==> Waiting for ${FNAME}..."
    aws lambda wait function-updated \
        --function-name "${FNAME}" \
        --region "${AWS_REGION}"

    FUNCTION_URL="$(
        aws lambda get-function-url-config \
            --function-name "${FNAME}" \
            --region "${AWS_REGION}" \
            --query FunctionUrl \
            --output text 2>/dev/null || true
    )"
    if [[ -n "${FUNCTION_URL}" ]]; then
        echo "    ${FNAME}: ${FUNCTION_URL}"
    else
        echo "    ${FNAME}: updated (no Function URL)"
    fi
done

# ---------------------------------------------------------------------------
# Update CloudFormation stacks for private-mirror Lambda functions
# ---------------------------------------------------------------------------

for STACK_NAME in "${!STACKS_TO_UPDATE[@]}"; do
    echo ""
    REFRESH_TOKEN="$(date -u +%Y%m%dT%H%M%SZ)"
    echo "==> Updating CF stack: ${STACK_NAME} (ImageRefreshToken=${REFRESH_TOKEN})..."

    # Build --parameters list: UsePreviousValue for every parameter except
    # ImageRefreshToken, which gets the new value.  This avoids hardcoding
    # the full set of parameter names.
    PARAM_KEYS="$(
        aws cloudformation describe-stacks \
            --stack-name "${STACK_NAME}" \
            --region "${AWS_REGION}" \
            --query 'Stacks[0].Parameters[].ParameterKey' \
            --output text
    )"
    PARAMS=()
    for KEY in ${PARAM_KEYS}; do
        if [[ "${KEY}" == "ImageRefreshToken" ]]; then
            PARAMS+=("ParameterKey=ImageRefreshToken,ParameterValue=${REFRESH_TOKEN}")
        else
            PARAMS+=("ParameterKey=${KEY},UsePreviousValue=true")
        fi
    done

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
done

echo ""
echo "==> Done. Updated ${UPDATED_COUNT} function(s)."
