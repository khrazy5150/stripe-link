const DEFAULT_API_BASE = "https://dev.juniorbay.com";
const LOCAL_DEV_API_BASE = "/api";
const API_BASE_STORAGE_KEY = "stripeLinkVueApiBase";
const TENANT_ID_STORAGE_KEY = "stripeLinkTenantId";
const SESSION_STORAGE_KEY = "stripeLinkSession";
const DEFAULT_TENANT_ID = "tenant_demo";

export function getApiBase() {
  const configured = localStorage.getItem(API_BASE_STORAGE_KEY);
  if (configured) return configured;
  if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
    return LOCAL_DEV_API_BASE;
  }
  return (
    localStorage.getItem("stripeLinkApiBaseTest") ||
    localStorage.getItem("stripeLinkApiBase") ||
    DEFAULT_API_BASE
  );
}

export function setApiBase(value) {
  localStorage.setItem(API_BASE_STORAGE_KEY, value.replace(/\/$/, ""));
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
