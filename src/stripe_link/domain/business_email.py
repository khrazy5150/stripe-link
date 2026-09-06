"""Verification of a tenant's business email — the address every tenant-authored send replies to.

Junior Bay's SES account has production access, so it will happily mail anyone on a tenant's behalf. That
is precisely why the PLATFORM has to be what refuses: SES will not check whether the reply-to belongs to
the tenant, so nothing else will.

Pure rules only — no I/O, no clock, no crypto side effects. The handler supplies `now` and the random code.
"""

import hashlib
import hmac
import re
from typing import Any

CODE_TTL_SECONDS = 5 * 60          # as specified: a code is a credential, and a stale one is a liability
MAX_ATTEMPTS = 5                   # 6 digits is 10^6; unlimited guesses is no protection at all
CODE_DIGITS = 6

_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")

# Blocking these is uncontroversial: they exist to be thrown away, so an address at one cannot be the place
# a business receives replies. Catch-all domains are deliberately NOT here — see plans/TENANT_SENDER_IDENTITY.md.
DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "throwawaymail.com",
    "yopmail.com", "trashmail.com", "sharklasers.com", "getnada.com", "temp-mail.org", "dispostable.com",
    "maildrop.cc", "fakeinbox.com", "mintemail.com", "spamgourmet.com",
})


def looks_like_email(value: str) -> bool:
    return bool(_EMAIL.match(str(value or "").strip()))


def is_disposable(value: str) -> bool:
    _, _, domain = str(value or "").strip().lower().partition("@")
    return domain in DISPOSABLE_DOMAINS


def hash_code(code: str, *, tenant_id: str) -> str:
    """Codes are stored hashed and salted per tenant. A stored plaintext code is a credential sitting in a
    database, and reading it would be enough to take over a tenant's sending identity."""
    return hashlib.sha256(f"{tenant_id}|{code}".encode("utf-8")).hexdigest()


def start_verification(email: str, *, tenant_id: str, code: str, now: int) -> dict[str, Any]:
    """The pending record to store alongside the profile's business block."""
    return {
        "pending_email": str(email or "").strip().lower(),
        "code_hash": hash_code(code, tenant_id=tenant_id),
        "expires_at": int(now) + CODE_TTL_SECONDS,
        "attempts": 0,
    }


def check_code(pending: Any, submitted: str, *, tenant_id: str, now: int) -> tuple[bool, str]:
    """(ok, reason). Reasons are for the tenant, so they say what to do next rather than what went wrong."""
    if not isinstance(pending, dict) or not pending.get("code_hash"):
        return False, "Request a new code to continue."
    if int(pending.get("expires_at") or 0) <= int(now):
        return False, "That code has expired. Request a new one."
    if int(pending.get("attempts") or 0) >= MAX_ATTEMPTS:
        return False, "Too many attempts. Request a new code."
    # Constant-time: a timing difference on a 6-digit code is a real oracle.
    if not hmac.compare_digest(str(pending["code_hash"]), hash_code(str(submitted or "").strip(), tenant_id=tenant_id)):
        return False, "That code is not right."
    return True, ""


def verified_email(business: Any) -> str:
    """The address a tenant-authored send may reply to, or "" — the ONE question the send-time gate asks.

    Pending is not verified. A tenant who types an address and never confirms it must not be able to send,
    or the verification is decorative.
    """
    business = business if isinstance(business, dict) else {}
    email = str(business.get("email") or "").strip()
    return email if email and business.get("email_verified") else ""
