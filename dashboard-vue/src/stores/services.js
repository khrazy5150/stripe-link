import { defineStore } from "pinia";
import { apiRequest, getTenantId } from "../api/client";

function localId(prefix = "svc") {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
  const cryptoApi = globalThis.crypto;
  const bytes = cryptoApi?.getRandomValues ? cryptoApi.getRandomValues(new Uint8Array(11)) : null;
  const suffix = Array.from({ length: 11 }, (_, index) => alphabet[(bytes ? bytes[index] : Math.floor(Math.random() * 62)) % alphabet.length]).join("");
  return `${prefix}_${suffix}`;
}

function cents(value) {
  return Math.max(0, Math.round(Number(value || 0) * 100));
}

export function formatServicePrice(service) {
  const price = service?.price || {};
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: String(price.currency || "usd").toUpperCase(),
  }).format(Number(price.unit_amount || 0) / 100);
}

export function formatServiceDuration(service) {
  const minutes = Math.max(0, Number(service?.duration_minutes || 0));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours} hr ${remainder} min` : `${hours} hr`;
}

export const LOCATION_MODES = ["onsite", "mobile", "virtual", "hybrid"];

export function serviceIsActive(service) {
  return service?.active !== false;
}

export const useServicesStore = defineStore("services", {
  state: () => ({
    services: [],
    loading: false,
    loaded: false,
    saving: false,
    error: "",
    message: "",
    filters: {
      search: "",
      status: "all",
    },
  }),

  getters: {
    filteredServices(state) {
      const search = state.filters.search.trim().toLowerCase();
      return state.services.filter((service) => {
        if (state.filters.status === "active" && !serviceIsActive(service)) return false;
        if (state.filters.status === "inactive" && serviceIsActive(service)) return false;
        if (!search) return true;
        return [
          service.service_id,
          service.name,
          service.description,
          service.location_mode,
        ].filter(Boolean).join(" ").toLowerCase().includes(search);
      });
    },
  },

  actions: {
    reset() {
      this.services = [];
      this.loading = false;
      this.loaded = false;
      this.saving = false;
      this.error = "";
      this.message = "";
      this.filters.search = "";
      this.filters.status = "all";
    },

    applyFilters() {
      if (!this.loaded) {
        this.message = "";
        return;
      }
      this.message = `${this.filteredServices.length} of ${this.services.length} service${this.services.length === 1 ? "" : "s"} shown.`;
    },

    async load() {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/services");
        this.services = Array.isArray(body.services) ? body.services : [];
        this.loaded = true;
        this.message = this.services.length
          ? `${this.filteredServices.length} of ${this.services.length} service${this.services.length === 1 ? "" : "s"} shown.`
          : "No services found. Create a service to get started.";
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
      } finally {
        this.loading = false;
      }
    },

    async saveService(form, base = null) {
      this.saving = true;
      this.error = "";
      try {
        const service = buildServiceDocument(form, base || {});
        // The services API upserts create and edit through a single collection-level
        // PUT /services; the document carries service_id (generated client-side for new).
        const body = await apiRequest("/services", { method: "PUT", body: service });
        this.upsertService(body.service || service);
        this.loaded = true;
        this.message = `${service.name} was saved.`;
        return body.service || service;
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
        throw error;
      } finally {
        this.saving = false;
      }
    },

    upsertService(service) {
      const index = this.services.findIndex((item) => item.service_id === service.service_id);
      if (index >= 0) this.services.splice(index, 1, service);
      else this.services.unshift(service);
    },
  },
});

export function buildServiceDocument(form, base = {}) {
  const now = Math.floor(Date.now() / 1000);
  const serviceId = form.service_id || base.service_id || localId("svc");

  const document = {
    // Preserve fields the catalog form doesn't render (booking_rules, fulfillers,
    // linked_product, metadata, ...). The API replaces the whole document, so without
    // this spread an edit would wipe them — matching legacy _update_service's merge.
    ...base,
    schema_version: base.schema_version || "2026-05-29",
    document_type: "service",
    tenant_id: getTenantId(),
    service_id: serviceId,
    name: String(form.name || "").trim(),
    description: String(form.description || "").trim(),
    duration_minutes: Math.max(1, Math.round(Number(form.duration_minutes || 0))),
    price: {
      currency: String(form.currency || "usd").toLowerCase(),
      unit_amount: cents(form.price_amount),
    },
    location_mode: LOCATION_MODES.includes(form.location_mode) ? form.location_mode : "onsite",
    active: form.active !== false,
    booking_rules: buildBookingRules(form),
    allowed_fulfillers: buildAllowedFulfillers(form.allowed_fulfillers),
    created_at: base.created_at || form.created_at || now,
    updated_at: now,
  };

  const defaultFulfillerId = String(form.default_fulfiller_id || "").trim();
  if (defaultFulfillerId) document.default_fulfiller_id = defaultFulfillerId;
  else delete document.default_fulfiller_id;

  const calendarConnectionId = String(form.calendar_connection_id || "").trim();
  if (calendarConnectionId) document.calendar_connection_id = calendarConnectionId;
  else delete document.calendar_connection_id;

  const productId = String(form.linked_product_id || "").trim();
  if (productId) {
    document.linked_product = { product_id: productId };
    const priceId = String(form.linked_price_id || "").trim();
    if (priceId) document.linked_product.price_id = priceId;
  } else {
    delete document.linked_product;
  }

  const heroImage = String(form.hero_image_url || "").trim();
  if (heroImage) {
    document.presentation = { ...(base.presentation || {}), hero_image_url: heroImage };
  } else if (document.presentation) {
    const { hero_image_url, ...rest } = document.presentation;
    if (Object.keys(rest).length) document.presentation = rest;
    else delete document.presentation;
  }

  return document;
}

export function defaultBookingRules() {
  return {
    check_in_required: false,
    check_in_window_start_minutes: 15,
    check_in_window_end_minutes: 5,
    check_in_label: "Ready on Site",
    completion_required: true,
    completion_label: "Done",
  };
}

function buildBookingRules(form) {
  const defaults = defaultBookingRules();
  const rules = form.booking_rules || {};
  return {
    check_in_required: Boolean(rules.check_in_required),
    check_in_window_start_minutes: Math.max(0, Math.round(Number(rules.check_in_window_start_minutes ?? defaults.check_in_window_start_minutes))),
    check_in_window_end_minutes: Math.max(0, Math.round(Number(rules.check_in_window_end_minutes ?? defaults.check_in_window_end_minutes))),
    check_in_label: String(rules.check_in_label || defaults.check_in_label).trim(),
    completion_required: rules.completion_required !== false,
    completion_label: String(rules.completion_label || defaults.completion_label).trim(),
  };
}

function buildAllowedFulfillers(entries) {
  // Form entries share the document shape (fulfiller_id, enabled, tips_to_fulfiller,
  // compensation_override:{type, amount?}); normalize/validate them here.
  return (Array.isArray(entries) ? entries : [])
    .filter((entry) => entry && entry.fulfiller_id)
    .map((entry) => {
      const row = {
        fulfiller_id: String(entry.fulfiller_id),
        enabled: entry.enabled !== false,
        tips_to_fulfiller: entry.tips_to_fulfiller !== false,
      };
      const type = entry.compensation_override?.type;
      if (type === "flat_fee" || type === "percent") {
        row.compensation_override = { type, amount: Math.max(0, Number(entry.compensation_override?.amount || 0)) };
      } else if (type === "use_fulfiller_default") {
        row.compensation_override = { type: "use_fulfiller_default" };
      }
      return row;
    });
}
