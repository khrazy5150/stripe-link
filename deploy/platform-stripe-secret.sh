#!/usr/bin/env bash
#
# Store / rotate the PLATFORM Stripe secrets in AWS Secrets Manager.
#
# Why this exists: until 2026-11-09 both stacks pointed STRIPE_PLATFORM_SECRET_ARN at
# `stripe-cart/{env}/platform/stripe`, a secret that was deleted along with stripe-cart's deployment on
# 2026-11-03. Every Connect charge path -- checkout, invoice send, tips, upsells, refunds, Connect
# onboarding, platform billing, and webhook signature verification -- resolves its key through that
# secret, so all of them were broken in BOTH environments. It surfaced late only because the platform
# had taken no payments in between.
#
# Values are read with a HIDDEN prompt and never echoed, never passed as an argument (argv is visible to
# every process on the box) and never written to a file. Press Enter at any prompt to KEEP the existing
# value, so this is safe to re-run to fill in one key.
#
# Usage:  ./deploy/platform-stripe-secret.sh [dev|prod]
#
set -euo pipefail

ENVIRONMENT="${1:-dev}"
REGION="${AWS_REGION:-us-west-2}"
SECRET_NAME="${PLATFORM_STRIPE_SECRET_NAME:-jb/platform-stripe/${ENVIRONMENT}}"

if [[ "${ENVIRONMENT}" != "dev" && "${ENVIRONMENT}" != "prod" ]]; then
  echo "Environment must be dev or prod (got '${ENVIRONMENT}')." >&2
  exit 2
fi

echo "Platform Stripe secrets -> Secrets Manager"
echo "  secret : ${SECRET_NAME}"
echo "  region : ${REGION}"
echo "  (press Enter at a prompt to keep the existing value; nothing you type is echoed)"
echo

EXISTING="$(aws secretsmanager get-secret-value --secret-id "${SECRET_NAME}" --region "${REGION}" \
  --query SecretString --output text 2>/dev/null || echo '{}')"

# Read one value without echoing it, and keep the existing one on an empty answer. The value goes
# straight into the JSON via python's stdin -- it is never a shell argument and never a file.
ask() {
  local key="$1" label="$2" value=""
  read -r -s -p "  ${label}: " value
  echo
  if [[ -n "${value}" ]]; then
    EXISTING="$(KEY="${key}" VALUE="${value}" CURRENT="${EXISTING}" python3 -c '
import json, os
doc = json.loads(os.environ["CURRENT"] or "{}")
doc[os.environ["KEY"]] = os.environ["VALUE"]
print(json.dumps(doc))')"
    echo "    set (${#value} chars)"
  else
    local had
    had="$(KEY="${key}" CURRENT="${EXISTING}" python3 -c '
import json, os
print("yes" if json.loads(os.environ["CURRENT"] or "{}").get(os.environ["KEY"]) else "no")')"
    [[ "${had}" == "yes" ]] && echo "    kept existing" || echo "    still unset"
  fi
}

echo "Stripe API keys (platform account -- Developers > API keys):"
ask sk_test "sk_test_... (test secret key)"
ask sk_live "sk_live_... (live secret key)"
echo
# WHICH ENDPOINT MAPS TO WHICH KEY. `kind` is decided by the URL PATH (stripe_webhook.py:113):
#
#   .../webhook/stripe-preview    -> kind "preview"           -> whsec_preview_{mode}
#   .../webhook/stripe            -> kind "stable"            -> whsec_stable_{mode}
#   .../webhook/platform-billing  -> kind "platform_billing"  -> whsec_platform_billing_{mode}
#
# A signing secret belongs to the ENDPOINT, not the account, so read each one off the destination whose
# URL matches, in the Stripe dashboard mode that matches (LIVE view -> _live, sandbox/test -> _test).
#
# PREVIEW IS THE ONE IN USE. Nothing is pointed at /webhook/stripe, so "stable" is unused today -- leave
# it blank rather than pasting a preview secret into it, or signature checks fail in a way that reads as
# Stripe sending bad events.
echo "Connect webhook signing secret -- the destination ending /webhook/stripe-preview"
echo "  (prod: 'stripe-connect-preview-prod'   dev: 'sandbox-preview-live')"
ask whsec_preview_test "whsec_... (connect/preview, TEST)"
ask whsec_preview_live "whsec_... (connect/preview, LIVE)"
echo
echo "Platform billing signing secret -- the destination ending /webhook/platform-billing"
echo "  (prod: 'prod-junior-bay-billing'). Only needed if tenant SaaS billing is in use."
ask whsec_platform_billing_test "whsec_... (platform billing, TEST)"
ask whsec_platform_billing_live "whsec_... (platform billing, LIVE)"
echo
echo "Legacy 'stable' Connect endpoint (/webhook/stripe). NOTHING points at it today -- press Enter to skip:"
ask whsec_stable_test "whsec_... (connect/stable, TEST)"
ask whsec_stable_live "whsec_... (connect/stable, LIVE)"

if aws secretsmanager describe-secret --secret-id "${SECRET_NAME}" --region "${REGION}" >/dev/null 2>&1; then
  printf '%s' "${EXISTING}" | aws secretsmanager put-secret-value --secret-id "${SECRET_NAME}" \
    --region "${REGION}" --secret-string file:///dev/stdin >/dev/null
  echo; echo "Updated ${SECRET_NAME}"
else
  printf '%s' "${EXISTING}" | aws secretsmanager create-secret --name "${SECRET_NAME}" \
    --region "${REGION}" --description "Junior Bay platform Stripe keys (${ENVIRONMENT})" \
    --secret-string file:///dev/stdin >/dev/null
  echo; echo "Created ${SECRET_NAME}"
fi

# Masked confirmation: which keys are present and how long they are, never the values.
aws secretsmanager get-secret-value --secret-id "${SECRET_NAME}" --region "${REGION}" \
  --query SecretString --output text | python3 -c '
import json, sys
doc = json.loads(sys.stdin.read() or "{}")
print("Keys now stored:")
for k in sorted(doc):
    v = str(doc[k] or "")
    print(f"  {k:32} {len(v):>3} chars  {v[:7]}..." if v else f"  {k:32} EMPTY")'

ARN="$(aws secretsmanager describe-secret --secret-id "${SECRET_NAME}" --region "${REGION}" \
  --query ARN --output text)"
echo
echo "ARN: ${ARN}"
echo
echo "Point the stack at it (this is a PARAMETER change, so it needs a deploy):"
echo "  STRIPE_PLATFORM_SECRET_ARN='${ARN}' ./deploy/deploy.sh ${ENVIRONMENT}"
