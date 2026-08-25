import { defineStore } from "pinia";
import { apiRequest } from "../api/client";

export const useNotificationsStore = defineStore("notifications", {
  state: () => ({
    items: [],
    unreadCount: 0,
    loaded: false,
    loading: false,
    error: "",
  }),
  getters: {
    // Bell badge label, capped at 99+.
    badgeLabel(state) {
      if (state.unreadCount <= 0) return "";
      return state.unreadCount > 99 ? "99+" : String(state.unreadCount);
    },
  },
  actions: {
    reset() {
      this.items = [];
      this.unreadCount = 0;
      this.loaded = false;
      this.error = "";
    },
    // `silent` keeps the loading flag/error untouched so background polling doesn't flicker the page.
    async load({ silent = false } = {}) {
      if (!silent) {
        this.loading = true;
        this.error = "";
      }
      try {
        const body = await apiRequest("/notifications");
        this.items = Array.isArray(body.notifications) ? body.notifications : [];
        this.unreadCount = this.items.filter((item) => item.status === "unread").length;
        this.loaded = true;
      } catch (err) {
        if (!silent) this.error = err.message || "Failed to load notifications.";
      } finally {
        if (!silent) this.loading = false;
      }
    },
    async markAllRead() {
      if (!this.items.some((item) => item.status === "unread")) {
        this.unreadCount = 0;
        return;
      }
      try {
        await apiRequest("/notifications/mark-read", { method: "POST" });
        this.items = this.items.map((item) => (item.status === "unread" ? { ...item, status: "read" } : item));
        this.unreadCount = 0;
      } catch (err) {
        this.error = err.message || "Failed to mark notifications read.";
      }
    },
  },
});
