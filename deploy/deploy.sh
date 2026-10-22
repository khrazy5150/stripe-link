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

# The AI image generator's API base, per environment. It is a SEPARATE STACK in a sibling repo
# (../sam/ai-image-generator), so its execute-api hostname cannot be derived here -- it is read off
# that stack's ApiBase output once and pinned. Empty disables image generation cleanly: the client is
# checked for configuration BEFORE a tenant's allowance is touched.
#
# THIS IS THE FILE THAT DECIDES. samconfig.toml also lists parameter_overrides, and it is NOT what a
# deploy uses -- the array below is passed as --parameter-overrides and wins outright. A parameter set
# only in samconfig silently takes its template Default, which is how AI_IMAGE_API_BASE first shipped
# empty while samconfig said otherwise (2026-10-20).
if [[ "${ENVIRONMENT}" == "prod" ]]; then
  AI_IMAGE_API_BASE="${AI_IMAGE_API_BASE:-https://gtomjryzk9.execute-api.us-west-2.amazonaws.com/prod}"
elif [[ "${ENVIRONMENT}" == "dev" ]]; then
  AI_IMAGE_API_BASE="${AI_IMAGE_API_BASE:-https://qlrkbhzbq7.execute-api.us-west-2.amazonaws.com/dev}"
fi

"$(dirname "$0")/validate-resource-names.sh"
sam build

PARAMETER_OVERRIDES=(
  "Environment=${ENVIRONMENT}"
  "ProjectPrefix=jb"
  "AiImageApiBase=${AI_IMAGE_API_BASE:-}"
)

# Free-tier Site hosting domain (Zone B, always noindex): prod serves on jbay.uk, test on jbay.be — separate
# zones so a test wildcard can never touch prod (plans/PLATFORM_HOSTNAME_SERVING.md).
if [[ "${ENVIRONMENT}" == "prod" ]]; then
  PARAMETER_OVERRIDES+=("PlatformHostingDomain=jbay.uk")
else
  PARAMETER_OVERRIDES+=("PlatformHostingDomain=jbay.be")
fi

# Link-in-bio apex (plans/CREATOR_DOMAIN_SERVING.md): prod serves creators on jbay.page, dev on
# test.jbay.page. ONE zone, two Worker routes pointing at the two environments' APIs -- the same live/test
# split the platform host makes with jbay.uk/jbay.be, without buying a second domain for it. Never a shared
# value: a dev stack must not write records on the apex prod serves live pages from.
if [[ "${ENVIRONMENT}" == "prod" ]]; then
  PARAMETER_OVERRIDES+=("CreatorHostingDomain=jbay.page")
else
  PARAMETER_OVERRIDES+=("CreatorHostingDomain=test.jbay.page")
fi

# Master switch for link-in-bio serving. Same preserve-on-silence rule as PLATFORM_SERVING below: an
# ordinary deploy must never turn a live feature off just because the operator did not re-export the flag.
if [[ -n "${CREATOR_SERVING_ENABLED:-}" ]]; then
  CREATOR_SERVING="${CREATOR_SERVING_ENABLED}"
else
  CREATOR_SERVING="$(aws cloudformation describe-stacks \
    --region "${REGION}" --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Parameters[?ParameterKey=='CreatorServingEnabled'].ParameterValue | [0]" \
    --output text 2>/dev/null)"
  if [[ -z "${CREATOR_SERVING}" || "${CREATOR_SERVING}" == "None" ]]; then
    CREATOR_SERVING="false"
  fi
fi
PARAMETER_OVERRIDES+=("CreatorServingEnabled=${CREATOR_SERVING}")

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

# --no-fail-on-empty-changeset: with `set -e`, an unchanged stack made `sam deploy` exit non-zero and the
# script stopped BEFORE uploading the billing config below — so a config-only change could never be
# deployed. That is how a stale fee table stayed live after the pricing pivot (2026-09-14).
#
# DEPLOY_EXTRA_ARGS exists so a PROD deploy can be audited before it applies: run with
# DEPLOY_EXTRA_ARGS=--no-execute-changeset to create the changeset, read what it actually changes, then
# `aws cloudformation execute-change-set`. The parameter logic above (which PRESERVES live feature flags
# read off the running stack) must not be bypassed by hand-rolling a separate `sam deploy` to get there.
read -r -a DEPLOY_EXTRA <<< "${DEPLOY_EXTRA_ARGS:-}"
sam deploy \
  --stack-name "${STACK_NAME}" \
  --region "${REGION}" \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset \
  --resolve-s3 \
  --parameter-overrides "${PARAMETER_OVERRIDES[@]}" \
  --tags "Project=stripe-link" "Environment=${ENVIRONMENT}" "ManagedBy=sam" \
  ${DEPLOY_EXTRA[@]+"${DEPLOY_EXTRA[@]}"}

CONFIG_BUCKET="$(aws cloudformation describe-stacks \
  --region "${REGION}" \
  --stack-name "${STACK_NAME}" \
  --query "Stacks[0].Outputs[?OutputKey=='ConfigBucketName'].OutputValue | [0]" \
  --output text)"

# SEED ONLY. This file is the baseline a NEW environment starts from; the LIVE fee table is the S3
# object, and the Admin Site edits it. Uploading unconditionally -- which this did until 2026-10-21 --
# meant the next deploy silently reverted every rate an admin had changed, and nothing would have said
# so until a tenant was charged the old number.
#
# To push the repo's baseline on purpose: BILLING_CONFIG_RESEED=1 ./deploy/deploy.sh <env>
if [[ -n "${CONFIG_BUCKET}" && "${CONFIG_BUCKET}" != "None" ]]; then
  if [[ "${BILLING_CONFIG_RESEED:-}" == "1" ]]; then
    echo "==> Billing config: RESEEDING from the repo (overwrites Admin Site edits)"
    aws s3 cp \
      "$(dirname "$0")/../schemas/examples/global-billing-config.json" \
      "s3://${CONFIG_BUCKET}/global_billing_config.json" \
      --region "${REGION}" --content-type "application/json"
  elif aws s3api head-object --bucket "${CONFIG_BUCKET}" --key "global_billing_config.json" \
       --region "${REGION}" >/dev/null 2>&1; then
    echo "==> Billing config: already present, left alone (the Admin Site owns it)"
  else
    echo "==> Billing config: seeding the baseline (none present)"
    aws s3 cp \
      "$(dirname "$0")/../schemas/examples/global-billing-config.json" \
      "s3://${CONFIG_BUCKET}/global_billing_config.json" \
      --region "${REGION}" --content-type "application/json"
  fi
fi
