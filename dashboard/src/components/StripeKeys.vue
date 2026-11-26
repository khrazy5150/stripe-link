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
            <p>Save your test and live keys in one request.</p>
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

    <section v-if="offerOtherMode" class="dashboard-card sandbox-card">
      <header class="dashboard-card-header">
        <div>
          <h2>Set up Stripe for {{ otherModeLabel }} mode</h2>
          <p v-if="otherMode === 'test'">Rehearse checkout, upsells, and funnels with Stripe test mode. No real charges, no real cards.</p>
          <p v-else>Connect Stripe in live mode to take real payments from your customers.</p>
        </div>
      </header>
      <div class="connect-card-body">
        <p class="connect-copy">
          Each mode has its own Stripe connection. You're in {{ modeLabel }} mode now; this switches you to
          {{ otherModeLabel }} mode and opens Stripe. Use the <strong>Test / Live</strong> switch at the top of the
          dashboard to move between modes any time.
        </p>
        <div class="connect-actions">
          <button type="button" class="primary-action" :disabled="store.connectStarting" @click="setUpOtherMode">
            {{ store.connectStarting ? "Opening Stripe..." : `Set up ${otherModeLabel} mode` }}
          </button>
        </div>
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
              <!-- Requesting/activating a capability is a live-only Stripe operation, so a not-yet-active method
                   can't be turned on in test mode at all (Klarna/Afterpay are the exception — active by default). -->
              <template v-if="pm.mode !== 'live'">{{ m.label }} can only be enabled in live mode.</template>
              <template v-else-if="m.onboarding_url">
                {{ m.label }} needs one more step to finish enabling.
                <a :href="m.onboarding_url" target="_blank" rel="noopener" class="bnpl-finish">Finish setup in Stripe →</a>
              </template>
              <template v-else-if="m.capability_status === 'pending'">Stripe is reviewing your account for {{ m.label }} — it appears at checkout once approved.</template>
              <template v-else>{{ m.label }} isn't active on your account yet — it appears at checkout once Stripe approves it.</template>
            </p>
            <p v-if="openInfo === m.method" class="bnpl-countries">
              Available when your Stripe account is based in: {{ m.countries.join(", ") }}
            </p>
          </li>
        </ul>
        <div v-if="pm.error" class="keys-status-banner error">{{ pm.error }}</div>
      </div>
    </section>

    <!-- SALES TAX. Beside the installment toggles because both answer "what happens to money at
         checkout". Every sentence comes from the server (domain/tax_status.describe) -- wording about a
         tenant's tax carries legal risk and must not be assembled from flags in a template.

         The switch is only rendered when the server says `may_enable`, which means Stripe already
         reports the account active AND a default tax behaviour is set. We never offer a control whose
         effect depends on a tax claim Stripe has not already accepted. -->
    <section v-if="isConnected && pm.tax" class="dashboard-card tax-card">
      <header class="dashboard-card-header">
        <div>
          <h2>Sales tax</h2>
          <p>Stripe works out what to charge and where. We only ask it to.</p>
        </div>
        <span :class="['tax-state', pm.tax.state]">{{ pm.tax.label }}</span>
      </header>
      <div class="connect-card-body">
        <p class="tax-headline">{{ pm.tax.headline }}</p>
        <p v-if="pm.tax.detail" class="tax-detail">{{ pm.tax.detail }}</p>

        <label v-if="pm.tax.may_enable" class="tax-switch-row">
          <input
            type="checkbox"
            :checked="pm.tax.enabled"
            :disabled="pm.savingTax"
            @change="pm.setTax($event.target.checked)"
          />
          <span class="bnpl-switch" aria-hidden="true"></span>
          <span class="tax-switch-label">Add sales tax at checkout</span>
        </label>

        <!-- The only action we can honestly ask for. The tenant does registrations in their own Stripe
             Dashboard; we never create one and never imply they have. -->
        <!-- ACCOUNT-SCOPED, from the server. The bare /settings/tax URL resolves to whatever account the
             viewer's session is on, which for a platform owner is not the connected account this panel
             just reported on. -->
        <a v-if="pm.tax.settings_url" class="tax-link" :href="pm.tax.settings_url" target="_blank" rel="noopener">
          {{ pm.tax.may_enable ? "Your Stripe Tax settings" : "Set up Stripe Tax" }} &#8599;
        </a>
      </div>
    </section>

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

const emit = defineEmits(["switch-environment"]);
const store = useStripeKeysStore();
const pm = usePaymentMethodsStore();
const openInfo = ref("");
// Two-way: offer whichever mode has no Stripe yet, starting from the mode the tenant is in. Switching mode
// remounts this screen (App keys it on the mode), so the connect intro opens after the remount, as the
// Dashboard wizard does for the same step.
const otherMode = computed(() => (store.verifyMode === "live" ? "test" : "live"));
const otherModeLabel = computed(() => (otherMode.value === "live" ? "Live" : "Test"));
const offerOtherMode = computed(() => store.loaded && !store.modeConfigured(otherMode.value));

function setUpOtherMode() {
  const target = otherMode.value;
  emit("switch-environment", target);
  window.setTimeout(() => {
    store.verifyMode = target;
    store.startConnect({ path: "existing" });
  }, 0);
}

function toggleInfo(method) {
  openInfo.value = openInfo.value === method ? "" : method;
}

const BNPL_STATUS_LABELS = { active: "Active", pending: "Pending review", inactive: "Inactive" };
function bnplStatusLabel(status) {
  return BNPL_STATUS_LABELS[status] || status;
}

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
  if (isConnected.value) pm.load(store.verifyMode);
});
</script>

<style scoped>
.tax-state { font-size: 1.1rem; font-weight: 600; padding: 0.2rem 0.7rem; border-radius: 0.4rem;
  text-transform: uppercase; letter-spacing: 0.03em; border: 1px solid var(--line); }
.tax-state.active { color: var(--money-in, #0a7f5b); border-color: currentColor; }
.tax-state.pending { color: var(--warn, #9a6b00); border-color: currentColor; }
.tax-headline { margin: 0 0 0.4rem; font-weight: 600; font-size: 1.5rem; }
.tax-detail { margin: 0; color: var(--muted); font-size: 1.3rem; }
.tax-switch-row { display: flex; align-items: center; gap: 0.8rem; margin: 1.4rem 0 0; cursor: pointer; }
.tax-switch-row input { position: absolute; opacity: 0; width: 0; height: 0; }
.tax-switch-label { font-weight: 600; }
.tax-link { display: inline-block; margin-top: 1.2rem; font-weight: 600; }
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
.bnpl-finish { font-weight: 700; color: var(--accent, #635bff); text-decoration: none; white-space: nowrap; }
.bnpl-finish:hover { text-decoration: underline; }
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
