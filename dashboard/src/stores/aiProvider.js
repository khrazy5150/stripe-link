import { defineStore } from "pinia";
import { apiRequest } from "../api/client";

// Per-tenant AI provider configuration (plans/AI_AND_COMMERCE_ARCHITECTURE.md §A.1). Two paths behind one
// setting: `bedrock` is billed to the platform and gated on plan; a bring-your-own-key provider is billed
// to the tenant and available on every plan, so page generation stays reachable on the free tier.
//
// Connecting always runs a REAL generation server-side before anything is stored -- no readable Bedrock
// field means "this model will answer" (§A.7), and a key that does not work must never become a saved
// setting the tenant discovers is broken later. So `connect` is slow by design; the UI says so.
export const useAiProviderStore = defineStore("aiProvider", {
  state: () => ({
    config: {},          // { provider, model, has_api_key, verified_at, ... } -- never the key itself
    verified: false,
    usage: {},           // { period, used, allowance, remaining, can_generate, reason, billed_to }
    models: [],          // Bedrock models we offer: [{ name, label, rate_in, rate_out, rate_confidence }]
    defaultModel: "",
    loading: false,
    connecting: false,
    error: "",
    message: "",
  }),
  getters: {
    isByok: (state) => !!state.config.provider && state.config.provider !== "bedrock",
    // The tenant's own key pays for its own inference; the allowance is a safety ceiling, not a ration.
    billedToTenant: (state) => state.usage.billed_to === "tenant",
  },
  actions: {
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/ai/config");
        this.config = body.ai_config || {};
        this.verified = !!body.verified;
        this.usage = body.usage || {};
        this.models = Array.isArray(body.models) ? body.models : [];
        this.defaultModel = body.default_model || "";
      } catch (error) {
        this.error = error.message || "Failed to load AI settings.";
      } finally {
        this.loading = false;
      }
    },
    async connect({ provider, model, apiKey }) {
      this.connecting = true;
      this.error = "";
      this.message = "";
      try {
        const payload = { provider, model };
        // Sent once, never stored here and never echoed back: the server encrypts it and returns only
        // whether a key exists.
        if (apiKey) payload.api_key = apiKey;
        const body = await apiRequest("/ai/connect", { method: "POST", body: payload });
        this.config = body.ai_config || {};
        this.verified = !!body.verified;
        this.usage = body.usage || {};
        this.message = "Connected and verified.";
        return true;
      } catch (error) {
        this.error = error.message || "Could not connect that provider.";
        return false;
      } finally {
        this.connecting = false;
      }
    },
  },
});

// What a tenant may bring a key for, and the model ids THEIR account uses. These are the vendor's names,
// not our Bedrock registry's -- "claude-sonnet-4-6" is Anthropic's id, where ours is "sonnet-4.6". Kept in
// step with BYOK_MODELS in src/stripe_link/ai_byok.py; a name missing there is refused server-side.
export const BYOK_PROVIDERS = [
  {
    key: "anthropic",
    label: "Anthropic",
    keyHint: "Starts with sk-ant-",
    consoleUrl: "https://platform.claude.com/settings/keys",
    // A Claude Pro/Max subscription covers the chat apps and NOT the API, which is billed separately
    // through prepaid credits. Said up front because otherwise every subscriber connects a key, gets
    // "add credits" from Anthropic, and reports it to US as a broken feature.
    billingNote: "A Claude Pro or Max subscription does not cover API use — the API is billed separately through credits in the Console.",
    billingUrl: "https://platform.claude.com/settings/billing",
    models: [
      { name: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
      { name: "claude-opus-4-6", label: "Claude Opus 4.6" },
      { name: "claude-haiku-4-5", label: "Claude Haiku 4.5" },
    ],
  },
  {
    key: "openai",
    label: "OpenAI",
    keyHint: "Starts with sk-",
    consoleUrl: "https://platform.openai.com/api-keys",
    // Same trap on the other vendor: a ChatGPT Plus subscription is not API billing either.
    billingNote: "A ChatGPT subscription does not cover API use — the API is billed separately.",
    billingUrl: "https://platform.openai.com/settings/organization/billing",
    models: [
      { name: "gpt-5.6", label: "GPT-5.6" },
      { name: "gpt-6", label: "GPT-6" },
      { name: "gpt-5.6-mini", label: "GPT-5.6 mini" },
    ],
  },
];
