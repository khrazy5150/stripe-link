#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT="${1:-dev}"
STACK_NAME="jb-stripe-link-stack-${ENVIRONMENT}"
REGION="${AWS_REGION:-us-west-2}"

"$(dirname "$0")/validate-resource-names.sh"
sam build
sam deploy \
  --stack-name "${STACK_NAME}" \
  --region "${REGION}" \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides "Environment=${ENVIRONMENT} ProjectPrefix=jb" \
  --tags "Project=stripe-link" "Environment=${ENVIRONMENT}" "ManagedBy=sam"
