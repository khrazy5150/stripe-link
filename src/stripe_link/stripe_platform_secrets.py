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
import os
from typing import Any, Dict, Optional

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
    response = client.get_secret_value(SecretId=arn)
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


def get_platform_webhook_secret(kind: str, mode: str, env_fallback: Optional[str] = None) -> Optional[str]:
    kind = (kind or "stable").lower()
    if kind not in ("preview", "stable"):
        kind = "stable"

    mode = (mode or "test").lower()
    if mode not in ("test", "live"):
        mode = "test"

    payload = _load_secret_payload()
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
