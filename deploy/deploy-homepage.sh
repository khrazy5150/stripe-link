#!/usr/bin/env bash
set -euo pipefail

# Deploy the static marketing homepage (homepage/) to its S3 bucket + invalidate CloudFront.
# No build step — the homepage is plain static HTML/CSS/JS (contrast deploy-dashboard.sh, which builds Vite).
# The bucket + distribution are created by the main stack (HomepageEnabled=true; see plans/HOMEPAGE.md).

ENVIRONMENT="${1:-prod}"
STACK_NAME="${STACK_NAME:-jb-stripe-link-stack-${ENVIRONMENT}}"
REGION="${AWS_REGION:-us-west-2}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${ROOT_DIR}/homepage"

stack_output() {
  aws cloudformation describe-stacks \
    --region "${REGION}" \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='${1}'].OutputValue | [0]" \
    --output text
}

if [[ ! -f "${SRC_DIR}/index.html" ]]; then
  echo "Homepage source not found: ${SRC_DIR}/index.html" >&2
  exit 1
fi

BUCKET="${HOMEPAGE_BUCKET:-$(stack_output HomepageBucketName)}"
DISTRIBUTION_ID="${HOMEPAGE_DISTRIBUTION_ID:-$(stack_output HomepageDistributionId)}"
HOMEPAGE_URL="${HOMEPAGE_URL:-$(stack_output HomepageUrl)}"

if [[ -z "${BUCKET}" || "${BUCKET}" == "None" ]]; then
  echo "HomepageBucketName output missing from stack ${STACK_NAME} (is HomepageEnabled=true deployed?)." >&2
  exit 1
fi
if [[ -z "${DISTRIBUTION_ID}" || "${DISTRIBUTION_ID}" == "None" ]]; then
  echo "HomepageDistributionId output missing from stack ${STACK_NAME}." >&2
  exit 1
fi

# 1) Static assets (css/images/fonts) — cache a day at the browser; edge TTL is longer (busted by invalidation).
#    Excludes *.html (short cache, below) and *.md (the images/ README is not a served asset).
# NOTE the fonts/* exclusion on --delete. The font library lives in the BUCKET, not in this repo — it is
# built by the fonts-api catalogue workflow and is far too large to track here (Merriweather alone is
# ~50MB). Without this exclusion, --delete removes every font that is not checked in, which is exactly
# what happened on 2026-09-04: a homepage deploy took the bucket from 456 woff2 files down to the 3 that
# happen to live under homepage/fonts/, and every published page silently lost its webfonts. Step 3 below
# already assumes the fonts live in the bucket, so the delete was contradicting it.
aws s3 sync "${SRC_DIR}/" "s3://${BUCKET}/" \
  --region "${REGION}" \
  --delete \
  --exclude "*.html" \
  --exclude "*.md" \
  --exclude "fonts/*" \
  --cache-control "public, max-age=86400"

# Fonts checked into the repo still upload — they are just never DELETED from the bucket.
aws s3 sync "${SRC_DIR}/fonts/" "s3://${BUCKET}/fonts/" \
  --region "${REGION}" \
  --cache-control "public, max-age=86400"

# 2) HTML — always revalidate so copy edits appear right after an invalidation.
aws s3 sync "${SRC_DIR}/" "s3://${BUCKET}/" \
  --region "${REGION}" \
  --exclude "*" \
  --include "*.html" \
  --content-type "text/html; charset=utf-8" \
  --cache-control "public, max-age=60, must-revalidate"

# 3) Fonts — set the correct content-type and treat as immutable (paths are version-stable).
aws s3 cp "s3://${BUCKET}/fonts/" "s3://${BUCKET}/fonts/" \
  --region "${REGION}" \
  --recursive \
  --exclude "*" \
  --include "*.woff2" \
  --metadata-directive REPLACE \
  --content-type "font/woff2" \
  --cache-control "public, max-age=31536000, immutable"

# 4) Extensionless copies of content pages (support.html -> /support) so clean URLs resolve on S3+CloudFront.
for page in "${SRC_DIR}"/*.html; do
  name="$(basename "${page}" .html)"
  [[ "${name}" == "index" || "${name}" == "404" ]] && continue
  aws s3 cp "${page}" "s3://${BUCKET}/${name}" \
    --region "${REGION}" \
    --content-type "text/html; charset=utf-8" \
    --cache-control "public, max-age=60, must-revalidate"
done

INVALIDATION_ID="$(aws cloudfront create-invalidation \
  --distribution-id "${DISTRIBUTION_ID}" \
  --paths "/*" \
  --query "Invalidation.Id" \
  --output text)"

echo "Homepage deployed to s3://${BUCKET}"
echo "Invalidation ${INVALIDATION_ID} created for ${DISTRIBUTION_ID}"
echo "Homepage URL: ${HOMEPAGE_URL}"
