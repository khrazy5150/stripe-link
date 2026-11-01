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
    unset: [],
    guaranteeOptions: {},
    guarantees: [],
    loaded: false,
    loading: false,
    error: "",
  }),
  getters: {
    classes: (state) => state.options.classes || ["physical", "digital", "subscription"],
    windows: (state) => state.options.windows || [],
    conditions: (state) => state.options.conditions || [],
    returnMethods: (state) => state.options.return_methods || [],
    returnShipping: (state) => state.options.return_shipping || [],
    originalShipping: (state) => state.options.original_shipping || [],
    resolutions: (state) => state.options.resolutions || [],
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
        this.unset = body.refund_policies_unset || [];
        this.guaranteeOptions = body.buyer_guarantee_options || this.guaranteeOptions;
        this.guarantees = body.buyer_guarantees || [];
        this.loaded = true;
      } catch (err) {
        // A tenant who has saved no config document gets a 404 -- and the vocabulary and the platform's
        // default terms ride along on it, because neither depends on that document existing. The config table
        // starts empty, so this is the NORMAL path for a tenant opening the screen for the first time, and
        // treating it as a failure left every picker blank.
        const payload = err.payload || {};
        if (payload.refund_policy_options || payload.refund_policies) {
          this.options = payload.refund_policy_options || {};
          this.resolved = payload.refund_policies || {};
          this.unset = payload.refund_policies_unset || [];
          this.guaranteeOptions = payload.buyer_guarantee_options || this.guaranteeOptions;
          this.guarantees = payload.buyer_guarantees || [];
          this.loaded = true;
          this.error = "";
        } else {
          this.error = err.message || "Failed to load refund options.";
        }
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

    /**
     * The extra clauses a policy will publish, at the numbers currently in the boxes.
     *
     * ONE COPY, shared by both screens -- the Configuration card and the product override ask the same
     * question and must not answer it differently. Every word comes from the server's templates; the only
     * thing filled in here is `{n}`, the digit the tenant just typed. That is formatting the server's
     * sentence, not composing one, and the published clause is regenerated server-side at publish
     * regardless, so the two cannot drift into disagreeing.
     *
     * The gates mirror `domain/refund_policy.refund_terms` and exist for the same reasons: no refund means
     * nothing to deduct from, nothing is restocked when nothing comes back, and nothing shipped to a
     * subscriber. A preview that showed a clause the page will suppress is worse than no preview.
     */
    termsPreview(policyClass, entry = {}) {
      if (entry.refund_window === "non_refundable") return [];
      const templates = this.options.terms || {};
      const returning = entry.return_method === "return_required";
      const shipped = policyClass === "physical";
      const out = [];
      // First, because it answers what the buyer gets before the clauses saying what comes off it.
      if (shipped) {
        const clause = (this.options.resolutions || [])
          .find((o) => o.value === entry.resolution)?.clause;
        if (clause) out.push(clause);
      }
      const fee = parseInt(String(entry.restocking_fee_percent || ""), 10);
      if (returning && Number.isFinite(fee) && fee > 0 && templates.restocking_fee?.template) {
        const capped = Math.min(fee, templates.restocking_fee.max || 50);
        out.push(templates.restocking_fee.template.replace("{n}", String(capped)));
      }
      if (shipped) {
        const clause = (this.options.original_shipping || [])
          .find((o) => o.value === entry.original_shipping)?.clause;
        if (clause) out.push(clause);
      }
      const days = parseInt(String(entry.refund_processing_days || ""), 10);
      const processing = templates.processing_days || {};
      const template = returning ? processing.template_after_return : processing.template_after_approval;
      if (Number.isFinite(days) && days > 0 && template) {
        out.push(template.replace("{n}", String(Math.min(days, processing.max || 30))));
      }
      return out;
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
