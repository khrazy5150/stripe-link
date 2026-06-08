#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT="${1:-dev}"
STACK_NAME="jb-stripe-link-stack-${ENVIRONMENT}"
REGION="${AWS_REGION:-us-west-2}"
API_CUSTOM_DOMAIN_NAME="${API_CUSTOM_DOMAIN_NAME:-}"
API_CUSTOM_DOMAIN_CERTIFICATE_ARN="${API_CUSTOM_DOMAIN_CERTIFICATE_ARN:-}"
API_CUSTOM_DOMAIN_HOSTED_ZONE_NAME="${API_CUSTOM_DOMAIN_HOSTED_ZONE_NAME:-juniorbay.com.}"
DASHBOARD_CUSTOM_DOMAIN_NAME="${DASHBOARD_CUSTOM_DOMAIN_NAME:-}"
DASHBOARD_CUSTOM_DOMAIN_CERTIFICATE_ARN="${DASHBOARD_CUSTOM_DOMAIN_CERTIFICATE_ARN:-}"
DASHBOARD_CUSTOM_DOMAIN_HOSTED_ZONE_NAME="${DASHBOARD_CUSTOM_DOMAIN_HOSTED_ZONE_NAME:-juniorbay.com.}"

if [[ "${ENVIRONMENT}" == "dev" ]]; then
  API_CUSTOM_DOMAIN_NAME="${API_CUSTOM_DOMAIN_NAME:-dev.juniorbay.com}"
  API_CUSTOM_DOMAIN_CERTIFICATE_ARN="${API_CUSTOM_DOMAIN_CERTIFICATE_ARN:-arn:aws:acm:us-west-2:150544707159:certificate/b40bb746-6e32-4a7d-8c24-b738cd1c359a}"
fi

"$(dirname "$0")/validate-resource-names.sh"
sam build

PARAMETER_OVERRIDES=(
  "Environment=${ENVIRONMENT}"
  "ProjectPrefix=jb"
  "ApiCustomDomainName=${API_CUSTOM_DOMAIN_NAME}"
  "ApiCustomDomainCertificateArn=${API_CUSTOM_DOMAIN_CERTIFICATE_ARN}"
  "ApiCustomDomainHostedZoneName=${API_CUSTOM_DOMAIN_HOSTED_ZONE_NAME}"
)

if [[ -n "${DASHBOARD_CUSTOM_DOMAIN_NAME}" ]]; then
  PARAMETER_OVERRIDES+=("DashboardCustomDomainName=${DASHBOARD_CUSTOM_DOMAIN_NAME}")
fi

if [[ -n "${DASHBOARD_CUSTOM_DOMAIN_CERTIFICATE_ARN}" ]]; then
  PARAMETER_OVERRIDES+=("DashboardCustomDomainCertificateArn=${DASHBOARD_CUSTOM_DOMAIN_CERTIFICATE_ARN}")
fi

if [[ -n "${DASHBOARD_CUSTOM_DOMAIN_NAME}" || -n "${DASHBOARD_CUSTOM_DOMAIN_CERTIFICATE_ARN}" ]]; then
  PARAMETER_OVERRIDES+=("DashboardCustomDomainHostedZoneName=${DASHBOARD_CUSTOM_DOMAIN_HOSTED_ZONE_NAME}")
fi

sam deploy \
  --stack-name "${STACK_NAME}" \
  --region "${REGION}" \
  --capabilities CAPABILITY_IAM \
  --resolve-s3 \
  --parameter-overrides "${PARAMETER_OVERRIDES[@]}" \
  --tags "Project=stripe-link" "Environment=${ENVIRONMENT}" "ManagedBy=sam"

CONFIG_BUCKET="$(aws cloudformation describe-stacks \
  --region "${REGION}" \
  --stack-name "${STACK_NAME}" \
  --query "Stacks[0].Outputs[?OutputKey=='ConfigBucketName'].OutputValue | [0]" \
  --output text)"

if [[ -n "${CONFIG_BUCKET}" && "${CONFIG_BUCKET}" != "None" ]]; then
  aws s3 cp \
    "$(dirname "$0")/../schemas/examples/global-billing-config.json" \
    "s3://${CONFIG_BUCKET}/global_billing_config.json" \
    --region "${REGION}" \
    --content-type "application/json"
fi
