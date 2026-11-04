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
#
# This list is a SUPPLEMENT to Debounce, not a substitute, and it is knowingly incomplete. Testing services
# rotate domains precisely to stay ahead of blocklists: verified 2026-09-06, Debounce flags mailslurp.com as
# Disposable but rates its sandbox domain zazamail.link "Safe to Send". No list wins that race.
#
# That is acceptable because this is NOT the security boundary. The confirmation code proves the tenant can
# receive at the address, which is the property the Reply-To actually needs; the list only turns away the
# careless. Anyone determined to use a throwaway inbox will succeed, and the answer to abuse is rate limits
# and monitoring, not a longer list.
DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "throwawaymail.com",
    "yopmail.com", "trashmail.com", "sharklasers.com", "getnada.com", "temp-mail.org", "dispostable.com",
    "maildrop.cc", "fakeinbox.com", "mintemail.com", "spamgourmet.com",
    # Testing-inbox services and their known sandbox domains.
    "mailslurp.com", "mailslurp.net", "mailslurp.biz", "zazamail.link", "mailsac.com", "inbox.testmail.app",
    "ethereal.email", "trashmail.de", "mytemp.email", "emailondeck.com",
})


# NOT disposable, and never to be added above: alias and forwarding services. Apple Hide My Email
# (privaterelay.appleid.com), DuckDuckGo, Firefox Relay and SimpleLogin all forward to a REAL person's
# inbox — they are privacy tools, not throwaways, and Hide My Email in particular is offered by default to
# every iPhone user at the point of sign-up. Blocking them would refuse a large slice of ordinary people
# whose address works perfectly well. Listed here so the distinction survives the next person extending
# DISPOSABLE_DOMAINS.
ALIAS_DOMAINS = frozenset({
    "privaterelay.appleid.com", "icloud.com", "duck.com", "mozmail.com", "simplelogin.io",
    "anonaddy.com", "addy.io", "relay.firefox.com",
})


# Domains RESERVED BY THE RFCs, which can never have an MX record and can never receive mail:
# RFC 2606 (example.*, .test, .invalid, .localhost) and RFC 6761. Distinct from DISPOSABLE_DOMAINS above,
# which are real inboxes we would rather a BUSINESS did not use — these are not inboxes at all.
#
# Sending to one costs SES 840 minutes of retries and then returns a Delivery Status Notification to the
# platform's own support mailbox. Thousands of those accumulated there before anyone looked
# (reported 2026-11-04), every one of them a message that never had a recipient.
UNDELIVERABLE_DOMAINS = frozenset({
    "example.com", "example.net", "example.org", "example.edu",
    "test", "invalid", "localhost", "local",
})
UNDELIVERABLE_SUFFIXES = (".test", ".invalid", ".localhost", ".local", ".example")


def is_undeliverable(value: str) -> bool:
    """True for an address no mail server can ever accept — reserved by RFC, not merely unwise.

    The question is deliberately narrow. "Will this bounce?" cannot be answered here and guessing at it
    would refuse real customers; "can this domain exist at all?" is a fact, and the answer is no.
    """
    address = str(value or "").strip().lower()
    if not looks_like_email(address):
        return True                 # not an address at all; nothing can be delivered to it
    domain = address.rsplit("@", 1)[-1]
    if domain in UNDELIVERABLE_DOMAINS or domain.endswith(UNDELIVERABLE_SUFFIXES):
        return True
    # SUBDOMAINS of a reserved name are reserved too (RFC 2606 reserves the whole tree). Matched on a
    # leading dot so `examples.com` — a real domain somebody owns — is not swept up with `example.com`.
    return any(domain.endswith(f".{reserved}") for reserved in UNDELIVERABLE_DOMAINS)


def disposable_domain_of(value: str) -> str:
    """The matched domain, or "". Matches SUBDOMAINS too: a service that hands out
    `{uuid}@sandbox.zazamail.link` is not defeated by listing the bare domain."""
    _, _, domain = str(value or "").strip().lower().partition("@")
    if not domain:
        return ""
    parts = domain.split(".")
    for index in range(len(parts) - 1):
        candidate = ".".join(parts[index:])
        if candidate in ALIAS_DOMAINS:
            return ""          # an alias forwards to a real person; stop before any disposable match
        if candidate in DISPOSABLE_DOMAINS:
            return candidate
    return ""


