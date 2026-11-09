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
# WHICH ENDPOINT MAPS TO WHICH KEY, and why mode is asked ONCE.
#
# `kind` is decided by the URL PATH (stripe_webhook.py:113):
#
#   .../webhook/stripe-preview    -> kind "preview"           -> whsec_preview_{mode}
#   .../webhook/stripe            -> kind "stable"            -> whsec_stable_{mode}
#   .../webhook/platform-billing  -> kind "platform_billing"  -> whsec_platform_billing_{mode}
#
# ONE ENDPOINT PER STACK CARRIES BOTH MODES. A connected account that authorised through LIVE OAuth and
# then works in test mode produces `livemode: false` events that the LIVE endpoint delivers, signed with
# the LIVE secret -- so prod's single Connect destination carries live AND test traffic, and sandbox's
# does the same (measured 2026-10-12: prod verified 0 of 36 such events before this was understood).
#
# The lookup, however, is keyed by the EVENT's mode: `webhook_secret_loader(kind, mode)`, and an empty
# result is a hard 500 BEFORE the cross-mode fallback can run. So a secret stored only under `_live`
# rejects every test-mode event outright. One endpoint therefore fills BOTH slots with the same value,
# which is why this asks once per endpoint and not once per mode.
#
# If per-mode endpoints are ever registered separately, set the two keys individually -- edit the secret
# in the console, or re-run with PLATFORM_STRIPE_SPLIT_MODES=1 to be prompted for each.
SPLIT="${PLATFORM_STRIPE_SPLIT_MODES:-}"

ask_endpoint() {
  local prefix="$1" label="$2"
  if [[ -n "${SPLIT}" ]]; then
    ask "${prefix}_test" "${label} -- TEST"
    ask "${prefix}_live" "${label} -- LIVE"
    return
  fi
  local value=""
  read -r -s -p "  ${label}: " value
  echo
  if [[ -n "${value}" ]]; then
    # The two key NAMES are composed in bash, not in python. A single quote inside a `python3 -c '...'`
    # block closes the bash string -- `os.environ['PREFIX']` arrives as `os.environ[PREFIX]` and dies with
    # NameError at the first keystroke, while `bash -n` passes because the quotes still balance.
    EXISTING="$(KEY_TEST="${prefix}_test" KEY_LIVE="${prefix}_live" VALUE="${value}" CURRENT="${EXISTING}" python3 -c '
import json, os
doc = json.loads(os.environ["CURRENT"] or "{}")
doc[os.environ["KEY_TEST"]] = os.environ["VALUE"]
doc[os.environ["KEY_LIVE"]] = os.environ["VALUE"]
print(json.dumps(doc))')"
    echo "    set (${#value} chars) -> ${prefix}_test AND ${prefix}_live"
  else
    local had
    had="$(KEY_TEST="${prefix}_test" KEY_LIVE="${prefix}_live" CURRENT="${EXISTING}" python3 -c '
import json, os
doc = json.loads(os.environ["CURRENT"] or "{}")
print("yes" if doc.get(os.environ["KEY_LIVE"]) or doc.get(os.environ["KEY_TEST"]) else "no")')"
    [[ "${had}" == "yes" ]] && echo "    kept existing" || echo "    still unset"
  fi
}

echo "Connect webhook -- the destination whose URL ends /webhook/stripe-preview"
if [[ "${ENVIRONMENT}" == "prod" ]]; then
  echo "  in Stripe this is 'stripe-connect-preview-prod' (https://prod.juniorbay.com/webhook/stripe-preview)"
else
  echo "  in Stripe this is 'sandbox-preview-live'  (https://dev.juniorbay.com/webhook/stripe-preview)"
fi
echo "  It carries BOTH live and test events, so this one value fills both mode slots."
ask_endpoint whsec_preview "whsec_... (Connect endpoint signing secret)"
echo
echo "Platform billing webhook -- the destination ending /webhook/platform-billing"
if [[ "${ENVIRONMENT}" == "prod" ]]; then
  echo "  in Stripe this is 'prod-junior-bay-billing'. Only needed if tenant SaaS billing is in use."
else
  echo "  only needed if tenant SaaS billing is in use in sandbox."
fi
ask_endpoint whsec_platform_billing "whsec_... (platform billing signing secret)"
echo
echo "Legacy 'stable' Connect endpoint (/webhook/stripe). NOTHING points at it -- press Enter to skip:"
ask_endpoint whsec_stable "whsec_... (connect/stable, unused)"

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
echo "NOW DEPLOY. The stack still points at whatever ARN it was given last; deploy.sh resolves this"
echo "secret BY NAME, so no ARN needs passing -- but nothing reads the new secret until it runs:"
echo "  ./deploy/deploy.sh ${ENVIRONMENT}"
