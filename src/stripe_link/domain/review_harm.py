"""Does this review need a human before it publishes? (plans/REVIEWS.md "Review integrity")

A HARM filter, never a QUALITY filter. It looks for things that are objectively unpublishable on someone
else's page -- contact details, links, slurs -- and it is **structurally incapable** of holding a review for
being negative: the rating is not an input, and neither is anything that could stand in for one.

That constraint is the whole design. Tenant moderation was removed because a tenant who can reject the bad
ones makes `AggregateRating` a claim about a set they chose. A filter that could be tuned to catch unhappy
customers would rebuild exactly that, with the platform holding the dial instead.
"""
from __future__ import annotations

import re
from typing import Any

# Contact details and links. A review is about a purchase; a phone number or a URL in one is either a
# scam, a spammer, or a real person publishing something they will regret -- and the last of those is the
# reason this holds rather than discards.
_PHONE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}")
_URL = re.compile(r"\b(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|net|org|io|co|ru|xyz)\b", re.I)

# Deliberately short and deliberately not configurable here: a slur list that a tenant or a preset could
# edit is a dial, and this file exists to have no dials. Extending it is a code change with a reviewer.
_SLURS = ("fuck", "shit", "cunt", "bitch", "bastard", "whore", "retard", "faggot", "nigger")
_SLUR = re.compile(r"\b(?:" + "|".join(_SLURS) + r")\w*\b", re.I)

REASONS = ("phone", "email", "link", "slur")


def harm_reasons(review: dict[str, Any] | None) -> list[str]:
    """Which objective patterns this review trips, in a stable order. Empty means publish.

    Reads only the free text a reviewer typed. It never sees the rating, and a test asserts that a
    one-star review and a five-star review with identical words get identical answers.
    """
    text = " ".join(str((review or {}).get(field) or "") for field in ("title", "body", "author"))
    found = []
    if _PHONE.search(text):
        found.append("phone")
    if _EMAIL.search(text):
        found.append("email")
    if _URL.search(text):
        found.append("link")
    if _SLUR.search(text):
        found.append("slur")
    return found


def needs_review(review: dict[str, Any] | None) -> bool:
    return bool(harm_reasons(review))
