#!/usr/bin/env bash
# Which Stripe PLATFORM account is each silo actually using?
#
#   ./deploy/verify-platform-account.sh            # every silo
#   ./deploy/verify-platform-account.sh prod       # one silo
#
# Run it BEFORE and AFTER a platform-account swap (plans/ADMIN_SITE.md §4). Before, to record what you are
# leaving; after, to prove the swap landed everywhere rather than in the one place you remembered.
#
# It ASKS STRIPE who the key belongs to rather than comparing the key to something. A fingerprint can only
# tell you two silos hold the same bytes; it cannot tell you which account those bytes open, and after a
# swap that is the only question worth answering.
#
# Secrets are never printed. Keys appear as prefix + last-4 + a short digest, which is enough to tell two
# keys apart and useless to anyone reading your terminal history.
set -euo pipefail

REGION="${AWS_REGION:-us-west-2}"
SILOS=("${@:-dev prod}")
[[ $# -gt 0 ]] && SILOS=("$@") || SILOS=(dev prod)

for silo in "${SILOS[@]}"; do
  echo "=============================================================="
  echo "silo: ${silo}"
  echo "=============================================================="

  fn=$(aws lambda list-functions --region "$REGION" \
        --query "Functions[?FunctionName=='jb-coupons-api-${silo}'].FunctionName" --output text)
  if [[ -z "${fn}" ]]; then
    echo "  no deployed stack found for '${silo}' — skipping"
    continue
  fi

  arn=$(aws lambda get-function-configuration --function-name "jb-coupons-api-${silo}" \
        --region "$REGION" --query 'Environment.Variables.STRIPE_PLATFORM_SECRET_ARN' --output text)
  echo "  secret        : ${arn##*:secret:}"

  # The Connect client_id is what a tenant's OAuth authorises AGAINST. If it still names the old platform
  # after a swap, tenants reconnect to the account you are leaving — and it looks like it worked.
  cid=$(aws lambda get-function-configuration --function-name "jb-billing-connect-card-${silo}" \
        --region "$REGION" --query 'Environment.Variables.{t:STRIPE_CLIENT_ID_TEST,l:STRIPE_CLIENT_ID_LIVE}' \
        --output json 2>/dev/null || echo '{}')
  echo "  connect ids   : $(echo "$cid" | tr -d '\n ')"

  AWS_REGION="$REGION" SECRET_ARN="$arn" python3 - <<'PY'
import hashlib, json, os, subprocess, sys
from base64 import b64encode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

raw = subprocess.check_output(["aws", "secretsmanager", "get-secret-value", "--secret-id",
                               os.environ["SECRET_ARN"], "--region", os.environ["AWS_REGION"],
                               "--query", "SecretString", "--output", "text"]).decode()
payload = json.loads(raw)

def fingerprint(value: str) -> str:
    """Enough to tell two keys apart, useless to anyone reading over your shoulder."""
    return f"{value[:8]}…{value[-4:]} sha256:{hashlib.sha256(value.encode()).hexdigest()[:8]}"

for slot in ("sk_test", "sk_live"):
    key = str(payload.get(slot) or "")
    if not key:
        print(f"  {slot:<8}: (absent)")
        continue
    request = Request("https://api.stripe.com/v1/account", headers={
        "Authorization": f"Basic {b64encode((key + ':').encode()).decode()}",
        "Stripe-Version": "2024-06-20",
    })
    try:
        with urlopen(request, timeout=20) as response:
            account = json.loads(response.read().decode())
        name = (account.get("business_profile") or {}).get("name") or account.get("email") or "—"
        print(f"  {slot:<8}: {fingerprint(key)}")
        print(f"            -> ACCOUNT {account.get('id')}  «{name}»  "
              f"charges={account.get('charges_enabled')} payouts={account.get('payouts_enabled')}")
    except HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode()).get("error", {}).get("message", "")
        except Exception:
            pass
        # A revoked or restricted key is exactly what a swap is trying to escape, so say so plainly.
        print(f"  {slot:<8}: {fingerprint(key)}")
        print(f"            -> STRIPE REFUSED IT ({exc.code}): {detail or 'no detail'}")
PY
  echo
done

echo "Two silos showing the SAME account id is expected today — dev and prod share one platform account."
echo "After a swap they may legitimately differ; what must never differ is a silo's own key vs its client id."
