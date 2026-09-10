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
    storeAvatarUrl: "",
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
        // The STORE avatar, so the builder can preview what a page will inherit without copying the URL
        // onto the page. Separate call because it lives on the tenant profile, not this user's.
        try {
          const avatar = await apiRequest("/tenant/avatar");
          this.storeAvatarUrl = avatar.avatar_url || "";
        } catch {
          this.storeAvatarUrl = "";
        }
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
