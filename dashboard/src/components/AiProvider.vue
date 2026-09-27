<template>
  <section class="screen">
    <header class="screen-head">
      <div>
        <h1>AI</h1>
        <p class="screen-sub">
          Which AI writes your page copy, and whose account pays for it.
        </p>
      </div>
    </header>

    <p v-if="store.loading" class="muted">Loading…</p>
    <p v-else-if="store.error" class="form-error">{{ store.error }}</p>

    <template v-if="!store.loading">
      <!-- Current state first: a tenant who already connected wants to know it still works. -->
      <div class="card ai-status" :class="{ 'ai-status--on': store.verified }">
        <div>
          <h2>{{ store.verified ? "Connected" : "Not connected" }}</h2>
          <p v-if="store.verified" class="muted">
            {{ providerLabel }} · {{ store.config.model }}
            <span v-if="store.config.has_api_key"> · your own API key</span>
          </p>
          <p v-else class="muted">Turn on AI below to start generating pages.</p>
        </div>
        <div v-if="store.verified" class="ai-usage">
          <strong>{{ usageLabel }}</strong>
          <span class="muted">{{ billedLabel }}</span>
        </div>
      </div>

      <!-- The default path. Nothing for the tenant to sign up for, fund, or paste. -->
      <div class="card">
        <h2>Junior Bay AI</h2>
        <p class="muted">
          Generations are included with your plan. Nothing to set up and no API key to manage.
        </p>
        <template v-if="store.models.length">
          <div class="field">
            <label for="ai-platform-model">Model</label>
            <select id="ai-platform-model" v-model="form.platformModel">
              <option v-for="m in store.models" :key="m.name" :value="m.name">{{ m.label }}</option>
            </select>
          </div>
          <button class="primary-action" type="button" :disabled="store.connecting" @click="connectPlatform">
            {{ store.connecting ? "Turning on…" : "Turn on AI" }}
          </button>
          <!-- Said out loud because the request really is slow: we run a real generation before
               saving anything, so a model that cannot answer never becomes a working-looking setting. -->
          <p class="field-hint">
            We run one real generation to check everything works. This takes a few seconds.
          </p>
        </template>
        <p v-else class="muted">No models are available right now.</p>
      </div>

      <!-- Kept, not promoted. Bringing a key means a separate vendor account funded with prepaid
           credits that expire in a year and never refund -- real friction, worth it only for a tenant
           who wants more headroom or their own vendor relationship. -->
      <details class="card ai-advanced">
        <summary><h2>Use your own AI account</h2></summary>
        <p class="muted">
          For higher volume, or if your policy requires generations run under your own vendor account.
          You supply an API key and they bill you directly.
        </p>

        <div class="field">
          <label for="ai-provider">Provider</label>
          <select id="ai-provider" v-model="form.provider">
            <option v-for="p in providers" :key="p.key" :value="p.key">{{ p.label }}</option>
          </select>
        </div>

        <div class="field">
          <label for="ai-model">Model</label>
          <select id="ai-model" v-model="form.model">
            <option v-for="m in selectedProvider.models" :key="m.name" :value="m.name">{{ m.label }}</option>
          </select>
        </div>

        <div class="field">
          <label for="ai-key">API key</label>
          <input
            id="ai-key"
            v-model="form.apiKey"
            type="password"
            autocomplete="off"
            spellcheck="false"
            :placeholder="selectedProvider.keyHint"
          />
          <p class="field-hint">
            Stored encrypted and never shown again — not even to you.
            <a :href="selectedProvider.consoleUrl" target="_blank" rel="noopener noreferrer">
              Get a key from {{ selectedProvider.label }}
            </a>
          </p>
        </div>

        <!-- Before the button, not after a failure: a subscriber who connects a key and is told to
             "add credits" by their provider reports it here as a broken feature. -->
        <div class="field">
          <p class="field-hint">
            {{ selectedProvider.billingNote }} Credits are prepaid, expire a year after purchase, and
            are not refundable — so buy a small amount first.
            <a :href="selectedProvider.billingUrl" target="_blank" rel="noopener noreferrer">
              Check your {{ selectedProvider.label }} billing
            </a>
          </p>
        </div>

        <button
          class="secondary-action"
          type="button"
          :disabled="!form.apiKey.trim() || store.connecting"
          @click="connectByok"
        >
          {{ store.connecting ? "Verifying…" : "Connect and verify" }}
        </button>
      </details>

      <p v-if="store.message" class="form-success">{{ store.message }}</p>
    </template>
  </section>
</template>

<script setup>
import { computed, reactive, watch } from "vue";
import { BYOK_PROVIDERS, useAiProviderStore } from "../stores/aiProvider";

const store = useAiProviderStore();
store.load();

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
