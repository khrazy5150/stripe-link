import { defineStore } from "pinia";
import { apiRequest, getTenantId } from "../api/client";

function localId(prefix = "exc") {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
  const cryptoApi = globalThis.crypto;
  const bytes = cryptoApi?.getRandomValues ? cryptoApi.getRandomValues(new Uint8Array(11)) : null;
  const suffix = Array.from({ length: 11 }, (_, index) => alphabet[(bytes ? bytes[index] : Math.floor(Math.random() * 62)) % alphabet.length]).join("");
  return `${prefix}_${suffix}`;
}

export const useAvailabilityExceptionsStore = defineStore("availabilityExceptions", {
  state: () => ({
    exceptions: [],
    loading: false,
    loaded: false,
    saving: false,
    error: "",
  }),

  actions: {
    reset() {
      this.exceptions = [];
      this.loaded = false;
      this.error = "";
    },

    async load() {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/services/availability/exceptions");
        this.exceptions = Array.isArray(body.availability_exceptions) ? body.availability_exceptions : [];
        this.loaded = true;
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },

    async saveException(form) {
      this.saving = true;
      this.error = "";
      try {
        const exception = buildExceptionDocument(form);
        const body = await apiRequest("/services/availability/exceptions", { method: "POST", body: exception });
        const saved = body.availability_exception || exception;
        const index = this.exceptions.findIndex((e) => e.exception_id === saved.exception_id);
        if (index >= 0) this.exceptions.splice(index, 1, saved);
        else this.exceptions.unshift(saved);
        this.loaded = true;
        return saved;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.saving = false;
      }
    },

    async removeException(exceptionId) {
      this.error = "";
      try {
        await apiRequest(`/services/availability/exceptions/${encodeURIComponent(exceptionId)}`, { method: "DELETE" });
        this.exceptions = this.exceptions.filter((e) => e.exception_id !== exceptionId);
      } catch (error) {
        this.error = error.message;
        throw error;
      }
    },
  },
});

export function buildExceptionDocument(form) {
  const now = Math.floor(Date.now() / 1000);
  const scope = form.fulfiller_scope === "specific" ? "specific" : "all";
  const document = {
    schema_version: "2026-05-29",
    document_type: "availability_exception",
    tenant_id: getTenantId(),
    exception_id: form.exception_id || localId("exc"),
    starts_at: String(form.starts_at || "").trim(),
    ends_at: String(form.ends_at || "").trim(),
    type: form.type === "open" ? "open" : "block",
    reason: String(form.reason || "").trim(),
    fulfiller_scope: scope,
    created_at: form.created_at || now,
    updated_at: now,
  };
  if (scope === "specific" && form.fulfiller_id) document.fulfiller_id = String(form.fulfiller_id);
  return document;
}
