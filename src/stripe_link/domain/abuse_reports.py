"""A visitor's report that a platform-hosted page is abusive.

plans/CREATOR_LINK_POLICY.md §6: "A registrar does not ask whether you have an interstitial. It asks what you
do when someone abuses the domain." The allowlist and the adult interstitial are preventive; this is the part
that answers for what gets through, and it was the one piece of the policy with no UI and no endpoint.

Deliberately NOT a moderation system. It records who complained about what, so a human can act quickly and so
there is an auditable trail if a registrar or a platform ever asks. Judging the report is a person's job.

Anonymous by design. A visitor reporting a page is often reporting the person who would see their details,
so nothing here asks who they are; an optional contact address is theirs to give or withhold.
"""
from __future__ import annotations

import time
from typing import Any

# Caps, matching the shape domain/leads.py already uses on its public endpoint: refuse absurd payloads
# outright rather than storing them. A report is a sentence and a URL, not an essay.
MAX_REASON_LEN = 2000
MAX_URL_LEN = 2048
MAX_CONTACT_LEN = 254        # RFC 5321 practical maximum for an address

# The hidden field a bot fills and a person never sees. Same trick as the lead form; a shared name would let
# one scraper's heuristics defeat both at once.
HONEYPOT_FIELD = "website_url"

# What a reporter can allege. Deliberately short: a long list invites mis-filing, and every one of these maps
# to an action someone can actually take. "other" carries the free text.
REPORT_REASONS = {
    "adult": "Adult content without a warning",
    "illegal": "Illegal or harmful content",
    "impersonation": "Pretending to be someone else",
    "spam": "Spam, scam or malware",
    "other": "Something else",
}


class ReportValidationError(ValueError):
    """The submission is unusable. The message is shown to the reporter."""


def build_abuse_report(payload: dict[str, Any], *, page_id: str, tenant_id: str, host: str,
                       source_ip: str = "", user_agent: str = "", now: int | None = None) -> dict[str, Any]:
    """Validate a public submission into a stored report.

    `page_id`/`tenant_id` are resolved by the CALLER from the page being reported -- never taken from the
    payload. A reporter who could name the tenant could file reports against anyone.
    """
    if not isinstance(payload, dict):
        raise ReportValidationError("A report must be an object.")
    if str(payload.get(HONEYPOT_FIELD) or "").strip():
        # Silently valid-looking to the bot; the caller drops it. Saying "you are a bot" teaches the bot.
        raise ReportValidationError("__honeypot__")

    reason = str(payload.get("reason") or "").strip()
    if reason not in REPORT_REASONS:
        raise ReportValidationError("Choose a reason for the report.")
    detail = str(payload.get("detail") or "").strip()[:MAX_REASON_LEN]
    if reason == "other" and not detail:
        raise ReportValidationError("Tell us what is wrong with this page.")
    if not page_id:
        raise ReportValidationError("The page being reported could not be identified.")

    moment = int(now if now is not None else time.time())
    return {
        "schema_version": "1",
        "document_type": "abuse_report",
        "report_id": f"rep_{moment}_{abs(hash((page_id, detail, moment))) % 10**10:010d}",
        "tenant_id": tenant_id,
        "page_id": page_id,
        "host": str(host or "")[:MAX_URL_LEN],
        "reason": reason,
        "detail": detail,
        # Optional and unverified. Recorded so a human can follow up, never used to authenticate anything.
        "contact": str(payload.get("contact") or "").strip()[:MAX_CONTACT_LEN],
        # Kept for rate-limiting and for answering "was this one person or many?" -- the question that
        # separates a genuine problem from a grudge.
        "source_ip": str(source_ip or "")[:64],
        "user_agent": str(user_agent or "")[:256],
        "status": "open",
        "created_at": moment,
        "updated_at": moment,
    }
