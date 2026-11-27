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

// A change made in Google Ads outside Junior Bay, found by Attention's settings watch. Each message names
// what the tenant should do, and the notice disappears once a clean read shows the change is gone.
export function driftMessage(campaign) {
  const drift = campaign?.provider_drift;
  if (!drift) return "";
  const approved = formatUsd(campaign.draft?.budget?.amount_micros);
  const change = ({
    budget_increased: `Its average daily budget was raised to ${formatUsd(drift.observed_budget_micros)} in Google Ads, above the ${approved} you approved.`,
    budget_replaced: `Its budget was replaced or shared in Google Ads, so the ${approved} average daily budget you approved no longer applies.`,
    enabled_in_google: "It was turned back on in Google Ads after Junior Bay paused it, so it can spend.",
    provider_access_lost: "Junior Bay can no longer read or pause it in Google Ads. Ads can keep serving there.",
  })[drift.code];
  if (!change) return "";
  if (drift.pause_queued) return `${change} As you chose at approval, Junior Bay requested a pause.`;
  if (drift.code === "provider_access_lost") return `${change} Reconnect Google Ads, or pause the campaign in Google Ads.`;
  return `${change} Review it in Google Ads, and pause the campaign if you didn't intend the change.`;
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

const humanize = (code) => String(code || "").replaceAll("_", " ").toLowerCase();

// Google's verdict on the ad, kept apart from Junior Bay's own state (a running campaign can be disapproved).
export function reviewText(review) {
  if (!review) return "";
  const topics = (review.policy_topics || []).map(humanize).join(", ");
  switch (review.approval_status) {
    case "APPROVED": return "Approved";
    case "APPROVED_LIMITED": return `Approved with limits${topics ? `: ${topics}` : ""}`;
    case "AREA_OF_INTEREST_ONLY": return "Approved for some places only";
    case "DISAPPROVED": return `Disapproved${topics ? `: ${topics}` : ""}`;
    default: return ["REVIEW_IN_PROGRESS", "UNDER_REVIEW"].includes(review.review_status) ? "Under review" : "Not reviewed yet";
  }
}

const ELIGIBILITY = {
  ELIGIBLE: "Eligible to show", PAUSED: "Paused", PENDING: "Pending", LIMITED: "Limited", LEARNING: "Learning",
  NOT_ELIGIBLE: "Not eligible to show", ENDED: "Ended", REMOVED: "Removed", MISCONFIGURED: "Misconfigured",
};

export function eligibilityText(review) {
  if (!review) return "";
  const reasons = (review.primary_reasons || []).map(humanize).join(", ");
  return `${ELIGIBILITY[review.primary_status] || humanize(review.primary_status)}${reasons ? ` (${reasons})` : ""}`;
}
