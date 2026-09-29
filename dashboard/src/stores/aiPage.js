import { defineStore } from "pinia";
import { apiRequest } from "../api/client";

// The AI page wizard (plans/AI_PAGE_BRIEF.md). Writes a brief, posts it, gets back a Product, an Offer
// and a DRAFT page.
//
// The organising rule, and the reason this store tracks `withheld`: every question the tenant does not
// answer is a fact the AI is not allowed to assert. The §A.7 floor rejects ungrounded claims, so a thin
// brief does not make a shorter page -- it makes a cautious one. Showing what will be WITHHELD before
// generating is what makes a thin page understandable instead of disappointing.

export const KINDS = [
  { key: "physical", label: "Something physical", hint: "You ship it to them." },
  { key: "digital", label: "A download", hint: "They get a file or access straight after paying." },
  { key: "service", label: "A service you perform", hint: "Sessions, appointments, consulting." },
];

export const TONES = ["direct", "warm", "playful", "technical", "premium"];

// Mirrors domain/page_brief.py steps_for(). The kind decides the shape -- a download is never asked
// about shipping, because asking it is the fulfilment question asked twice.
const COMMON_HEAD = ["identity", "price", "audience", "facts"];
const KIND_STEP = { physical: "shipping_use", digital: "delivery", service: "session" };
const COMMON_TAIL = ["promises", "voice", "exact", "review"];

export const STEP_LABELS = {
  identity: "What you're selling", price: "Price", audience: "Who it's for",
  facts: "What people should know", shipping_use: "Shipping & use",
  delivery: "What they receive", session: "The session", promises: "Promises you make",
  voice: "Voice", exact: "Anything exact", review: "Review",
};

// Steps a tenant may leave untouched. "Leave it" should be one click, not a guess -- the ServiceWizard
// lesson. Note `session` is NOT here: a service page that cannot say how long it takes is not worth
// generating, so it blocks.
export const SKIPPABLE = new Set(["shipping_use", "delivery", "promises", "voice", "exact"]);

export function stepsFor(kind) {
  if (!KIND_STEP[kind]) return ["identity"];
  return [...COMMON_HEAD, KIND_STEP[kind], ...COMMON_TAIL];
}

function emptyBrief() {
  return {
    kind: "", name: "", what_it_is: "", audience: "", facts: "",
    price: { unit_amount: null, currency: "usd", pricing_model: "one_time", recurring_interval: "month" },
    guarantee: "", terms: "", certifications: "", evidence: "",
    tone: "direct", category: "", must_say: "", must_not_say: "",
    // Measurements are separate NUMBERS, not one free-text box: these are the packer's own inputs
    // (fulfillment.dimensions + weight_lb), and label_readiness gates buying a label on them.
    physical: { shipping: "", usage: "", materials: "",
                length_in: null, width_in: null, height_in: null, weight_lb: null },
    digital: { format: "", access: "" },
    service: { duration_minutes: 60, location_mode: "remote", performed_by: "", what_happens: "" },
  };
}

// Lines in the textarea become a list; the server accepts either, but sending the shape it stores
// keeps the wire honest.
function lines(value) {
  return String(value || "").split("\n").map((s) => s.trim()).filter(Boolean);
}

