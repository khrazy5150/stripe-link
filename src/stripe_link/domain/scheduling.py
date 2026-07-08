"""Booking slot-availability engine — pure, timezone-aware, no I/O.

Given a service, the tenant's default availability, the in-scope fulfillers, exceptions, and
existing appointments, compute the open start times a customer can book. Handlers load the
documents and pass them in; this module does only date math (via stdlib ``zoneinfo``, so it is
DST-aware).

A slot [start, start+duration] is offered when at least one in-scope fulfiller is free at that
start: inside their working hours for that weekday, past the lead time, not inside a ``block``
exception that applies to them, and not overlapping one of their existing appointments once the
tenant's before/after buffers are applied. Reserved holds block only until ``hold_expires_at``.
"""
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# datetime.weekday(): Monday == 0 … Sunday == 6.
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
BLOCKING_STATUSES = {"reserved", "booked", "paid", "checked_in"}
MAX_RANGE_DAYS = 62


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo("UTC")


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    parts = str(value or "").split(":")
    if len(parts) < 2:
        return None
    try:
        return max(0, min(23, int(parts[0]))), max(0, min(59, int(parts[1])))
    except ValueError:
        return None


def _parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _weekly_hours_map(weekly_hours: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for day in weekly_hours or []:
        if isinstance(day, dict) and day.get("day"):
            result[str(day["day"])] = day
    return result


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def _to_windows(intervals):
    """Parse [{start, end}] ISO intervals into [(datetime, datetime)] blocking windows."""
    windows = []
    for interval in intervals or []:
        start = _parse_iso(interval.get("start"))
        end = _parse_iso(interval.get("end"))
        if start and end:
            windows.append((start, end))
    return windows


def _resolve_scope(service: dict[str, Any], fulfillers: list[dict[str, Any]], fulfiller_id: str | None):
    """Return a list of (fulfiller_id_or_None, weekly_hours_map_or_None) to consider. When a
    fulfiller has its own weekly hours they override the tenant default (None means 'use tenant')."""
    by_id = {str(f.get("fulfiller_id")): f for f in fulfillers if f.get("fulfiller_id")}
    allowed = [
        str(entry.get("fulfiller_id"))
        for entry in (service.get("allowed_fulfillers") or [])
        if entry.get("enabled") is not False and entry.get("fulfiller_id")
    ]

    if fulfiller_id:
        candidate_ids = [fulfiller_id] if (not allowed or fulfiller_id in allowed) else []
    elif allowed:
        candidate_ids = allowed
    elif service.get("default_fulfiller_id"):
        candidate_ids = [str(service["default_fulfiller_id"])]
    else:
        candidate_ids = [None]

    scope = []
    for fid in candidate_ids:
        hours = None
        if fid and fid in by_id:
            weekly = (by_id[fid].get("availability") or {}).get("weekly_hours")
            if weekly:
                hours = _weekly_hours_map(weekly)
        scope.append((fid, hours))
    return scope


def _blocking_windows(
    appointments: list[dict[str, Any]],
    *,
    fulfiller_id: str | None,
    buffer_before: int,
    buffer_after: int,
    now_epoch: int,
) -> list[tuple[datetime, datetime]]:
    windows = []
    for appt in appointments:
        status = str(appt.get("status") or "")
        if status not in BLOCKING_STATUSES:
            continue
        if status == "reserved":
            hold = appt.get("hold_expires_at")
            if hold is not None and int(hold) <= int(now_epoch):
                continue  # abandoned hold no longer blocks
        assigned = str(appt.get("assigned_fulfiller_id") or "")
        # An appointment blocks a fulfiller when it is theirs, when it is unassigned (blocks
        # everyone), or when we are computing without a specific fulfiller.
        if fulfiller_id and assigned and assigned != fulfiller_id:
            continue
        start = _parse_iso(appt.get("starts_at"))
        end = _parse_iso(appt.get("ends_at"))
        if not start or not end:
            continue
        windows.append((start - timedelta(minutes=buffer_before), end + timedelta(minutes=buffer_after)))
    return windows


def _block_exception_windows(exceptions: list[dict[str, Any]], *, fulfiller_id: str | None) -> list[tuple[datetime, datetime]]:
    windows = []
    for exc in exceptions:
        if str(exc.get("type") or "block") != "block":
            continue  # 'open' exceptions are a future enhancement
        scope = str(exc.get("fulfiller_scope") or "all")
        if scope == "specific" and fulfiller_id and str(exc.get("fulfiller_id") or "") != fulfiller_id:
            continue
        start = _parse_iso(exc.get("starts_at"))
        end = _parse_iso(exc.get("ends_at"))
        if start and end:
            windows.append((start, end))
    return windows


def available_slots(
    service: dict[str, Any],
    tenant_availability: dict[str, Any],
    fulfillers: list[dict[str, Any]],
    exceptions: list[dict[str, Any]],
    appointments: list[dict[str, Any]],
    *,
    now_epoch: int,
    range_start_epoch: int,
    range_end_epoch: int,
    fulfiller_id: str | None = None,
    external_busy: list[dict[str, str]] | None = None,
    external_busy_by_fulfiller: dict[Any, list[dict[str, str]]] | None = None,
) -> list[dict[str, Any]]:
    tenant_availability = tenant_availability or {}
    tz = _zone(str(tenant_availability.get("timezone") or "UTC"))
    slot_interval = max(5, int(tenant_availability.get("slot_interval_minutes") or 30))
    lead = max(0, int(tenant_availability.get("lead_time_minutes") or 0))
    buffer_before = max(0, int(tenant_availability.get("buffer_before_minutes") or 0))
    buffer_after = max(0, int(tenant_availability.get("buffer_after_minutes") or 0))
    duration = max(1, int(service.get("duration_minutes") or 60))
    tenant_hours = _weekly_hours_map(tenant_availability.get("weekly_hours"))

    now = datetime.fromtimestamp(int(now_epoch), tz=timezone.utc)
    earliest = now + timedelta(minutes=lead)
    range_start = datetime.fromtimestamp(int(range_start_epoch), tz=timezone.utc)
    range_end = datetime.fromtimestamp(int(range_end_epoch), tz=timezone.utc)
    if range_end <= range_start:
        return []
    range_end = min(range_end, range_start + timedelta(days=MAX_RANGE_DAYS))

    scope = _resolve_scope(service, fulfillers, fulfiller_id)

    # External busy from connected calendars. `external_busy` (legacy) and the None key of
    # `external_busy_by_fulfiller` apply globally (the shared service/default calendar); a
    # per-fulfiller key applies to ONLY that fulfiller (their own delegated calendar) and
    # REPLACES the global for them — so a delegate is blocked by their calendar, not everyone's.
    by_fulfiller = external_busy_by_fulfiller or {}
    global_windows = _to_windows(external_busy) + _to_windows(by_fulfiller.get(None))
    per_fulfiller_windows = {fid: _to_windows(intervals) for fid, intervals in by_fulfiller.items() if fid is not None}

    # Precompute the busy/exception windows for each fulfiller once.
    busy_by_fulfiller = {}
    for fid, _ in scope:
        external_windows = per_fulfiller_windows.get(fid, global_windows)
        busy_by_fulfiller[fid] = (
            _blocking_windows(appointments, fulfiller_id=fid, buffer_before=buffer_before, buffer_after=buffer_after, now_epoch=now_epoch)
            + _block_exception_windows(exceptions, fulfiller_id=fid)
            + external_windows
        )

    slots_by_start: dict[datetime, str | None] = {}
    first_local_date = range_start.astimezone(tz).date()
    last_local_date = range_end.astimezone(tz).date()
    num_days = min(MAX_RANGE_DAYS, (last_local_date - first_local_date).days) + 1
    for day_offset in range(num_days):
        local_date = first_local_date + timedelta(days=day_offset)
        day_key = DAY_KEYS[local_date.weekday()]

        for fid, fulfiller_hours in scope:
            hours = (fulfiller_hours or tenant_hours).get(day_key)
            if not hours or not hours.get("enabled"):
                continue
            open_hm = _parse_hhmm(hours.get("start_time") or "")
            close_hm = _parse_hhmm(hours.get("end_time") or "")
            if not open_hm or not close_hm:
                continue

            window_open = datetime(local_date.year, local_date.month, local_date.day, open_hm[0], open_hm[1], tzinfo=tz)
            window_close = datetime(local_date.year, local_date.month, local_date.day, close_hm[0], close_hm[1], tzinfo=tz)
            busy = busy_by_fulfiller.get(fid, [])

            cursor = window_open
            step = timedelta(minutes=slot_interval)
            slot_len = timedelta(minutes=duration)
            while cursor + slot_len <= window_close:
                start_utc = cursor.astimezone(timezone.utc)
                end_utc = start_utc + slot_len
                if start_utc < earliest or start_utc < range_start or start_utc >= range_end:
                    cursor += step
                    continue
                if any(_overlaps(start_utc, end_utc, b_start, b_end) for b_start, b_end in busy):
                    cursor += step
                    continue
                slots_by_start.setdefault(start_utc, fid)
                cursor += step

    return [
        {
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": (start + timedelta(minutes=duration)).isoformat().replace("+00:00", "Z"),
            "fulfiller_id": fid,
        }
        for start, fid in sorted(slots_by_start.items())
    ]
