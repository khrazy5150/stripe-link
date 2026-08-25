import { defineStore } from "pinia";
import { apiRequest } from "../api/client";

// Per-tenant BNPL / installment payment-method toggles (plans/BNPL_PAYMENT_METHODS.md). Reads/writes the
// /payment-methods endpoint, which requests the Stripe capability on the connected account and returns live
// status. `mode` is the Stripe mode (test/live), driven by the Payments screen's verifyMode.
export const usePaymentMethodsStore = defineStore("paymentMethods", {
  state: () => ({
    methods: [],           // [{ method, label, enabled, capability_status, country_eligible, countries }]
    connected: false,
    accountCountry: "",
    mode: "test",
    loading: false,
    savingMethod: "",      // the method key currently being toggled (for per-row spinner/disable)
    error: "",
  }),
  actions: {
    async load(mode = "test") {
      this.mode = mode === "live" ? "live" : "test";
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/payment-methods", { params: { mode: this.mode } });
        this.methods = Array.isArray(body.methods) ? body.methods : [];
        this.connected = !!body.connected;
        this.accountCountry = body.account_country || "";
      } catch (error) {
        this.error = error.message || "Failed to load payment methods.";
      } finally {
        this.loading = false;
      }
    },
    async toggle(method, enabled) {
      this.savingMethod = method;
      this.error = "";
      try {
        // return_url lets the backend mint a Stripe Account Link back to this screen if the capability still
        // needs the tenant to finish some requirement (so they never navigate their raw dashboard).
        const body = await apiRequest("/payment-methods", {
          method: "PUT",
          body: { mode: this.mode, method, enabled, return_url: window.location.href },
        });
        const index = this.methods.findIndex((m) => m.method === method);
        if (index >= 0) {
          this.methods.splice(index, 1, {
            ...this.methods[index],
            enabled: body.enabled,
            capability_status: body.capability_status,
            requirements_due: body.requirements_due || [],
            onboarding_url: body.onboarding_url || "",
          });
        }
      } catch (error) {
        this.error = error.message || "Failed to update the payment method.";
      } finally {
        this.savingMethod = "";
      }
    },
    reset() {
      this.methods = [];
      this.connected = false;
      this.accountCountry = "";
      this.error = "";
    },
  },
});
