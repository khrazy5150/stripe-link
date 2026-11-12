// Pure, and in utils/ rather than stores/appointments.js for a reason that is also a test: the store
// imports pinia and the API client, so a node process cannot load it, and this helper's whole job is
// string shaping that deserves to be checked directly.
// WHAT is being performed. The canonical shape is `appointment.services[]` (domain/booking.py), and the
// top-level `service_name` is a RESPONSE-ONLY mirror that `_public_appointment` adds for the booking page
// -- the dashboard's list route returns raw documents, which carry no such field. So every row on the
// Appointments calendar read `a.service_name` and rendered nothing, which is survivable with one service
// and useless to a spa offering a 60-minute Thai and a 120-minute Swedish (author, 2026-11-12).
//
// Every line is named, not just the first: a Booking covers services[] line items, so a visit can be a
// massage AND a facial, and naming one of them is a different appointment from the one that was booked.
export function appointmentServiceLabel(appointment) {
  const names = (appointment?.services || [])
    .map((line) => String(line?.service_name || "").trim())
    .filter(Boolean);
  if (names.length) return names.join(" + ");
  // The mirrors, for anything reading a booking-page response rather than a stored document.
  return String(appointment?.service_name || "").trim()
    || String(appointment?.service_id || "").trim()
    || "—";
}
