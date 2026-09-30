import { defineStore } from "pinia";
import { apiRequest } from "../api/client";

/**
 * The refund-policy vocabulary and the SERVER-GENERATED sentences.
 *
 * plans/REFUND_POLICY.md. Two screens need this -- Configuration sets the tenant's defaults, Products
 * overrides one product -- and they must agree, so it is fetched once and shared.
 *
 * Nothing here composes a sentence. `previews` arrives from the server with an entry for every
 * class/window/condition combination, because a JavaScript copy of that template is exactly how the literal
 * in `stores/products.js` came to be published: a browser file became the author of a commercial promise.
 */
export const useRefundPolicyStore = defineStore("refundPolicy", {
  state: () => ({
    options: {},
    // The tenant's three defaults as the server resolves them, each carrying a `source` that says whether
    // the tenant chose it or the platform fell back.
    resolved: {},
    loaded: false,
    loading: false,
    error: "",
  }),
  getters: {
    classes: (state) => state.options.classes || ["physical", "digital", "subscription"],
    windows: (state) => state.options.windows || [],
    conditions: (state) => state.options.conditions || [],
    returnMethods: (state) => state.options.return_methods || [],
    classLabels: (state) => state.options.class_labels || {},
    classHints: (state) => state.options.class_hints || {},
    classDefaults: (state) => state.options.class_defaults || {},
  },
  actions: {
    async load({ force = false } = {}) {
      if (this.loading) return;
      if (this.loaded && !force) return;
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/config", { params: { refund_options: "1" } });
        this.options = body.refund_policy_options || {};
        this.resolved = body.refund_policies || {};
        this.loaded = true;
      } catch (err) {
        // A tenant with no saved config gets a 404 from /config, and the vocabulary comes back with it. That
        // is not an error worth showing -- but it does leave the pickers empty, which the screens check for.
        this.error = /not found/i.test(err.message || "") ? "" : (err.message || "Failed to load refund options.");
      } finally {
        this.loading = false;
      }
    },

    /** What a storefront will say, for a class and a set of choices. `prose` wins when the tenant typed it. */
    preview(policyClass, { refund_window: window, condition, full_policy: prose } = {}) {
      const generated = (this.options.previews || {})[`${policyClass}|${window}|${condition}`] || {};
      const wording = String(prose || "").trim();
      return {
        short_label: generated.short_label || "",
        full_policy: wording || generated.full_policy || "",
      };
    },

    /** The tenant's default for a class, or the platform's fallback -- whichever actually applies. */
    effective(policyClass) {
      return this.resolved[policyClass] || {};
    },

    /** Why a policy reads the way it does, in words a tenant can act on. */
    sourceNote(policyClass) {
      const source = this.effective(policyClass).source;
      if (source === "tenant_default") return "Your saved default for this product type.";
      if (source === "product_override") return "Set on this product.";
      return "The platform's default — nobody chose this. Set your own in Configuration → Refund Policy.";
    },
  },
});
