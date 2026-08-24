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
  const raw = sessionStorage.getItem(SESSION_STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
    return null;
  }
}

export function setAuthSession(session) {
  if (!session) {
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
    return;
  }
  sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
  if (session.tenant_id || session.client_id) setTenantId(session.tenant_id || session.client_id);
}

export function clearAuthSession() {
  sessionStorage.removeItem(SESSION_STORAGE_KEY);
  localStorage.removeItem(TENANT_ID_STORAGE_KEY);
}

export async function apiRequest(path, { method = "GET", body, params = {}, mode } = {}) {
  // Backend base is hostname-derived (release channel). `mode` (test/live) is a DATA filter sent as ?mode=;
  // pass an explicit `mode` to target the OTHER Stripe mode on the same backend (cross-mode copy).
  const base = getApiBase();
  const url = new URL(`${base.replace(/\/$/, "")}${path}`, window.location.origin);
  const stripeMode = normalizeStripeMode(mode || getStripeMode());
  Object.entries({ tenant_id: getTenantId(), client_id: getClientId(), mode: stripeMode, ...params }).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  });
  const session = getAuthSession();

  const response = await fetch(url, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-Stripe-Mode": stripeMode,
      ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(payload.message || payload.error || `Request failed with ${response.status}`);
  }
  return payload;
}