def looks_like_email(value: str) -> bool:
    return bool(_EMAIL.match(str(value or "").strip()))


def is_disposable(value: str) -> bool:
    return bool(disposable_domain_of(value))


def verification_scope(tenant_id: str, site_id: str = "") -> str:
    """What a code is valid FOR. The salt, and therefore the blast radius of one code.

    A tenant may run several businesses, each on its own Site with its own address
    (plans/SITE_AS_BUSINESS_IDENTITY.md §P3), so a code mailed to prove one Site's mailbox must not
    confirm another's -- otherwise a tenant who controls one address verifies every Site they own, and the
    whole gate reduces to "this tenant has an inbox somewhere".

    A bare tenant scope is NOT the same string as a Site scope, so the tenant-level flow is untouched: its
    stored hashes keep verifying. A code in flight across the deploy that introduced this would fail, and
    the message already says to request a new one -- against a 5-minute TTL, that is the whole exposure.
    """
    site_id = str(site_id or "").strip()
    return f"{tenant_id}|{site_id}" if site_id else str(tenant_id)


def hash_code(code: str, *, tenant_id: str, site_id: str = "") -> str:
    """Codes are stored hashed and salted per scope. A stored plaintext code is a credential sitting in a
    database, and reading it would be enough to take over a tenant's sending identity."""
    return hashlib.sha256(f"{verification_scope(tenant_id, site_id)}|{code}".encode("utf-8")).hexdigest()


def start_verification(email: str, *, tenant_id: str, code: str, now: int,
                       site_id: str = "") -> dict[str, Any]:
    """The pending record to store beside the address being proven: the profile's `business` block, or a
    Site's `organization`. Same shape either way, because it is the same question about a mailbox."""
    return {
        "pending_email": str(email or "").strip().lower(),
        "code_hash": hash_code(code, tenant_id=tenant_id, site_id=site_id),
        "expires_at": int(now) + CODE_TTL_SECONDS,
        "attempts": 0,
    }


def check_code(pending: Any, submitted: str, *, tenant_id: str, now: int,
               site_id: str = "") -> tuple[bool, str]:
    """(ok, reason). Reasons are for the tenant, so they say what to do next rather than what went wrong."""
    if not isinstance(pending, dict) or not pending.get("code_hash"):
        return False, "Request a new code to continue."
    if int(pending.get("expires_at") or 0) <= int(now):
        return False, "That code has expired. Request a new one."
    if int(pending.get("attempts") or 0) >= MAX_ATTEMPTS:
        return False, "Too many attempts. Request a new code."
    # Constant-time: a timing difference on a 6-digit code is a real oracle.
    if not hmac.compare_digest(
            str(pending["code_hash"]),
            hash_code(str(submitted or "").strip(), tenant_id=tenant_id, site_id=site_id)):
        return False, "That code is not right."
    return True, ""


def preserve_email_verification(incoming_org: Any, existing_org: Any) -> dict[str, Any]:
    """Strip client-supplied email-verification state and restore what the SERVER stored.

    The same merge, for the same reason, as `social_links.preserve_verification`: the Sites editor sends
    the whole `organization` back, so anything a client can put in the payload is something a client can
    assert. `email_verified` decides whether SES will put that address in a Reply-To, and SES does not
    check it for us -- a tenant who could set the flag could receive another business's customer replies.

    **Re-pointing the address drops the proof**, exactly as re-pointing a sameAs URL does: the code proved
    "someone can read mail AT THIS ADDRESS", and that finding does not travel to a different address. So a
    tenant may freely edit `organization.email` -- it is their published contact address and belongs in the
    markup either way -- and it simply stops being usable as a Reply-To until they prove the new one.

    Returns the fields to overlay, so the caller stays one assignment.
    """
    incoming = incoming_org if isinstance(incoming_org, dict) else {}
    existing = existing_org if isinstance(existing_org, dict) else {}
    verified_address = str(existing.get("email") or "").strip().lower()
    asked_for = str(incoming.get("email") or "").strip().lower()
    same_address = bool(verified_address) and asked_for == verified_address
    return {
        "email_verified": bool(existing.get("email_verified")) and same_address,
        "email_verified_at": existing.get("email_verified_at") if same_address else None,
        # The pending record follows the address it was issued for, so asking for a different one does not
        # let yesterday's unconfirmed code confirm it.
        "email_verification": existing.get("email_verification") if same_address else None,
    }


