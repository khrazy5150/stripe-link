// Stripe-mode / release-channel decoupling (plans/STRIPE_MODE_DECOUPLING.md).
//
// TWO orthogonal concepts, previously one toggle:
//   - RELEASE CHANNEL (dev/prod) = which backend/code version. Derived from the HOSTNAME, not chosen by the user.
//   - STRIPE MODE (test/live)     = a per-tenant DATA filter WITHIN a backend. The dashboard toggle; sent as ?mode=.
// The backend base follows the hostname; the toggle only changes which mode's data we read/write.

const API_BASES = {
  dev: "https://dev.juniorbay.com",
  prod: "https://prod.juniorbay.com",
};
// Localhost hits the dev backend through the Vite proxy; mode is a query param, so a single proxy suffices.
const LOCAL_DEV_API_BASE = "/api";
const API_BASE_STORAGE_KEY = "stripeLinkVueApiBase";
const APP_CONFIG_STORAGE_KEY = "stripeLinkVueAppConfig";
const STRIPE_MODE_STORAGE_KEY = "stripeLinkVueStripeMode";
// Pre-decoupling toggle key — its value (test/live) was the Stripe mode, so carry it forward once.
const LEGACY_ENV_STORAGE_KEY = "stripeLinkVueEnvironment";
const TENANT_ID_STORAGE_KEY = "stripeLinkTenantId";
const SESSION_STORAGE_KEY = "stripeLinkSession";
const DEFAULT_TENANT_ID = "tenant_demo";

export function normalizeStripeMode(mode) {
  return mode === "live" ? "live" : "test";
}

// The platform RELEASE CHANNEL ("dev" | "prod"), derived from the HOSTNAME: app.* = prod (released),
// sandbox.*/localhost = dev (staging). Unknown hosts assume released prod (verify per deployment at cutover).
export function hostnameReleaseChannel() {
  const host = window.location.hostname;
  if (host === "localhost" || host === "127.0.0.1") return "dev";
  if (host.startsWith("app.")) return "prod";
  if (host.startsWith("sandbox.")) return "dev";
  return "prod";
}

function isLocalhost() {
  return window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
}

function apiBaseStorageKey(channel = hostnameReleaseChannel()) {
  return `${API_BASE_STORAGE_KEY}:${channel}`;
}

function appConfigStorageKey(channel = hostnameReleaseChannel()) {
  return `${APP_CONFIG_STORAGE_KEY}:${channel}`;
}

// --- Stripe mode (the tenant-facing test/live toggle) -------------------------------------------------------

// The per-tenant Stripe mode (test/live) — a DATA filter within a backend, independent of the release channel.
// Product default is "live" (live-first onboarding); a tenant opts into a test sandbox explicitly. Falls back to
// the pre-decoupling toggle value so an existing dashboard keeps its current selection across the change.
export function getStripeMode() {
  const stored = localStorage.getItem(STRIPE_MODE_STORAGE_KEY) || localStorage.getItem(LEGACY_ENV_STORAGE_KEY);
  return normalizeStripeMode(stored || "live");
}

export function setStripeMode(mode) {
  localStorage.setItem(STRIPE_MODE_STORAGE_KEY, normalizeStripeMode(mode));
}

// The "other" Stripe mode — the target for a cross-mode copy (test <-> live), now on the SAME backend.
export function getOtherEnvironment(mode = getStripeMode()) {
  return normalizeStripeMode(mode) === "live" ? "test" : "live";
}

// --- Backend base (release channel) ------------------------------------------------------------------------

export function getApiBase() {
  const channel = hostnameReleaseChannel();
  const configured = localStorage.getItem(apiBaseStorageKey(channel));
  if (configured) return configured;
  if (isLocalhost()) return LOCAL_DEV_API_BASE;
  return API_BASES[channel];
}

export function setApiBase(value) {
  localStorage.setItem(apiBaseStorageKey(), value.replace(/\/$/, ""));
}

