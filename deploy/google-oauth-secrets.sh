#!/usr/bin/env bash
#
# Store / rotate the platform Google OAuth credentials in AWS Secrets Manager
# (encrypted at rest with KMS). Prompts for each value individually; press Enter
# at a prompt to KEEP the existing value, or type a new one to OVERRIDE it.
#
# Usage:  ./deploy/google-oauth-secrets.sh [dev|prod]
#
set -euo pipefail

ENVIRONMENT="${1:-dev}"
REGION="${AWS_REGION:-us-west-2}"
SECRET_NAME="${GOOGLE_OAUTH_SECRET_NAME:-jb/google-oauth/${ENVIRONMENT}}"

echo "Google OAuth credentials -> Secrets Manager"
echo "  secret : ${SECRET_NAME}"
echo "  region : ${REGION}"
echo "  (press Enter to keep an existing value)"
echo

# Load the current value (if any) so a blank prompt keeps it.
EXISTING="$(aws secretsmanager get-secret-value --secret-id "${SECRET_NAME}" --region "${REGION}" \
  --query SecretString --output text 2>/dev/null || echo '{}')"

read -r  -p "Client ID: " CLIENT_ID
read -r -s -p "Client Secret (hidden): " CLIENT_SECRET; echo
read -r -s -p "Refresh Token (hidden): " REFRESH_TOKEN; echo

PAYLOAD="$(EXISTING="$EXISTING" CLIENT_ID="$CLIENT_ID" CLIENT_SECRET="$CLIENT_SECRET" REFRESH_TOKEN="$REFRESH_TOKEN" python3 - <<'PY'
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

out = {
    "client_id": pick("client_id", os.environ["CLIENT_ID"]),
    "client_secret": pick("client_secret", os.environ["CLIENT_SECRET"]),
    "refresh_token": pick("refresh_token", os.environ["REFRESH_TOKEN"]),
}
missing = [k for k, v in out.items() if not v]
if missing:
    raise SystemExit("No value entered and none stored for: " + ", ".join(missing))
print(json.dumps(out))
PY
)"

if aws secretsmanager describe-secret --secret-id "${SECRET_NAME}" --region "${REGION}" >/dev/null 2>&1; then
  aws secretsmanager put-secret-value --secret-id "${SECRET_NAME}" --secret-string "${PAYLOAD}" --region "${REGION}" >/dev/null
  echo "Updated secret (new version created)."
else
  aws secretsmanager create-secret --name "${SECRET_NAME}" --secret-string "${PAYLOAD}" --region "${REGION}" \
    --description "Platform Google OAuth credentials + test refresh token (${ENVIRONMENT})" >/dev/null
  echo "Created secret."
fi

# Masked confirmation — never print full secret values.
printf '%s' "${PAYLOAD}" | python3 -c "import sys,json
d=json.load(sys.stdin)
mask=lambda s:(s[:6]+'…'+s[-4:]) if len(s)>12 else '***'
print('Stored:')
[print('  %-14s %s'%(k+':',mask(v))) for k,v in d.items()]"
