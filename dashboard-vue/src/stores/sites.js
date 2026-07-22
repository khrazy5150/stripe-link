import { defineStore } from "pinia";
import { apiRequest, getApiEnvironment, getTenantId } from "../api/client";
import { isE164, normalizeE164 } from "../utils/phone";

const SITE_SCHEMA_VERSION = "2026-07-20";

function slugify(value) {
  const slug = String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return slug || "site";
}

function pruneEmpty(object) {
  return Object.fromEntries(
    Object.entries(object).filter(([, v]) => v !== undefined && v !== null && v !== "" && !(typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length)),
  );
}

// Consolidate the tenant's business identity (from the Profile "business" block) into a Site Organization.
export function organizationFromBusiness(business = {}) {
  const address = business.address || {};
  // Only carry a valid E.164 phone into the derived Organization — a legacy malformed number must not block
  // the default-Site creation (the API validates the telephone strictly). Directly-entered phones are
  // validated in the form instead.
  return pruneEmpty({
    name: business.name || "",
    entity_type: "OnlineStore",
    telephone: isE164(business.phone) ? normalizeE164(business.phone) : "",
    email: business.email || "",
    address: pruneEmpty({
      street: address.street || "", locality: address.locality || "", region: address.region || "",
      postal_code: address.postal_code || "", country: address.country || "US",
    }),
  });
}

// Build a default Site from the tenant's existing pages + business identity (the incremental backfill).
// Requires >=1 page (the schema needs a non-empty route map). Slug = each page's route.slug; a lone page
// becomes the "/" root. The backend fills the platform hostname from the configured hosting domain.
// A DNS-safe slug suggestion for a tenant's store subdomain, seeded from the business name.
export function suggestSubdomain(business = {}) {
  return slugify(business.name || business.brand || "");
}

export function buildDefaultSite(pages, business = {}, subdomain = "") {
  const list = (pages || []).filter((p) => p && p.page_id);
  const map = {};
  const used = new Set();
  list.forEach((page, index) => {
    let slug = list.length === 1 ? "/" : "/" + slugify(page.route?.slug || page.name || page.page_id);
    while (used.has(slug)) slug = `${slug === "/" ? "/home" : slug}-${index}`;
    used.add(slug);
    map[slug] = pruneEmpty({
      page_id: page.page_id,
      page_type: "landing",
      label: page.name || "",
      enabled: page.status === "published",
    });
  });
  const chosen = slugify(subdomain || business.name || "site");
  return {
    schema_version: SITE_SCHEMA_VERSION,
    document_type: "site",
    tenant_id: getTenantId(),
    environment: getApiEnvironment(),
    name: business.name || "My Site",
    status: "active",
    hosting: { type: "platform", platform_subdomain: chosen },
    organization: organizationFromBusiness(business),
    indexing: { eligibility: "blocked", reasons: ["no_custom_domain"] },
    pages: map,
  };
}

export const useSitesStore = defineStore("sites", {
  state: () => ({
    sites: [],
    loading: false,
    loaded: false,
    saving: false,
    error: "",
    message: "",
  }),
  getters: {
    hasSites: (state) => state.sites.length > 0,
  },
  actions: {
    async ensureLoaded() {
      if (!this.loaded && !this.loading) await this.load();
    },
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/sites");
        this.sites = Array.isArray(body.sites) ? body.sites : [];
        this.loaded = true;
      } catch (error) {
        this.error = error.message || "Failed to load sites.";
      } finally {
        this.loading = false;
      }
    },
    async save(site) {
      this.saving = true;
      this.error = "";
      try {
        const body = await apiRequest("/sites", { method: "POST", body: site });
        const saved = body.site || site;
        const index = this.sites.findIndex((s) => s.site_id === saved.site_id);
        if (index >= 0) this.sites.splice(index, 1, saved);
        else this.sites.push(saved);
        this.loaded = true;
        this.message = `${saved.name || "Site"} was saved.`;
        return saved;
      } catch (error) {
        this.error = error.message || "Failed to save site.";
        throw error;
      } finally {
        this.saving = false;
      }
    },
    async createDefault(pages, business, subdomain = "") {
      return this.save(buildDefaultSite(pages, business, subdomain));
    },
    // Live availability check for a desired subdomain. Returns { normalized, available, reason, suggestions, hostname }.
    async checkSubdomain(name, siteId = "") {
      const query = new URLSearchParams({ name: String(name || "") });
      if (siteId) query.set("site_id", siteId);
      return apiRequest(`/sites/subdomain?${query.toString()}`);
    },
    _replace(site) {
      const index = this.sites.findIndex((s) => s.site_id === site.site_id);
      if (index >= 0) this.sites.splice(index, 1, site);
      else this.sites.push(site);
      return site;
    },
    async connectDomain(siteId, domain, homepagePageId = "") {
      const body = { domain };
      if (homepagePageId) body.homepage_page_id = homepagePageId;
      const res = await apiRequest(`/sites/${encodeURIComponent(siteId)}/domain`, { method: "POST", body });
      return this._replace(res.site);
    },
    async checkDomain(siteId) {
      const res = await apiRequest(`/sites/${encodeURIComponent(siteId)}/domain/check`, { method: "POST" });
      return { site: this._replace(res.site), status: res.status, hint: res.hint, diagnostics: res.diagnostics || [] };
    },
    async disconnectDomain(siteId) {
      const res = await apiRequest(`/sites/${encodeURIComponent(siteId)}/domain`, { method: "DELETE" });
      return this._replace(res.site);
    },
    async setHomepage(siteId, pageId, tenantId = "") {
      const res = await apiRequest(`/sites/${encodeURIComponent(siteId)}/homepage`, {
        method: "POST",
        body: { tenant_id: tenantId || getTenantId(), page_id: pageId },
      });
      return this._replace(res.site);
    },
    async attachPage(siteId, { pageId, slug, pageType, category, label } = {}, tenantId = "") {
      const body = { tenant_id: tenantId || getTenantId(), page_id: pageId, slug };
      if (pageType) body.page_type = pageType;
      if (category) body.category = category;
      if (label) body.label = label;
      const res = await apiRequest(`/sites/${encodeURIComponent(siteId)}/pages`, { method: "POST", body });
      return this._replace(res.site);
    },
    async setStatus(site, status) {
      const body = await apiRequest(`/sites/${encodeURIComponent(site.site_id)}/status`, {
        method: "PATCH",
        body: { tenant_id: site.tenant_id || getTenantId(), status },
      });
      const saved = body.site || { ...site, status };
      const index = this.sites.findIndex((s) => s.site_id === saved.site_id);
      if (index >= 0) this.sites.splice(index, 1, saved);
      return saved;
    },
  },
});
