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

# What the SESSION is doing, which is a different question from whether you may still register.
# A webinar is a free event whose whole point is that people watch the presentation, so the page's job
# changes at the start time: before it collects a lead, during it pushes them at the join URL, after it
# says they missed it (author, 2026-10-14).
UPCOMING = "upcoming"
LIVE = "live"
ENDED = "ended"

# How long a session runs when the event does not say. Long enough that a page is not declaring a webinar
# over while the host is still talking, which is the failure that matters here.
DEFAULT_DURATION_MINUTES = 90


def duration_minutes(event: Any) -> int:
    try:
        minutes = int((event or {}).get("duration_minutes") or 0)
    except (TypeError, ValueError, AttributeError):
        minutes = 0
    return minutes if minutes > 0 else DEFAULT_DURATION_MINUTES


def ends_at(event: Any, occurrence: Any) -> int:
    """When this sitting finishes. 0 when it has no start."""
    start = starts_at(occurrence)
    return start + duration_minutes(event) * 60 if start else 0


def session_state(event: Any, occurrence: Any, *, now: int) -> str:
    """UPCOMING, LIVE, ENDED or CANCELLED -- what the PAGE should be doing right now.

    Deliberately separate from `registration_state`. That one answers "may this person still sign up";
    this one answers "is the thing happening". They disagree during the live window, which is the whole
    reason both exist: a session that has started is no longer registerable in the ordinary sense, but it
    is exactly when someone needs the join link put in front of them.
    """
    if str((occurrence or {}).get("status") or "scheduled") == "cancelled":
        return CANCELLED
    start = starts_at(occurrence)
    if not start:
        return ENDED
    moment = int(now)
    if moment < start:
        return UPCOMING
    return LIVE if moment < ends_at(event, occurrence) else ENDED


def live_occurrence(event: Any, *, now: int) -> dict[str, Any] | None:
    """The sitting happening right now, if one is. The page shows its join link above everything else."""
    for row in occurrences(event):
        if session_state(event, row, now=now) == LIVE:
            return row
    return None


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


# When registrants are reminded, as minutes before the session. The day-before catches people who need to
# move something; the hour-before catches everyone else, and is the one that actually fills a room.
REMINDER_LEAD_MINUTES = (1440, 60)
EMAIL_CHANNEL = "email"


def _reminder_records(occurrence: Any) -> list[dict[str, Any]]:
    return [row for row in ((occurrence or {}).get("reminders") or []) if isinstance(row, dict)]


def reminder_sent(occurrence: Any, lead_minutes: int) -> bool:
    """Whether this notice is SETTLED -- delivered, or deliberately skipped because a more imminent one
    went instead. Both mean "do not send it", which is the only question the sweep asks."""
    return any(
        int(row.get("lead_minutes") or 0) == int(lead_minutes)
        and row.get("status") in ("sent", "superseded")
        for row in _reminder_records(occurrence)
    )


def due_reminder_leads(event: Any, occurrence: Any, *, now: int) -> list[int]:
    """Which lead times are due for this sitting right now, soonest-sent first.

    Derived from `starts_at` rather than planned ahead and stored. A stored schedule has to be rewritten
    whenever the tenant moves the session, and a missed sweep leaves it stale; deriving means the answer is
    always current and a sweep that does not run simply sends late rather than not at all.

    Nothing is due once the session has started -- a reminder arriving mid-session is noise, and the page
    is already showing the join link by then.
    """
    start = starts_at(occurrence)
    moment = int(now)
    if not start or moment >= start:
        return []
    if session_state(event, occurrence, now=moment) != UPCOMING:
        return []
    due = [
        lead for lead in REMINDER_LEAD_MINUTES
        if moment >= start - lead * 60 and not reminder_sent(occurrence, lead)
    ]
    # MOST IMMINENT FIRST. When several are due at once -- a session created an hour before it runs, or a
    # sweep that missed a window -- only the first is worth sending: "starts tomorrow" about a session
    # starting in thirty minutes is not a duplicate, it is wrong. The caller sends `[0]` and supersedes
    # the rest so they cannot fire later.
    return sorted(due)


def record_reminder(occurrence: dict[str, Any], lead_minutes: int, *,
                    now: int, status: str = "sent", recipients: int = 0) -> dict[str, Any]:
    """The occurrence with this reminder's outcome stamped on it. Returns a NEW dict, like every other
    writer here, so the caller controls when it is persisted."""
    rows = [row for row in _reminder_records(occurrence)
            if int(row.get("lead_minutes") or 0) != int(lead_minutes)]
    rows.append({
        "lead_minutes": int(lead_minutes),
        "channel": EMAIL_CHANNEL,
        "status": status,
        "sent_at": int(now),
        "recipients": int(recipients),
    })
    return {**occurrence, "reminders": rows}
