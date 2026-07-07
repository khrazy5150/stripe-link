"""Appointment lifecycle — pure state-machine transitions (no I/O).

Statuses: reserved → booked/paid → checked_in → completed, plus the terminal branches
canceled and no_show. Handlers load the appointment, call ``transition_appointment``, and
persist the returned document.
"""
from datetime import datetime, timezone
from typing import Any


class AppointmentTransitionError(ValueError):
    """Raised when an action is not legal for the appointment's current status."""


TERMINAL_STATUSES = {"completed", "canceled", "no_show"}

# action -> (allowed-from statuses, resulting status, ISO timestamp field to stamp)
_TRANSITIONS: dict[str, tuple[set[str], str, str | None]] = {
    "check-in": ({"booked", "paid"}, "checked_in", "checked_in_at"),
    "complete": ({"booked", "paid", "checked_in"}, "completed", "completed_at"),
    "cancel": ({"reserved", "booked", "paid", "checked_in"}, "canceled", "canceled_at"),
    "no-show": ({"booked", "paid", "checked_in"}, "no_show", None),
}


def _iso(now_epoch: int) -> str:
    return datetime.fromtimestamp(int(now_epoch), tz=timezone.utc).isoformat()


def transition_appointment(
    appointment: dict[str, Any],
    action: str,
    *,
    now_epoch: int,
    assigned_fulfiller_id: str | None = None,
) -> dict[str, Any]:
    """Return a new appointment document with the transition applied.

    ``assign`` sets the fulfiller without changing status; the lifecycle actions
    (check-in/complete/cancel/no-show) validate the current status and stamp the
    matching timestamp. Raises AppointmentTransitionError on an illegal transition.
    """
    status = str(appointment.get("status") or "")

    if action == "assign":
        if status in TERMINAL_STATUSES:
            raise AppointmentTransitionError(f"Cannot assign a {status} appointment.")
        fulfiller_id = str(assigned_fulfiller_id or "").strip()
        if not fulfiller_id:
            raise AppointmentTransitionError("assigned_fulfiller_id is required to assign.")
        return {**appointment, "assigned_fulfiller_id": fulfiller_id, "updated_at": int(now_epoch)}

    spec = _TRANSITIONS.get(action)
    if not spec:
        raise AppointmentTransitionError(f"Unknown appointment action '{action}'.")
    allowed_from, new_status, timestamp_field = spec
    if status not in allowed_from:
        raise AppointmentTransitionError(f"Cannot {action} an appointment in status '{status}'.")

    updated = {**appointment, "status": new_status, "updated_at": int(now_epoch)}
    if timestamp_field:
        updated[timestamp_field] = _iso(now_epoch)
    return updated
