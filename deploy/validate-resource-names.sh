#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="${ROOT_DIR}/template.yaml"

if ! grep -q "Default: jb" "${TEMPLATE}"; then
  echo "ProjectPrefix must default to jb." >&2
  exit 1
fi

if grep -Eq '(TableName|BucketName|FunctionName): !Sub "stripe-' "${TEMPLATE}"; then
  echo "Found legacy stripe-* resource naming without the jb prefix in template.yaml." >&2
  exit 1
fi

if grep -Eq '(TableName|BucketName|FunctionName): "(stripe-|landing-pages-|dashboard-|products-|offers-|orders-)' "${TEMPLATE}"; then
  echo "Found hard-coded legacy resource naming in template.yaml." >&2
  exit 1
fi

if grep -Eq 'TableName:.*[^}]-(dev|prod)"' "${TEMPLATE}" && ! grep -q 'TableName: !Sub "${ProjectPrefix}-' "${TEMPLATE}"; then
  echo "DynamoDB table names must use the ProjectPrefix parameter." >&2
  exit 1
fi

if grep -Eq 'BucketName:.*[^}]-(dev|prod)-' "${TEMPLATE}" && ! grep -q 'BucketName: !Sub "${ProjectPrefix}-' "${TEMPLATE}"; then
  echo "S3 bucket names must use the ProjectPrefix parameter." >&2
  exit 1
fi

if grep -Eq 'FunctionName:.*[^}]-(dev|prod)"' "${TEMPLATE}" && ! grep -q 'FunctionName: !Sub "${ProjectPrefix}-' "${TEMPLATE}"; then
  echo "Lambda function names must use the ProjectPrefix parameter." >&2
  exit 1
fi

echo "Resource naming guard passed."
