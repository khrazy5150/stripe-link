#!/usr/bin/env bash
#
# Reveal the SMS origination identity currently stored in Secrets Manager for an
# environment (read-only — makes no changes). Handy when you forget which number is
# live. Set/rotate the value with ./deploy/sms-origination-secrets.sh instead.
#
# Usage:  ./deploy/sms-origination-phone.sh [dev|prod]
#
set -euo pipefail

ENVIRONMENT="${1:-dev}"
REGION="${AWS_REGION:-us-west-2}"
SECRET_NAME="${SMS_ORIGINATION_SECRET_NAME:-jb/sms-origination/${ENVIRONMENT}}"

echo "SMS origination identity"
echo "  secret : ${SECRET_NAME}"
echo "  region : ${REGION}"
echo

PAYLOAD="$(aws secretsmanager get-secret-value --secret-id "${SECRET_NAME}" --region "${REGION}" \
  --query SecretString --output text 2>/dev/null || true)"

if [[ -z "${PAYLOAD}" ]]; then
  echo "Not set — no secret found for ${ENVIRONMENT}."
  echo "SMS reminders are OFF for this environment. Set a number with:"
  echo "  ./deploy/sms-origination-secrets.sh ${ENVIRONMENT}"
  exit 0
fi

printf '%s' "${PAYLOAD}" | python3 -c "import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
identity = (d.get('origination_identity') or '').strip()
config_set = (d.get('configuration_set') or '').strip()
if not identity:
    print('Not set — secret exists but has no origination_identity.')
    print('SMS reminders are OFF for this environment.')
    raise SystemExit(0)
print('  origination_identity :', identity)
print('  configuration_set    :', config_set or '(none)')
print()
print('SMS reminders are ON for this environment.')"
