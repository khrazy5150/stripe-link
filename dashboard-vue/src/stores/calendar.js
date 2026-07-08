import { defineStore } from "pinia";
import { apiRequest } from "../api/client";

export const useCalendarStore = defineStore("calendar", {
  state: () => ({
    connections: [],
    loaded: false,
    loading: false,
    connecting: false,
    error: "",
  }),

  getters: {
    // A tenant may connect many calendars; "connected" means at least one is live.
    connected(state) {
      return state.connections.some((c) => c.connected);
    },
    defaultConnection(state) {
      return state.connections.find((c) => c.is_default) || null;
    },
  },

  actions: {
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/calendar/connections");
        this.connections = Array.isArray(body.connections) ? body.connections : [];
        this.loaded = true;
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },

    // Opens Google's consent screen in a popup; the caller polls load() to detect the new connection.
    async connect() {
      this.connecting = true;
      this.error = "";
      try {
        const body = await apiRequest("/calendar/connect", { method: "POST", body: {} });
        if (!body.authorize_url) throw new Error("No authorization URL was returned.");
        window.open(body.authorize_url, "gcal_connect", "width=520,height=680");
        return true;
      } catch (error) {
        this.error = error.message;
        return false;
      } finally {
        this.connecting = false;
      }
    },

    async setDefault(connectionId) {
      await this._patch(connectionId, { is_default: true });
    },

    async rename(connectionId, displayName) {
      await this._patch(connectionId, { display_name: displayName });
    },

    async _patch(connectionId, body) {
      this.error = "";
      try {
        await apiRequest(`/calendar/connections/${encodeURIComponent(connectionId)}`, { method: "PATCH", body });
        await this.load();
      } catch (error) {
        this.error = error.message;
        throw error;
      }
    },

    async disconnect(connectionId) {
      this.error = "";
      try {
        await apiRequest(`/calendar/connections/${encodeURIComponent(connectionId)}`, { method: "DELETE" });
        await this.load();
      } catch (error) {
        this.error = error.message;
        throw error;
      }
    },
  },
});
