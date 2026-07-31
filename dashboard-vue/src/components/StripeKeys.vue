<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Payments</h1>
        <p>Connect Stripe, manage your keys, and choose which payment methods buyers can use.</p>
      </div>
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
            <input
              v-model.trim="store.tenantId"
              required
              autocomplete="off"
              readonly
              title="Click to copy Tenant ID"
              @click="copyTenantId"
            />
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
            class="secondary-action danger-action"
            :disabled="store.connectStarting"
            @click="store.disconnectConnect"
          >
            {{ store.connectStarting ? "Disconnecting..." : "Disconnect from Stripe" }}
          </button>
          <button
            v-else
            type="button"
            class="primary-action"
            :disabled="store.connectLoading || store.connectStarting"
            @click="store.startConnect({ path: 'existing' })"
          >
            {{ store.connectStarting ? "Starting..." : "Connect to Stripe" }}
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

    <section v-if="isConnected" class="dashboard-card bnpl-card">
      <header class="dashboard-card-header">
        <div>
          <h2>Installments — Buy Now, Pay Later</h2>
          <p>Let buyers pay over time. You're paid in full upfront; the usual platform fee still applies.</p>
        </div>
        <span class="tier-pill">{{ modeLabel }}</span>
      </header>
      <div class="connect-card-body">
        <div v-if="pm.loading" class="connect-muted">Loading installment options…</div>
        <ul v-else class="bnpl-list">
          <li v-for="m in pm.methods" :key="m.method" class="bnpl-row">
            <div class="bnpl-row-head">
              <div class="bnpl-row-name">
                <span class="bnpl-label">{{ m.label }}</span>
                <span v-if="m.enabled && m.capability_status !== 'unrequested'" :class="['bnpl-status', m.capability_status]">
                  {{ bnplStatusLabel(m.capability_status) }}
                </span>
              </div>
              <label class="bnpl-toggle" :class="{ disabled: !m.country_eligible }">
                <input
                  type="checkbox"
                  :checked="m.enabled"
                  :disabled="!m.country_eligible || pm.savingMethod === m.method"
                  @change="pm.toggle(m.method, $event.target.checked)"
                />
                <span class="bnpl-switch" aria-hidden="true"></span>
              </label>
            </div>
            <p v-if="!m.country_eligible" class="bnpl-note">
              Not available in your country
              <button type="button" class="bnpl-info" :aria-label="`Where ${m.label} is available`" @click="toggleInfo(m.method)">ⓘ</button>
            </p>
            <p v-if="m.enabled && m.country_eligible && m.capability_status !== 'active'" class="bnpl-note">
              <template v-if="m.capability_status === 'pending'">Stripe is reviewing your account for {{ m.label }} — it appears at checkout once approved.</template>
              <template v-else>{{ m.label }} isn't active on your Stripe account yet. Enable it in your Stripe dashboard and it will appear at checkout.</template>
            </p>
            <p v-if="openInfo === m.method" class="bnpl-countries">
              Available when your Stripe account is based in: {{ m.countries.join(", ") }}
            </p>
          </li>
        </ul>
        <div v-if="pm.error" class="keys-status-banner error">{{ pm.error }}</div>
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
import { computed, onMounted, ref, watch } from "vue";
import StripeKeyPanel from "./StripeKeyPanel.vue";
import { useStripeKeysStore } from "../stores/stripeKeys";
import { usePaymentMethodsStore } from "../stores/paymentMethods";

const store = useStripeKeysStore();
const pm = usePaymentMethodsStore();
const openInfo = ref("");

function toggleInfo(method) {
  openInfo.value = openInfo.value === method ? "" : method;
}

