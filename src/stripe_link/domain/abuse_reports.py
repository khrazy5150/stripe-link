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


# What a tenant can ALLEGE about a review (plans/REVIEWS.md "Review integrity", plans/ADMIN_SITE.md §1b).
#
# Deliberately a SEPARATE list from the admin's removal reasons, although the words overlap. A report is an
# allegation and a removal is a finding; sharing one list would let the report pre-write the verdict, and
# the whole design rests on those being two different acts by two different parties.
#
# "Low rating" is absent here for the same reason it is absent there -- and its absence matters more here,
# because this is the list a TENANT reads. A merchant who is offered no way to say "this review is unfair"
# learns what the system is for from the form itself.
REVIEW_REPORT_REASONS = {
    "not_a_customer": "This is not from a real customer",
    "spam": "Spam or advertising",
    "abusive": "Abusive or illegal content",
    "personal_data": "Contains someone's personal details",
    "wrong_product": "It is about a different product",
    "other": "Something else",
}


def build_review_report(payload: dict[str, Any], *, review: dict[str, Any], reported_by: str,
                        source_ip: str = "", now: int | None = None) -> dict[str, Any]:
    """Validate a tenant's report about one of their own reviews into a stored report.

    Same table and same shape as a page report, so [[ADMIN_SITE]] §1 and §1b are one queue rather than two.
    `review` is resolved by the CALLER and the tenant comes from it -- a reporter who could name the tenant
    could file reports against anyone, which is the rule the page path already follows.

    **This function cannot hide a review.** It returns a report document and nothing else; the review is not
    an output. That is the integrity rule from plans/REVIEWS.md made structural: if flagging pulled a review
    down pending a decision, tenants would flag every two-star review and recover curation with a delay.
    """
    if not isinstance(payload, dict):
        raise ReportValidationError("A report must be an object.")
    if not isinstance(review, dict) or not review.get("review_id"):
        raise ReportValidationError("That review could not be found.")

    reason = str(payload.get("reason") or "").strip()
    if reason not in REVIEW_REPORT_REASONS:
        raise ReportValidationError("Choose a reason for the report.")
    detail = str(payload.get("detail") or "").strip()[:MAX_REASON_LEN]
    if reason == "other" and not detail:
        raise ReportValidationError("Tell us what is wrong with this review.")

    moment = int(now if now is not None else time.time())
    review_id = str(review.get("review_id"))
    return {
        "schema_version": "1",
        "document_type": "abuse_report",
        "report_id": f"rep_{moment}_{abs(hash((review_id, detail, moment))) % 10**10:010d}",
        # WHOSE reviews these are -- taken from the review, never from the payload.
        "tenant_id": str(review.get("tenant_id") or ""),
        # What is being reported. The page path leaves these empty and sets page_id instead; one table, one
        # queue, and a reader can tell the two apart without a second lookup.
        "target_type": "review",
        "review_id": review_id,
        "page_id": "",
        "product_id": str(review.get("product_id") or review.get("target_id") or ""),
        "review_rating": review.get("rating"),
        "review_author": str(review.get("author") or "")[:120],
        "reason": reason,
        "detail": detail,
        # The VERIFIED tenant who filed it. This is the field that answers the question §1b exists to ask --
        # is this one grudge or a pattern? -- and it is only answerable because this path is authenticated.
        "reported_by": str(reported_by or ""),
        "contact": "",
        "source_ip": str(source_ip or "")[:64],
        "user_agent": "",
        "status": "open",
        "created_at": moment,
        "updated_at": moment,
    }
