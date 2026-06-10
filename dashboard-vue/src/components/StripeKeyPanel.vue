<template>
  <section class="stripe-key-panel" :class="{ 'stripe-key-panel-live': dark, 'stripe-key-panel-test': !dark }">
    <header>
      <h3>{{ title }}</h3>
    </header>
    <div class="stripe-key-panel-body">
      <label>
        {{ mode === "live" ? "pk_live" : "pk_test" }}
        <input
          v-model.trim="model.publishable_key"
          autocomplete="off"
          :placeholder="schema.fields.publishable_key.placeholders[mode]"
        />
      </label>

      <label>
        {{ mode === "live" ? "sk_live" : "sk_test" }} (plaintext)
        <input
          v-model="model.secret_key_ref"
          type="password"
          autocomplete="new-password"
          :placeholder="secretPlaceholder('secret_key_ref')"
          :title="secretTitle('secret_key_ref')"
        />
      </label>

      <label>
        {{ mode === "live" ? "wh_secret_live" : "wh_secret_test" }} (auto-generated)
        <input
          v-model="model.webhook_secret_ref"
          type="password"
          autocomplete="new-password"
          :placeholder="secretPlaceholder('webhook_secret_ref')"
          :title="secretTitle('webhook_secret_ref')"
        />
      </label>

      <div class="webhook-row">
        <label>
          Webhook Endpoint ({{ modeLabel }})
          <input readonly :value="webhookEndpoint" />
        </label>
        <button type="button" class="secondary-action">Test this endpoint</button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from "vue";
import { useStripeKeysStore } from "../stores/stripeKeys";
import { stripeKeysSchema as schema } from "../schema/stripeKeysSchema";

const props = defineProps({
  mode: {
    type: String,
    required: true,
    validator: (value) => ["test", "live"].includes(value),
  },
  title: {
    type: String,
    required: true,
  },
  dark: {
    type: Boolean,
    default: false,
  },
});

const store = useStripeKeysStore();
const model = computed(() => store.modes[props.mode]);
const modeLabel = computed(() => props.mode === "live" ? "Live" : "Test");
const webhookEndpoint = computed(() => {
  const tenantId = encodeURIComponent(store.tenantId || "tenant_demo");
  const host = props.mode === "live" ? "https://prod.juniorbay.com" : "https://dev.juniorbay.com";
  return `${host}/webhook/${tenantId}`;
});

function secretPlaceholder(field) {
  const saved = field === "secret_key_ref" ? model.value.saved_secret_key : model.value.saved_webhook_secret;
  if (saved) return "Saved (hidden)";
  return schema.fields[field].placeholders[props.mode];
}

function secretTitle(field) {
  const saved = field === "secret_key_ref" ? model.value.saved_secret_key : model.value.saved_webhook_secret;
  return saved ? "Encrypted value is stored. Enter a new value to replace it." : schema.fields[field].description;
}
</script>
