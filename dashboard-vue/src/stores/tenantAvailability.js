import { defineStore } from "pinia";
import { apiRequest, getTenantId } from "../api/client";
import { defaultWeeklyHours, normalizeWeeklyHours } from "../utils/weeklyHours";

export const useTenantAvailabilityStore = defineStore("tenantAvailability", {
  state: () => ({
    availability: null,
    loading: false,
    loaded: false,
    saving: false,
    error: "",
    message: "",
  }),

  actions: {
    reset() {
      this.availability = null;
      this.loaded = false;
      this.error = "";
      this.message = "";
    },

    async load() {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/services/availability/defaults");
        this.availability = body.availability || null;
        this.loaded = true;
      } catch (error) {
        // A 404 just means the tenant hasn't set defaults yet — start from defaults.
        if (String(error.message || "").toLowerCase().includes("not found")) {
          this.availability = null;
          this.loaded = true;
        } else {
          this.error = error.message;
        }
      } finally {
        this.loading = false;
      }
    },

    async saveDefaults(form) {
      this.saving = true;
      this.error = "";
      try {
        const document = buildTenantAvailabilityDocument(form);
        const body = await apiRequest("/services/availability/defaults", { method: "PUT", body: document });
        this.availability = body.availability || document;
        this.loaded = true;
        this.message = "Availability defaults saved.";
        return this.availability;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.saving = false;
      }
    },
  },
});

export function buildTenantAvailabilityDocument(form) {
  const now = Math.floor(Date.now() / 1000);
  return {
    schema_version: "2026-05-29",
    document_type: "tenant_availability",
    tenant_id: getTenantId(),
    availability_id: "default",
    timezone: String(form.timezone || "America/Denver").trim(),
    slot_interval_minutes: Math.max(1, Math.round(Number(form.slot_interval_minutes || 30))),
    lead_time_minutes: Math.max(0, Math.round(Number(form.lead_time_minutes || 60))),
    buffer_before_minutes: Math.max(0, Math.round(Number(form.buffer_before_minutes || 0))),
    buffer_after_minutes: Math.max(0, Math.round(Number(form.buffer_after_minutes || 0))),
    weekly_hours: normalizeWeeklyHours(form.weekly_hours && form.weekly_hours.length ? form.weekly_hours : defaultWeeklyHours()),
    updated_at: now,
  };
}
