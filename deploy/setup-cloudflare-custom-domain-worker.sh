#!/usr/bin/env bash
set -euo pipefail

# Uploads deploy/cloudflare-custom-domain-worker.js as a Cloudflare Worker and routes it
# in front of the custom domain fallback origin (CustomDomainTargetHost, e.g.
# domains.jbay.uk). Run this once after the stripe-link stack is deployed, and again
# whenever the worker script changes.
#
# Requires: aws CLI (to read the API token secret + stack output), jq, curl.
# Requires: CLOUDFLARE_API_TOKEN_SECRET_ID pointing at the secret created by template.yaml
# (default matches the CloudflareApiTokenSecret resource name) already populated with a
# real Cloudflare API token (Zone:SSL and Certificates:Edit, Zone:Custom Hostname:Edit,
# Account:Workers Scripts:Edit, Zone:Workers Routes:Edit scopes).

STACK_NAME="${STACK_NAME:-jb-stripe-link-stack-dev}"
REGION="${AWS_REGION:-us-west-2}"
PROJECT_PREFIX="${PROJECT_PREFIX:-jb}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
SECRET_ID="${CLOUDFLARE_API_TOKEN_SECRET_ID:-${PROJECT_PREFIX}-cloudflare-api-token-${ENVIRONMENT}}"
ZONE_ID="${CLOUDFLARE_ZONE_ID:?Set CLOUDFLARE_ZONE_ID to the Cloudflare zone used for custom domains}"
SCRIPT_NAME="${CLOUDFLARE_WORKER_SCRIPT_NAME:-${PROJECT_PREFIX}-custom-domain-router-${ENVIRONMENT}}"
SCRIPT_FILE="${CLOUDFLARE_WORKER_SCRIPT_FILE:-$(dirname "$0")/cloudflare-custom-domain-worker.js}"
ROUTE_PATTERN="${CLOUDFLARE_WORKER_ROUTE_PATTERN:-*/*}"

if [[ ! -f "$SCRIPT_FILE" ]]; then
  echo "Worker script not found: $SCRIPT_FILE" >&2
  exit 1
fi

echo "Looking up API base URL from stack $STACK_NAME..."
api_base_url="$(aws cloudformation describe-stacks \
  --region "$REGION" \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='CustomApiUrl' || OutputKey=='ApiUrl'] | [0].OutputValue" \
  --output text)"

if [[ -z "$api_base_url" || "$api_base_url" == "None" ]]; then
  echo "Could not determine the stack's API base URL from CloudFormation outputs." >&2
  exit 1
fi
echo "Using API base URL: $api_base_url"

api_token="$(aws secretsmanager get-secret-value \
  --region "$REGION" \
  --secret-id "$SECRET_ID" \
  --query SecretString \
  --output text)"

if [[ -z "$api_token" || "$api_token" == "PLACEHOLDER-SET-VIA-put-secret-value" ]]; then
  echo "Cloudflare API token secret ($SECRET_ID) is not populated yet." >&2
  echo "Set it with: aws secretsmanager put-secret-value --region $REGION --secret-id $SECRET_ID --secret-string 'YOUR_TOKEN'" >&2
  exit 1
fi

account_id="$(curl -sS \
  -H "Authorization: Bearer $api_token" \
  -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/$ZONE_ID" \
  | jq -r '.result.account.id // empty')"

if [[ -z "$account_id" ]]; then
  echo "Unable to determine Cloudflare account id from zone $ZONE_ID" >&2
  exit 1
fi

worker_tmp="$(mktemp)"
trap 'rm -f "$worker_tmp"' EXIT
sed "s#https://REPLACE_WITH_PUBLIC_API_BASE_URL#${api_base_url}#" "$SCRIPT_FILE" > "$worker_tmp"

echo "Uploading Cloudflare Worker $SCRIPT_NAME..."
upload_response="$(curl -sS -X PUT \
  -H "Authorization: Bearer $api_token" \
  -H "Content-Type: application/javascript" \
  --data-binary "@$worker_tmp" \
  "https://api.cloudflare.com/client/v4/accounts/$account_id/workers/scripts/$SCRIPT_NAME")"
jq . <<<"$upload_response"
if [[ "$(jq -r '.success' <<<"$upload_response")" != "true" ]]; then
  echo "Cloudflare Worker upload failed" >&2
  exit 1
fi

echo "Ensuring Worker route $ROUTE_PATTERN..."
routes_json="$(curl -sS \
  -H "Authorization: Bearer $api_token" \
  -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/workers/routes")"

existing_route_id="$(jq -r --arg pattern "$ROUTE_PATTERN" --arg script "$SCRIPT_NAME" \
  '.result[]? | select(.pattern == $pattern and .script == $script) | .id' <<<"$routes_json" | head -n 1)"

if [[ -n "$existing_route_id" ]]; then
  echo "Worker route already exists: $existing_route_id"
else
  route_response="$(curl -sS -X POST \
    -H "Authorization: Bearer $api_token" \
    -H "Content-Type: application/json" \
    --data "$(jq -nc --arg pattern "$ROUTE_PATTERN" --arg script "$SCRIPT_NAME" '{pattern:$pattern, script:$script}')" \
    "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/workers/routes")"
  jq . <<<"$route_response"
  if [[ "$(jq -r '.success' <<<"$route_response")" != "true" ]]; then
    echo "Cloudflare Worker route creation failed" >&2
    exit 1
  fi
fi

echo "Done. Tenants can now CNAME their subdomain to the CustomDomainTargetHost."
