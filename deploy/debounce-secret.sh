#!/usr/bin/env bash
# Store the Debounce API key for one environment.
#
#   ./deploy/debounce-secret.sh dev  dbc_live_xxx
#   ./deploy/debounce-secret.sh prod dbc_live_xxx
#
# Separate keys per environment are worth the extra minute: sandbox testing then cannot burn production
# credits, and a leaked dev key can be rotated without touching live traffic.
#
# Until this is set, validation is simply OFF — check_email() fails open and the confirmation code still
# does the real work of proving the mailbox exists.
set -euo pipefail

ENVIRONMENT="${1:-}"
API_KEY="${2:-}"
REGION="${AWS_REGION:-us-west-2}"

if [[ -z "${ENVIRONMENT}" || -z "${API_KEY}" ]]; then
  echo "Usage: $0 <dev|prod> <debounce-api-key>" >&2
  exit 1
fi

SECRET_NAME="jb/debounce/${ENVIRONMENT}"
PAYLOAD="$(printf '{"api_key":"%s"}' "${API_KEY}")"

if aws secretsmanager describe-secret --secret-id "${SECRET_NAME}" --region "${REGION}" >/dev/null 2>&1; then
  aws secretsmanager put-secret-value --secret-id "${SECRET_NAME}" \
    --secret-string "${PAYLOAD}" --region "${REGION}" >/dev/null
  echo "Updated ${SECRET_NAME}"
else
  aws secretsmanager create-secret --name "${SECRET_NAME}" \
    --description "Debounce email-validation API key (${ENVIRONMENT})" \
    --secret-string "${PAYLOAD}" --region "${REGION}" >/dev/null
  echo "Created ${SECRET_NAME}"
fi

# Lambdas cache the key per process, so a rotation takes effect as containers recycle.
echo "Done. Existing Lambda containers keep the old key until they recycle."