export function getEnvironmentConfig(channel = hostnameReleaseChannel()) {
  const raw = localStorage.getItem(appConfigStorageKey(channel));
  if (raw) {
    try {
      return JSON.parse(raw)?.environments?.[channel] || {};
    } catch {
      localStorage.removeItem(appConfigStorageKey(channel));
    }
  }
  return {};
}

export function getPagesBaseUrl(channel = hostnameReleaseChannel()) {
  // Config-driven per channel (pages_base_url, deploy-populated from the stack's PagesDistributionDomainName).
  // No hardcoded CDN fallback; empty only until app_config loads (bootstrap).
  const configured = getEnvironmentConfig(channel).pages_base_url;
  return configured ? configured.replace(/\/$/, "") : "";
}

export function getPreviewPagesBaseUrl(channel = hostnameReleaseChannel()) {
  // Config-driven per channel ({stage}-live.juniorbay.com, deploy-populated). No hardcoded fallback: a default here
  // previously pointed prod at the DEV preview dist (the misroute). Empty until app_config loads (bootstrap).
  const configured = getEnvironmentConfig(channel).pages_preview_base_url;
  return configured ? configured.replace(/\/$/, "") : "";
}

// The per-channel test-mode page-viewer host ({stage}-test.juniorbay.com), deploy-populated into app_config.
// Replaces the old hardcoded TEST_PAGES_HOST = "test.juniorbay.com" (which was dev-only → prod test previews 404'd).
export function getTestPagesHost(channel = hostnameReleaseChannel()) {
  return getEnvironmentConfig(channel).test_pages_host || "";
}

// The shared asset-delivery CDN base (public_asset_base_url, e.g. https://images.juniorbay.com). Config-driven so
// a CDN migration is a single app_config change, not a code sweep. "" until app_config loads.
export function getAssetBaseUrl(channel = hostnameReleaseChannel()) {
  return (getEnvironmentConfig(channel).public_asset_base_url || "").replace(/\/$/, "");
}

// Build an asset URL from the configured CDN base: assetUrl("/icon/favicon.png") -> https://<cdn>/icon/favicon.png.
export function assetUrl(path = "") {
  const base = getAssetBaseUrl();
  if (!base) return "";
  return base + (path.startsWith("/") ? path : `/${path}`);
}

// Rewrite an upload-bucket URL (images.juniorbay.net host) onto the configured asset CDN host — replaces the
// scattered `.replace("images.juniorbay.net", "images.juniorbay.com")` so the CDN host lives only in config.
export function toAssetCdnUrl(url, uploadBucketHost = "images.juniorbay.net") {
  const host = getAssetBaseUrl().replace(/^https?:\/\//, "");
  return host ? String(url || "").replace(uploadBucketHost, host) : String(url || "");
}

export async function loadAppConfigApiBase(channel = hostnameReleaseChannel()) {
  const base = getApiBase();
  try {
    const url = new URL(`${base.replace(/\/$/, "")}/app-config/app_config`, window.location.origin);
    url.searchParams.set("environment", "global");
    const response = await fetch(url);
    const body = await response.json().catch(() => ({}));
    const configuredBase = body.app_config?.environments?.[channel]?.api_base_url;
    if (response.ok && configuredBase) {
      localStorage.setItem(apiBaseStorageKey(channel), configuredBase.replace(/\/$/, ""));
      localStorage.setItem(appConfigStorageKey(channel), JSON.stringify(body.app_config));
      return {
        source: base,
        environment: channel,
        api_base_url: configuredBase.replace(/\/$/, ""),
        app_config: body.app_config,
      };
    }
  } catch {
    // Fall through to the built-in per-channel base.
  }

  const fallback = isLocalhost() ? LOCAL_DEV_API_BASE : API_BASES[channel];
  localStorage.removeItem(appConfigStorageKey(channel));
  return {
    source: "fallback",
    environment: channel,
    api_base_url: fallback.replace(/\/$/, ""),
    app_config: null,
  };
}

// --- Tenant / session --------------------------------------------------------------------------------------

export function getTenantId() {
  return getAuthSession()?.tenant_id || getAuthSession()?.client_id || localStorage.getItem(TENANT_ID_STORAGE_KEY) || DEFAULT_TENANT_ID;
}

export function setTenantId(value) {
  localStorage.setItem(TENANT_ID_STORAGE_KEY, value || DEFAULT_TENANT_ID);
}

export function getClientId() {
  return getAuthSession()?.client_id || getTenantId();
}

export function getAuthSession() {
  // The session lives in localStorage, NOT sessionStorage (moved 2026-09-28).
  //
  // sessionStorage is per-tab and dies with the tab, so a reopened dashboard had a tenant id (localStorage)
  // and no token -- and because `Authorization` was attached conditionally, it cheerfully issued tenant-scoped
  // requests with no credentials, which the API answered 200. That is measurable in the logs: nine such calls
  // across eight screens inside 3.7 seconds, one per page load (plans/API_AUTHENTICATION.md). The moment the
  // Cognito authorizer lands those become 401 on every screen, so the two halves of the identity have to
  // live in the same place and last as long as each other.
  let raw = localStorage.getItem(SESSION_STORAGE_KEY);
  if (!raw) {
    // Carry a signed-in user across the change instead of logging everyone out on deploy.
    const legacy = sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (legacy) {
      localStorage.setItem(SESSION_STORAGE_KEY, legacy);
      sessionStorage.removeItem(SESSION_STORAGE_KEY);
      raw = legacy;
    }
  }
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    localStorage.removeItem(SESSION_STORAGE_KEY);
    return null;
  }
}

