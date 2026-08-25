import { defineStore } from "pinia";
import { apiRequest, getTenantId } from "../api/client";
import { buildPriceDocument } from "./pricing";
import { defaultPriceForm } from "../utils/priceForm";
import { imageDimsForUrls } from "../utils/imageDims";

const SERVICE_BOOKING_FLOWS = ["book_then_pay", "pay_then_book"];

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

    // Live count, so the banner tracks the filter as you type — no Apply button needed.
    statusMessage() {
      if (!this.loaded) return this.message;
      return `${this.filteredServices.length} of ${this.services.length} service${this.services.length === 1 ? "" : "s"} shown.`;
    },
  },

  actions: {
    // Load on first filter interaction so search works without clicking Load Services first (mirrors Products).
    ensureLoaded() {
      if (!this.loaded && !this.loading) this.load();
    },

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
        const service = await buildServiceDocument(form, base || {});
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

    // Archive (soft) / restore: flip the active flag. References (offers, appointments) are
    // preserved, unlike a hard delete — so this is the safe, reversible default.
    async setActive(service, active) {
      this.saving = true;
      this.error = "";
      try {
        const updated = { ...service, active, updated_at: Math.floor(Date.now() / 1000) };
        const body = await apiRequest("/services", { method: "PUT", body: updated });
        this.upsertService(body.service || updated);
        this.message = `${service.name || "Service"} was ${active ? "restored" : "archived"}.`;
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
      } finally {
        this.saving = false;
      }
    },

    // Permanent delete (hard). Only reached for an already-archived service that no live offer
    // references (the caller checks offersReferencing first).
    async deleteService(service) {
      this.saving = true;
      this.error = "";
      try {
        await apiRequest(`/services/${encodeURIComponent(service.service_id)}`, { method: "DELETE" });
        this.services = this.services.filter((item) => item.service_id !== service.service_id);
        this.message = `${service.name || "Service"} was deleted.`;
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
      } finally {
        this.saving = false;
      }
    },

    // Names of offers whose items reference this service — used to block a delete that would break
    // a live landing page. Best-effort: on a fetch failure we return none rather than hard-block.
    async offersReferencing(serviceId) {
      try {
        const body = await apiRequest("/offers");
        const offers = Array.isArray(body.offers) ? body.offers : [];
        return offers
          .filter((offer) => (offer.items || []).some((item) => item.service_id === serviceId))
          .map((offer) => offer.name || offer.offer_id);
      } catch {
        return [];
      }
    },
  },
});

// Fallback price-form built from the legacy single-price inputs (form.price_amount/currency),
// for callers that haven't migrated to a prices[] editor yet.
function legacyServicePriceForm(form) {
  return { ...defaultPriceForm(), sales_price: Number(form.price_amount || 0), currency: String(form.currency || "usd").toLowerCase() };
}

export async function buildServiceDocument(form, base = {}) {
  const now = Math.floor(Date.now() / 1000);
  const serviceId = form.service_id || base.service_id || localId("svc");

  // Services own a canonical prices[] on the shared Price primitive, exactly like products.
  const priceForms = Array.isArray(form.prices) && form.prices.length ? form.prices : [legacyServicePriceForm(form)];
  const prices = await Promise.all(priceForms.map((priceForm) => buildPriceDocument(priceForm, "service", now)));
  const defaultIndex = Math.min(Math.max(Number(form.default_price_index || 0), 0), prices.length - 1);
  const defaultPrice = prices[defaultIndex] || prices[0];

  const document = {
    // Preserve fields the catalog form doesn't render (metadata, ...). The API replaces the whole
    // document, so without this spread an edit would wipe them.
    ...base,
    schema_version: base.schema_version || "2026-05-29",
    document_type: "service",
    tenant_id: getTenantId(),
    service_id: serviceId,
    name: String(form.name || "").trim(),
    description: String(form.description || "").trim(),
    fulfillment_mode: form.fulfillment_mode === "no_booking" ? "no_booking" : "scheduled",
    duration_minutes: Math.max(1, Math.round(Number(form.duration_minutes || 0))),
    prices,
    default_price_id: defaultPrice.price_id,
    // Legacy mirror of the default price (the backend keeps this in sync too).
    price: { currency: defaultPrice.currency, unit_amount: defaultPrice.unit_amount },
    booking_flow: SERVICE_BOOKING_FLOWS.includes(form.booking_flow) ? form.booking_flow : "pay_then_book",
    location_mode: LOCATION_MODES.includes(form.location_mode) ? form.location_mode : "onsite",
    active: form.active !== false,
    booking_rules: buildBookingRules(form),
    allowed_fulfillers: buildAllowedFulfillers(form.allowed_fulfillers),
    created_at: base.created_at || form.created_at || now,
    updated_at: now,
  };
  delete document.linked_product;  // retired workaround
  // no_booking services have no slot, so they carry no duration (backend validates this).
  if (form.fulfillment_mode === "no_booking") delete document.duration_minutes;

  const defaultFulfillerId = String(form.default_fulfiller_id || "").trim();
  if (defaultFulfillerId) document.default_fulfiller_id = defaultFulfillerId;
  else delete document.default_fulfiller_id;

  const calendarConnectionId = String(form.calendar_connection_id || "").trim();
  if (calendarConnectionId) document.calendar_connection_id = calendarConnectionId;
  else delete document.calendar_connection_id;

  const heroImage = String(form.hero_image_url || "").trim();
  if (heroImage) {
    document.presentation = { ...(base.presentation || {}), hero_image_url: heroImage };
  } else if (document.presentation) {
    const { hero_image_url, ...rest } = document.presentation;
    if (Object.keys(rest).length) document.presentation = rest;
    else delete document.presentation;
  }

  // Intrinsic dimensions of the hero image (base-keyed) so the renderer reserves layout space.
  const imageDims = imageDimsForUrls(form.image_dims, heroImage ? [heroImage] : []);
  if (Object.keys(imageDims).length) document.image_dims = imageDims;
  else delete document.image_dims;

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
