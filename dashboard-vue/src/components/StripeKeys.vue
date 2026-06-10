<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Stripe Keys</h1>
        <p>Manage tenant Stripe API keys using the StripeKeys schema.</p>
      </div>
      <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load">
        {{ store.loading ? "Loading..." : "Load Keys" }}
      </button>
    </header>

    <form class="stripe-keys-form" @submit.prevent="store.save">
      <section class="dashboard-card stripe-keys-card">
        <header class="dashboard-card-header">
          <div>
            <h2>Tenant Stripe Keys</h2>
            <p>Save test keys to the dev table and live keys to the prod table in one request.</p>
          </div>
          <label class="tenant-field">
            Tenant ID
            <input v-model.trim="store.tenantId" required autocomplete="off" />
          </label>
        </header>

        <div class="stripe-keys-body">
          <button type="submit" class="primary-action" :disabled="store.saving">
            {{ store.saving ? "Saving..." : "Save Test + Live Keys" }}
          </button>

          <div class="stripe-key-grid">
            <StripeKeyPanel mode="test" title="Test Keys" />
            <StripeKeyPanel mode="live" title="Live Keys" dark />
          </div>

          <div class="verify-row">
            <label>
              Verify Mode
              <select v-model="store.verifyMode">
                <option value="test">Test</option>
                <option value="live">Live</option>
              </select>
            </label>
            <button class="primary-action" type="button" :disabled="store.verifying" @click="store.verify">
              {{ store.verifying ? "Verifying..." : "Verify Selected Keys" }}
            </button>
          </div>

          <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
          <div v-else class="keys-status-banner">{{ store.message }}</div>
        </div>
      </section>
    </form>

    <section v-if="store.output" class="dashboard-card output-card">
      <header class="dashboard-card-header">
        <h2>API Output</h2>
      </header>
      <pre>{{ JSON.stringify(store.output, null, 2) }}</pre>
    </section>
  </section>
</template>

<script setup>
import { onMounted } from "vue";
import StripeKeyPanel from "./StripeKeyPanel.vue";
import { useStripeKeysStore } from "../stores/stripeKeys";

const store = useStripeKeysStore();

onMounted(() => {
  store.resetForCurrentTenant();
  store.load();
});
</script>
