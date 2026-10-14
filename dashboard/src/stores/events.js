import { defineStore } from "pinia";
import { apiRequest, getTenantId } from "../api/client";

// Scheduled events — a webinar and the occurrences it runs at (plans/WEBINAR.md P1). An event is the thing;
// an occurrence is one running of it. Registrations are LEADS pointing at an occurrence, so they live in the
// leads store, not here.
//
// NOT per-environment, unlike collections: an event carries no Stripe state, and a tenant flipping between
// test and live should not find their sessions have vanished.
export const useEventsStore = defineStore("events", {
  state: () => ({ events: [], loaded: false, loading: false, error: "" }),
  getters: {
    byId: (state) => (eventId) => state.events.find((e) => e.event_id === eventId) || null,
  },
  actions: {
    async ensureLoaded() {
      if (!this.loaded && !this.loading) await this.load();
    },
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/events");
        this.events = Array.isArray(body.events) ? body.events : [];
        this.loaded = true;
      } catch (error) {
        this.error = error.message || "Failed to load events.";
      } finally {
        this.loading = false;
      }
    },
    async save(document) {
      // Stamped HERE rather than in the editor, so every caller gets it and only one place can forget.
      // `validate_event` requires it, and without it the save failed with "tenant_id must be a non-empty
      // string" -- a message about a field no tenant ever sees (reported 2026-10-14).
      const body = await apiRequest("/events", {
        method: "POST", body: { ...document, tenant_id: document.tenant_id || getTenantId() },
      });
      const saved = body.event || document;
      const index = this.events.findIndex((e) => e.event_id === saved.event_id);
      if (index >= 0) this.events.splice(index, 1, saved);
      else this.events.push(saved);
      return saved;
    },
    async remove(eventId) {
      await apiRequest(`/events/${encodeURIComponent(eventId)}`, { method: "DELETE" });
      this.events = this.events.filter((e) => e.event_id !== eventId);
    },
    reset() {
      this.events = [];
      this.loaded = false;
      this.error = "";
    },
  },
});
