#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT="${1:-dev}"
STACK_NAME="${STACK_NAME:-jb-stripe-link-stack-${ENVIRONMENT}}"
REGION="${AWS_REGION:-us-west-2}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DASHBOARD_APP_DIR="${ROOT_DIR}/dashboard-vue"
DASHBOARD_DIR="${DASHBOARD_DIR:-${DASHBOARD_APP_DIR}/dist}"

stack_output() {
  local output_key="$1"
  aws cloudformation describe-stacks \
    --region "${REGION}" \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='${output_key}'].OutputValue | [0]" \
    --output text
}

if [[ ! -d "${DASHBOARD_APP_DIR}" ]]; then
  echo "Dashboard app directory not found: ${DASHBOARD_APP_DIR}" >&2
  exit 1
fi

npm --prefix "${DASHBOARD_APP_DIR}" run build

if [[ ! -d "${DASHBOARD_DIR}" ]]; then
  echo "Dashboard build directory not found: ${DASHBOARD_DIR}" >&2
  exit 1
fi

DASHBOARD_BUCKET="${DASHBOARD_BUCKET:-$(stack_output DashboardBucketName)}"
DASHBOARD_DISTRIBUTION_ID="${DASHBOARD_DISTRIBUTION_ID:-$(stack_output DashboardDistributionId)}"
DASHBOARD_URL="${DASHBOARD_URL:-$(stack_output DashboardUrl)}"

if [[ -z "${DASHBOARD_BUCKET}" || "${DASHBOARD_BUCKET}" == "None" ]]; then
  echo "DashboardBucketName output is missing from stack ${STACK_NAME}." >&2
  exit 1
fi

if [[ -z "${DASHBOARD_DISTRIBUTION_ID}" || "${DASHBOARD_DISTRIBUTION_ID}" == "None" ]]; then
  echo "DashboardDistributionId output is missing from stack ${STACK_NAME}." >&2
  exit 1
fi

aws s3 sync "${DASHBOARD_DIR}/" "s3://${DASHBOARD_BUCKET}/" \
  --region "${REGION}" \
  --delete \
  --cache-control "no-cache, no-store, must-revalidate"

INVALIDATION_ID="$(aws cloudfront create-invalidation \
  --distribution-id "${DASHBOARD_DISTRIBUTION_ID}" \
  --paths "/*" \
  --query "Invalidation.Id" \
  --output text)"

echo "Dashboard deployed to s3://${DASHBOARD_BUCKET}"
echo "Invalidation ${INVALIDATION_ID} created for ${DASHBOARD_DISTRIBUTION_ID}"
echo "Dashboard URL: ${DASHBOARD_URL}"
