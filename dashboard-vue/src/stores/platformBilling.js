import { defineStore } from "pinia";
import { apiRequest, getTenantId } from "../api/client";

// The platform->tenant SaaS subscription (plans/SAAS_BILLING_PAYWALL.md): the tenant's own plan + trial status +
// which product features their plan entitles. Drives the Billing screen, the trial banner, and the disable-menu
// gating. Distinct from Stripe CONNECT (how the tenant gets paid by THEIR buyers).
export const usePlatformBillingStore = defineStore("platformBilling", {
  state: () => ({
    loaded: false,
    loading: false,
    error: "",
    plans: [],           // [{ plan_key, label, monthly_amount, trial_days, features, ... }]
    capabilities: [],    // [{ key, label, view }] — the full gateable-feature catalog
    current: {
      billing_status: "trial",
      billing_plan_key: "",
      billing_exempt: false,
      has_subscription: false,
      current_period_end: null,
      trial_ends_at: null,
      entitlements: [],
    },
    working: false,      // subscribe/portal request in flight
  }),

  getters: {
    // The capabilities the tenant currently has (server-computed: exempt=all, live trial=all, else plan's list).
    entitlementSet: (state) => new Set(state.current.entitlements || []),

    // view key -> capability key (only for gated views with a dedicated screen; capabilities with no `view` — e.g.
    // bnpl, custom_domains — are sub-features of shared screens and never lock a menu item).
    viewCapability: (state) => {
      const map = {};
      for (const cap of state.capabilities) if (cap.view) map[cap.view] = cap.key;
      return map;
    },

    // Seconds remaining in the platform trial (null if not on a trial clock / already subscribed / exempt).
    trialSecondsLeft: (state) => {
      const ends = state.current.trial_ends_at;
      if (!ends || state.current.has_subscription || state.current.billing_exempt) return null;
      if (state.current.billing_status !== "trial" && state.current.billing_status !== "trial_expired") return null;
      return ends - Math.floor(Date.now() / 1000);
    },

    onTrial() {
      return this.trialSecondsLeft !== null && this.trialSecondsLeft > 0;
    },
    trialDaysLeft() {
      const s = this.trialSecondsLeft;
      return s === null ? null : Math.max(0, Math.ceil(s / 86400));
    },
    trialExpired(state) {
      if (state.current.billing_exempt || state.current.has_subscription) return false;
      const s = this.trialSecondsLeft;
      return s !== null && s <= 0;
    },
    // The hard wall: an expired trial with no subscription, or a suspended/canceled account.
    walled(state) {
      if (state.current.billing_exempt) return false;
      if (this.trialExpired) return true;
      return ["suspended", "canceled", "trial_expired"].includes(state.current.billing_status);
    },
  },

  actions: {
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/platform-billing/plans", { params: { tenant_id: getTenantId() } });
        const pb = body.platform_billing || {};
        this.plans = Array.isArray(pb.plans) ? pb.plans : [];
        this.capabilities = Array.isArray(pb.capabilities) ? pb.capabilities : [];
        if (pb.current) this.current = { ...this.current, ...pb.current };
        this.loaded = true;
      } catch (error) {
        this.error = error.message || "Failed to load billing.";
      } finally {
        this.loading = false;
      }
    },

    // A view is allowed if it isn't a gated capability, or the tenant's entitlements include that capability.
    isViewAllowed(view) {
      const cap = this.viewCapability[view];
      if (!cap) return true;
      return this.entitlementSet.has(cap);
    },

    async subscribe({ planKey = "", promoCode = "" } = {}) {
      this.working = true;
      this.error = "";
      try {
        const origin = window.location.origin;
        const body = await apiRequest("/platform-billing/subscribe", {
          method: "POST",
          body: {
            tenant_id: getTenantId(),
            plan_key: planKey || undefined,
            promo_code: promoCode || undefined,
            success_url: `${origin}/?billing=success`,
            cancel_url: `${origin}/?billing=cancel`,
          },
        });
        const pb = body.platform_billing || {};
        if (pb.checkout_url) {
          window.location.assign(pb.checkout_url);
          return;
        }
        if (pb.exempt) await this.load();  // comped tenant: nothing to pay
      } catch (error) {
        this.error = error.message || "Could not start checkout.";
      } finally {
        this.working = false;
      }
    },

    async openPortal() {
      this.working = true;
      this.error = "";
      try {
        const body = await apiRequest("/platform-billing/portal", {
          method: "POST",
          body: { tenant_id: getTenantId(), return_url: `${window.location.origin}/?billing=managed` },
        });
        const url = body.platform_billing?.portal_url;
        if (url) window.location.assign(url);
      } catch (error) {
        this.error = error.message || "Could not open the billing portal.";
      } finally {
        this.working = false;
      }
    },
  },
});
