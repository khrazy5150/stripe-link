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

# NOTE: the SMS origination identity (10DLC number) is NOT a deploy parameter — it lives in
# Secrets Manager and is read at runtime. Set/rotate it with ./deploy/sms-origination-secrets.sh
# [dev|prod]; it takes effect on the next reminder sweep with no redeploy.

if [[ "${ENVIRONMENT}" == "dev" ]]; then
  API_CUSTOM_DOMAIN_NAME="${API_CUSTOM_DOMAIN_NAME:-dev.juniorbay.com}"
  API_CUSTOM_DOMAIN_CERTIFICATE_ARN="${API_CUSTOM_DOMAIN_CERTIFICATE_ARN:-arn:aws:acm:us-west-2:150544707159:certificate/b40bb746-6e32-4a7d-8c24-b738cd1c359a}"
fi

# Dashboard CloudFront custom domain per environment. The cert must be in us-east-1 (CloudFront requirement);
# the *.juniorbay.com wildcard covers both. Prod is the canonical app URL; dev is a sandbox.
if [[ "${ENVIRONMENT}" == "prod" ]]; then
  DASHBOARD_CUSTOM_DOMAIN_NAME="${DASHBOARD_CUSTOM_DOMAIN_NAME:-app.juniorbay.com}"
  DASHBOARD_CUSTOM_DOMAIN_CERTIFICATE_ARN="${DASHBOARD_CUSTOM_DOMAIN_CERTIFICATE_ARN:-arn:aws:acm:us-east-1:150544707159:certificate/1a72b7c6-bf14-40d2-8e07-c2d2df84c70a}"
elif [[ "${ENVIRONMENT}" == "dev" ]]; then
  DASHBOARD_CUSTOM_DOMAIN_NAME="${DASHBOARD_CUSTOM_DOMAIN_NAME:-sandbox.juniorbay.com}"
  DASHBOARD_CUSTOM_DOMAIN_CERTIFICATE_ARN="${DASHBOARD_CUSTOM_DOMAIN_CERTIFICATE_ARN:-arn:aws:acm:us-east-1:150544707159:certificate/1a72b7c6-bf14-40d2-8e07-c2d2df84c70a}"
fi

"$(dirname "$0")/validate-resource-names.sh"
sam build

PARAMETER_OVERRIDES=(
  "Environment=${ENVIRONMENT}"
  "ProjectPrefix=jb"
)

# Free-tier Site hosting domain (Zone B, always noindex): prod serves on jbay.uk, test on jbay.be — separate
# zones so a test wildcard can never touch prod (plans/PLATFORM_HOSTNAME_SERVING.md).
if [[ "${ENVIRONMENT}" == "prod" ]]; then
  PARAMETER_OVERRIDES+=("PlatformHostingDomain=jbay.uk")
else
  PARAMETER_OVERRIDES+=("PlatformHostingDomain=jbay.be")
fi

# Master switch for serving Sites on the free platform host (plans/PLATFORM_HOSTNAME_SERVING.md). Flip it by
# exporting PLATFORM_SERVING_ENABLED=true before the deploy. When the env var is NOT set, PRESERVE the value
# already on the stack instead of resetting it — otherwise a plain `./deploy/deploy.sh <env>` would silently
# turn platform serving off. A brand-new stack (no existing value) defaults to false.
if [[ -n "${PLATFORM_SERVING_ENABLED:-}" ]]; then
  PLATFORM_SERVING="${PLATFORM_SERVING_ENABLED}"
else
  PLATFORM_SERVING="$(aws cloudformation describe-stacks \
    --region "${REGION}" --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Parameters[?ParameterKey=='PlatformServingEnabled'].ParameterValue | [0]" \
    --output text 2>/dev/null)"
  if [[ -z "${PLATFORM_SERVING}" || "${PLATFORM_SERVING}" == "None" ]]; then
    PLATFORM_SERVING="false"
  fi
fi
PARAMETER_OVERRIDES+=("PlatformServingEnabled=${PLATFORM_SERVING}")

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
