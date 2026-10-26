#!/usr/bin/env bash
#
# Store / rotate the MANAGED DNS Cloudflare API token (plans/MANAGED_DNS.md).
#
# This is a SECOND Cloudflare token, separate from the custom-hostname one on purpose. That one mints
# custom hostnames and is read on every connect, Verify and health sweep -- wide reach through the code,
# narrow power. This one creates zones and edits DNS across all of them, so it can rewrite any tenant's
# records, their mail included -- narrow reach, wide power. Keeping them apart is what stops a leak of
# the busy credential from being unrecoverable.
#
# ---------------------------------------------------------------------------------------------------
# CREATING THE TOKEN, in the Cloudflare dashboard. It is a credential, not a domain and not a site.
#
#   1. cloudflare.com -> log in -> the profile icon, top right -> "My Profile"
#   2. "API Tokens" in the left menu -> "Create Token" -> "Create Custom Token" ("Get started")
#   3. Name it something you will recognise in a year, e.g. "junior-bay-managed-dns"
#   4. Permissions -- three rows, added with "+ Add more":
#        Account | Zone        | Edit      <- this is the one that allows creating zones
#        Zone    | DNS         | Edit
#        Zone    | Workers Routes | Edit
#   5. Account Resources : Include -> your account
#      Zone Resources    : Include -> All zones from an account -> your account
#      (NOT "Specific zone": a tenant's zone does not exist yet when you write this, so naming zones
#       here would lock the token out of every zone it is being created to manage.)
#   6. Continue -> Create Token -> copy the value. Cloudflare shows it ONCE.
#   7. Run this script and paste it.
# ---------------------------------------------------------------------------------------------------
#
# Usage:  ./deploy/cloudflare-dns-token.sh [dev|prod]
#
set -euo pipefail

ENVIRONMENT="${1:-dev}"
REGION="${AWS_REGION:-us-west-2}"
PROJECT_PREFIX="${PROJECT_PREFIX:-jb}"
SECRET_ID="${CLOUDFLARE_DNS_TOKEN_SECRET_NAME:-${PROJECT_PREFIX}-cloudflare-dns-token-${ENVIRONMENT}}"

echo "Managed DNS Cloudflare token -> Secrets Manager"
echo "  secret : ${SECRET_ID}"
echo "  region : ${REGION}"
echo

read -r -s -p "Paste the token (input hidden): " TOKEN
echo
if [[ -z "${TOKEN}" ]]; then
  echo "No token entered; nothing changed." >&2
  exit 1
fi

# VERIFIED BEFORE IT IS STORED. A token missing the account-level Zone:Edit permission looks identical to
# a working one until the first tenant tries to move their domain, and by then the failure is in front of
# a customer. The probe uses a deliberately invalid zone name: it cannot create anything, and the error
# it comes back with distinguishes "wrong permissions" from "wrong token" from "fine".
echo "==> Checking the token before storing it..."
VERIFY="$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "https://api.cloudflare.com/client/v4/user/tokens/verify" || true)"
if ! grep -q '"success":true' <<<"${VERIFY}"; then
  echo "    Cloudflare rejected this token outright. Not stored." >&2
  echo "    ${VERIFY}" >&2
  exit 1
fi

ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "https://api.cloudflare.com/client/v4/accounts" \
  | python3 -c 'import json,sys; r=(json.load(sys.stdin).get("result") or []); print(r[0]["id"] if r else "")' || true)}"

if [[ -n "${ACCOUNT_ID}" ]]; then
  PROBE="$(curl -s -X POST -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
    --data "{\"name\":\"not a valid domain\",\"account\":{\"id\":\"${ACCOUNT_ID}\"},\"type\":\"full\"}" \
    "https://api.cloudflare.com/client/v4/zones" || true)"
  if grep -q "zone.create" <<<"${PROBE}"; then
    echo "    This token CANNOT create zones -- it is missing Account | Zone | Edit." >&2
    echo "    Add that permission in the Cloudflare dashboard and run this again. Not stored." >&2
    exit 1
  fi
  echo "    Zone-create permission looks present."
else
  echo "    Could not read the account list; storing without the zone-create probe."
fi

aws secretsmanager put-secret-value \
  --secret-id "${SECRET_ID}" \
  --secret-string "${TOKEN}" \
  --region "${REGION}" \
  --query 'VersionId' --output text >/dev/null

echo "==> Stored. It is read at RUNTIME, so no redeploy is needed for the value itself."
echo "    A stack deploy IS needed once, to create the secret and hand its ARN to the functions:"
echo "      ./deploy/deploy.sh ${ENVIRONMENT}"