const BNPL_STATUS_LABELS = { active: "Active", pending: "Pending review", inactive: "Inactive" };
function bnplStatusLabel(status) {
  return BNPL_STATUS_LABELS[status] || status;
}
const wizardMaxStep = 4;
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
const wizardTitle = computed(() => {
  if (wizardStep.value === 1) return "Welcome to Junior Bay! Let's connect your Stripe account.";
  if (wizardStep.value === 2) return "Authorize Junior Bay in Stripe";
  if (wizardStep.value === 3) return "Confirm your Stripe connection";
  return "Complete Stripe onboarding";
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

async function beginStripeOAuth() {
  wizardError.value = "";
  wizardSaving.value = true;
  try {
    await store.startConnect({ path: wizardIntent.value });
    if (store.connectError) wizardError.value = store.connectError;
  } finally {
    wizardSaving.value = false;
  }
}

async function refreshConnectStatus() {
  await store.load();
  await store.loadConnectCard();
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

async function copyTenantId() {
  if (!store.tenantId || !navigator.clipboard) return;
  try {
    await navigator.clipboard.writeText(store.tenantId);
    store.message = "Tenant ID copied to clipboard.";
    store.messageTone = "success";
  } catch {
    store.message = "Tenant ID selected. Copy it from the field.";
    store.messageTone = "info";
  }
}

async function handleConnectReturn() {
  const params = new URLSearchParams(window.location.search);
  const result = params.get("stripe_connect");
  if (!result) return;

  const returnedMode = params.get("mode") === "live" ? "live" : params.get("mode") === "test" ? "test" : "";
  if (returnedMode) store.verifyMode = returnedMode;
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

// BNPL toggles are per Stripe mode (test/live) — reload them whenever the viewed mode changes, and once connected.
watch(() => store.verifyMode, (mode) => {
  if (isConnected.value) pm.load(mode);
});
watch(isConnected, (connected) => {
  if (connected) pm.load(store.verifyMode);
});

onMounted(async () => {
  store.resetForCurrentTenant();
  pm.reset();
  await store.load();
  await handleConnectReturn();
  if (isConnected.value) pm.load(store.verifyMode);
});
</script>

<style scoped>
.bnpl-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 1rem; }
.bnpl-row { border: 1px solid var(--line); border-radius: 10px; padding: 1rem 1.2rem; }
.bnpl-row-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.bnpl-row-name { display: flex; align-items: center; gap: 0.6rem; }
.bnpl-label { font-weight: 700; font-size: 1.5rem; }
.bnpl-status { font-size: 1.1rem; font-weight: 600; padding: 0.1rem 0.5rem; border-radius: 0.4rem; text-transform: uppercase; letter-spacing: 0.03em; }
.bnpl-status.active { background: #dcfce7; color: #166534; }
.bnpl-status.pending { background: #fef9c3; color: #854d0e; }
.bnpl-status.inactive { background: var(--line); color: var(--muted); }
.bnpl-note { margin: 0.6rem 0 0; color: var(--muted); font-size: 1.3rem; }
.bnpl-countries { margin: 0.5rem 0 0; color: var(--muted); font-size: 1.25rem; line-height: 1.5; }
.bnpl-info { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 1.3rem; padding: 0 0.2rem; }
.bnpl-info:hover { color: var(--text); }

/* Toggle switch */
.bnpl-toggle { position: relative; display: inline-flex; width: 4.4rem; height: 2.4rem; flex: none; }
.bnpl-toggle.disabled { opacity: 0.45; }
.bnpl-toggle input { position: absolute; inset: 0; opacity: 0; margin: 0; cursor: pointer; }
.bnpl-toggle input:disabled { cursor: not-allowed; }
.bnpl-switch { position: absolute; inset: 0; border-radius: 999px; background: var(--line); transition: background 0.15s ease; }
.bnpl-switch::after { content: ""; position: absolute; top: 0.3rem; left: 0.3rem; width: 1.8rem; height: 1.8rem; border-radius: 50%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.3); transition: transform 0.15s ease; }
.bnpl-toggle input:checked + .bnpl-switch { background: var(--brand, #4f46e5); }
.bnpl-toggle input:checked + .bnpl-switch::after { transform: translateX(2rem); }
</style>
