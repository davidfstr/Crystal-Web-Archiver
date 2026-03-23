#!/usr/bin/env bash
# Removes a custom domain from a Crystal on AWS CloudFormation stack.
#
# This script reverses what custom-domain-add.sh created:
#   1. Disables and deletes the CloudFront distribution
#   2. Deletes the ACM certificate
#   3. Clears CustomDomainHost on the CloudFormation stack
#   4. Reminds the user to remove DNS records at their registrar
#
# Resources are found by the crystal-stack=<stack-name> tag that
# custom-domain-add.sh applies.
#
# Prerequisites:
#   - A deployed Crystal CloudFormation stack with a custom domain
#
# Run from AWS CloudShell (no local install needed):
#   Open CloudShell:
#     https://console.aws.amazon.com/cloudshell/
#   Select the region matching your Crystal stack from the page's top-right corner:
#     e.g. "United States (Ohio): us-east-2"
#   Then paste:
#     curl -sL https://raw.githubusercontent.com/davidfstr/Crystal-Web-Archiver/main/src/crystal_on_aws/custom-domain-remove.sh | bash -s <stack-name>
#   Example:
#     curl -sL https://raw.githubusercontent.com/davidfstr/Crystal-Web-Archiver/main/src/crystal_on_aws/custom-domain-remove.sh | bash -s crystal-xkcd
#
# Run locally (requires AWS CLI and jq):
#   src/crystal_on_aws/custom-domain-remove.sh <stack-name>

set -euo pipefail

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <stack-name>"
    echo "Example: $0 crystal-xkcd"
    exit 1
fi

STACK_NAME="$1"

# ---------------------------------------------------------------------------
# Check prerequisites
# ---------------------------------------------------------------------------

if ! command -v jq &>/dev/null; then
    echo "ERROR: jq is required but not installed."
    echo "Install it with: brew install jq"
    exit 1
fi

# Resolve AWS region
if [[ -z "${AWS_REGION:-}" ]]; then
    AWS_REGION="$(aws configure get region 2>/dev/null || true)"
fi
if [[ -z "${AWS_REGION:-}" ]]; then
    echo "ERROR: Could not determine AWS region."
    echo "Set AWS_REGION, or configure a region with: aws configure [--profile <name>]"
    exit 1
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

# ---------------------------------------------------------------------------
# Find tagged resources
# ---------------------------------------------------------------------------

echo "==> Finding resources for stack: ${STACK_NAME}..."

# Find CloudFront distribution tagged with crystal-stack=<stack-name>
CF_DIST_ID=""
# CloudFront is a global service; its tags live in us-east-1
CF_DIST_ARNS="$(aws resourcegroupstaggingapi get-resources \
    --tag-filters "Key=crystal-stack,Values=${STACK_NAME}" \
    --resource-type-filters cloudfront:distribution \
    --region us-east-1 \
    --query 'ResourceTagMappingList[].ResourceARN' \
    --output text 2>/dev/null || true)"
if [[ -n "${CF_DIST_ARNS}" ]]; then
    # ARN format: arn:aws:cloudfront::<account>:distribution/<id>
    CF_DIST_ID="$(echo "${CF_DIST_ARNS}" | head -1 | sed 's|.*/||')"
    echo "    CloudFront distribution: ${CF_DIST_ID}"
else
    echo "    No tagged CloudFront distribution found."
fi

# Find ACM certificate tagged with crystal-stack=<stack-name>
CERT_ARN=""
CERT_ARNS="$(aws resourcegroupstaggingapi get-resources \
    --tag-filters "Key=crystal-stack,Values=${STACK_NAME}" \
    --resource-type-filters acm:certificate \
    --region us-east-1 \
    --query 'ResourceTagMappingList[].ResourceARN' \
    --output text 2>/dev/null || true)"
if [[ -n "${CERT_ARNS}" ]]; then
    CERT_ARN="$(echo "${CERT_ARNS}" | head -1)"
    echo "    ACM certificate: ${CERT_ARN}"
else
    echo "    No tagged ACM certificate found."
fi

# Get the custom domain from the stack (for the DNS reminder at the end)
CUSTOM_DOMAIN=""
STACK_JSON="$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --output json 2>/dev/null || true)"
if [[ -n "${STACK_JSON}" ]]; then
    CUSTOM_DOMAIN="$(echo "${STACK_JSON}" \
        | jq -r '.Stacks[0].Parameters[] | select(.ParameterKey=="CustomDomainHost") | .ParameterValue')"
fi

# Collect DNS record details before we delete anything
CF_DOMAIN=""
if [[ -n "${CF_DIST_ID}" ]]; then
    CF_DOMAIN="$(aws cloudfront get-distribution \
        --id "${CF_DIST_ID}" \
        --query 'Distribution.DomainName' \
        --output text 2>/dev/null || true)"
fi

VALIDATION_HOST=""
VALIDATION_VALUE=""
if [[ -n "${CERT_ARN}" ]]; then
    CERT_DETAIL="$(aws acm describe-certificate \
        --certificate-arn "${CERT_ARN}" \
        --region us-east-1 \
        --output json 2>/dev/null || true)"
    if [[ -n "${CERT_DETAIL}" ]]; then
        VALIDATION_NAME="$(echo "${CERT_DETAIL}" \
            | jq -r '.Certificate.DomainValidationOptions[0].ResourceRecord.Name')"
        VALIDATION_VALUE="$(echo "${CERT_DETAIL}" \
            | jq -r '.Certificate.DomainValidationOptions[0].ResourceRecord.Value')"
        # Strip the base domain suffix for registrar display
        if [[ -n "${CUSTOM_DOMAIN}" ]]; then
            BASE_DOMAIN="$(echo "${CUSTOM_DOMAIN}" | sed 's/^[^.]*\.//')"
            VALIDATION_HOST="$(echo "${VALIDATION_NAME}" | sed "s/\.${BASE_DOMAIN}\.$//")"
            CUSTOM_HOST="$(echo "${CUSTOM_DOMAIN}" | sed "s/\.${BASE_DOMAIN}$//")"
        fi
    fi
