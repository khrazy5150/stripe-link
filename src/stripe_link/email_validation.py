"""Debounce (api.debounce.io) — a second opinion on an address before we bother emailing it.

FAILS OPEN, deliberately. If Debounce is unreachable, rate-limited, misconfigured or slow, the address is
allowed through. A validator that can block signup during its own outage is worse than no validator: the
confirmation code is what actually proves a mailbox exists, and this only catches the obvious.

Catch-all is reported, never blocking. A catch-all domain accepts any local part, so the service returns
"unknown" rather than "bad" — and plenty of legitimate small businesses run one. Rejecting them refuses
real customers in a way nobody ever hears about (plans/TENANT_SENDER_IDENTITY.md §4).
"""

import json
import os
import urllib.parse
import urllib.request
from typing import Any

_KEY_CACHE: dict[str, str] = {}

DEBOUNCE_URL = "https://api.debounce.io/v1/"
TIMEOUT_SECONDS = 4          # in a signup path: better to let it through than to make someone wait

# Debounce result codes. 5 = deliverable, 4 = risky/accept-all, 8 = disposable, 6 = invalid/undeliverable.
BLOCKING_CODES = {"6", "8"}
CATCH_ALL_CODES = {"4"}


def _region() -> str:
    return os.environ.get("AWS_REGION", "us-west-2")


def load_api_key(*, client=None) -> str:
    """The Debounce key, from Secrets Manager — same shape as the SMS and Cloudflare secrets.

    Not an environment variable: a key in the template is a key in git and in every deploy log. Cached per
    process, and a missing or denied secret returns "" so validation simply stays off rather than failing
    a tenant's signup.
    """
    secret_name = os.environ.get("DEBOUNCE_SECRET_NAME", "")
    if not secret_name:
        return ""
    if secret_name in _KEY_CACHE:
        return _KEY_CACHE[secret_name]
    if client is None:
        import boto3

        client = boto3.client("secretsmanager", region_name=_region())
    try:
        response = client.get_secret_value(SecretId=secret_name)
        data = json.loads(response.get("SecretString") or "{}")
        key = str((data or {}).get("api_key") or "").strip()
    except Exception:  # noqa: BLE001 - a missing/denied secret means validation stays off, never a block
        key = ""
    if key:
        _KEY_CACHE[secret_name] = key
    return key


def check_email(email: str, *, api_key: str | None = None, opener=None, secrets_client=None) -> dict[str, Any]:
    """{allowed, reason, catch_all, checked}. `checked` is False whenever we did not get an answer, so a
    caller can tell "Debounce said fine" from "Debounce said nothing"."""
    key = api_key if api_key is not None else load_api_key(client=secrets_client)
    if not key:
        return {"allowed": True, "reason": "", "catch_all": False, "checked": False}

    url = f"{DEBOUNCE_URL}?{urllib.parse.urlencode({'api': key, 'email': email})}"
    try:
        raw = (opener or urllib.request.urlopen)(url, timeout=TIMEOUT_SECONDS).read()
        payload = json.loads(raw)
    except Exception:
        return {"allowed": True, "reason": "", "catch_all": False, "checked": False}

    debounce = payload.get("debounce") or {}
    code = str(debounce.get("code") or "")
    if code in BLOCKING_CODES:
        reason = ("That looks like a disposable address. Please use your business email."
                  if code == "8" else "That address does not appear to exist.")
        return {"allowed": False, "reason": reason, "catch_all": False, "checked": True}
    return {"allowed": True, "reason": "", "catch_all": code in CATCH_ALL_CODES, "checked": True}
