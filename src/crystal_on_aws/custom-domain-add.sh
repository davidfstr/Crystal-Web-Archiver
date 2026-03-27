#!/usr/bin/env bash
# Adds a custom domain to a Crystal on AWS CloudFormation stack.
#
# This script:
#   1. Requests an ACM certificate for the domain
#   2. Creates a CloudFront distribution pointing at the Lambda Function URL
#   3. Displays the DNS records for the user to add at their registrar
#   4. Waits for certificate validation
#   5. Attaches the custom domain to the CloudFront distribution
#   6. Updates the CloudFormation stack so Crystal generates correct links
#
# Prerequisites:
#   - A deployed Crystal CloudFormation stack
#   - A domain you own (DNS managed by any registrar)
#
# Run from AWS CloudShell (no local install needed):
#   Open CloudShell:
#     https://console.aws.amazon.com/cloudshell/
#   Select the region matching your Crystal stack from the page's top-right corner:
#     e.g. "United States (Ohio): us-east-2"
#   Then paste:
#     curl -sL https://raw.githubusercontent.com/davidfstr/Crystal-Web-Archiver/main/src/crystal_on_aws/custom-domain-add.sh | bash -s <stack-name> <domain>
#   Example:
#     curl -sL https://raw.githubusercontent.com/davidfstr/Crystal-Web-Archiver/main/src/crystal_on_aws/custom-domain-add.sh | bash -s crystal-xkcd xkcd2.daarchive.net
#
# Run locally (requires AWS CLI and jq):
#   src/crystal_on_aws/custom-domain-add.sh <stack-name> <domain>

set -euo pipefail

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <stack-name> <domain>"
    echo "Example: $0 crystal-xkcd xkcd2.daarchive.net"
    exit 1
fi

STACK_NAME="$1"
CUSTOM_DOMAIN="$2"

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

# ---------------------------------------------------------------------------
# Validate stack
# ---------------------------------------------------------------------------

echo "==> Checking stack: ${STACK_NAME}..."

STACK_JSON="$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --output json 2>&1)" || {
    echo "ERROR: Stack '${STACK_NAME}' not found in region ${AWS_REGION}."
    exit 1
}

# Get Lambda Function URL domain from stack outputs
FUNCTION_URL="$(echo "${STACK_JSON}" \
    | jq -r '.Stacks[0].Outputs[] | select(.OutputKey=="SiteUrl1") | .OutputValue')"
if [[ -z "${FUNCTION_URL}" ]]; then
    echo "ERROR: Stack has no SiteUrl1 output. Is this a Crystal stack?"
    exit 1
fi
LAMBDA_DOMAIN="$(echo "${FUNCTION_URL}" | sed 's|https://||; s|/.*||')"
echo "    Lambda Function URL domain: ${LAMBDA_DOMAIN}"

# Check if custom domain is already configured (completed setup)
CURRENT_DOMAIN="$(echo "${STACK_JSON}" \
    | jq -r '.Stacks[0].Parameters[] | select(.ParameterKey=="CustomDomainHost") | .ParameterValue')"
if [[ -n "${CURRENT_DOMAIN}" ]]; then
    echo "ERROR: Stack already has CustomDomainHost='${CURRENT_DOMAIN}'."
    echo "       Remove it first with: custom-domain-remove.sh ${STACK_NAME}"
    exit 1
fi

# ---------------------------------------------------------------------------
# Clean up orphaned resources from a previous interrupted run
# ---------------------------------------------------------------------------

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

# Check for orphaned CloudFront distribution
ORPHAN_CF_ARNS="$(aws resourcegroupstaggingapi get-resources \
    --tag-filters "Key=crystal-stack,Values=${STACK_NAME}" \
    --resource-type-filters cloudfront:distribution \
    --region us-east-1 \
    --query 'ResourceTagMappingList[].ResourceARN' \
    --output text 2>/dev/null || true)"

# Check for orphaned ACM certificate
ORPHAN_CERT_ARNS="$(aws resourcegroupstaggingapi get-resources \
    --tag-filters "Key=crystal-stack,Values=${STACK_NAME}" \
    --resource-type-filters acm:certificate \
    --region us-east-1 \
    --query 'ResourceTagMappingList[].ResourceARN' \
    --output text 2>/dev/null || true)"

