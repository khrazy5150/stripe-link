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

# AWS End User Messaging (SMS) origination identity for appointment reminders. Set this to
# the approved A2P 10DLC phone number (E.164, e.g. +18885551234) or a phone-pool ARN once
# 10DLC registration completes. Until it is set, the reminder sweep no-ops (nothing is sent).
# Enter it here per environment (persists across deploys) or override with the env var.
SMS_ORIGINATION_IDENTITY="${SMS_ORIGINATION_IDENTITY:-}"
SMS_CONFIGURATION_SET="${SMS_CONFIGURATION_SET:-}"

if [[ "${ENVIRONMENT}" == "prod" ]]; then
  # Paste the approved prod 10DLC number / pool ARN below (leave empty to keep SMS off):
  SMS_ORIGINATION_IDENTITY="${SMS_ORIGINATION_IDENTITY:-}"
  SMS_CONFIGURATION_SET="${SMS_CONFIGURATION_SET:-}"
fi

if [[ "${ENVIRONMENT}" == "dev" ]]; then
  # Optional: a separate test/dev 10DLC or simulator number for staging SMS.
  SMS_ORIGINATION_IDENTITY="${SMS_ORIGINATION_IDENTITY:-}"
  SMS_CONFIGURATION_SET="${SMS_CONFIGURATION_SET:-}"
fi

if [[ "${ENVIRONMENT}" == "dev" ]]; then
  API_CUSTOM_DOMAIN_NAME="${API_CUSTOM_DOMAIN_NAME:-dev.juniorbay.com}"
  API_CUSTOM_DOMAIN_CERTIFICATE_ARN="${API_CUSTOM_DOMAIN_CERTIFICATE_ARN:-arn:aws:acm:us-west-2:150544707159:certificate/b40bb746-6e32-4a7d-8c24-b738cd1c359a}"
fi

"$(dirname "$0")/validate-resource-names.sh"
sam build

PARAMETER_OVERRIDES=(
  "Environment=${ENVIRONMENT}"
  "ProjectPrefix=jb"
)

if [[ -n "${API_CUSTOM_DOMAIN_NAME}" ]]; then
  PARAMETER_OVERRIDES+=("ApiCustomDomainName=${API_CUSTOM_DOMAIN_NAME}")
fi

if [[ -n "${API_CUSTOM_DOMAIN_CERTIFICATE_ARN}" ]]; then
  PARAMETER_OVERRIDES+=("ApiCustomDomainCertificateArn=${API_CUSTOM_DOMAIN_CERTIFICATE_ARN}")
fi

if [[ -n "${API_CUSTOM_DOMAIN_NAME}" || -n "${API_CUSTOM_DOMAIN_CERTIFICATE_ARN}" ]]; then
  PARAMETER_OVERRIDES+=("ApiCustomDomainHostedZoneName=${API_CUSTOM_DOMAIN_HOSTED_ZONE_NAME}")
fi

# Google Calendar OAuth redirect URI (must be registered in the Google OAuth client).
# Defaults to the API custom domain's /calendar/callback when a custom domain is set.
CALENDAR_REDIRECT_URI="${CALENDAR_REDIRECT_URI:-}"
if [[ -z "${CALENDAR_REDIRECT_URI}" && -n "${API_CUSTOM_DOMAIN_NAME}" ]]; then
  CALENDAR_REDIRECT_URI="https://${API_CUSTOM_DOMAIN_NAME}/calendar/callback"
fi
if [[ -n "${CALENDAR_REDIRECT_URI}" ]]; then
  PARAMETER_OVERRIDES+=("CalendarRedirectUri=${CALENDAR_REDIRECT_URI}")
fi

if [[ -n "${SMS_ORIGINATION_IDENTITY}" ]]; then
  PARAMETER_OVERRIDES+=("SmsOriginationIdentity=${SMS_ORIGINATION_IDENTITY}")
fi

if [[ -n "${SMS_CONFIGURATION_SET}" ]]; then
  PARAMETER_OVERRIDES+=("SmsConfigurationSet=${SMS_CONFIGURATION_SET}")
fi

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
