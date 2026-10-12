import { defineStore } from "pinia";
import { apiRequest } from "../api/client";

// Per-tenant BNPL / installment payment-method toggles (plans/BNPL_PAYMENT_METHODS.md). Reads/writes the
// /payment-methods endpoint, which requests the Stripe capability on the connected account and returns live
// status. `mode` is the Stripe mode (test/live), driven by the Payments screen's verifyMode.
export const usePaymentMethodsStore = defineStore("paymentMethods", {
  state: () => ({
    methods: [],           // [{ method, label, enabled, capability_status, country_eligible, countries }]
    // Sales tax (plans/TAX_STATUS_AND_THRESHOLDS.md). The server sends the whole rendered block --
    // { state, label, headline, detail, may_enable, calculating, enabled, missing_fields } -- because the
    // wording about a tenant's tax carries legal risk and belongs somewhere this repo can test it, not
    // composed from flags in a template.
    tax: null,
    savingTax: false,
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
        this.tax = body.tax || null;
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
    async setTax(enabled) {
      this.savingTax = true;
      this.error = "";
      try {
        const body = await apiRequest("/payment-methods", {
          method: "PUT",
          body: { mode: this.mode, tax_enabled: !!enabled },
        });
        this.tax = body.tax || this.tax;
      } catch (error) {
        // A REFUSAL STILL CARRIES THE FRESH STATUS. The server re-reads Stripe before honouring the
        // switch, so a rejection usually means the account changed since this screen loaded -- adopting
        // the status it returns is what stops the control sitting there offering something the server
        // has just declined.
        // `extra` from error_response merges into the body top level, which the client keeps as
        // `error.payload` -- not an `extra` property.
        if (error.payload && error.payload.tax) this.tax = error.payload.tax;
        this.error = error.message || "Failed to update sales tax.";
      } finally {
        this.savingTax = false;
      }
    },
    reset() {
      this.methods = [];
      this.tax = null;
      this.connected = false;
      this.accountCountry = "";
      this.error = "";
    },
  },
});
