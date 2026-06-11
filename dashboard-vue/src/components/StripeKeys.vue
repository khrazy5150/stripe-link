<template>
  <section class="page">
    <div v-if="setupWarning" class="stripe-setup-banner">
      <div>
        <strong>{{ setupWarning.title }}</strong>
        <span>{{ setupWarning.body }}</span>
      </div>
      <button type="button" class="setup-action" @click="openWizard(setupStartStep)">
        Complete Setup
      </button>
    </div>

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
              <select v-model="store.verifyMode" @change="store.loadConnectCard">
                <option value="test">Test</option>
                <option value="live">Live</option>
              </select>
            </label>
            <button class="primary-action" type="button" :disabled="store.verifying" @click="store.verify">
              {{ store.verifying ? "Verifying..." : "Verify Selected Keys" }}
            </button>
          </div>

          <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
          <div v-else :class="['keys-status-banner', store.messageTone]">{{ store.message }}</div>
        </div>
      </section>
    </form>

    <section class="dashboard-card connect-card">
      <header class="dashboard-card-header connect-card-header">
        <div>
          <h2>Stripe Connect</h2>
          <p>Connect your Stripe account to receive payments</p>
        </div>
        <span v-if="store.connectCard" class="tier-pill">{{ tierLabel }}</span>
      </header>

      <div class="connect-card-body">
        <p class="connect-copy">
          Connect your Stripe account to start receiving payments. A platform fee will be applied to each transaction.
        </p>

        <div class="connect-fee-panel">
          <h3>Platform Fees</h3>
          <dl v-if="feeRows.length" class="connect-fee-list">
            <template v-for="fee in feeRows" :key="fee.key">
              <dt>{{ fee.label }}</dt>
              <dd>{{ fee.value }}</dd>
            </template>
          </dl>
          <p v-else class="connect-muted">Fee schedule is not available for this tier.</p>
        </div>

        <div class="connect-actions">
          <button
            v-if="isConnected"
            type="button"
            class="primary-action connect-connected"
            disabled
          >
            {{ modeLabel }} Account Connected
          </button>
          <button
            v-else
            type="button"
            class="primary-action"
            :disabled="store.connectLoading || store.connectStarting"
            @click="store.startConnect({ chain: 'both', path: 'existing' })"
          >
            {{ store.connectStarting ? "Starting..." : `Connect ${modeLabel} Account` }}
          </button>
        </div>

        <div class="connect-account-lines">
          <p v-if="testAccountId">Test Account ID: {{ testAccountId }}</p>
          <p v-if="liveAccountId">Live Account ID: {{ liveAccountId }}</p>
          <p v-if="!testAccountId && !liveAccountId" class="connect-muted">
            No Stripe Connect account linked yet.
          </p>
        </div>

        <div v-if="isRestricted" class="connect-warning">
          {{ modeLabel }} account restricted in Stripe. Action required: {{ restrictionReason }}.
        </div>
        <div v-if="store.connectError" class="keys-status-banner error">{{ store.connectError }}</div>
      </div>
    </section>

    <div v-if="wizardOpen" class="modal-backdrop" @click.self="closeWizard">
      <section class="modal-card stripe-onboarding-modal" role="dialog" aria-modal="true" aria-labelledby="stripe-onboarding-title">
        <header class="modal-card-header">
          <div>
            <h2 id="stripe-onboarding-title">{{ wizardTitle }}</h2>
            <p>Step {{ wizardStep }} of {{ wizardMaxStep }}</p>
            <div class="onboarding-progress" aria-hidden="true">
              <span
                v-for="step in wizardMaxStep"
                :key="step"
                :class="['onboarding-dot', { active: step === wizardStep, complete: step < wizardStep }]"
              ></span>
            </div>
          </div>
          <button class="modal-close" type="button" aria-label="Close" @click="closeWizard">&times;</button>
        </header>

        <div class="onboarding-body">
          <div v-if="wizardStep === 1" class="onboarding-step">
            <p>
              To accept payments from your customers, Junior Bay needs permission to connect to your Stripe account.
            </p>
            <button
              type="button"
              :class="['onboarding-option-card', { selected: wizardIntent === 'create' }]"
              @click="wizardIntent = 'create'"
            >
              <strong>Create a new Stripe account</strong>
              <span>Stripe will guide you through account creation, then return you to Junior Bay.</span>
            </button>
            <button
              type="button"
              :class="['onboarding-option-card', { selected: wizardIntent === 'existing' }]"
              @click="wizardIntent = 'existing'"
            >
              <strong>Connect an existing Stripe account</strong>
              <span>Authorize Junior Bay from the Stripe account you already use.</span>
            </button>
          </div>

          <div v-else-if="wizardStep === 2" class="onboarding-step">
            <p>
              Continue to Stripe to authorize Junior Bay. No API keys need to be copied or pasted.
            </p>
            <div class="keys-status-banner info">
              Stripe sends Junior Bay a secure OAuth token after approval. The token is encrypted before it is stored.
            </div>
            <button
              type="button"
              class="primary-action onboarding-link"
              :disabled="wizardSaving || store.connectStarting"
              @click="beginStripeOAuth"
            >
              {{ wizardSaving || store.connectStarting ? "Opening Stripe..." : "Continue with Stripe" }}
            </button>
          </div>

          <div v-else-if="wizardStep === 3" class="onboarding-step">
            <p>
              After Stripe redirects back, Junior Bay confirms the connected account here.
            </p>
            <div v-if="isConnected" class="keys-status-banner success">
              Stripe account connected{{ connectAccountId ? `: ${connectAccountId}` : "" }}.
            </div>
            <div v-else class="keys-status-banner warning">
              Waiting for Stripe authorization to complete.
            </div>
            <button type="button" class="secondary-action" :disabled="store.connectLoading" @click="refreshConnectStatus">
              {{ store.connectLoading ? "Refreshing..." : "Refresh Status" }}
            </button>
          </div>

          <div v-else-if="wizardStep === 4" class="onboarding-step">
            <p>Complete Stripe onboarding so payouts, compliance, and payment acceptance are ready.</p>
            <div v-if="isConnected && !isRestricted" class="keys-status-banner success">
              {{ modeLabel }} Stripe Connect account is linked{{ connectAccountId ? `: ${connectAccountId}` : "" }}.
            </div>
            <div v-else-if="isRestricted" class="keys-status-banner warning">
              {{ modeLabel }} account restricted in Stripe. Action required: {{ restrictionReason }}.
            </div>
            <div v-else class="keys-status-banner warning">
              Stripe Connect is not linked yet.
            </div>
            <div class="onboarding-actions-row">
              <button type="button" class="primary-action" :disabled="store.connectStarting" @click="beginStripeOAuth">
                {{ store.connectStarting ? "Starting..." : "Continue Stripe onboarding" }}
              </button>
              <button type="button" class="secondary-action" :disabled="store.connectLoading" @click="refreshConnectStatus">
                {{ store.connectLoading ? "Refreshing..." : "Refresh Status" }}
              </button>
            </div>
          </div>

          <div v-else class="onboarding-step">
            <p>
              Verify the webhook endpoint once Stripe has returned webhook credentials. The advanced keys page remains available for manual secret management.
            </p>
            <dl class="onboarding-review">
              <div>
                <dt>Test webhook endpoint</dt>
                <dd>{{ webhookUrl("test") }}</dd>
              </div>
              <div>
                <dt>Live webhook endpoint</dt>
                <dd>{{ webhookUrl("live") }}</dd>
              </div>
            </dl>
            <div class="onboarding-actions-row">
              <button type="button" class="primary-action" :disabled="store.verifying" @click="verifyWebhook">
                {{ store.verifying ? "Verifying..." : "Verify Webhook Endpoint" }}
              </button>
              <button type="button" class="secondary-action" :disabled="store.connectLoading" @click="refreshConnectStatus">
                {{ store.connectLoading ? "Refreshing..." : "Refresh Status" }}
              </button>
            </div>
          </div>

          <div v-if="wizardError" class="keys-status-banner error">{{ wizardError }}</div>
        </div>

        <footer class="onboarding-footer">
          <button type="button" class="link-action" @click="closeWizard">Skip for now</button>
          <div class="onboarding-footer-actions">
            <button v-if="wizardStep > 1" type="button" class="secondary-action" :disabled="wizardSaving" @click="wizardStep -= 1">
              Back
            </button>
            <button type="button" class="primary-action" :disabled="wizardSaving" @click="nextWizardStep">
              {{ wizardNextLabel }}
            </button>
          </div>
        </footer>
      </section>
    </div>

    <section v-if="store.output" class="dashboard-card output-card">
      <header class="dashboard-card-header">
        <h2>API Output</h2>
      </header>
      <pre>{{ JSON.stringify(store.output, null, 2) }}</pre>
    </section>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import StripeKeyPanel from "./StripeKeyPanel.vue";
