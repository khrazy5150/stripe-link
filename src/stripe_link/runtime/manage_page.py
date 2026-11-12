"""The page a customer reaches from their confirmation email: GET /booking/manage.

Self-contained HTML, same shape and visual language as `booking_page.py`, whose `_price_label` and
`_duration_label` it reuses rather than restating. The script drives the manage API that already existed —
`/services/appointments/manage/cancel` and `/manage/reschedule`, both authorised by the opaque
`customer_manage_token` the booking generated and nothing else.

Until this page there was no way for a customer to change a booking without finding a human. The routes
had been written, the token had been minted on every booking, and `_authorized_appointment` had already
been taught to search both Stripe modes *for this moment* — its own comment says "nothing links here yet,
which is exactly why this is worth doing now". This is the link.

Rendered server-side with the appointment already resolved, so the page never has to ask the API who it is
about, and a stranger with no token gets a 404 before any HTML exists. `noindex` and `no-store` because the
URL carries a bearer token: a search engine or a shared proxy cache holding this is the whole threat model.
"""
from html import escape
from typing import Any

from stripe_link.domain.booking import (
    appointment_duration_minutes,
    appointment_price,
    service_lines,
)
from stripe_link.runtime.booking_page import _duration_label, _price_label
from stripe_link.runtime.slot_picker import HORIZON_DAYS, PICKER_CSS, PICKER_JS, THEME_STANDALONE

# Mirrors handlers/booking.py. Duplicated deliberately rather than imported: runtime/ must not import
# handlers/ (tests/envreach.py follows imports transitively, and a renderer that reaches into a handler
# inherits every table that handler can touch). The pair is small, and the test asserts they agree.
RESCHEDULABLE_STATUSES = {"reserved", "booked", "paid"}
TERMINAL_STATUSES = {"completed", "canceled", "no_show"}

_TERMINAL_NOTES = {
    "canceled": "This appointment was cancelled.",
    "completed": "This appointment is complete.",
    "no_show": "This appointment was marked as a no-show.",
}


def appointment_service_label(appointment: dict[str, Any]) -> str:
    """Every line named, not just the first: a visit can be a massage AND a facial."""
    names = [str(line.get("service_name") or "").strip() for line in service_lines(appointment)]
    return " + ".join(name for name in names if name) or "Your appointment"


def _payment_note(appointment: dict[str, Any]) -> str:
    """Said only when there is money involved — see domain/booking_email for why $0.00 stays unsaid."""
    price = appointment_price(appointment) or {}
    if int(price.get("unit_amount") or 0) <= 0:
        return ""
    label = _price_label(price)
    if str(appointment.get("payment_status") or "") == "paid":
        return f"Paid in full — {label}."
    if str(appointment.get("booking_flow") or "") == "book_then_pay":
        return f"{label} is due for this appointment. We'll send you an invoice."
    return f"{label} is due for this appointment."


