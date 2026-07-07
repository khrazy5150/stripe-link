#!/usr/bin/env bash
#
# Validate the stored Google OAuth credentials: exchange the refresh token for an
# access token, then run two read-only Calendar calls (calendarList + freeBusy).
# Distinguishes a bad refresh token (expired/revoked) from bad client credentials.
#
# Usage:  ./deploy/google-oauth-test.sh [dev|prod]
#
set -euo pipefail

ENVIRONMENT="${1:-dev}"
REGION="${AWS_REGION:-us-west-2}"
SECRET_NAME="${GOOGLE_OAUTH_SECRET_NAME:-jb/google-oauth/${ENVIRONMENT}}"

echo "Testing Google OAuth credentials from ${SECRET_NAME} (${REGION})"
SECRET="$(aws secretsmanager get-secret-value --secret-id "${SECRET_NAME}" --region "${REGION}" --query SecretString --output text)"

read_field() { printf '%s' "$SECRET" | python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))"; }
CLIENT_ID="$(read_field client_id)"
CLIENT_SECRET="$(read_field client_secret)"
REFRESH_TOKEN="$(read_field refresh_token)"

if [ -z "$CLIENT_ID" ] || [ -z "$CLIENT_SECRET" ] || [ -z "$REFRESH_TOKEN" ]; then
  echo "Secret is missing one of client_id / client_secret / refresh_token."; exit 1
fi

RESP="$(curl -s -X POST https://oauth2.googleapis.com/token \
  --data-urlencode client_id="$CLIENT_ID" \
  --data-urlencode client_secret="$CLIENT_SECRET" \
  --data-urlencode refresh_token="$REFRESH_TOKEN" \
  --data-urlencode grant_type=refresh_token)"

ACCESS_TOKEN="$(printf '%s' "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true)"

if [ -z "$ACCESS_TOKEN" ]; then
  echo "=== TOKEN EXCHANGE FAILED ==="
  printf '%s\n' "$RESP"
  ERR="$(printf '%s' "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('error',''))" 2>/dev/null || true)"
  case "$ERR" in
    invalid_grant)  echo ">> Diagnosis: the REFRESH TOKEN is bad (expired / revoked / superseded). Client id+secret are fine. Re-mint the refresh token and re-run google-oauth-secrets.sh." ;;
    invalid_client) echo ">> Diagnosis: the CLIENT ID or SECRET is wrong. Re-check and re-run google-oauth-secrets.sh." ;;
    *)              echo ">> Diagnosis: see the error payload above." ;;
  esac
  exit 1
fi

echo "=== Token exchange: OK ==="
printf '%s' "$RESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print('scopes    :',d.get('scope','(none)'));print('expires_in:',d.get('expires_in'),'s')"

echo; echo "=== calendarList (read-only) ==="
curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "https://www.googleapis.com/calendar/v3/users/me/calendarList?maxResults=10" \
 | python3 -c "import sys,json
d=json.load(sys.stdin)
if 'error' in d:
    print('error:', d['error']); raise SystemExit(1)
for c in d.get('items', []):
    print(' -', c.get('summary'), '| id=', c.get('id'), '| access=', c.get('accessRole'), ('| primary' if c.get('primary') else ''))"

echo; echo "=== freeBusy (read-only, primary, next 7 days) ==="
TMIN="$(python3 -c "import datetime;print(datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")"
TMAX="$(python3 -c "import datetime;print((datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ'))")"
curl -s -H "Authorization: Bearer $ACCESS_TOKEN" -H "Content-Type: application/json" -X POST "https://www.googleapis.com/calendar/v3/freeBusy" \
  -d "{\"timeMin\":\"$TMIN\",\"timeMax\":\"$TMAX\",\"items\":[{\"id\":\"primary\"}]}" \
 | python3 -c "import sys,json
d=json.load(sys.stdin)
if 'error' in d:
    print('error:', d['error']); raise SystemExit(1)
cal=(d.get('calendars') or {}).get('primary', {})
print('busy intervals:', len(cal.get('busy', [])), cal.get('busy', [])[:3])"

echo; echo "All checks passed — these credentials work."