import { useStripeKeysStore } from "../stores/stripeKeys";

const store = useStripeKeysStore();
const wizardMaxStep = 5;
const wizardOpen = ref(false);
const wizardStep = ref(1);
const wizardIntent = ref("create");
const wizardSaving = ref(false);
const wizardError = ref("");

const feeLabels = {
  physical: "Physical Products",
  digital: "Digital Products",
  tip_jar: "Tip Jar",
};

const modeLabel = computed(() => (store.verifyMode === "live" ? "Live" : "Test"));

const tierLabel = computed(() => {
  const tier = store.connectCard?.tier_id || "basic";
  return `${tier.charAt(0).toUpperCase()}${tier.slice(1)} tier`;
});

const feeRows = computed(() => {
  const rates = store.connectCard?.platform_fees?.rates || {};
  return Object.entries(rates).map(([key, value]) => ({
    key,
    label: feeLabels[key] || key.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase()),
    value: `${Number(value || 0)}%`,
  }));
});

const connectDocument = computed(() => store.connectCard?.stripe_connect || {});
const connectStatus = computed(() => String(connectDocument.value.connect_status || "not_connected"));
const isConnected = computed(() => connectStatus.value === "connected" || Boolean(connectAccountId.value));
const isRestricted = computed(() => connectStatus.value === "restricted");
const connectAccountId = computed(() => (
  connectDocument.value.connect_account_id
  || connectDocument.value.stripe_account_id
  || connectDocument.value.account_id
  || ""
));
const testAccountId = computed(() => (store.verifyMode === "test" ? connectAccountId.value : ""));
const liveAccountId = computed(() => (store.verifyMode === "live" ? connectAccountId.value : ""));
const restrictionReason = computed(() => connectDocument.value.restriction_reason || "Verification Document");
const setupWarning = computed(() => {
  if (isRestricted.value) {
    return {
      title: `Your ${modeLabel.value.toLowerCase()} Stripe account is restricted.`,
      body: " Resolve the Stripe requirement before accepting payments.",
    };
  }
  if (!isConnected.value) {
    return {
      title: "Your Stripe account is not configured.",
      body: " You won't be able to accept payments until setup is complete.",
    };
  }
  return null;
});