export function setAuthSession(session) {
  if (!session) {
    localStorage.removeItem(SESSION_STORAGE_KEY);
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
    return;
  }
  // Stamp an absolute deadline. The backend sends expires_in (a DURATION) plus the moment it was issued, and a
  // duration is useless to a page that may be reloaded hours later -- the whole reason nothing could tell a
  // fresh token from an expired one.
  const stored = { ...session };
  const issuedAt = Number(stored.refreshed_at || stored.created_at || Math.floor(Date.now() / 1000));
  const ttl = Number(stored.expires_in || 0);
  if (issuedAt && ttl) stored.expires_at = issuedAt + ttl;
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(stored));
  if (stored.tenant_id || stored.client_id) setTenantId(stored.tenant_id || stored.client_id);
}

export function clearAuthSession() {
  localStorage.removeItem(SESSION_STORAGE_KEY);
  sessionStorage.removeItem(SESSION_STORAGE_KEY);  // the pre-2026-09-28 location
  localStorage.removeItem(TENANT_ID_STORAGE_KEY);
}

export class UnauthenticatedError extends Error {
  constructor() {
    super("Your session has ended. Please sign in again.");
    this.name = "UnauthenticatedError";
  }
}

export const SESSION_ENDED_EVENT = "jb:session-ended";

/**
 * Drop the session AND tell the app.
 *
 * Clearing storage is not enough on its own: the auth store keeps its own copy of the session in state, so a
 * silent wipe leaves the dashboard rendered and authenticated-looking while every request fails. The event is
 * how the API layer reaches the Vue layer without importing it.
 */
function endSession() {
  clearAuthSession();
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(SESSION_ENDED_EVENT));
}

// Renew a little BEFORE the token dies, so a request already in flight cannot cross the boundary.
const EXPIRY_SKEW_SECONDS = 120;

// One refresh at a time. A dashboard screen fires several requests at once, and without this each would mint
// its own token -- N round trips where one will do, and with rotation enabled the later ones would be
// refreshing against an already-spent token.
let refreshInFlight = null;

function sessionExpiresAt(session) {
  if (!session) return 0;
  if (session.expires_at) return Number(session.expires_at);
  const issuedAt = Number(session.refreshed_at || session.created_at || 0);
  const ttl = Number(session.expires_in || 0);
  return issuedAt && ttl ? issuedAt + ttl : 0;
}

