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
#   4. Permissions -- the left dropdown is the RESOURCE TYPE, the middle one is the permission. All
#      three rows are "Zone" on the left; there is no account-scoped "Zone" permission, which is the
#      opposite of what this file said until 2026-10-25:
#        Zone | Zone           | Edit   <- "write access to zone management", i.e. creating them
#        Zone | DNS            | Edit
#        Zone | Workers Routes | Edit
#      Optional fourth row, only so this script can run its check below:
#        Account | Account Settings | Read
#      The middle dropdown is a filter box -- type "zone" rather than scrolling; the list is long and
#      "Zone" sorts after every "Zero Trust" entry, right at the bottom.
#   5. Account Resources : Include -> your account
#      Zone Resources    : Include -> All zones from an account -> your account
#      (NOT "Specific zone": a tenant's zone does not exist yet when you write this, so naming zones
#       here would lock the token out of every zone it is being created to manage. This is also what
#       makes a zone-scoped permission able to create a zone at all -- the policy has to cover zones
#       that do not exist when it is written.)
#   6. Continue -> Create Token -> copy the value. Cloudflare shows it ONCE.
#   7. Run this script and paste it.
# ---------------------------------------------------------------------------------------------------
#
# ONE TOKEN, TWO SECRETS. Each stack creates and grants its own secret, so there are two to populate --
# but the value can be the same, and for the existing custom-hostname token it already is (verified
# 2026-10-25: identical in both). There is one Cloudflare account and a managed-DNS token must be scoped
# to all zones in order to create new ones, so a dev token can already reach a prod tenant's zone:
# separate values would isolate the CREDENTIAL, not the data. Worth it only if you want to revoke dev
# without a prod outage; pass `dev` and `prod` separately with different tokens if so.
#
# `all` prompts once and writes both, which also stops the two drifting -- a rotation applied to one
# secret and not the other fails on exactly one code path, days later.
#
# Usage:  ./deploy/cloudflare-dns-token.sh [dev|prod|all]
#
set -euo pipefail

TARGET="${1:-all}"
case "${TARGET}" in
  dev|prod) ENVIRONMENTS=("${TARGET}") ;;
  all)      ENVIRONMENTS=(dev prod) ;;
  *) echo "Usage: $0 [dev|prod|all]" >&2; exit 1 ;;
esac
REGION="${AWS_REGION:-us-west-2}"
PROJECT_PREFIX="${PROJECT_PREFIX:-jb}"

echo "Managed DNS Cloudflare token -> Secrets Manager"
for env in "${ENVIRONMENTS[@]}"; do
  echo "  secret : ${CLOUDFLARE_DNS_TOKEN_SECRET_NAME:-${PROJECT_PREFIX}-cloudflare-dns-token-${env}}"
done
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
    echo "    This token CANNOT create zones -- it is missing  Zone | Zone | Edit  with" >&2
    echo "    Zone Resources set to 'All zones from an account'. Add that and run this again." >&2
    echo "    Not stored." >&2
    exit 1
  fi
  echo "    Zone-create permission looks present."
else
  echo "    Could not read the account list (the token has no Account Settings:Read), so the"
  echo "    zone-create check was SKIPPED -- the token is stored unverified. To check it, re-run with"
  echo "      CLOUDFLARE_ACCOUNT_ID=<your account id> ./deploy/cloudflare-dns-token.sh ${ENVIRONMENT}"
fi

for env in "${ENVIRONMENTS[@]}"; do
  SECRET_ID="${CLOUDFLARE_DNS_TOKEN_SECRET_NAME:-${PROJECT_PREFIX}-cloudflare-dns-token-${env}}"
  if aws secretsmanager put-secret-value \
      --secret-id "${SECRET_ID}" \
      --secret-string "${TOKEN}" \
      --region "${REGION}" \
      --query 'VersionId' --output text >/dev/null 2>&1; then
    echo "==> Stored in ${SECRET_ID}"
  else
    # The usual cause, and worth saying rather than printing an AWS error: the stack that owns this
    # secret has not been deployed since CloudflareDnsTokenSecret was added, so it does not exist yet.
    echo "    Could not write ${SECRET_ID}." >&2
    echo "    If that secret does not exist yet, deploy the stack once and re-run:" >&2
    echo "      ./deploy/deploy.sh ${env}" >&2
  fi
done

echo
echo "The value is read at RUNTIME, so rotating it later needs no redeploy. A stack deploy is needed"
echo "only once per environment, to create the secret and hand its ARN to the functions."
