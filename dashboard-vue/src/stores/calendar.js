import { defineStore } from "pinia";
import { apiRequest } from "../api/client";

export const useCalendarStore = defineStore("calendar", {
  state: () => ({
    connection: null,
    loading: false,
    connecting: false,
    error: "",
  }),

  getters: {
    connected(state) {
      return Boolean(state.connection?.connected);
    },
  },

  actions: {
    async loadStatus() {
      this.loading = true;
      this.error = "";
      try {
        this.connection = await apiRequest("/calendar/connection");
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },

    // Opens Google's consent screen in a popup; the caller polls loadStatus() to detect success.
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

    async disconnect() {
      this.error = "";
      try {
        await apiRequest("/calendar/connection", { method: "DELETE" });
        this.connection = { connected: false };
      } catch (error) {
        this.error = error.message;
        throw error;
      }
    },
  },
});
