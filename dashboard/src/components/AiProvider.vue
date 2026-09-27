<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>AI</h1>
        <p>Which AI writes your page copy, and whose account pays for it</p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load()">
          {{ store.loading ? "Loading..." : "Reload" }}
        </button>
      </div>
    </header>

    <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
    <div v-else-if="store.message" class="keys-status-banner">{{ store.message }}</div>

    <template v-if="!store.loading">
      <section class="dashboard-card">
        <header class="dashboard-card-header"><h2>Status</h2></header>
        <div class="dashboard-card-body">
          <p v-if="store.verified">
            <strong>{{ providerLabel }}</strong> &middot; {{ modelLabel }}
            <span v-if="store.config.has_api_key"> &middot; your own API key</span>
          </p>
          <p v-else>AI is off. Turn it on below to start generating pages.</p>
          <p v-if="store.verified" class="field-note">{{ usageLabel }} &middot; {{ billedLabel }}</p>
        </div>
      </section>

      <!-- The default path. Nothing for the tenant to sign up for, fund, or paste. -->
      <section class="dashboard-card">
        <header class="dashboard-card-header"><h2>Junior Bay AI</h2></header>
        <div class="dashboard-card-body">
          <p class="field-note">
            Generations are included with your plan. Nothing to set up and no API key to manage.
          </p>
          <template v-if="store.models.length">
            <label class="offer-field">
              <span>Model</span>
              <select v-model="form.platformModel">
                <option v-for="m in store.models" :key="m.name" :value="m.name">{{ m.label }}</option>
              </select>
            </label>
            <div class="button-row">
              <button class="primary-action" type="button" :disabled="store.connecting" @click="connectPlatform">
                {{ platformButtonLabel }}
              </button>
            </div>
            <!-- Said out loud because the request really is slow: a real generation runs before
                 anything is saved, so a model that cannot answer never looks configured. -->
            <p class="field-note">
              We run one real generation to check everything works. This takes a few seconds.
            </p>
          </template>
          <p v-else class="field-note">No models are available right now.</p>
        </div>
      </section>

      <!-- Kept, not promoted. Bringing a key means a separate vendor account funded with prepaid
           credits that expire in a year and never refund. -->
      <section class="dashboard-card">
        <header class="dashboard-card-header">
          <h2>Use your own AI account</h2>
          <button class="secondary-action compact" type="button" @click="showByok = !showByok">
            {{ showByok ? "Hide" : "Show" }}
          </button>
        </header>
        <div v-if="showByok" class="dashboard-card-body">
          <p class="field-note">
            For higher volume, or if your policy requires generations run under your own vendor
            account. You supply an API key and they bill you directly.
          </p>

          <div class="offer-two-column">
            <label class="offer-field">
              <span>Provider</span>
              <select v-model="form.provider">
                <option v-for="p in providers" :key="p.key" :value="p.key">{{ p.label }}</option>
              </select>
            </label>
            <label class="offer-field">
              <span>Model</span>
              <select v-model="form.model">
                <option v-for="m in selectedProvider.models" :key="m.name" :value="m.name">{{ m.label }}</option>
              </select>
            </label>
          </div>

          <label class="offer-field">
            <span>API key</span>
            <input
              v-model="form.apiKey"
              type="password"
              autocomplete="off"
              spellcheck="false"
              :placeholder="selectedProvider.keyHint"
            />
          </label>
          <p class="field-note">
            Stored encrypted and never shown again &mdash; not even to you.
            <a :href="selectedProvider.consoleUrl" target="_blank" rel="noopener noreferrer">
              Get a key from {{ selectedProvider.label }}
            </a>
          </p>
          <!-- Before the button, not after a failure: a subscriber who connects a key and is told to
               "add credits" by their provider reports it here as a broken feature. -->
          <p class="field-note">
            {{ selectedProvider.billingNote }} Credits are prepaid, expire a year after purchase, and
            are not refundable &mdash; so buy a small amount first.
            <a :href="selectedProvider.billingUrl" target="_blank" rel="noopener noreferrer">
              Check your {{ selectedProvider.label }} billing
            </a>
          </p>

          <div class="button-row">
            <button
              class="secondary-action"
              type="button"
              :disabled="!form.apiKey.trim() || store.connecting"
              @click="connectByok"
            >
              {{ store.connecting ? "Verifying..." : "Connect and verify" }}
            </button>
          </div>
        </div>
      </section>
    </template>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import { BYOK_PROVIDERS, useAiProviderStore } from "../stores/aiProvider";

const store = useAiProviderStore();
store.load();

const showByok = ref(false);

const providers = BYOK_PROVIDERS;
const form = reactive({
  provider: BYOK_PROVIDERS[0].key,
  model: BYOK_PROVIDERS[0].models[0].name,
  apiKey: "",
  platformModel: "",
});

const selectedProvider = computed(
  () => providers.find((p) => p.key === form.provider) || providers[0],
);

// Switching provider must not leave a model id from the previous vendor in the form -- the server
// refuses it (their names, not ours) and the tenant would see a puzzling "unknown model".
watch(() => form.provider, () => {
  form.model = selectedProvider.value.models[0].name;
});

// The platform select starts empty because the catalogue arrives with the first load. Without this the
// primary button would post an empty model and fall back server-side -- correct, but it would show the
// tenant a blank dropdown beside a button that works, which reads as broken.
watch(() => store.models, (models) => {
  if (!form.platformModel && models.length) {
    form.platformModel = store.defaultModel || models[0].name;
  }
}, { immediate: true });

const providerLabel = computed(() => {
  if (store.config.provider === "bedrock") return "Junior Bay's AI";
  return (providers.find((p) => p.key === store.config.provider) || {}).label || store.config.provider;
});

// The raw registry id ("sonnet-4.6") is ours, not a name a tenant recognises.
const modelLabel = computed(() => {
  const name = store.config.model;
  const fromPlatform = (store.models || []).find((m) => m.name === name);
  if (fromPlatform) return fromPlatform.label;
  for (const p of providers) {
    const found = (p.models || []).find((m) => m.name === name);
    if (found) return found.label;
  }
  return name || "";
});

// "Turn on AI" is wrong once it IS on -- the same click then means "switch model" or "re-check".
const platformButtonLabel = computed(() => {
  if (store.connecting) return "Checking...";
  if (!store.verified) return "Turn on AI";
  if (store.config.provider !== "bedrock") return "Switch to Junior Bay AI";
  return form.platformModel && form.platformModel !== store.config.model
    ? "Switch model"
    : "Re-check connection";
});

const usageLabel = computed(() => {
  const { used = 0, allowance = 0 } = store.usage || {};
  if (allowance < 0) return `${used} generations this month`;
  return `${used} of ${allowance} generations this month`;
});

const billedLabel = computed(() =>
  store.billedToTenant ? "billed to your own account" : "included with your plan",
);

async function connectByok() {
  const ok = await store.connect({
    provider: form.provider,
    model: form.model,
    apiKey: form.apiKey.trim(),
  });
  // Cleared either way: a rejected key is not worth keeping in a field, and a good one is already saved.
  form.apiKey = "";
  if (ok) await store.load();
}

async function connectPlatform() {
  const ok = await store.connect({
    provider: "bedrock",
    model: form.platformModel || store.defaultModel,
  });
  if (ok) await store.load();
}
</script>