if [[ -n "${ORPHAN_CF_ARNS}" || -n "${ORPHAN_CERT_ARNS}" ]]; then
    echo ""
    echo "    Found resources from a previous interrupted run:"
    [[ -n "${ORPHAN_CF_ARNS}" ]] && echo "      CloudFront distribution: ${ORPHAN_CF_ARNS##*/}"
    [[ -n "${ORPHAN_CERT_ARNS}" ]] && echo "      ACM certificate: ${ORPHAN_CERT_ARNS}"
    echo ""
    read -rp "    Clean these up before proceeding? (Y/n) " CLEANUP_CONFIRM < /dev/tty
    if [[ "${CLEANUP_CONFIRM}" != "n" && "${CLEANUP_CONFIRM}" != "N" ]]; then
        if [[ -n "${ORPHAN_CF_ARNS}" ]]; then
            ORPHAN_CF_ID="${ORPHAN_CF_ARNS##*/}"
            echo "    Disabling CloudFront distribution ${ORPHAN_CF_ID}..."
            DIST_CONFIG_RESULT="$(aws cloudfront get-distribution-config --id "${ORPHAN_CF_ID}")"
            ETAG="$(echo "${DIST_CONFIG_RESULT}" | jq -r '.ETag')"
            CURRENT_ENABLED="$(echo "${DIST_CONFIG_RESULT}" | jq -r '.DistributionConfig.Enabled')"
            if [[ "${CURRENT_ENABLED}" == "true" ]]; then
                UPDATED_CONFIG="$(echo "${DIST_CONFIG_RESULT}" | jq '
                    .DistributionConfig |
                    .Aliases = {"Quantity": 0, "Items": []} |
                    .ViewerCertificate = {"CloudFrontDefaultCertificate": true, "MinimumProtocolVersion": "TLSv1"} |
                    .Enabled = false')"
                aws cloudfront update-distribution \
                    --id "${ORPHAN_CF_ID}" \
                    --distribution-config "${UPDATED_CONFIG}" \
                    --if-match "${ETAG}" \
                    --no-cli-pager > /dev/null
                echo "    Waiting for distribution to be disabled (this may take a few minutes)..."
                aws cloudfront wait distribution-deployed --id "${ORPHAN_CF_ID}"
                ETAG="$(aws cloudfront get-distribution-config --id "${ORPHAN_CF_ID}" | jq -r '.ETag')"
            fi
            echo "    Deleting CloudFront distribution ${ORPHAN_CF_ID}..."
            aws cloudfront delete-distribution --id "${ORPHAN_CF_ID}" --if-match "${ETAG}"
            echo "    Distribution deleted."
        fi
        if [[ -n "${ORPHAN_CERT_ARNS}" ]]; then
            echo "    Deleting ACM certificate..."
            aws acm delete-certificate --certificate-arn "${ORPHAN_CERT_ARNS}" --region us-east-1
            echo "    Certificate deleted."
        fi
        echo ""
    else
        echo "ERROR: Cannot proceed with orphaned resources."
        echo "       Run custom-domain-remove.sh ${STACK_NAME} to clean up manually."
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Step 1: Request ACM certificate (must be in us-east-1 for CloudFront)
# ---------------------------------------------------------------------------

echo ""
echo "==> Requesting ACM certificate for ${CUSTOM_DOMAIN} (in us-east-1)..."
CERT_ARN="$(aws acm request-certificate \
    --domain-name "${CUSTOM_DOMAIN}" \
    --validation-method DNS \
    --tags "Key=crystal-stack,Value=${STACK_NAME}" \
    --region us-east-1 \
    --query CertificateArn \
    --output text)"
echo "    Certificate ARN: ${CERT_ARN}"

# Wait for the validation record to become available
echo "    Waiting for validation details..."
for i in {1..12}; do
    VALIDATION_NAME="$(aws acm describe-certificate \
        --certificate-arn "${CERT_ARN}" \
        --region us-east-1 \
        --query 'Certificate.DomainValidationOptions[0].ResourceRecord.Name' \
        --output text 2>/dev/null || true)"
    if [[ -n "${VALIDATION_NAME}" && "${VALIDATION_NAME}" != "None" ]]; then
        break
    fi
    sleep 5
