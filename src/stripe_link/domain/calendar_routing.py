"""Calendar routing — pure resolution of which calendar a booking touches (no I/O).

Two decisions, both driven by data already on the documents:

- **Write target** (`resolve_write_connection`): where an appointment's event is created —
  the assigned fulfiller's own calendar (delegation) → the service's calendar → the tenant
  default. Only `connected` connections are eligible.
- **Busy sources** for availability: a fulfiller who has their own calendar is checked against
  *that* calendar (so booking them respects their real schedule); everyone else falls back to
  the service/default calendar. This is what makes per-fulfiller delegation correct and fixes
  the "one shared calendar blocks every staff member" bug.
"""
from typing import Any


def _connected(connections):
    return [c for c in (connections or []) if c.get("status") == "connected"]


def _by_id(connections):
    return {c.get("connection_id"): c for c in connections if c.get("connection_id")}


def _default(connected):
    for conn in connected:
        if conn.get("is_default"):
            return conn
    if connected:
        return sorted(connected, key=lambda c: (int(c.get("connected_at") or 0), str(c.get("connection_id") or "")))[0]
    return None


def service_busy_connection(service, connections):
    """The calendar whose busy time blocks the whole service: the service's chosen calendar,
    else the tenant default. Returns a connection dict or None."""
    connected = _connected(connections)
    by_id = _by_id(connected)
    return by_id.get((service or {}).get("calendar_connection_id")) or _default(connected)


def fulfiller_busy_connection(fulfiller, connections):
    """A fulfiller's own calendar, if they have a connected one; else None (they fall back to the
    service/default calendar for busy-checking)."""
    if not fulfiller:
        return None
    return _by_id(_connected(connections)).get(fulfiller.get("calendar_connection_id"))


def resolve_write_connection(appointment, service, fulfiller, connections):
    """Where to write the appointment's calendar event: assigned fulfiller's own calendar
    (delegation) → service calendar → tenant default. Returns a connection dict or None when the
    tenant has no connected calendar at all."""
    connected = _connected(connections)
    by_id = _by_id(connected)
    if fulfiller and by_id.get(fulfiller.get("calendar_connection_id")):
        return by_id[fulfiller["calendar_connection_id"]]
    svc = by_id.get((service or {}).get("calendar_connection_id"))
    if svc:
        return svc
    return _default(connected)


def is_delegated_to_own_calendar(connection, fulfiller):
    """True when the chosen write calendar is the assigned delegate's own calendar."""
    return bool(connection and fulfiller and connection.get("connection_id") == fulfiller.get("calendar_connection_id"))


def delegation_status(connection, fulfiller):
    """Stamp for `appointment.delegation_calendar` when the appointment is delegated to a staff
    person who names a calendar: 'written' if the event landed on their calendar, 'unavailable' if
    it had to fall back. Returns None when this is not a delegation scenario."""
    if not (fulfiller and fulfiller.get("calendar_connection_id")):
        return None
    return "written" if is_delegated_to_own_calendar(connection, fulfiller) else "unavailable"


def candidate_fulfiller_ids(service, fulfiller_id=None):
    """The fulfillers a booking could be assigned to for this service (mirrors the slot engine):
    a specific requested fulfiller, else the service's enabled allowed_fulfillers, else its
    default fulfiller, else none."""
    allowed = [
        str(entry.get("fulfiller_id"))
        for entry in ((service or {}).get("allowed_fulfillers") or [])
        if entry.get("enabled") is not False and entry.get("fulfiller_id")
    ]
    if fulfiller_id:
        return [str(fulfiller_id)]
    if allowed:
        return allowed
    if (service or {}).get("default_fulfiller_id"):
        return [str(service["default_fulfiller_id"])]
    return []
