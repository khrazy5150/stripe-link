// Cross-environment copy (test <-> live). Shared by the page copy (LandingPages.vue) and the Site copy
// (Sites.vue) so the transform + dependency-resolution rules live in exactly one place.
//
// The copy is client-orchestrated: cross-env writes go through the OTHER environment's API base
// (apiRequest({ environment })), which a backend Lambda can't reach — so the browser resolves the dependency
// graph in the source env and re-POSTs each document to the target env, bottom-up (products -> offers -> pages
// -> Site) so references resolve as they land. IDs are preserved across environments.
import { apiRequest } from "../api/client";

// "live"/"test" — the Stripe mode + Site.environment value for the target.
export const targetMode = (env) => (env === "live" ? "live" : "test");

// Faithful clone — NOT a null/empty-stripping clean: these are already-valid documents, and dropping
// null/empty values would delete schema-required-but-nullable keys (e.g. fulfillment.ship_from: null). We only
// touch specific fields per transform.
export const cloneDoc = (doc) => JSON.parse(JSON.stringify(doc));
const freshSync = () => ({ status: "pending", last_synced_at: null, error: null });
const nowSec = () => Math.floor(Date.now() / 1000);

// Transforms: flip stripe_mode to the target and drop the SOURCE env's Stripe object ids — the target rebuilds
// the price inline at checkout with its own key (see the checkout mode-guard).
export function productForTarget(product, env) {
  const p = cloneDoc(product);
  p.stripe_mode = targetMode(env);
  delete p.stripe_product_id;
  for (const price of p.prices || []) delete price.stripe_price_id;
  if ("sync" in p) p.sync = freshSync();  // Stripe-sync state is per-env; reset it
  p.updated_at = nowSec();
  return p;
}

export function offerForTarget(offer, env) {
  const o = cloneDoc(offer);
  o.stripe_mode = targetMode(env);
  if ("sync" in o) o.sync = freshSync();
  o.updated_at = nowSec();
  return o;
}

export function pageForTarget(page, existingTarget, env) {  // eslint-disable-line no-unused-vars
  const now = nowSec();
  const status = existingTarget?.status || "draft";  // new -> draft; never downgrade a published target
  const p = cloneDoc(page);
  p.status = status;
  delete p.analytics_summary;  // target keeps its own (or zero) analytics
  p.published_at = status === "published" ? (existingTarget?.published_at || page.published_at || null) : null;
  p.created_at = existingTarget?.created_at || page.created_at || now;
  p.updated_at = now;
  p.revision = (existingTarget?.revision || 0) + 1;
  return p;
}

// The Site itself. The route map, organization, SEO settings, navigation and pages carry over verbatim (same
// IDs). The custom domain is env-specific and NOT copied — the target Site is immediately navigable on its own
// free platform host, and connecting a domain there is a separate step. The platform hostname is regenerated
// for the TARGET env's hosting domain (jbay.uk vs jbay.be), so we strip it and pass the subdomain label for the
// target's handler to rebuild (plans/PLATFORM_HOSTNAME_SERVING.md P2).
export function siteForTarget(site, existingTarget, env) {
  const now = nowSec();
  const s = cloneDoc(site);
  s.environment = env === "live" ? "live" : "test";
  const hosting = s.hosting || {};
  const label = subdomainLabel(hosting.platform_hostname) || subdomainLabel(existingTarget?.hosting?.platform_hostname);
  s.hosting = { type: "platform", platform_subdomain: label };  // drop custom_domain + verification + hostname
  delete s.domain_provisioning;
  // No custom domain on the copy -> not eligible to be indexed; the target recomputes on domain connect/verify.
  s.indexing = { ...(s.indexing || {}), eligibility: "blocked" };
  s.created_at = existingTarget?.created_at || site.created_at || now;
  s.updated_at = now;
  return s;
}

// The label of a platform hostname ("axel-mart" from "axel-mart.jbay.be").
function subdomainLabel(hostname) {
  return String(hostname || "").split(".")[0] || "";
}

// Every offer a page references — its primary offer plus any catalog-grid items.
export function offerIdsForPage(page) {
  const ids = new Set();
  if (page.offer_id) ids.add(page.offer_id);
  for (const section of page.sections || []) {
    if (section && section.type === "catalog_grid") {
      for (const item of section.items || []) if (item.offer_id) ids.add(item.offer_id);
    }
  }
  return [...ids];
}

// Resolve a document from an in-memory cache first (the loaded catalog for the current env), falling back to the
// source-env API. Returns null if it can't be found, so callers filter(Boolean).
export async function resolveOfferDoc(offerId, cache = []) {
  return cache.find((o) => o.offer_id === offerId)
    || apiRequest(`/offers/${encodeURIComponent(offerId)}`).then((b) => b.offer).catch(() => null);
}
export async function resolveProductDoc(productId, cache = []) {
  return cache.find((p) => p.product_id === productId)
    || apiRequest(`/products/${encodeURIComponent(productId)}`).then((b) => b.product).catch(() => null);
}
export async function resolvePageDoc(pageId, cache = []) {
  return cache.find((p) => p.page_id === pageId)
    || apiRequest(`/pages/${encodeURIComponent(pageId)}`).then((b) => b.page).catch(() => null);
}

// Resolve a page's full catalog dependency graph (its offers + their products). `hasServices` flags that the
// offer(s) reference services, which are NOT copied (surfaced to the user).
export async function resolvePageDeps(page, { offerCache = [], productCache = [] } = {}) {
  const offerDocs = (await Promise.all(offerIdsForPage(page).map((id) => resolveOfferDoc(id, offerCache)))).filter(Boolean);
  const productIds = new Set();
  let hasServices = false;
  for (const offer of offerDocs) {
    for (const item of offer.items || []) {
      if (item.product_id) productIds.add(item.product_id);
      if (item.service_id) hasServices = true;
    }
  }
  const productDocs = (await Promise.all([...productIds].map((id) => resolveProductDoc(id, productCache)))).filter(Boolean);
  return { offerDocs, productDocs, hasServices };
}

// Write a catalog (products then offers) to the target env — the shared bottom-up prefix of every copy.
export async function copyCatalogToEnv(productDocs, offerDocs, env) {
  for (const product of productDocs) {
    await apiRequest("/products", { method: "POST", body: productForTarget(product, env), environment: env });
  }
  for (const offer of offerDocs) {
    await apiRequest("/offers", { method: "POST", body: offerForTarget(offer, env), environment: env });
  }
}
