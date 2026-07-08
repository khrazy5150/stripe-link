// Canonical IANA time-zone list for pickers. Uses the browser's own list
// (Intl.supportedValuesOf) so it stays current and matches what the zoneinfo-based
// backend accepts; falls back to a common subset on older browsers.

const FALLBACK = [
  "UTC",
  "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix",
  "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu",
  "America/Toronto", "America/Vancouver", "America/Mexico_City", "America/Sao_Paulo",
  "Europe/London", "Europe/Dublin", "Europe/Paris", "Europe/Berlin", "Europe/Madrid",
  "Europe/Rome", "Europe/Amsterdam", "Europe/Athens", "Europe/Moscow",
  "Africa/Johannesburg", "Africa/Cairo", "Africa/Lagos",
  "Asia/Dubai", "Asia/Karachi", "Asia/Kolkata", "Asia/Bangkok", "Asia/Singapore",
  "Asia/Hong_Kong", "Asia/Shanghai", "Asia/Tokyo", "Asia/Seoul",
  "Australia/Perth", "Australia/Sydney", "Pacific/Auckland",
];

export function timeZoneOptions(current = "") {
  let zones;
  try {
    zones = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : FALLBACK;
  } catch {
    zones = FALLBACK;
  }
  const list = Array.isArray(zones) && zones.length ? [...zones] : [...FALLBACK];
  if (!list.includes("UTC")) list.unshift("UTC");
  // Keep a previously-stored value selectable even if it's not in the canonical list.
  const value = String(current || "").trim();
  if (value && !list.includes(value)) list.push(value);
  return list;
}
