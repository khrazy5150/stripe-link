#!/usr/bin/env bash
#
# Store / rotate the AWS End User Messaging SMS origination identity in AWS Secrets
# Manager, per environment. The reminder sweep reads this at RUNTIME, so setting or
# rotating the number takes effect on the next sweep with NO app redeploy. Prompts for
# each value; press Enter at a prompt to KEEP the existing value, or type a new one.
#
# Use a test/simulator number in dev and the approved A2P 10DLC number in prod. The
# value may be an E.164 phone number (e.g. +18885551234) or a phone-pool ARN.
#
# Usage:  ./deploy/sms-origination-secrets.sh [dev|prod]
#
set -euo pipefail

ENVIRONMENT="${1:-dev}"
REGION="${AWS_REGION:-us-west-2}"
SECRET_NAME="${SMS_ORIGINATION_SECRET_NAME:-jb/sms-origination/${ENVIRONMENT}}"

echo "SMS origination identity -> Secrets Manager"
echo "  secret : ${SECRET_NAME}"
echo "  region : ${REGION}"
echo "  (press Enter to keep an existing value)"
echo

# Load the current value (if any) so a blank prompt keeps it.
EXISTING="$(aws secretsmanager get-secret-value --secret-id "${SECRET_NAME}" --region "${REGION}" \
  --query SecretString --output text 2>/dev/null || echo '{}')"

read -r -p "Origination identity (E.164 number or phone-pool ARN): " ORIGINATION_IDENTITY
read -r -p "Configuration set name (optional): " CONFIGURATION_SET

PAYLOAD="$(EXISTING="$EXISTING" ORIGINATION_IDENTITY="$ORIGINATION_IDENTITY" CONFIGURATION_SET="$CONFIGURATION_SET" python3 - <<'PY'
import json, os
try:
    existing = json.loads(os.environ.get("EXISTING") or "{}")
    if not isinstance(existing, dict):
        existing = {}
except Exception:
    existing = {}

def pick(key, entered):
    entered = entered.strip()
    return entered if entered else existing.get(key, "")

out = {"origination_identity": pick("origination_identity", os.environ["ORIGINATION_IDENTITY"])}
if not out["origination_identity"]:
    raise SystemExit("No origination identity entered and none stored.")
configuration_set = pick("configuration_set", os.environ["CONFIGURATION_SET"])
if configuration_set:
    out["configuration_set"] = configuration_set
print(json.dumps(out))
PY
)"

if aws secretsmanager describe-secret --secret-id "${SECRET_NAME}" --region "${REGION}" >/dev/null 2>&1; then
  aws secretsmanager put-secret-value --secret-id "${SECRET_NAME}" --secret-string "${PAYLOAD}" --region "${REGION}" >/dev/null
  echo "Updated secret (new version created)."
else
  aws secretsmanager create-secret --name "${SECRET_NAME}" --secret-string "${PAYLOAD}" --region "${REGION}" \
    --description "AWS End User Messaging SMS origination identity for appointment reminders (${ENVIRONMENT})" >/dev/null
  echo "Created secret."
fi

printf '%s' "${PAYLOAD}" | python3 -c "import sys,json
d=json.load(sys.stdin)
print('Stored:')
[print('  %-22s %s'%(k+':',v)) for k,v in d.items()]"
echo
echo "Takes effect on the next reminder sweep (~15 min) — no redeploy needed."
