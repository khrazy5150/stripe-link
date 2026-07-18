import { defineStore } from "pinia";
import { apiRequest, getAuthSession } from "../api/client";

// Tenant business identity (name, brands, NAP), read from the current user's profile. Cached once so the
// Offers modal (brand picker) and the landing-page builder (brand default) can resolve brand without each
// re-fetching. A lightweight precursor to the canonical Business Profile (plans/BUSINESS_PROFILE_AND_GBP.md).
export const useProfileStore = defineStore("profile", {
  state: () => ({
    business: { name: "", phone: "", brands: [], address: {} },
    loading: false,
    loaded: false,
  }),
  getters: {
    businessName: (state) => state.business.name || "",
    brands: (state) => state.business.brands || [],
  },
  actions: {
    async ensureLoaded() {
      if (this.loaded || this.loading) return;
      await this.load();
    },
    async load() {
      const userId = (getAuthSession() || {}).user_id || "";
      if (!userId) {
        this.loaded = true;
        return;
      }
      this.loading = true;
      try {
        const body = await apiRequest("/profile", { params: { user_id: userId } });
        const business = (body.profile || {}).business || {};
        this.business = {
          name: business.name || "",
          phone: business.phone || "",
          brands: Array.isArray(business.brands) ? [...business.brands] : [],
          address: business.address || {},
        };
        this.loaded = true;
      } catch {
        // No profile yet (or load failed) — brand simply falls back to the product name. Non-fatal.
        this.loaded = true;
      } finally {
        this.loading = false;
      }
    },
  },
});
