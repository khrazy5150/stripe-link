const API_BASES = {
  test: "https://dev.juniorbay.com",
  live: "https://prod.juniorbay.com",
};
const LOCAL_DEV_API_BASES = {
  test: "/api",
  live: "/api-live",
};
const API_BASE_STORAGE_KEY = "stripeLinkVueApiBase";
const APP_CONFIG_STORAGE_KEY = "stripeLinkVueAppConfig";
const API_ENVIRONMENT_STORAGE_KEY = "stripeLinkVueEnvironment";
const TENANT_ID_STORAGE_KEY = "stripeLinkTenantId";
const SESSION_STORAGE_KEY = "stripeLinkSession";
const DEFAULT_TENANT_ID = "tenant_demo";

function normalizeEnvironment(environment) {
  return environment === "live" ? "live" : "test";
}

function configEnvironment(environment) {
  return normalizeEnvironment(environment) === "live" ? "prod" : "dev";
}

function fallbackApiBase(environment) {
  const normalized = normalizeEnvironment(environment);
  if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
    return LOCAL_DEV_API_BASES[normalized];
  }
  return API_BASES[normalized];
}

function apiBaseStorageKey(environment) {
  return `${API_BASE_STORAGE_KEY}:${normalizeEnvironment(environment)}`;
}

function appConfigStorageKey(environment) {
  return `${APP_CONFIG_STORAGE_KEY}:${normalizeEnvironment(environment)}`;
}

export function getApiEnvironment() {
  return normalizeEnvironment(localStorage.getItem(API_ENVIRONMENT_STORAGE_KEY));
}

export function setApiEnvironment(environment) {
  localStorage.setItem(API_ENVIRONMENT_STORAGE_KEY, normalizeEnvironment(environment));
}

export function getApiBase() {
  const environment = getApiEnvironment();
  const configured = localStorage.getItem(apiBaseStorageKey(environment));
  if (configured) return configured;
  return (
    localStorage.getItem(environment === "live" ? "stripeLinkApiBaseLive" : "stripeLinkApiBaseTest") ||
    localStorage.getItem("stripeLinkApiBase") ||
    fallbackApiBase(environment)
  );
}

export function setApiBase(value) {
  localStorage.setItem(apiBaseStorageKey(getApiEnvironment()), value.replace(/\/$/, ""));
}

export function getEnvironmentConfig(environment = getApiEnvironment()) {
  const normalized = normalizeEnvironment(environment);
  const targetEnvironment = configEnvironment(normalized);
  const raw = localStorage.getItem(appConfigStorageKey(normalized));
  if (raw) {
    try {
      return JSON.parse(raw)?.environments?.[targetEnvironment] || {};
    } catch {
      localStorage.removeItem(appConfigStorageKey(normalized));
    }
  }
  return {};
}

export function getPagesBaseUrl(environment = getApiEnvironment()) {
  const configured = getEnvironmentConfig(environment).pages_base_url;
  if (configured) return configured.replace(/\/$/, "");
  return normalizeEnvironment(environment) === "live"
    ? "https://dlxn0y34f7dbz.cloudfront.net"
    : "https://drjfn283z66uz.cloudfront.net";
}

export function getPreviewPagesBaseUrl(environment = getApiEnvironment()) {
  const configured = getEnvironmentConfig(environment).pages_preview_base_url;
  if (configured) return configured.replace(/\/$/, "");
  return normalizeEnvironment(environment) === "live"
    ? "https://d1lcshydc31m77.cloudfront.net"
    : "https://d1lcshydc31m77.cloudfront.net";
}

export async function loadAppConfigApiBase(environment = getApiEnvironment()) {
  const normalized = normalizeEnvironment(environment);
  const targetEnvironment = configEnvironment(normalized);
  const candidateBases = [
    fallbackApiBase(normalized),
    normalized === "live" ? fallbackApiBase("test") : "",
  ].filter(Boolean);

  for (const base of [...new Set(candidateBases)]) {
    try {
      const url = new URL(`${base.replace(/\/$/, "")}/app-config/app_config`, window.location.origin);
      url.searchParams.set("environment", "global");
      const response = await fetch(url);
      const body = await response.json().catch(() => ({}));
      const configuredBase = body.app_config?.environments?.[targetEnvironment]?.api_base_url;
      if (response.ok && configuredBase) {
        localStorage.setItem(apiBaseStorageKey(normalized), configuredBase.replace(/\/$/, ""));
        localStorage.setItem(appConfigStorageKey(normalized), JSON.stringify(body.app_config));
        return {
          source: base,
          environment: targetEnvironment,
          api_base_url: configuredBase.replace(/\/$/, ""),
          app_config: body.app_config,
        };
      }
    } catch {
      // Keep bootstrapping from the next candidate; hard-coded fallback remains last resort.
    }
  }

  const fallback = fallbackApiBase(normalized);
  localStorage.setItem(apiBaseStorageKey(normalized), fallback.replace(/\/$/, ""));
  localStorage.removeItem(appConfigStorageKey(normalized));
  return {
    source: "fallback",
    environment: targetEnvironment,
    api_base_url: fallback.replace(/\/$/, ""),
    app_config: null,
  };
}

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

export async function apiRequest(path, { method = "GET", body, params = {} } = {}) {
  const url = new URL(`${getApiBase().replace(/\/$/, "")}${path}`, window.location.origin);
  Object.entries({ tenant_id: getTenantId(), client_id: getClientId(), ...params }).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  });
  const session = getAuthSession();

  const response = await fetch(url, {
    method,
    headers: {
      "Content-Type": "application/json",
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
