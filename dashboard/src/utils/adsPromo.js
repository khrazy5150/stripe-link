const MICROS = 1_000_000;
const usd = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", maximumFractionDigits: 6,
});

export const ESTIMATE_DAYS = [7, 14, 30];
export const PROMO_DEFAULT_MICROS = 5_000_000;

export function formatUsd(micros) {
  return usd.format(micros / MICROS);
}

export function usdToMicros(value) {
  const parts = /^(\d{1,8})(?:\.(\d{0,6}))?$/.exec(String(value).trim());
  if (!parts) return null;
  return Number(parts[1]) * MICROS + Number((parts[2] || "").padEnd(6, "0"));
}

export function spendEstimate(micros, days) {
  if (!Number.isSafeInteger(micros) || micros <= 0 || !ESTIMATE_DAYS.includes(days)) return null;
  return micros * days;
}

export function campaignStatus(campaign) {
  if (campaign.pause_pending) return "Pause queued";
  return ({
    draft: "Draft",
    preparing: "Creating paused campaign",
    paused: "Paused",
    launch_pending: "Launch queued",
    enabled: "Enabled in Google Ads",
    pause_pending: "Pause queued",
    removed: "Removed in Google Ads",
    reconciling: "Checking Google Ads",
    reconcile_required: "Needs a Google Ads status check",
  })[campaign.state] || "Status unavailable";
}


export function dateInZone(timeZone, now = new Date()) {
  if (!timeZone) return "";
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone, year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(now);
    const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
    return `${values.year}-${values.month}-${values.day}`;
  } catch {
    return "";
  }
}

export function addCalendarDays(date, days) {
  const utc = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(utc.getTime())) return "";
  utc.setUTCDate(utc.getUTCDate() + days);
  return utc.toISOString().slice(0, 10);
}

export function formatExperimentTime(seconds, timeZone) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone, dateStyle: "medium", timeStyle: "short",
  }).format(new Date(seconds * 1000));
}