def render_manage_page(
    appointment: dict[str, Any],
    service: dict[str, Any] | None = None,
    *,
    business_name: str = "",
    when: str = "",
    place: str = "",
) -> str:
    """`when` is pre-formatted by the caller (domain/booking_email.appointment_when) so the page and the
    email that linked to it say the same sentence about the same moment."""
    status = str(appointment.get("status") or "")
    terminal = status in TERMINAL_STATUSES
    service_name = str((service or {}).get("name") or "").strip() or appointment_service_label(appointment)
    minutes = int(appointment_duration_minutes(appointment) or 0)

    replacements = {
        "__APPOINTMENT_ID__": escape(str(appointment.get("appointment_id") or ""), quote=True),
        "__MANAGE_TOKEN__": escape(str(appointment.get("customer_manage_token") or ""), quote=True),
        "__SERVICE_ID__": escape(str((service_lines(appointment) or [{}])[0].get("service_id") or ""), quote=True),
        "__STRIPE_MODE__": "live" if str(appointment.get("stripe_mode") or "").lower() == "live" else "test",
        "__BUSINESS__": escape(str(business_name or "")),
        "__SERVICE_NAME__": escape(service_name),
        "__WHEN__": escape(str(when or "")),
        "__DURATION_LABEL__": escape(_duration_label(minutes) if minutes else ""),
        "__WHERE__": (f'<p class="meta">{escape(place)}</p>' if place else ""),
        "__PAYMENT__": (lambda note: f'<p class="meta">{escape(note)}</p>' if note else "")(_payment_note(appointment)),
        "__TERMINAL_NOTE__": (
            f'<div class="msg error">{escape(_TERMINAL_NOTES.get(status, "This appointment is closed."))}</div>'
            if terminal else ""
        ),
        "__ACTIONS_HIDDEN__": " hidden" if terminal else "",
        "__PICKER_CSS__": PICKER_CSS + THEME_STANDALONE,
        "__PICKER_JS__": PICKER_JS,
        "__HORIZON_DAYS__": str(HORIZON_DAYS),
        "__CAN_RESCHEDULE__": "1" if status in RESCHEDULABLE_STATUSES else "",
    }
    page = _TEMPLATE
    for token, value in replacements.items():
        page = page.replace(token, value)
    return page


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta name="referrer" content="no-referrer">
<title>Your appointment</title>
<style>
  :root { --accent:#4f46e5; --danger:#b91c1c; --line:#e5e7eb; --muted:#6b7280; --bg:#f8fafc; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:var(--bg); color:#111827; }
  .wrap { max-width:40rem; margin:0 auto; padding:1.5rem; }
  .card { background:#fff; border:1px solid var(--line); border-radius:14px; padding:1.5rem; margin-bottom:1.25rem; }
  .biz { margin:0 0 .4rem; color:var(--muted); font-size:.85rem; text-transform:uppercase; letter-spacing:.04em; }
  h1 { margin:0 0 .5rem; font-size:1.5rem; }
  .when { margin:0 0 .25rem; font-size:1.15rem; font-weight:700; }
  .meta { color:var(--muted); margin:.25rem 0; }
  button.act { width:100%; margin-top:.75rem; padding:.8rem; border:0; border-radius:10px; font-size:1rem; font-weight:700; cursor:pointer; }
  button.primary { background:var(--accent); color:#fff; }
  button.quiet { background:#fff; color:var(--danger); border:1px solid var(--line); }
  button.act:disabled { opacity:.5; cursor:not-allowed; }
  .msg { padding:.9rem 1rem; border-radius:10px; margin-bottom:1rem; }
__PICKER_CSS__
  .msg.error { background:#fef2f2; color:var(--danger); }
  .msg.ok { background:#ecfdf5; color:#047857; }
</style>
</head>
<body>
<div class="wrap">
  <div id="banner">__TERMINAL_NOTE__</div>

  <div class="card">
    <p class="biz">__BUSINESS__</p>
    <h1>__SERVICE_NAME__</h1>
    <p class="when" id="when">__WHEN__</p>
    <p class="meta">__DURATION_LABEL__</p>
    __WHERE__
    __PAYMENT__
  </div>

  <div class="card" id="actions"__ACTIONS_HIDDEN__>
    <div id="picker" hidden>
      <h3>Pick a new time</h3>
      <div id="slotgrid"></div>
      <button id="confirm" class="act primary" disabled>Select a time</button>
    </div>
    <button id="reschedule" class="act primary">Reschedule</button>
    <button id="cancel" class="act quiet">Cancel this appointment</button>
  </div>
</div>
<script>
__PICKER_JS__
(function () {
  var appointmentId = "__APPOINTMENT_ID__";
  var manageToken = "__MANAGE_TOKEN__";
  var serviceId = "__SERVICE_ID__";
  var stripeMode = "__STRIPE_MODE__";
  var canReschedule = "__CAN_RESCHEDULE__" === "1";
  var apiBase = window.location.pathname.replace(/\\/booking\\/manage$/, "");
  var banner = document.getElementById("banner");
  var actions = document.getElementById("actions");
  var picker = document.getElementById("picker");
  var slotPicker = null;
  var rescheduleBtn = document.getElementById("reschedule");
  var cancelBtn = document.getElementById("cancel");
  var confirmBtn = document.getElementById("confirm");
  var selected = null;
  var selectedTimeLabel = "";
  var selectedDayLabel = "";

  if (!canReschedule && rescheduleBtn) { rescheduleBtn.hidden = true; }

  function showError(text) { banner.innerHTML = '<div class="msg error">' + text + '</div>'; }
  function showOk(text) { banner.innerHTML = '<div class="msg ok">' + text + '</div>'; }

  function post(path, body) {
    return fetch(apiBase + path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ appointment_id: appointmentId, manage_token: manageToken }, body))
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); });
  }

  function mountPicker() {
    if (slotPicker) { return; }
    slotPicker = window.slpMount({
      host: document.getElementById("slotgrid"),
      apiBase: apiBase,
      serviceId: serviceId,
      mode: stripeMode,
      horizonDays: __HORIZON_DAYS__,
      onSelect: function (slot, timeLabel, dayLabel) {
        selected = slot ? slot.start : null;
        selectedTimeLabel = timeLabel || "";
        selectedDayLabel = dayLabel || "";
        confirmBtn.disabled = !slot;
        confirmBtn.textContent = slot ? ("Move to " + timeLabel) : "Select a time";
      }
    });
  }

  if (rescheduleBtn) {
    rescheduleBtn.addEventListener("click", function () {
      picker.hidden = false;
      rescheduleBtn.hidden = true;
      mountPicker();
    });
  }

  confirmBtn.addEventListener("click", function () {
    if (!selected) { return; }
    confirmBtn.disabled = true; confirmBtn.textContent = "Moving\\u2026";
    post("/services/appointments/manage/reschedule", { slot_start: selected })
      .then(function (res) {
        if (!res.ok) { throw new Error(res.j.message || "That time is no longer available."); }
        document.getElementById("when").textContent = selectedDayLabel + " at " + selectedTimeLabel;
        picker.hidden = true;
        rescheduleBtn.hidden = false;
        selected = null;
        showOk("Your appointment has been moved. We've updated the details above.");
      })
      .catch(function (e) {
        showError(e.message);
        confirmBtn.disabled = true; confirmBtn.textContent = "Select a time";
        if (slotPicker) slotPicker.refresh();
      });
  });

  cancelBtn.addEventListener("click", function () {
    // A cancellation cannot be undone from here -- the slot goes straight back on sale -- so it asks.
    if (!window.confirm("Cancel this appointment? This cannot be undone.")) { return; }
    cancelBtn.disabled = true; cancelBtn.textContent = "Cancelling\\u2026";
    post("/services/appointments/manage/cancel", {})
      .then(function (res) {
        if (!res.ok) { throw new Error(res.j.message || "Could not cancel this appointment."); }
        actions.hidden = true;
        showOk("Your appointment has been cancelled.");
      })
      .catch(function (e) {
        showError(e.message);
        cancelBtn.disabled = false; cancelBtn.textContent = "Cancel this appointment";
      });
  });
})();
</script>
</body>
</html>
"""