const setupStartStep = computed(() => (isConnected.value ? 4 : 1));

const wizardTitle = computed(() => {
  if (wizardStep.value === 1) return "Welcome to Junior Bay! Let's connect your Stripe account.";
  if (wizardStep.value === 2) return "Authorize Junior Bay in Stripe";
  if (wizardStep.value === 3) return "Confirm your Stripe connection";
  if (wizardStep.value === 4) return "Complete Stripe onboarding";
  return "Verify your webhook endpoint";
});

const wizardNextLabel = computed(() => {
  if (wizardSaving.value || store.connectStarting) return "Opening Stripe...";
  if (wizardStep.value === 2) return "Continue with Stripe";
  if (wizardStep.value === wizardMaxStep) return "Done";
  return "Next ->";
});

function openWizard(step = 1) {
  wizardError.value = "";
  wizardStep.value = step;
  wizardOpen.value = true;
}

function closeWizard() {
  wizardOpen.value = false;
  wizardError.value = "";
}

function webhookUrl(mode) {
  const host = mode === "live" ? "https://prod.juniorbay.com" : "https://dev.juniorbay.com";
  return `${host}/webhook/${store.tenantId}`;
}

async function beginStripeOAuth() {
  wizardError.value = "";
  wizardSaving.value = true;
  try {
    await store.startConnect({ chain: "both", path: wizardIntent.value });
    if (store.connectError) wizardError.value = store.connectError;
  } finally {
    wizardSaving.value = false;
  }
}

async function refreshConnectStatus() {
  await store.load();
  await store.loadConnectCard();
}

async function verifyWebhook() {
  wizardError.value = "";
  await store.verify();
  if (store.error) wizardError.value = store.error;
}

async function nextWizardStep() {
  wizardError.value = "";
  if (wizardStep.value === wizardMaxStep) {
    closeWizard();
    return;
  }
  if (wizardStep.value === 2) {
    await beginStripeOAuth();
    return;
  }
  wizardStep.value += 1;
}

async function handleConnectReturn() {
  const params = new URLSearchParams(window.location.search);
  const result = params.get("stripe_connect");
  if (!result) return;

  await refreshConnectStatus();
  if (result === "connected") {
    wizardOpen.value = true;
    wizardStep.value = 3;
    store.message = "Stripe Connect account linked.";
    store.messageTone = "success";
  } else if (result === "error") {
    wizardOpen.value = true;
    wizardStep.value = 2;
    wizardError.value = params.get("message") || "Stripe Connect authorization failed.";
  }

  const cleanUrl = `${window.location.origin}${window.location.pathname}${window.location.hash || ""}`;
  window.history.replaceState({}, document.title, cleanUrl);
}

onMounted(async () => {
  store.resetForCurrentTenant();
  await store.load();
  await handleConnectReturn();
});
</script>