function sessionIsFresh(session) {
  const expiresAt = sessionExpiresAt(session);
  // No deadline recorded (a session stored before this shipped) means we cannot judge -- treat it as fresh
  // rather than forcing a login on missing data. A 401 still triggers the reactive path below.
  if (!expiresAt) return true;
  return expiresAt - EXPIRY_SKEW_SECONDS > Math.floor(Date.now() / 1000);
}

/**
 * Exchange the refresh token for a new access token.
 *
 * Cognito access tokens last an hour and refresh tokens 30 days, and until this existed nothing used the
 * second fact: the session carried a refresh_token that no code read (plans/API_AUTHENTICATION.md). Failure is
 * deliberately terminal -- clear the session and surface UnauthenticatedError, because a refresh token Cognito
 * has rejected will not start working on a retry.
 */
export async function refreshSession() {
  const current = getAuthSession();
  if (!current?.refresh_token) {
    endSession();
    throw new UnauthenticatedError();
  }
  if (!refreshInFlight) {
    refreshInFlight = apiRequest("/auth/refresh", {
      method: "POST",
      body: { refresh_token: current.refresh_token },
      anonymous: true,
    })
      .then((payload) => {
        const merged = { ...current, ...(payload.session || {}) };
        setAuthSession(merged);
        return getAuthSession();
      })
      .catch(() => {
        endSession();
        throw new UnauthenticatedError();
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

export async function apiRequest(path, { method = "GET", body, params = {}, mode, raw = false, anonymous = false } = {}) {
  // Backend base is hostname-derived (release channel). `mode` (test/live) is a DATA filter sent as ?mode=;
  // pass an explicit `mode` to target the OTHER Stripe mode on the same backend (cross-mode copy).
  const base = getApiBase();
  const url = new URL(`${base.replace(/\/$/, "")}${path}`, window.location.origin);
  const stripeMode = normalizeStripeMode(mode || getStripeMode());
  Object.entries({ tenant_id: getTenantId(), client_id: getClientId(), mode: stripeMode, ...params }).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  });
  let session = getAuthSession();

  // Fail CLOSED, the same way the server's route table does (stripe_link/api_auth.py): a caller that cannot
  // name itself does not get to send a tenant-scoped request. Without this the client did something worse
  // than going unauthenticated -- `getTenantId()` falls back to localStorage and then to a hardcoded
  // "tenant_demo", so a token-less dashboard CLAIMED a specific tenant id. `anonymous` is the explicit opt-in
  // for the handful of calls that legitimately precede a session (the /auth/* family), rather than the client
  // keeping its own copy of the public-route list and letting it drift from the server's.
  if (!anonymous) {
    if (!session?.access_token) {
      endSession();
      throw new UnauthenticatedError();
    }
    // Renew BEFORE sending rather than after being refused. The reactive path below cannot fire yet -- no
    // authorizer answers 401 today -- so proactive renewal is the half that actually works now, and the half
    // that keeps working if an authorizer's 401 ever arrives without a WWW-Authenticate we recognise.
    if (!sessionIsFresh(session)) session = await refreshSession();
  }

  const send = (active) => fetch(url, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-Stripe-Mode": stripeMode,
      ...(active?.access_token ? { Authorization: `Bearer ${active.access_token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  let response = await send(session);
  // Belt to the proactive braces: a token can be rejected while our clock says it is fine (a revoked session, a
  // skewed clock, a pool-side signing change). Retry exactly ONCE -- a second 401 after a fresh token is a real
  // refusal, and looping on it would hammer the API with an unusable credential.
  if (response.status === 401 && !anonymous) {
    session = await refreshSession();
    response = await send(session);
  }

  const text = await response.text();
  // `raw` is for endpoints that answer with a file rather than JSON (the coupon-codes CSV). The error
  // path still parses, because a failure comes back as JSON whatever the happy path returns.
  if (raw && response.ok) return text;
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const error = new Error(payload.message || payload.error || `Request failed with ${response.status}`);
    // Keep the body and the status on the error. A failure response often carries usable data -- a 404 from
    // /config still returns the refund vocabulary and the platform's default terms, because neither depends
    // on the tenant having saved a config document -- and throwing that away forced callers to guess.
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}