export const useAiPageStore = defineStore("aiPage", {
  state: () => ({
    brief: emptyBrief(),
    step: 0,
    generating: false,
    progress: "",
    error: "",
    result: null,       // { product, offer, page, withheld, decisions, generation }
  }),
  getters: {
    steps: (state) => stepsFor(state.brief.kind),
    stepKey() { return this.steps[this.step] || "identity"; },
    stepLabels() { return this.steps.map((s) => STEP_LABELS[s]); },
    // Every kind is the same LENGTH -- only the content of the kind step differs -- so the total is
    // honest before a kind is picked. Showing `steps.length` there said "Step 1 of 1", because the
    // shape is unknown until the kind is answered and the list is a single placeholder.
    totalSteps() { return this.brief.kind ? this.steps.length : stepsFor("physical").length; },
    // And a one-item placeholder list must not read as "you are on the last step", which offered
    // "Generate the page" on an empty brief.
    onLastStep() { return !!this.brief.kind && this.step >= this.steps.length - 1; },
    // What the generated page will NOT be able to say, computed locally so the review step is
    // instant. The server returns its own authoritative copy after generating.
    withheld(state) {
      const b = state.brief;
      const kindBlock = b[b.kind] || {};
      const gaps = [
        [!b.terms, "cancellation", "Tell us your cancellation terms and we can answer \"can I cancel anytime?\""],
        [!b.guarantee, "guarantee", "Add your guarantee and we can write about it."],
        [!lines(b.certifications).length, "certification", "List certifications you hold and we can name them."],
        [!b.evidence, "efficacy", "Add evidence you can stand behind and we can describe results."],
      ];
      if (b.kind === "physical") {
        gaps.push([!kindBlock.shipping, "shipping", "Tell us your shipping and we can mention delivery."]);
        gaps.push([!kindBlock.usage, "dosage", "Add directions and we can explain how to use it."]);
      }
      if (b.kind === "service") {
        gaps.push([!kindBlock.what_happens, "dosage", "Describe the session and we can explain what happens."]);
      }
      return gaps.filter(([missing]) => missing).map(([, claimClass, prompt]) => ({ claimClass, prompt }));
    },
    canAdvance(state) {
      const b = state.brief;
      switch (this.stepKey) {
        case "identity": return !!(b.kind && b.name.trim() && b.what_it_is.trim());
        case "price": return Number(b.price.unit_amount) > 0;
        case "audience": return !!b.audience.trim();
        case "facts": return lines(b.facts).length > 0;
        // The only kind block that can block, and deliberately: a service page unable to say how long
        // it takes or whether it is remote is not worth generating.
        case "session": return Number(b.service.duration_minutes) > 0 && !!b.service.location_mode;
        default: return true;
      }
    },
  },
  actions: {
    // A full wipe. Separate from `editAnswers` and `regenerate` because the BRIEF is the expensive
    // part -- the answers took minutes, the generation took seconds. Throwing the brief away to get
    // different words was the original flaw in this flow.
    reset() { this.brief = emptyBrief(); this.step = 0; this.result = null; this.error = ""; },

    // Back into the wizard with every answer intact, landing on the review step so a small change is
    // one edit away rather than nine Next clicks.
    editAnswers() {
      this.result = null;
      this.error = "";
      this.step = Math.max(0, this.steps.length - 1);
    },
    next() { if (this.canAdvance && !this.onLastStep) this.step += 1; },
    back() { if (this.step > 0) this.step -= 1; },
    goTo(index) { if (index >= 0 && index < this.steps.length) this.step = index; },

    payload() {
      const b = this.brief;
      const price = {
        unit_amount: Math.round(Number(b.price.unit_amount) * 100),
        currency: b.price.currency,
        pricing_model: b.price.pricing_model,
      };
      if (price.pricing_model === "recurring") price.recurring_interval = b.price.recurring_interval;
      const brief = {
        source: "wizard", kind: b.kind, name: b.name.trim(), what_it_is: b.what_it_is.trim(),
        audience: b.audience.trim(), facts: lines(b.facts), price,
        guarantee: b.guarantee.trim(), terms: b.terms.trim(),
        certifications: lines(b.certifications), evidence: b.evidence.trim(),
        tone: b.tone, category: b.category.trim(),
        must_say: lines(b.must_say), must_not_say: lines(b.must_not_say),
      };
      brief[b.kind] = { ...b[b.kind] };
      return brief;
    },

    // `pageId` rewrites the copy on a page that already exists: same product, same offer, same Stripe
    // sync, new words. Without it every retry would leave a duplicate product behind.
    //
    // POST only QUEUES -- generation runs past API Gateway's 29-second ceiling, so the answer is a job
    // id and the rest is polling. A measured 35s generation is what made this necessary: the work
    // succeeded and the browser reported "Failed to fetch".
    async generate(mode = "test", pageId = "") {
      this.generating = true;
      this.error = "";
      this.progress = "Starting…";
      try {
        const body = { brief: this.payload(), mode };
        if (pageId) body.page_id = pageId;
        const queued = await apiRequest("/ai/generate", { method: "POST", body });
        return await this.awaitJob(queued.job.job_id);
      } catch (error) {
        this.error = error.message || "The page could not be generated.";
        this.generating = false;
        return false;
      }
    },

    async awaitJob(jobId) {
      // Generation measured 13-35s, so a 2s poll is ~10 reads. The ceiling is generous rather than
      // tight: a job that outlives it has almost certainly failed in a way that never reached the
      // record, and saying so beats spinning forever.
      const started = Date.now();
      try {
        for (;;) {
          await new Promise((resolve) => setTimeout(resolve, 2000));
          const body = await apiRequest(`/ai/jobs/${encodeURIComponent(jobId)}`);
          const job = body.job || {};
          if (job.status === "complete") {
            this.result = { ...job.result, usage: job.usage, withheld: job.withheld };
            return true;
          }
          if (job.status === "failed") {
            this.error = job.error?.message || "The page could not be generated.";
            return false;
          }
          this.progress = job.status === "running" ? "Writing your page…" : "Waiting to start…";
          if (Date.now() - started > 180000) {
            this.error = "That took longer than expected. Check Landing Pages before trying again — "
              + "it may have finished.";
            return false;
          }
        }
      } catch (error) {
        this.error = error.message || "Lost contact with the generation.";
        return false;
      } finally {
        this.generating = false;
        this.progress = "";
      }
    },

    /**
     * Build a page for a product the tenant ALREADY has — the fork off the product wizard.
     *
     * The brief is projected server-side from the product, the tenant's refund/shipping policy and
     * `Product.ai_context`, so nothing the product wizard already asked is asked again
     * (plans/AI_PAGE_BRIEF.md v2). All this sends is the product and the one step's answers; sending a
     * brief from here would mean the browser deciding what the AI is licensed to assert.
     *
     * Queue-and-poll, same as `generate`: a generation runs past API Gateway's 29-second ceiling, and the
     * one time it did not, the work succeeded and the browser reported "Failed to fetch".
     */
    async generateForProduct(productId, aiContext = {}, mode = "test") {
      this.generating = true;
      this.error = "";
      this.progress = "Starting…";
      this.result = null;
      try {
        const queued = await apiRequest("/ai/generate", {
          method: "POST",
          body: { product_id: productId, ai_context: aiContext, mode },
        });
        return await this.awaitJob(queued.job.job_id);
      } catch (error) {
        this.error = error.message || "The page could not be generated.";
        this.generating = false;
        this.progress = "";
        return false;
      }
    },

    regenerate(mode = "test") {
      return this.generate(mode, this.result?.page?.page_id || "");
    },
  },
});
