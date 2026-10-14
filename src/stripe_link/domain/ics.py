"""iCalendar files for scheduled sessions (plans/WEBINAR.md P2).

The `.ics` matters more than any reminder we send: it puts the session in the registrant's own calendar,
where their own device reminds them, on the phone they actually carry. A reminder email competes with every
other email; a calendar entry does not.

RFC 5545 is picky in ways that fail silently -- a file with LF endings or an unescaped comma is accepted by
one client and ignored by another, which is the worst kind of bug to have in an attachment nobody opens
until the morning of the session. So the mechanics are here, tested, and not improvised at a call site:

* **CRLF** line endings, always (§3.1).
* Lines **folded at 75 octets** with a leading space on continuations -- counted in OCTETS, not characters,
  so a multi-byte title cannot be split mid-character.
* TEXT values escape `\\`, `;`, `,` and newlines (§3.3.11).
* Times in **UTC** (`...Z`), because a floating local time means something different to every reader.

`METHOD:PUBLISH`, not `REQUEST`. REQUEST is an invitation with an organiser expecting an RSVP, and a
webinar registration is neither -- the registrant already said yes on the page, and we are not running
their calendar's attendee list.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

PRODID = "-//Junior Bay//Scheduled Events//EN"


def _escape(value: Any) -> str:
    """Escape a TEXT value (RFC 5545 §3.3.11). Backslash FIRST, or the escapes escape each other."""
    text = str(value or "")
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;").replace(",", "\\,")
    return text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _stamp(epoch: int) -> str:
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fold(line: str) -> list[str]:
    """Fold one content line to 75 octets, continuations prefixed with a space.

    Counted in OCTETS because the limit is bytes, and split on a character boundary because a UTF-8
    sequence broken in half renders as a replacement glyph in the middle of a tenant's title.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return [line]
    out: list[str] = []
    chunk = ""
    size = 0
    limit = 75
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > limit:
            out.append(chunk)
            chunk = char
            size = width + 1      # the leading space on a continuation counts toward its 75
            limit = 75
            continue
        chunk += char
        size += width
    if chunk:
        out.append(chunk)
    return [out[0]] + [f" {part}" for part in out[1:]]


def calendar_invite(
    *,
    uid: str,
    title: str,
    starts_at: int,
    ends_at: int,
    description: str = "",
    location: str = "",
    organiser_name: str = "",
    now: int | None = None,
) -> str:
    """One VEVENT as a complete .ics document.

    `uid` must be STABLE for a given session: a calendar treats a repeated UID as an update to the entry it
    already has, so resending a confirmation moves the existing block rather than leaving two.
    """
    stamped = _stamp(now if now is not None else int(datetime.now(tz=timezone.utc).timestamp()))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{_escape(uid)}",
        f"DTSTAMP:{stamped}",
        f"DTSTART:{_stamp(starts_at)}",
        f"DTEND:{_stamp(ends_at)}",
        f"SUMMARY:{_escape(title)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    if location:
        # The join URL lives here as well as in the body: most clients turn LOCATION into a tappable link,
        # which is the one thing a registrant needs at the moment the entry fires.
        lines.append(f"LOCATION:{_escape(location)}")
    if organiser_name:
        lines.append(f"ORGANIZER;CN={_escape(organiser_name)}:MAILTO:noreply@invalid")
    lines.extend(["STATUS:CONFIRMED", "END:VEVENT", "END:VCALENDAR"])

    folded: list[str] = []
    for line in lines:
        folded.extend(_fold(line))
    return "\r\n".join(folded) + "\r\n"


def invite_for_occurrence(event: dict[str, Any], occurrence: dict[str, Any], *,
                          organiser_name: str = "", now: int | None = None) -> str:
    """The .ics for one sitting of an event, or "" when it has no start to describe."""
    from .events import ends_at as occurrence_ends_at, starts_at as occurrence_starts_at

    start = occurrence_starts_at(occurrence)
    if not start:
        return ""
    return calendar_invite(
        # Stable per sitting, and namespaced so it cannot collide with another system's entry.
        uid=f"{occurrence.get('occurrence_id') or 'session'}@juniorbay",
        title=str(event.get("title") or "Live session"),
        starts_at=start,
        ends_at=occurrence_ends_at(event, occurrence) or start + 3600,
        description=str(event.get("description") or ""),
        location=str(event.get("join_url") or ""),
        organiser_name=organiser_name,
        now=now,
    )
