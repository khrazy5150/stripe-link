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

# Cloudflare for SaaS, per environment. A tenant's custom domain becomes a custom hostname on THIS
# stack's zone and is told to CNAME at THIS stack's fallback origin -- otherwise the DNS points at the
# other stack's Worker, which asks the other stack's resolver, which has never heard of the Site. That is
# not hypothetical: both stacks carried the jbay.uk zone and domains.jbay.uk until 2026-10-23, so a domain
# connected on sandbox verified successfully and then served a 404 (shop.coderbay.net, found the hard way).
#
# SET HERE AND NOT ONLY IN samconfig.toml. This script passes its own --parameter-overrides, so
# CloudFormation keeps the PREVIOUS stack value for anything absent from the array below and samconfig's
# copy is never read. Editing samconfig alone deploys nothing -- verified on this very change.
# Both zones are already configured for SaaS with an active fallback origin.
if [[ "${ENVIRONMENT}" == "prod" ]]; then
  PARAMETER_OVERRIDES+=("CloudflareZoneId=d842792b5a5240f5518f263835220df6")   # jbay.uk
  PARAMETER_OVERRIDES+=("CustomDomainTargetHost=domains.jbay.uk")
else
  PARAMETER_OVERRIDES+=("CloudflareZoneId=d5a70f95c54659e26600cae1bb0ce48a")   # jbay.be
  PARAMETER_OVERRIDES+=("CustomDomainTargetHost=domains.jbay.be")
fi

# Managed DNS (plans/MANAGED_DNS.md): the Cloudflare ACCOUNT that tenant zones are created on. One value
# for both environments -- the zones differ per environment, the account does not. Empty disables managed
# DNS cleanly, the same way an empty AiImageApiBase disables image generation.
PARAMETER_OVERRIDES+=("CloudflareAccountId=c7b1afadd7f220d780f4f742a12aef16")

# Apex custom domains (plans/SITE_OBJECT.md 2.6b). CloudflareApexIpv4/IPV6 ARE DELIBERATELY UNSET, and the
# reason is the kind that gets rediscovered the hard way, so it is written down here rather than only in
# the plan.
#
# On 2026-10-23 these were set to each zone's public anycast pair -- 104.21.71.205/172.67.149.43 for
# jbay.uk, 104.21.88.48/172.67.173.6 for jbay.be -- on the reasoning that Cloudflare's edge routes by
# SNI, which it demonstrably does: `curl --resolve shop.coderbay.net:443:<either pair>` served 200 from
# both. That proved ROUTING and said nothing about VERIFICATION, which is the actual gate. Cloudflare
# refused the first real apex (coderbay.net, Route 53) in its own words:
#
#   "custom hostname does not CNAME to this zone."
#   "The hostname is using Cloudflare and cannot be activated with an TXT or HTTP validation token.
#    To activate the custom hostname, the DNS target needs to point to the SaaS zone"
#
# Pointing an apex at Cloudflare's shared addresses makes the hostname "using Cloudflare", which BLOCKS
# the token-validation fallback as well -- so the A-record path does not merely fail to help, it closes
# the only other door. Setting these to anything other than addresses Cloudflare has allocated to this
# SaaS zone through its Apex Proxying add-on produces instructions that can never verify, and it also
# suppresses the ALIAS/flattening row that IS the working apex path today.
#
# Set them ONLY from an Apex Proxying allocation. Never from `dig domains.jbay.uk`.
#
# THEY CANNOT SIMPLY BE PASSED AS EMPTY, which is why this is a guard and not an override. The shorthand
# `CloudflareApexIpv4=` is rejected outright ("is not in valid format"), and the long
# `ParameterKey=CloudflareApexIpv4,ParameterValue=` form parses but is DROPPED -- CloudFormation then
# keeps the previous value. Both were tried on 2026-10-23 and the changeset came back still carrying the
# old addresses. Clearing them took a one-off `update-stack --use-previous-template` with every other
# parameter on UsePreviousValue.
#
# So: nothing is passed, and instead the live value is compared against the intent. Stored state and
# served reality drifting with nothing comparing them is the shape of most of this week's bugs; here the
# comparison costs one describe-stacks and turns a silent wrong answer into a stopped deploy.
APEX_IPS_LIVE="$(aws cloudformation describe-stacks \
  --region "${REGION}" --stack-name "${STACK_NAME}" \
  --query "Stacks[0].Parameters[?ParameterKey=='CloudflareApexIpv4'].ParameterValue | [0]" \
  --output text 2>/dev/null)"
if [[ -n "${APEX_IPS_LIVE}" && "${APEX_IPS_LIVE}" != "None" ]]; then
  echo "ERROR: ${STACK_NAME} has CloudflareApexIpv4='${APEX_IPS_LIVE}'." >&2
  echo "       Apex A records only work with addresses Cloudflare allocated to this SaaS zone through" >&2
  echo "       its Apex Proxying add-on. Anything else hands tenants records that can never verify and" >&2
  echo "       suppresses the ALIAS row that does work. See the comment above this check." >&2
  echo "       If Apex Proxying IS now in place, remove this guard in the same change that sets them." >&2
  exit 1
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