fi

if [[ -z "${CF_DIST_ID}" && -z "${CERT_ARN}" && -z "${CUSTOM_DOMAIN}" ]]; then
    echo ""
    echo "Nothing to remove."
    exit 0
fi

# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------

echo ""
echo "This will:"
if [[ -n "${CF_DIST_ID}" ]]; then
    echo "  - Delete CloudFront distribution ${CF_DIST_ID}"
fi
if [[ -n "${CERT_ARN}" ]]; then
    echo "  - Delete ACM certificate for ${CUSTOM_DOMAIN:-unknown domain}"
fi
if [[ -n "${CUSTOM_DOMAIN}" ]]; then
    echo "  - Clear CustomDomainHost on stack ${STACK_NAME}"
fi
echo ""
read -rp "Proceed? (y/N) " CONFIRM < /dev/tty
if [[ "${CONFIRM}" != "y" && "${CONFIRM}" != "Y" ]]; then
    echo "Cancelled."
    exit 0
fi

# ---------------------------------------------------------------------------
# Step 1: Remove custom domain from CloudFront, then disable it
# ---------------------------------------------------------------------------

if [[ -n "${CF_DIST_ID}" ]]; then
    echo ""
    echo "==> Removing custom domain from CloudFront distribution..."

    # Get current config and ETag
    DIST_CONFIG_RESULT="$(aws cloudfront get-distribution-config --id "${CF_DIST_ID}")"
    ETAG="$(echo "${DIST_CONFIG_RESULT}" | jq -r '.ETag')"
    CURRENT_CONFIG="$(echo "${DIST_CONFIG_RESULT}" | jq '.DistributionConfig')"

    # Remove aliases, revert to default certificate, and disable
    UPDATED_CONFIG="$(echo "${CURRENT_CONFIG}" | jq '
        .Aliases = {"Quantity": 0, "Items": []} |
        .ViewerCertificate = {"CloudFrontDefaultCertificate": true, "MinimumProtocolVersion": "TLSv1"} |
        .Enabled = false')"

    aws cloudfront update-distribution \
        --id "${CF_DIST_ID}" \
        --distribution-config "${UPDATED_CONFIG}" \
        --if-match "${ETAG}" \
        --no-cli-pager > /dev/null

    echo "    Distribution disabled. Waiting for deployment (this may take a few minutes)..."
    aws cloudfront wait distribution-deployed \
        --id "${CF_DIST_ID}"

    # Now delete the disabled distribution
    echo "==> Deleting CloudFront distribution ${CF_DIST_ID}..."
    DELETE_ETAG="$(aws cloudfront get-distribution-config --id "${CF_DIST_ID}" \
        | jq -r '.ETag')"
    aws cloudfront delete-distribution \
        --id "${CF_DIST_ID}" \
        --if-match "${DELETE_ETAG}"
    echo "    Distribution deleted."
fi

# ---------------------------------------------------------------------------
# Step 2: Delete ACM certificate
# ---------------------------------------------------------------------------

if [[ -n "${CERT_ARN}" ]]; then
    echo ""
    echo "==> Deleting ACM certificate..."
    aws acm delete-certificate \
        --certificate-arn "${CERT_ARN}" \
        --region us-east-1
    echo "    Certificate deleted."
fi

# ---------------------------------------------------------------------------
# Step 3: Clear CustomDomainHost on the CloudFormation stack
# ---------------------------------------------------------------------------

if [[ -n "${CUSTOM_DOMAIN}" && -n "${STACK_JSON}" ]]; then
    echo ""
    echo "==> Clearing CustomDomainHost on stack ${STACK_NAME}..."

    PARAM_OVERRIDES="$(echo "${STACK_JSON}" | jq -r '
        .Stacks[0].Parameters[].ParameterKey' | while read -r key; do
            if [[ "${key}" == "CustomDomainHost" ]]; then
                echo "ParameterKey=${key},ParameterValue="
            else
                echo "ParameterKey=${key},UsePreviousValue=true"
            fi
        done)"

    aws cloudformation update-stack \
        --stack-name "${STACK_NAME}" \
        --use-previous-template \
        --capabilities CAPABILITY_NAMED_IAM \
        --region "${AWS_REGION}" \
        --parameters ${PARAM_OVERRIDES} \
        --no-cli-pager > /dev/null

    aws cloudformation wait stack-update-complete \
        --stack-name "${STACK_NAME}" \
        --region "${AWS_REGION}"
    echo "    Stack updated."
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo ""
echo "==> Done. Custom domain removed from ${STACK_NAME}."
if [[ -n "${VALIDATION_HOST}" || -n "${CUSTOM_HOST}" ]]; then
    echo ""
    echo "    Remember to remove these CNAME records at your registrar:"
    if [[ -n "${VALIDATION_HOST}" && -n "${VALIDATION_VALUE}" ]]; then
        echo ""
        echo "      Host:  ${VALIDATION_HOST}"
        echo "      Value: ${VALIDATION_VALUE}"
    fi
    if [[ -n "${CUSTOM_HOST}" && -n "${CF_DOMAIN}" ]]; then
        echo ""
        echo "      Host:  ${CUSTOM_HOST}"
        echo "      Value: ${CF_DOMAIN}"
    fi
fi