done

if [[ -z "${VALIDATION_NAME}" || "${VALIDATION_NAME}" == "None" ]]; then
    echo "ERROR: Timed out waiting for ACM validation details."
    echo "       Certificate ARN: ${CERT_ARN}"
    echo "       Check the ACM console in us-east-1 manually."
    exit 1
fi

VALIDATION_VALUE="$(aws acm describe-certificate \
    --certificate-arn "${CERT_ARN}" \
    --region us-east-1 \
    --query 'Certificate.DomainValidationOptions[0].ResourceRecord.Value' \
    --output text)"

# ---------------------------------------------------------------------------
# Step 2: Create CloudFront distribution (without custom domain yet)
# ---------------------------------------------------------------------------

echo ""
echo "==> Creating CloudFront distribution (origin: ${LAMBDA_DOMAIN})..."

# Well-known AWS managed policy IDs:
#   CachingDisabled:            4135ea2d-6df8-44a3-9df3-4b5a84be39ad
#   AllViewerExceptHostHeader:  b689b0a8-53d0-40ab-baf2-68738e2966ac
CF_CONFIG="$(cat <<EOF
{
  "CallerReference": "${STACK_NAME}-custom-domain-$(date +%s)",
  "Comment": "${STACK_NAME}",
  "Enabled": true,
  "Origins": {
    "Quantity": 1,
    "Items": [{
      "Id": "lambda-function-url",
      "DomainName": "${LAMBDA_DOMAIN}",
      "CustomOriginConfig": {
        "HTTPPort": 80,
        "HTTPSPort": 443,
        "OriginProtocolPolicy": "https-only"
      }
    }]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "lambda-function-url",
    "ViewerProtocolPolicy": "redirect-to-https",
    "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
    "OriginRequestPolicyId": "b689b0a8-53d0-40ab-baf2-68738e2966ac",
    "AllowedMethods": {
      "Quantity": 2,
      "Items": ["GET", "HEAD"]
    },
    "Compress": true
  },
  "Aliases": {
    "Quantity": 0
  },
  "ViewerCertificate": {
    "CloudFrontDefaultCertificate": true
  }
}
EOF
)"

CF_RESULT="$(aws cloudfront create-distribution \
    --distribution-config "${CF_CONFIG}" \
    --output json)"
CF_DIST_ID="$(echo "${CF_RESULT}" | jq -r '.Distribution.Id')"
CF_DOMAIN="$(echo "${CF_RESULT}" | jq -r '.Distribution.DomainName')"
echo "    Distribution ID: ${CF_DIST_ID}"
echo "    Distribution domain: ${CF_DOMAIN}"

# Tag the distribution so custom-domain-remove.sh can find it
aws cloudfront tag-resource \
    --resource "arn:aws:cloudfront::${ACCOUNT_ID}:distribution/${CF_DIST_ID}" \
    --tags "Items=[{Key=crystal-stack,Value=${STACK_NAME}}]"

# ---------------------------------------------------------------------------
# Step 3: Display DNS records for the user
# ---------------------------------------------------------------------------

# Compute the registrar "host" fields by stripping the base domain suffix.
# e.g. for domain "xkcd2.daarchive.net":
#   "_abc.xkcd2.daarchive.net." -> "_abc.xkcd2"
#   "xkcd2.daarchive.net"      -> "xkcd2"
BASE_DOMAIN="$(echo "${CUSTOM_DOMAIN}" | sed 's/^[^.]*\.//')"
VALIDATION_HOST="$(echo "${VALIDATION_NAME}" | sed "s/\.${BASE_DOMAIN}\.$//")"
CUSTOM_HOST="$(echo "${CUSTOM_DOMAIN}" | sed "s/\.${BASE_DOMAIN}$//")"