def verified_email(business: Any) -> str:
    """The address a tenant-authored send may reply to, or "" — the ONE question the send-time gate asks.

    Pending is not verified. A tenant who types an address and never confirms it must not be able to send,
    or the verification is decorative.
    """
    business = business if isinstance(business, dict) else {}
    email = str(business.get("email") or "").strip()
    return email if email and business.get("email_verified") else ""


def sender_display_name(profile: Any) -> str:
    """The name a tenant-authored email appears to come FROM, or "" to fall back to the bare address.

    The point of the whole sender identity is that the mail reads as the tenant's, not the platform's — a
    recipient who sees "support@juniorbay.net" with no name has been handed Junior Bay's mail, not the
    merchant's. So an empty business name falls through to the person instead of giving up: a sole trader
    who never filled in a business name still has a name, and it is a better sender than no name at all.

    Reply-To is the verified BUSINESS address; this is only the display name beside the platform's From.
    """
    profile = profile if isinstance(profile, dict) else {}
    business = profile.get("business") if isinstance(profile.get("business"), dict) else {}
    candidates = (
        business.get("name"),
        profile.get("display_name"),
        " ".join(part for part in (profile.get("first_name"), profile.get("last_name")) if part),
    )
    for candidate in candidates:
        name = str(candidate or "").strip()
        if name:
            return name
    return ""


def reply_to_address(profile: Any) -> str:
    """Where a customer's reply should land, or "" when the tenant has no reachable address at all.

    Two sources, in this order, and the second is the one that actually fires today:

    1. the VERIFIED business email — the address the tenant deliberately nominated for replies;
    2. the SIGNUP email — the Cognito account address, proven at registration.

    The signup email is a legitimate fallback rather than a hole in `verified_email`'s gate: that gate
    exists because SES will mail from any Reply-To a tenant types, so the platform has to prove the address
    belongs to them. A Cognito account email is proof of exactly that, obtained by a stronger flow.

    Falling back matters because the alternative is what shipped: NO Reply-To, so a customer answering a
    receipt writes to the platform's support box, which cannot help them and is not the merchant. Measured
    2026-09-23: zero tenants in dev or prod had ever verified a business email, so gating on verification
    alone left every customer reply undeliverable to the merchant.
    """
    profile = profile if isinstance(profile, dict) else {}
    business = profile.get("business") if isinstance(profile.get("business"), dict) else {}
    verified = verified_email(business)
    if verified:
        return verified
    signup = str(profile.get("email") or "").strip()
    return signup if looks_like_email(signup) else ""


def email_identity(profile: Any, organization: Any = None) -> dict[str, str]:
    """The sending identity of the business behind one message: the name a customer sees, and the address
    their reply reaches.

    ONE answer, so every message a tenant sends is from the same business with the same reply address.
    Before this existed each emitter resolved its own: the review invite read `Site.organization.name`, the
    receipt read `TenantProfile.business_name` (empty on every tenant and in every environment) and most
    emitters asked for neither -- so the same shop appeared as "Poliaxis Nutrition" on one message and as a
    bare "support@juniorbay.net" on the next (reported 2026-09-23, both screenshots).

    `organization` is the Site's, and it WINS the display name when it has one
    (plans/SITE_AS_BUSINESS_IDENTITY.md §4). The tenant profile holds one business name for a tenant who
    may run several businesses, so preferring it is how a Quill customer's review invite came to be signed
    "Poliaxis Nutrition". The profile is the fallback, for a Site with no organization and for the mail
    that has no Site at all -- a verification code, or anything sent before a Site exists.

    Reply-To follows the SITE too, but only once the Site's address has been PROVEN (§P3): the Site's
    `email` with `email_verified`, else the tenant's verified address. Never the Site's unverified one --
    SES will mail from any Reply-To it is handed, so an unverified Site address is precisely the hole the
    verification gate exists to close, and falling back is what keeps a half-set-up second Site from
    silently sending replies nowhere.
    """
    org = organization if isinstance(organization, dict) else {}
    return {
        "business_name": str(org.get("name") or "").strip() or sender_display_name(profile),
        "reply_to": verified_email(org) or reply_to_address(profile),
    }