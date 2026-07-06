"""Minimal raw-HTTP Stripe client shared across handlers (checkout, upsell, product sync,
refunds). No SDK -- form-encoded requests over urllib, with per-tenant Connect support via
the Stripe-Account header and optional idempotency keys.
"""

import json
from base64 import b64encode
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

STRIPE_API_BASE = "https://api.stripe.com/v1"
STRIPE_API_VERSION = "2024-06-20"


class StripeApiError(Exception):
    def __init__(self, status_code, message, stripe_code=None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.stripe_code = stripe_code


def encode_form(data: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten a nested dict/list into Stripe's bracketed form encoding, e.g.
    {"metadata": {"a": 1}} -> metadata[a]=1 ; {"expand": ["x"]} -> expand[0]=x."""
    pairs: list[tuple[str, str]] = []
    for key, value in data.items():
        field = f"{prefix}[{key}]" if prefix else str(key)
        pairs.extend(_encode_value(field, value))
    return pairs


def _encode_value(field: str, value) -> list[tuple[str, str]]:
    if value is None:
        return []
    if isinstance(value, bool):
        return [(field, "true" if value else "false")]
    if isinstance(value, dict):
        pairs: list[tuple[str, str]] = []
        for key, inner in value.items():
            pairs.extend(_encode_value(f"{field}[{key}]", inner))
        return pairs
    if isinstance(value, (list, tuple)):
        pairs = []
        for index, inner in enumerate(value):
            pairs.extend(_encode_value(f"{field}[{index}]", inner))
        return pairs
    return [(field, str(value))]


def stripe_request(method, path, *, api_key, stripe_account="", params=None, data=None, opener=None, idempotency_key=None):
    opener = opener or urlopen
    url = f"{STRIPE_API_BASE}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    headers = {
        "Authorization": f"Basic {b64encode((api_key + ':').encode('utf-8')).decode('ascii')}",
        "Stripe-Version": STRIPE_API_VERSION,
    }
    if stripe_account:
        headers["Stripe-Account"] = stripe_account
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    body = None
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        # data may be a flat dict (simple) or already-encoded list of pairs (nested).
        encoded = encode_form(data) if isinstance(data, dict) else data
        body = urlencode(encoded).encode("utf-8")

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with opener(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = {}
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            pass
        error = payload.get("error") or {}
        raise StripeApiError(exc.code, error.get("message") or str(exc), error.get("code")) from exc
