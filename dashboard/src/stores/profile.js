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
    // The owner's own name, as the user pill shows it -- distinct from the BUSINESS name above. A link page
    // is often about a person rather than a company, which is the whole reason the brand mark can be hidden.
    displayName: "",
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
      // TWO independent reads, deliberately not nested. The store avatar lives on the TENANT profile and the
      // business identity on THIS USER's, so a user with no profile row yet -- or any failure of /profile at
      // all -- used to take the avatar down with it, silently: the avatar fetch sat inside the /profile try,
      // so one catch disabled a feature that had nothing to do with it. The symptom was a page that rendered
      // its inherited avatar perfectly while the builder behaved as though there were none.
      const [profile, avatar] = await Promise.allSettled([
        apiRequest("/profile", { params: { user_id: userId } }),
        apiRequest("/tenant/avatar"),
      ]);
      if (profile.status === "fulfilled") {
        const doc = profile.value.profile || {};
        this.displayName = String(doc.display_name
          || [doc.first_name, doc.last_name].filter(Boolean).join(" ")
          || "").trim();
        const business = doc.business || {};
        this.business = {
          name: business.name || "",
          phone: business.phone || "",
          brands: Array.isArray(business.brands) ? [...business.brands] : [],
          address: business.address || {},
        };
      }
      // No profile yet (or the load failed) — brand simply falls back to the product name. Non-fatal.
      this.storeAvatarUrl = avatar.status === "fulfilled" ? (avatar.value.avatar_url || "") : "";
      this.loaded = true;
      this.loading = false;
    },
  },
});
