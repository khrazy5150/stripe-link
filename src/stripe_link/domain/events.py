"""Scheduled events — a webinar and its occurrences (plans/WEBINAR.md P1).

An **event** is the thing ("How to sell AI tools"); an **occurrence** is one running of it (Wednesday 7pm
EST, and again Friday 9:30am AEST for Australia). Registrations point at an occurrence, not at the event,
because "which one did they sign up for" is the question every reminder and every join link has to answer.

Pure logic: no repository, no clock of its own, no I/O. `now` is always passed in, so a test can stand on
either side of a start time without sleeping and the renderer can ask "is this open?" at publish time with
the same function the registration endpoint uses to refuse.
"""
from __future__ import annotations

from typing import Any

PROVIDERS = ("zoom", "webinarjam", "meet", "teams", "other")
OCCURRENCE_STATUSES = ("scheduled", "cancelled")

# Registration states, in the order the page cares about them.
OPEN = "open"
FULL = "full"
PASSED = "passed"
CANCELLED = "cancelled"


def occurrences(event: Any) -> list[dict[str, Any]]:
    """Every occurrence on the event, as dicts. Anything that is not one is dropped rather than raising:
    a malformed row must not take the page down for the ones beside it."""
    raw = (event or {}).get("occurrences") if isinstance(event, dict) else None
    return [row for row in (raw or []) if isinstance(row, dict)]


def occurrence_by_id(event: Any, occurrence_id: Any) -> dict[str, Any] | None:
    wanted = str(occurrence_id or "").strip()
    if not wanted:
        return None
    for row in occurrences(event):
        if str(row.get("occurrence_id") or "") == wanted:
            return row
    return None


def starts_at(occurrence: Any) -> int:
    try:
        return max(0, int((occurrence or {}).get("starts_at") or 0))
    except (TypeError, ValueError, AttributeError):
        return 0


def capacity(occurrence: Any) -> int:
    """0 means UNLIMITED, which is also what an absent capacity means. A tenant who clears the field is
    saying "no limit", not "nobody may register"."""
    try:
        return max(0, int((occurrence or {}).get("capacity") or 0))
    except (TypeError, ValueError, AttributeError):
        return 0


def registered_count(occurrence: Any) -> int:
    try:
        return max(0, int((occurrence or {}).get("registered_count") or 0))
    except (TypeError, ValueError, AttributeError):
        return 0


def seats_left(occurrence: Any) -> int | None:
    """Remaining seats, or None when the occurrence is uncapped. None is not 0 -- a page must be able to
    tell "unlimited" from "sold out", and they are the two states this most needs to distinguish."""
    limit = capacity(occurrence)
    if not limit:
        return None
    return max(0, limit - registered_count(occurrence))


def registration_state(occurrence: Any, *, now: int) -> str:
    """Whether this occurrence can still be registered for, and if not, why.

    Order matters: a CANCELLED occurrence reports cancelled even if it is also full and in the past,
    because that is the one a visitor needs explaining. Past beats full for the same reason -- "you missed
    it" is true and actionable, "it is full" invites them to wait for a seat that will never free up.
    """
    if str((occurrence or {}).get("status") or "scheduled") == "cancelled":
        return CANCELLED
    moment = starts_at(occurrence)
    if not moment or moment <= int(now):
        return PASSED
    left = seats_left(occurrence)
    if left is not None and left <= 0:
        return FULL
    return OPEN


def is_open(occurrence: Any, *, now: int) -> bool:
    return registration_state(occurrence, now=now) == OPEN


def open_occurrences(event: Any, *, now: int) -> list[dict[str, Any]]:
    """The ones a visitor may still choose, soonest first. Sorting here rather than trusting the stored
    order means a tenant who adds a session out of sequence still gets a sensible picker."""
    return sorted((row for row in occurrences(event) if is_open(row, now=now)), key=starts_at)


def next_occurrence(event: Any, *, now: int) -> dict[str, Any] | None:
    """The soonest occurrence still open, or None. This is what a page offers when the one the visitor
    came for has passed -- the case that justifies occurrences living inside the event."""
    upcoming = open_occurrences(event, now=now)
    return upcoming[0] if upcoming else None


def accepts_registration(event: Any, occurrence_id: Any, *, now: int) -> tuple[bool, str]:
    """May this registration be accepted? Returns (ok, reason).

    The server calls this; the page calls it too, at publish, to decide what to render. One function, so a
    page cannot invite a registration the endpoint will refuse. The reason is a STATE from this module, not
    a sentence -- the wording belongs to whatever is showing it.
    """
    occurrence = occurrence_by_id(event, occurrence_id)
    if occurrence is None:
        return False, "unknown"
    state = registration_state(occurrence, now=now)
    return (state == OPEN), state


def record_registration(event: dict[str, Any], occurrence_id: Any) -> dict[str, Any]:
    """The event with that occurrence's `registered_count` incremented by one.

    Returns a NEW document rather than mutating: the caller writes it back, and a function that quietly
    edited the dict it was handed would make the write ordering impossible to follow.

    Read-compare-write, so two registrations landing in the same instant can both pass a capacity check
    and overbook by one. That is accepted for v1: the alternative is an atomic counter the document
    repository does not currently offer, and a webinar seat is not a seat on a plane.
    """
    updated = dict(event or {})
    rows = []
    wanted = str(occurrence_id or "").strip()
    for row in occurrences(updated):
        if str(row.get("occurrence_id") or "") == wanted:
            row = {**row, "registered_count": registered_count(row) + 1}
        rows.append(row)
    updated["occurrences"] = rows
    return updated
