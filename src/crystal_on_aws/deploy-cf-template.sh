#!/usr/bin/env bash
# Uploads crystal.cloudformation.yaml to the public S3 bucket so that
# "Launch Stack" buttons in the wiki can reference it.
#
# Prerequisites:
#   - AWS CLI installed and configured (aws configure, or env vars)
#
# Usage:
#   src/crystal_on_aws/deploy-cf-template.sh --public --dev      Upload to dev/
#   src/crystal_on_aws/deploy-cf-template.sh --public --release  Upload to stable/
#
# Options:
#   --public    Required (there is no private target for CF templates).
#   --dev       Upload to the dev/ prefix.
#   --release   Upload to the stable/ prefix.
#
# Environment variables (optional overrides):
#   CF_TEMPLATE_BUCKET  S3 bucket for public CF templates (default: crystal-on-aws)
#   CF_TEMPLATE_REGION  Region of the S3 bucket (default: us-east-2)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

TEMPLATE_FILE="${SCRIPT_DIR}/crystal.cloudformation.yaml"

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
            echo "Usage: $0 --public (--dev | --release)"
            exit 1
            ;;
    esac
done

# Validate option combinations
if ${USE_DEV} && ${USE_RELEASE}; then
    echo "ERROR: --dev and --release are mutually exclusive."
    exit 1
fi
if ! ${USE_PUBLIC}; then
    echo "ERROR: --public is required (there is no private target for CF templates)."
    echo "Usage: $0 --public (--dev | --release)"
    exit 1
fi
if ! ${USE_DEV} && ! ${USE_RELEASE}; then
    echo "ERROR: --public requires --dev or --release."
    echo "Usage: $0 --public (--dev | --release)"
    exit 1
fi

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CF_TEMPLATE_BUCKET="${CF_TEMPLATE_BUCKET:-crystal-on-aws}"
CF_TEMPLATE_REGION="${CF_TEMPLATE_REGION:-us-east-2}"

if ${USE_DEV}; then
    S3_PREFIX="dev"
elif ${USE_RELEASE}; then
    S3_PREFIX="stable"
fi

S3_DEST="s3://${CF_TEMPLATE_BUCKET}/${S3_PREFIX}/crystal.cloudformation.yaml"
PUBLIC_URL="https://${CF_TEMPLATE_BUCKET}.s3.${CF_TEMPLATE_REGION}.amazonaws.com/${S3_PREFIX}/crystal.cloudformation.yaml"

# ---------------------------------------------------------------------------
# Verify template exists
# ---------------------------------------------------------------------------

if [[ ! -f "${TEMPLATE_FILE}" ]]; then
    echo "ERROR: Template not found: ${TEMPLATE_FILE}"
    exit 1
fi

# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

echo "==> Uploading CF template to ${S3_DEST}"
aws s3 cp "${TEMPLATE_FILE}" "${S3_DEST}" \
    --region "${CF_TEMPLATE_REGION}"

echo ""
echo "==> Done. Template available at:"
echo "    ${PUBLIC_URL}"
