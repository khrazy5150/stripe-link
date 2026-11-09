"""
Shared helper for loading Junior Bay platform Stripe secrets.

Primary source:
- AWS Secrets Manager secret referenced by STRIPE_PLATFORM_SECRET_ARN

Fallback sources:
- STRIPE_SECRET_KEY_TEST / STRIPE_SECRET_KEY_LIVE environment variables
- STRIPE_SECRET_KEY environment variable
- STRIPE_WEBHOOK_SECRET_PREVIEW_TEST / STRIPE_WEBHOOK_SECRET_PREVIEW_LIVE environment variables
- STRIPE_WEBHOOK_SECRET_STABLE_TEST / STRIPE_WEBHOOK_SECRET_STABLE_LIVE environment variables
"""

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CACHE: Dict[str, Any] = {}


def _get_region() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"


def _get_secret_arn() -> str:
    return (
        os.environ.get("STRIPE_PLATFORM_SECRET_ARN")
        or os.environ.get("PLATFORM_STRIPE_SECRET_ARN")
        or ""
    )


def _load_secret_payload(*, refresh: bool = False) -> Dict[str, Any]:
    if refresh:
        _CACHE.pop("payload", None)
    if "payload" in _CACHE:
        payload = _CACHE.get("payload")
        return payload if isinstance(payload, dict) else {}

    arn = _get_secret_arn()
    if not arn:
        _CACHE["payload"] = {}
        return {}

    import boto3

    client = boto3.client("secretsmanager", region_name=_get_region())
    try:
        response = client.get_secret_value(SecretId=arn)
    except Exception as exc:  # noqa: BLE001 - see below; the type is botocore's and varies by failure
        # A CONFIGURED BUT UNREADABLE SECRET IS A CONFIGURATION FAULT, NOT A CRASH.
        #
        # boto3 raises ResourceNotFoundException when the ARN names a secret that no longer exists, and
        # that is not an exception any caller here catches: it escaped as an unhandled 500/502, which
        # API Gateway answers WITHOUT CORS headers, so the browser reported the bare "Failed to fetch"
        # and the dashboard could never show what was wrong. Every caller already handles an EMPTY key
        # -- `invoices.py` answers "Stripe keys are not configured", `checkout.py` the same -- so the
        # honest result is an empty payload and a loud log, which turns an opaque 502 into a sentence
        # naming the problem. (2026-11-09: the prod ARN pointed at a stripe-cart secret deleted with
        # that stack, and every Connect charge path in both environments resolved to this line.)
        #
        # DELIBERATELY NOT CACHED. `{}` is cached when no ARN is configured, because that cannot change
        # without a redeploy; a read FAILURE can -- the secret may be created a minute from now, or the
        # call may simply have been throttled. Caching the failure would keep a warm container answering
        # "not configured" long after the secret existed, and these containers are held warm indefinitely
        # by the sweeps that share them.
        logger.error("platform stripe secret %s could not be read (%s); treating it as unconfigured",
                     arn, type(exc).__name__)
        return {}
    raw = response.get("SecretString") or "{}"
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            _CACHE["payload"] = payload
            return payload
    except Exception:
        pass

    _CACHE["payload"] = {}
    return {}


def _first_non_empty(payload: Dict[str, Any], keys: list[str]) -> Optional[str]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def get_platform_secret_key(mode: str, env_fallback: Optional[str] = None) -> Optional[str]:
    mode = (mode or "test").lower()
    if mode not in ("test", "live"):
        mode = "test"

    payload = _load_secret_payload()
    keys = [
        f"sk_{mode}",
        f"stripe_secret_key_{mode}",
        f"{mode}_secret_key",
        f"{mode}_sk",
        f"platform_sk_{mode}",
    ]
    key = _first_non_empty(payload, keys)
    if key:
        return key

    env_specific = os.environ.get(f"STRIPE_SECRET_KEY_{mode.upper()}")
    if isinstance(env_specific, str) and env_specific.strip():
        return env_specific.strip()
    if env_fallback and env_fallback.strip():
        return env_fallback.strip()
    generic = os.environ.get("STRIPE_SECRET_KEY")
    if isinstance(generic, str) and generic.strip():
        return generic.strip()
    return None


def get_platform_webhook_secret(kind: str, mode: str, env_fallback: Optional[str] = None,
                                *, refresh: bool = False) -> Optional[str]:
    """`refresh=True` re-reads Secrets Manager before answering.

    The cache has no TTL, and the existing refresh only fires when a key is ABSENT. A key that is present
    but STALE -- which is what a rotated signing secret is -- is served from cache for as long as the
    container lives, and this function's container is kept warm indefinitely by the sweeps that share it.
    The caller that knows the value is wrong is the signature check, so it asks.
    """
    kind = (kind or "stable").lower()
    # "platform_billing" is the platform-account Stripe Billing webhook (the tenant SaaS subscription); "preview"/
    # "stable" are the Connect webhooks. An unknown kind falls back to "stable" (plans/SAAS_BILLING_PAYWALL.md).
    if kind not in ("preview", "stable", "platform_billing"):
        kind = "stable"

    mode = (mode or "test").lower()
    if mode not in ("test", "live"):
        mode = "test"

    payload = _load_secret_payload(refresh=refresh)
    keys = [
        f"whsec_{kind}_{mode}",
        f"stripe_webhook_secret_{kind}_{mode}",
        f"webhook_secret_{kind}_{mode}",
        f"stripe_connect_{kind}_webhook_secret_{mode}",
        f"{kind}_webhook_secret_{mode}",
    ]
    secret = _first_non_empty(payload, keys)
    if not secret:
        payload = _load_secret_payload(refresh=True)
        secret = _first_non_empty(payload, keys)
    if secret:
        return secret

    env_specific = os.environ.get(f"STRIPE_WEBHOOK_SECRET_{kind.upper()}_{mode.upper()}")
    if isinstance(env_specific, str) and env_specific.strip():
        return env_specific.strip()
    if env_fallback and env_fallback.strip():
        return env_fallback.strip()

    generic = os.environ.get(f"STRIPE_WEBHOOK_SECRET_{mode.upper()}") or os.environ.get("STRIPE_WEBHOOK_SECRET")
    if isinstance(generic, str) and generic.strip():
        return generic.strip()
    return None


def checkout_credentials(tenant_id: str, mode: str, stripe_keys: Dict[str, Any], secret_cipher: Any) -> tuple[str, str]:
    """Resolve the (api_key, stripe_account) pair used to call Stripe on a tenant's behalf.

    Connected tenants use the platform's own secret key scoped to their connected account
    (direct charges); tenants without Connect use their own KMS-wrapped secret key.
    """
    connect_account_id = str(stripe_keys.get("connect_account_id") or "").strip()
    if connect_account_id:
        return get_platform_secret_key(mode), connect_account_id

    secret_ref = str(stripe_keys.get("secret_key_ref") or "").strip()
    if not secret_ref:
        return "", ""
    return secret_cipher.decrypt(secret_ref, tenant_id=tenant_id, mode=mode, field="secret_key_ref"), ""
