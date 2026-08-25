import { defineStore } from "pinia";
import { apiRequest, getTenantId } from "../api/client";
import { defaultWeeklyHours, normalizeWeeklyHours } from "../utils/weeklyHours";

function localId(prefix = "ful") {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
  const cryptoApi = globalThis.crypto;
  const bytes = cryptoApi?.getRandomValues ? cryptoApi.getRandomValues(new Uint8Array(11)) : null;
  const suffix = Array.from({ length: 11 }, (_, index) => alphabet[(bytes ? bytes[index] : Math.floor(Math.random() * 62)) % alphabet.length]).join("");
  return `${prefix}_${suffix}`;
}

export const COMPENSATION_TYPES = ["flat_fee", "percent", "hourly"];

export function fulfillerDisplayName(fulfiller) {
  return (
    fulfiller?.display_name ||
    [fulfiller?.first_name, fulfiller?.last_name].filter(Boolean).join(" ") ||
    fulfiller?.email ||
    "Fulfiller"
  );
}

export function formatCompensation(fulfiller) {
  const comp = fulfiller?.compensation || {};
  const amount = Number(comp.amount || 0);
  const label =
    comp.type === "percent"
      ? `${amount}%`
      : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(amount);
  const type = String(comp.type || "flat_fee").replace(/_/g, " ");
  const tips = comp.tips_to_fulfiller ? " · Tips" : "";
  return `${type} · ${label}${tips}`;
}

export const useFulfillersStore = defineStore("fulfillers", {
  state: () => ({
    fulfillers: [],
    loading: false,
    loaded: false,
    saving: false,
    error: "",
    message: "",
  }),

  actions: {
    reset() {
      this.fulfillers = [];
      this.loaded = false;
      this.error = "";
      this.message = "";
    },

    async load() {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/services/fulfillers");
        this.fulfillers = Array.isArray(body.fulfillers) ? body.fulfillers : [];
        this.loaded = true;
        this.message = this.fulfillers.length ? "" : "No fulfillers yet. Add staff who deliver appointments.";
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },

    async saveFulfiller(form, base = null) {
      this.saving = true;
      this.error = "";
      try {
        const fulfiller = buildFulfillerDocument(form, base || {});
        const body = await apiRequest("/services/fulfillers", { method: "PUT", body: fulfiller });
        this.upsert(body.fulfiller || fulfiller);
        this.loaded = true;
        return body.fulfiller || fulfiller;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.saving = false;
      }
    },

    async removeFulfiller(fulfillerId) {
      this.error = "";
      try {
        await apiRequest(`/services/fulfillers/${encodeURIComponent(fulfillerId)}`, { method: "DELETE" });
        this.fulfillers = this.fulfillers.filter((f) => f.fulfiller_id !== fulfillerId);
      } catch (error) {
        this.error = error.message;
        throw error;
      }
    },

    upsert(fulfiller) {
      const index = this.fulfillers.findIndex((f) => f.fulfiller_id === fulfiller.fulfiller_id);
      if (index >= 0) this.fulfillers.splice(index, 1, fulfiller);
      else this.fulfillers.unshift(fulfiller);
    },
  },
});

export function buildFulfillerDocument(form, base = {}) {
  const now = Math.floor(Date.now() / 1000);
  const fulfillerId = form.fulfiller_id || base.fulfiller_id || localId("ful");
  const displayName =
    String(form.display_name || "").trim() ||
    [form.first_name, form.last_name].map((s) => String(s || "").trim()).filter(Boolean).join(" ") ||
    String(form.email || "").trim();

  const document = {
    ...base,
    schema_version: base.schema_version || "2026-05-29",
    document_type: "fulfiller",
    tenant_id: getTenantId(),
    fulfiller_id: fulfillerId,
    first_name: String(form.first_name || "").trim(),
    last_name: String(form.last_name || "").trim(),
    email: String(form.email || "").trim(),
    phone: String(form.phone || "").trim(),
    display_name: displayName,
    status: ["active", "inactive", "invited"].includes(form.status) ? form.status : "active",
    compensation: {
      type: COMPENSATION_TYPES.includes(form.compensation_type) ? form.compensation_type : "flat_fee",
      amount: Math.max(0, Number(form.compensation_amount || 0)),
      tips_to_fulfiller: form.tips_to_fulfiller !== false,
    },
    availability: {
      weekly_hours: normalizeWeeklyHours(form.weekly_hours && form.weekly_hours.length ? form.weekly_hours : defaultWeeklyHours()),
    },
    created_at: base.created_at || form.created_at || now,
    updated_at: now,
  };

  // The staff member's own calendar (delegation): bookings assigned to them write there.
  const calendarConnectionId = String(form.calendar_connection_id || "").trim();
  if (calendarConnectionId) document.calendar_connection_id = calendarConnectionId;
  else delete document.calendar_connection_id;

  return document;
}
