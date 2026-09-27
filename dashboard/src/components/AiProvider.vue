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
          <p v-else class="muted">Choose a provider below to start generating pages.</p>
        </div>
        <div v-if="store.verified" class="ai-usage">
          <strong>{{ usageLabel }}</strong>
          <span class="muted">{{ billedLabel }}</span>
        </div>
      </div>

      <!-- Bring your own key. Listed FIRST: it works on every plan, and it is the only path that does
           not depend on this platform's own model access. -->
      <div class="card">
        <h2>Use your own AI account</h2>
        <p class="muted">
          You supply an API key from your own provider account, and they bill you directly for what you
          use. Available on every plan.
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
            {{ selectedProvider.billingNote }}
            <a :href="selectedProvider.billingUrl" target="_blank" rel="noopener noreferrer">
              Check your {{ selectedProvider.label }} billing
            </a>
          </p>
        </div>

        <button
          class="primary-action"
          type="button"
          :disabled="!form.apiKey.trim() || store.connecting"
          @click="connectByok"
        >
          {{ store.connecting ? "Verifying…" : "Connect and verify" }}
        </button>
        <!-- Said out loud because the request really is slow: we run a real generation before saving
             anything, so a key that does not work never becomes a setting you discover is broken later. -->
        <p class="field-hint">
          We run one real generation to check the key works before saving it. This takes a few seconds.
        </p>
      </div>

      <!-- Platform-paid. Shown second, and only as far as it is actually usable. -->
      <div class="card">
        <h2>Use Junior Bay's AI</h2>
        <p class="muted">
          No key to manage — generations are included with your plan.
        </p>
        <template v-if="store.models.length">
          <div class="field">
            <label for="ai-platform-model">Model</label>
            <select id="ai-platform-model" v-model="form.platformModel">
              <option v-for="m in store.models" :key="m.name" :value="m.name">{{ m.label }}</option>
            </select>
          </div>
          <button class="secondary-action" type="button" :disabled="store.connecting" @click="connectPlatform">
            {{ store.connecting ? "Verifying…" : "Use Junior Bay's AI" }}
          </button>
        </template>
        <p v-else class="muted">No platform models are available right now.</p>
      </div>

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
