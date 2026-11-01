#!/usr/bin/env bash
# Store the shared token that authenticates Shippo's track_updated webhook, for one environment.
#
#   ./deploy/shippo-webhook-secret.sh dev            # generates a token for you
#   ./deploy/shippo-webhook-secret.sh prod <token>   # or set one you already have
#
# It then prints the URL to paste into Shippo (Settings -> Webhooks), which carries the token as a query
# parameter. Shippo echoes that parameter back on every POST and the handler compares it; their HMAC
# option needs their solutions team to provision a shared secret (up to ten business days), so this is
# the mechanism available today (src/stripe_link/domain/tracking.py).
#
# UNTIL THIS IS SET THE ENDPOINT REJECTS EVERYTHING. That is deliberate and the opposite of the Debounce
# key: an unconfigured deploy must not accept anonymous writes to delivery state. Nothing else breaks --
# labels are bought, parcels ship, and shipments simply carry no tracking, which is where they all started.
#
# Separate tokens per environment, for the same reason the Stripe and Debounce secrets are separated: a
# leaked sandbox token can be rotated without touching live traffic.
set -euo pipefail

ENVIRONMENT="${1:-}"
TOKEN="${2:-}"
REGION="${AWS_REGION:-us-west-2}"

if [[ "${ENVIRONMENT}" != "dev" && "${ENVIRONMENT}" != "prod" ]]; then
  echo "Usage: $0 <dev|prod> [token]" >&2
  exit 1
fi

if [[ -z "${TOKEN}" ]]; then
  # 32 bytes of urandom, hex. Long enough that guessing is not a strategy, and URL-safe without escaping.
  TOKEN="$(openssl rand -hex 32)"
  echo "Generated a token for ${ENVIRONMENT}."
fi

SECRET_NAME="jb/shippo-webhook/${ENVIRONMENT}"
PAYLOAD="$(printf '{"token":"%s"}' "${TOKEN}")"

if aws secretsmanager describe-secret --secret-id "${SECRET_NAME}" --region "${REGION}" >/dev/null 2>&1; then
  aws secretsmanager put-secret-value --secret-id "${SECRET_NAME}" \
    --secret-string "${PAYLOAD}" --region "${REGION}" >/dev/null
  echo "Updated ${SECRET_NAME}"
else
  aws secretsmanager create-secret --name "${SECRET_NAME}" \
    --description "Shippo track_updated webhook token (${ENVIRONMENT})" \
    --secret-string "${PAYLOAD}" --region "${REGION}" >/dev/null
  echo "Created ${SECRET_NAME}"
fi

STACK_NAME="jb-stripe-link-stack-${ENVIRONMENT}"
# CustomApiUrl first where it exists (dev has dev.juniorbay.com), falling back to the execute-api host.
# Either works; the custom domain survives a stack replacement, which a webhook URL pasted into another
# company's dashboard would rather not depend on.
API_BASE="$(aws cloudformation describe-stacks --region "${REGION}" --stack-name "${STACK_NAME}" \
  --query "Stacks[0].Outputs[?OutputKey=='CustomApiUrl'].OutputValue | [0]" --output text 2>/dev/null || echo "")"
if [[ -z "${API_BASE}" || "${API_BASE}" == "None" ]]; then
  API_BASE="$(aws cloudformation describe-stacks --region "${REGION}" --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue | [0]" --output text 2>/dev/null || echo "")"
fi

echo
echo "In the PLATFORM tracking account (the one whose key ./deploy/shippo-tracking-key.sh holds, NOT a"
echo "tenant's), create a Track Updated webhook for EACH of these."
echo
echo "TWO URLS FOR THIS ONE DEPLOYMENT, because ${ENVIRONMENT} serves BOTH Stripe modes -- that is the"
echo "decoupling, and it is why the Shippo environment cannot stand in for a deployment or for a mode."
echo "Register the test URL under Shippo's TEST environment and the live URL under its LIVE one; the"
echo "other deployment needs its own pair, so four webhooks in total across dev and prod."
echo
if [[ -n "${API_BASE}" && "${API_BASE}" != "None" ]]; then
  echo "  Shippo environment TEST  ->  ${API_BASE%/}/webhook/shipping-tracking?token=${TOKEN}&mode=test"
  echo "  Shippo environment LIVE  ->  ${API_BASE%/}/webhook/shipping-tracking?token=${TOKEN}&mode=live"
else
  echo "  Stack output not readable; the URLs are <your api base> plus:"
  echo "    /webhook/shipping-tracking?token=${TOKEN}&mode=test"
  echo "    /webhook/shipping-tracking?token=${TOKEN}&mode=live"
fi
echo
echo "'mode' is a QUERY parameter, not a #fragment -- a fragment never leaves the browser and would"
echo "arrive here as nothing at all. Without it the handler searches both partitions, which works until"
echo "one shipment id exists in both and a test event lands on a live parcel."
echo
echo "Shippo's URL limit is 200 characters, which these are comfortably inside."
echo "Lambdas cache the token per process, so a rotation takes effect as containers recycle --"
echo "update Shippo FIRST when rotating, or events in flight will be rejected until they do."
