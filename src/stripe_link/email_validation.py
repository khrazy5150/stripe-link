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

DEBOUNCE_URL = "https://api.debounce.io/v1/"
TIMEOUT_SECONDS = 4          # in a signup path: better to let it through than to make someone wait

# Debounce result codes. 5 = deliverable, 4 = risky/accept-all, 8 = disposable, 6 = invalid/undeliverable.
BLOCKING_CODES = {"6", "8"}
CATCH_ALL_CODES = {"4"}


def check_email(email: str, *, api_key: str | None = None, opener=None) -> dict[str, Any]:
    """{allowed, reason, catch_all, checked}. `checked` is False whenever we did not get an answer, so a
    caller can tell "Debounce said fine" from "Debounce said nothing"."""
    key = api_key if api_key is not None else os.environ.get("DEBOUNCE_API_KEY", "")
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
