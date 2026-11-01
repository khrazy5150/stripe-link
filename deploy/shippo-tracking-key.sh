#!/usr/bin/env bash
# Store the PLATFORM's Shippo keys, used for one thing: registering trackers.
#
#   ./deploy/shippo-tracking-key.sh dev  shippo_test_xxx            # test key only
#   ./deploy/shippo-tracking-key.sh prod shippo_live_xxx shippo_test_xxx
#
# Shipping is BYOK per tenant and stays that way: every tenant's own Shippo account buys their labels.
# Tracking is the ONE Shippo call this platform makes with its own credentials, because a tracker
# registered with a tenant's key reports to a webhook on THEIR account -- which is not ours, and which no
# tenant is going to configure. See src/stripe_link/shippo_tracking.py.
#
# THIS IS NOT A PLATFORM/PARTNER ACCOUNT. It is an ordinary Shippo account whose Tracking API is used to
# follow parcels "created outside of Shippo" by carrier and tracking number. It buys no labels and needs no
# partner agreement.
#
# USE A DEDICATED KEY, NOT THE ONE A TENANT'S SHIPPING CONFIG ALREADY HOLDS. Shippo allows two live keys
# and two test keys per account, and spending one on tracking buys rotation independence: regenerating the
# tracking key then cannot stop labels being bought, and a leaked platform secret costs one key rather than
# both. The alternative -- the same value in the per-tenant shipping config AND in Secrets Manager -- fails
# in the shape that is hardest to read: labels keep working while tracking goes quiet, which looks like
# Shippo being slow rather than an auth failure.
#
# Note the consequence once both live slots are in use: a future rotation cannot do create-new-then-swap,
# so it has to delete first and run briefly on one key. Harmless for THIS key (registrations stop for the
# gap and those parcels carry no feed, which everything already handles) and not harmless for the label
# key, so rotate that one deliberately.
#
# TWO KEYS. The live key tracks real parcels and is billed per tracking number, since a label bought on a
# tenant's account is "not created on" this one. The test key accepts Shippo's mock tracking numbers and
# costs nothing, so a test-mode order never burns a paid track on a parcel that does not exist. They are
# chosen by the STRIPE mode of the shipment.
#
# Until this is set, registration is simply OFF: parcels carry no tracking, exactly as before, and the
# delivery-guarantee sweep stays silent on them because `observable` refuses to report what it cannot see.
#
# Set the webhook first (./deploy/shippo-webhook-secret.sh) and paste its URL into THIS account's
# Settings -> Webhooks with the Track Updated event. Shippo requires a registered webhook before POSTing
# to the tracking endpoint, and now there is only one account to do it on.
set -euo pipefail

ENVIRONMENT="${1:-}"
FIRST_KEY="${2:-}"
SECOND_KEY="${3:-}"
REGION="${AWS_REGION:-us-west-2}"

if [[ "${ENVIRONMENT}" != "dev" && "${ENVIRONMENT}" != "prod" ]]; then
  echo "Usage: $0 <dev|prod> <key> [second-key]" >&2
  exit 1
fi
if [[ -z "${FIRST_KEY}" ]]; then
  echo "A Shippo API key is required. Live keys start shippo_live_, test keys shippo_test_." >&2
  exit 1
fi

# Sorted by what the key SAYS IT IS rather than by argument order, so putting them the other way round
# cannot quietly file a live key as the test one -- which would bill real tracking against test orders.
LIVE_KEY=""
TEST_KEY=""
for key in "${FIRST_KEY}" "${SECOND_KEY}"; do
  [[ -z "${key}" ]] && continue
  case "${key}" in
    shippo_live_*) LIVE_KEY="${key}" ;;
    shippo_test_*) TEST_KEY="${key}" ;;
    *) echo "Unrecognised key '${key:0:14}...' — expected shippo_live_ or shippo_test_." >&2; exit 1 ;;
  esac
done

SECRET_NAME="jb/shippo-tracking/${ENVIRONMENT}"
PAYLOAD="$(printf '{"live_key":"%s","test_key":"%s"}' "${LIVE_KEY}" "${TEST_KEY}")"

if aws secretsmanager describe-secret --secret-id "${SECRET_NAME}" --region "${REGION}" >/dev/null 2>&1; then
  aws secretsmanager put-secret-value --secret-id "${SECRET_NAME}" \
    --secret-string "${PAYLOAD}" --region "${REGION}" >/dev/null
  echo "Updated ${SECRET_NAME}"
else
  aws secretsmanager create-secret --name "${SECRET_NAME}" \
    --description "Platform Shippo key for tracking registration (${ENVIRONMENT})" \
    --secret-string "${PAYLOAD}" --region "${REGION}" >/dev/null
  echo "Created ${SECRET_NAME}"
fi

echo
[[ -n "${LIVE_KEY}" ]] && echo "  live_key: set — real parcels will be tracked, billed per tracking number."
[[ -z "${LIVE_KEY}" ]] && echo "  live_key: EMPTY — live-mode parcels carry no tracking feed."
[[ -n "${TEST_KEY}" ]] && echo "  test_key: set — test-mode orders track Shippo's mock numbers, free."
[[ -z "${TEST_KEY}" ]] && echo "  test_key: EMPTY — test-mode parcels carry no tracking feed."
echo
echo "Lambdas cache the key per process, so a change takes effect as containers recycle."
