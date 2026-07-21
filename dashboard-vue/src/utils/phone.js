// E.164 phone helpers — mirror of domain/documents.py normalize_e164/require_e164 so the dashboard shows the
// same validation the API enforces. E.164 is what the registration flow (Cognito) already requires for the
// account phone; the business phone and Site Organization telephone are held to the same standard.

const E164_RE = /^\+[1-9]\d{1,14}$/;

// Strip human formatting and treat a leading international "00" as "+". Does NOT invent a country code —
// a number without a leading "+" stays without one, so isE164 flags it instead of guessing wrong.
export function normalizeE164(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return "";
  const digits = raw.replace(/\D/g, "");
  if (raw.startsWith("+")) return "+" + digits;
  if (digits.startsWith("00")) return "+" + digits.slice(2);
  // North American Numbering Plan: recover +1 for a bare NANP number — 1 + 10 digits, or a plain 10-digit
  // national number (the everyday US/Canada format). Non-NANP numbers are entered with a full "+<country>".
  if (digits.length === 11 && digits.startsWith("1")) return "+" + digits;
  if (digits.length === 10) return "+1" + digits;
  return digits;
}

export function isE164(value) {
  return E164_RE.test(normalizeE164(value));
}

// A ready-to-show error for an optional phone field, or "" when empty/valid.
export function phoneError(value) {
  if (!String(value ?? "").trim()) return "";
  return isE164(value) ? "" : "Use international format, e.g. +12065551234 (same as your account phone).";
}