echo ""
echo "========================================================================"
echo ""
echo "  Add these 2 CNAME records at your domain registrar:"
echo ""
echo "  1. Certificate validation:"
echo "     Type:  CNAME"
echo "     Host:  ${VALIDATION_HOST}"
echo "     Value: ${VALIDATION_VALUE}"
echo ""
echo "  2. Custom domain:"
echo "     Type:  CNAME"
echo "     Host:  ${CUSTOM_HOST}"
echo "     Value: ${CF_DOMAIN}"
echo ""
echo "========================================================================"
echo ""
read -rp "Press Enter after adding both records (Ctrl-C to abort)... " < /dev/tty

# ---------------------------------------------------------------------------
# Step 4: Wait for certificate validation
# ---------------------------------------------------------------------------

echo ""
echo "==> Waiting for certificate validation (this may take a few minutes, Ctrl-C to abort)..."
if ! aws acm wait certificate-validated \
    --certificate-arn "${CERT_ARN}" \
    --region us-east-1; then
    echo ""
    echo "ERROR: Certificate validation timed out."
    echo "       The DNS CNAME record may be missing or incorrect."
    echo ""
    echo "       To debug, verify the validation CNAME resolves:"
    echo "         dig CNAME ${VALIDATION_NAME}"
    echo ""
    echo "       Re-run this script to retry (orphaned resources will be cleaned up)."
    exit 1
fi
echo "    Certificate issued."

# ---------------------------------------------------------------------------
# Step 5: Wait for CloudFront distribution to be deployed
# ---------------------------------------------------------------------------

echo ""
echo "==> Waiting for CloudFront distribution to be deployed (this may take a few minutes)..."
aws cloudfront wait distribution-deployed \
    --id "${CF_DIST_ID}"
echo "    Distribution deployed."

# ---------------------------------------------------------------------------
# Step 6: Attach custom domain + certificate to CloudFront distribution
# ---------------------------------------------------------------------------

echo ""
echo "==> Attaching custom domain to CloudFront distribution..."

# Get current config and ETag (required for update)
DIST_CONFIG_RESULT="$(aws cloudfront get-distribution-config --id "${CF_DIST_ID}")"
ETAG="$(echo "${DIST_CONFIG_RESULT}" | jq -r '.ETag')"
UPDATED_CONFIG="$(echo "${DIST_CONFIG_RESULT}" | jq \
    --arg domain "${CUSTOM_DOMAIN}" \
    --arg cert_arn "${CERT_ARN}" \
    '.DistributionConfig |
     .Aliases = {"Quantity": 1, "Items": [$domain]} |
     .ViewerCertificate = {
       "ACMCertificateArn": $cert_arn,
       "SSLSupportMethod": "sni-only",
       "MinimumProtocolVersion": "TLSv1.2_2021"
     }')"

aws cloudfront update-distribution \
    --id "${CF_DIST_ID}" \
    --distribution-config "${UPDATED_CONFIG}" \
    --if-match "${ETAG}" \
    --no-cli-pager > /dev/null

echo "    Waiting for distribution update (this may take a few minutes)..."
aws cloudfront wait distribution-deployed \
    --id "${CF_DIST_ID}"
echo "    Custom domain attached."

# ---------------------------------------------------------------------------
# Step 7: Update CloudFormation stack to set CRYSTAL_REQUEST_HOST
# ---------------------------------------------------------------------------

echo ""
echo "==> Updating stack ${STACK_NAME} (CustomDomainHost=${CUSTOM_DOMAIN})..."

# Build parameter overrides: keep all existing values, override CustomDomainHost
PARAM_OVERRIDES="$(echo "${STACK_JSON}" | jq -r '
    .Stacks[0].Parameters[].ParameterKey' | while read -r key; do
        if [[ "${key}" == "CustomDomainHost" ]]; then
            echo "ParameterKey=${key},ParameterValue=${CUSTOM_DOMAIN}"
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

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo ""
echo "==> Done! https://${CUSTOM_DOMAIN}/ is now live."
echo ""
echo "    CloudFront distribution: ${CF_DIST_ID}"
echo "    ACM certificate:         ${CERT_ARN}"
echo "    To remove: src/crystal_on_aws/custom-domain-remove.sh ${STACK_NAME}"
