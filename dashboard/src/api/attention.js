// The Attention service (../sam/attention), reached on the SHARED Cognito pool.
//
// A thin adapter, deliberately: no campaign logic lives here. The service derives everything from the
// offer's own semantic model, and duplicating any of that in the dashboard would be the second extraction
// ATTENTION_PRIMITIVE.md §2 forbids. These functions do two things the components should not: they name the
// base, and they turn the service's refusals into something a panel can render.
import { apiRequest, getAttentionApiBase } from "./client";

export const CHANNELS = [
  { key: "instagram", label: "Instagram carousel" },
  { key: "tiktok", label: "TikTok" },
  { key: "youtube_shorts", label: "YouTube Shorts" },
];

// Display names for the five pillars. A LABEL MAP, not logic: the service decides which pillars an offer
// supports and in what order, and this only spells them for a human. Any pillar it does not know is shown
// by its own key rather than hidden, so a new pillar added service-side appears instead of vanishing.
const PILLAR_LABELS = {
  problem: "The problem",
  education: "Something useful",
  mistakes: "A mistake to stop making",
  transformation: "Before and after",
  product_proof: "The ask",
};

export function pillarLabel(key) {
  return PILLAR_LABELS[key] || String(key || "");
}

export function attentionConfigured() {
  return Boolean(getAttentionApiBase());
}

// The refusals a panel must tell apart, rather than showing one "something went wrong". Each maps to a
// DIFFERENT next action for the tenant, which is the whole reason the service returns distinct codes.
export const NOT_ENTITLED = "not_entitled";
export const NO_SEMANTIC_MODEL = "no_semantic_model";
export const OFFER_NOT_FOUND = "offer_not_found";

async function get(path, params) {
  const base = getAttentionApiBase();
  // Callers gate on `attentionConfigured()`; this is the backstop, because firing at `undefined/me/context`
  // would surface as an opaque network error rather than as "not configured here yet".
  if (!base) {
    const error = new Error("Attention is not configured for this environment.");
    error.code = "not_configured";
    throw error;
  }
  try {
    // `mode` is added by apiRequest from the dashboard's current Stripe mode, which is exactly what the
    // service requires -- it refuses a request that does not name one rather than defaulting to test.
    return await apiRequest(path, { base, params });
  } catch (err) {
    // Keep the service's own code on the error so a panel can branch on it. `payload.error` is the code;
    // `message` is already written for a tenant to read, so it is passed through unchanged rather than
    // being replaced by a worse sentence here.
    err.code = err.payload?.error || err.code || "";
    throw err;
  }
}

export function fetchContext(offerId) {
  return get("/me/context", { offer_id: offerId });
}

export function fetchBriefs(offerId, channel, count) {
  return get("/me/briefs", { offer_id: offerId, channel, ...(count ? { count } : {}) });
}

// ---------------------------------------------------------------------------------------------------
// A3/A4 -- campaigns and the calendar.
// ---------------------------------------------------------------------------------------------------

export const INTENSITIES = [
  { key: "light", label: "One post a week" },
  { key: "standard", label: "Two posts a week" },
  { key: "committed", label: "Three posts a week" },
];

export const DURATIONS = [7, 14, 30, 60, 90];

export const STATUS_PLANNED = "planned";
export const STATUS_SKIPPED = "skipped";

async function postJson(path, body, params) {
  const base = getAttentionApiBase();
  if (!base) {
    const error = new Error("Attention is not configured for this environment.");
    error.code = "not_configured";
    throw error;
  }
  try {
    return await apiRequest(path, { base, method: "POST", body, ...(params ? { params } : {}) });
  } catch (err) {
    err.code = err.payload?.error || err.code || "";
    throw err;
  }
}

export function planCampaign(offerId, { days, intensity, channels } = {}) {
  // The offer rides in the QUERY STRING, not the body: the service reads it with the same `?offer_id=`
  // the read routes use, so one route does not learn a second way to name an offer.
  return postJson("/me/campaigns", { days, intensity, channels }, { offer_id: offerId });
}

export function fetchCampaigns() {
  return get("/me/campaigns");
}

export function fetchCalendar({ campaignId, from, to } = {}) {
  return get("/me/posts", {
    ...(campaignId ? { campaign_id: campaignId } : {}),
    ...(from ? { from } : {}),
    ...(to ? { to } : {}),
  });
}

// Both amendments send the post's CURRENT due_at as well as its id, because due_at is part of the
// storage key -- without it the service has no key to address and would have to scan to find one.
export function setPostStatus(post, status) {
  return postJson("/me/posts/status", { post_id: post.post_id, due_at: post.due_at, status });
}

export function reschedulePost(post, to) {
  return postJson("/me/posts/schedule", { post_id: post.post_id, due_at: post.due_at, to });
}
