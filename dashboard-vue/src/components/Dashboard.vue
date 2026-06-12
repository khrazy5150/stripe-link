<template>
  <section class="page">
    <div v-if="setupWarning" class="stripe-setup-banner">
      <div>
        <strong>{{ setupWarning.title }}</strong>
        <span>{{ setupWarning.body }}</span>
      </div>
      <button type="button" class="setup-action" @click="openWizard">
        Complete Setup
      </button>
    </div>

    <header class="page-header">
      <div>
        <h1>Dashboard</h1>
        <p>Overview of your business metrics</p>
      </div>
      <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load">
        {{ store.loading ? "Loading..." : "Refresh" }}
      </button>
    </header>

    <div class="stats-grid">
      <article class="stats-card">
        <div class="stats-icon primary" aria-hidden="true">
          <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2" />
          </svg>
        </div>
        <div class="stats-content">
          <span class="stats-label">Total Orders</span>
          <strong class="stats-value">{{ store.loading && !store.loaded ? "--" : store.stats.orders }}</strong>
          <span class="stats-meta">Lifetime &bull; {{ environmentLabel }}</span>
        </div>
      </article>

      <article class="stats-card">
        <div class="stats-icon success" aria-hidden="true">
          <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z" />
          </svg>
        </div>
        <div class="stats-content">
          <span class="stats-label">Net Revenue</span>
          <strong class="stats-value">{{ store.loading && !store.loaded ? "--" : store.stats.revenue }}</strong>
          <span class="stats-meta">{{ store.stats.revenueMeta }}</span>
        </div>
      </article>

      <article class="stats-card">
        <div class="stats-icon warning" aria-hidden="true">
          <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 0 0-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 0 1 5.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 0 1 9.288 0M15 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0zm6 3a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM7 10a2 2 0 1 1-4 0 2 2 0 0 1 4 0z" />
          </svg>
        </div>
        <div class="stats-content">
          <span class="stats-label">Customers</span>
          <strong class="stats-value">{{ store.loading && !store.loaded ? "--" : store.stats.customers }}</strong>
          <span class="stats-meta">Lifetime &bull; {{ environmentLabel }}</span>
        </div>
      </article>

      <article class="stats-card">
        <div class="stats-icon danger" aria-hidden="true">
          <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m20 7-8-4-8 4m16 0-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
          </svg>
        </div>
        <div class="stats-content">
          <span class="stats-label">Products</span>
          <strong class="stats-value">{{ store.loading && !store.loaded ? "--" : store.stats.products }}</strong>
          <span class="stats-meta">Lifetime &bull; {{ environmentLabel }}</span>
        </div>
      </article>
    </div>

    <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>

    <div class="dashboard-grid">
      <section class="dashboard-card recent-orders-card">
        <header class="dashboard-card-header">
          <h2>Recent Orders</h2>
          <button type="button" class="secondary-action">View All</button>
        </header>
        <div class="dashboard-table">
          <div class="dashboard-table-row table-head">
            <span>Date</span>
            <span>Customer</span>
            <span>Amount</span>
            <span>Product</span>
          </div>
          <div v-if="store.loading && !store.loaded" class="dashboard-table-row muted-row">
            <span>Loading</span><span>Backend</span><span>--</span><span>Fetching invoices</span>
          </div>
          <div v-else-if="!store.recentOrders.length" class="dashboard-table-row muted-row">
            <span>No invoices</span><span>Backend returned 0</span><span>--</span><span>Create invoices to populate this table</span>
          </div>
          <div v-for="order in store.recentOrders" :key="`${order.date}-${order.product}-${order.amount}`" class="dashboard-table-row">
            <span>{{ order.date }}</span>
            <span>{{ order.customer }}</span>
            <span>{{ order.amount }}</span>
            <span>{{ order.product }}</span>
          </div>
        </div>
      </section>

      <section class="dashboard-card activity-card">
        <header class="dashboard-card-header">
          <h2>Recent Activity</h2>
          <span class="activity-notification-dot" aria-hidden="true"></span>
        </header>
        <div class="activity-list">
          <article v-if="store.loading && !store.loaded" class="activity-item">
            <span class="activity-dot" aria-hidden="true"></span>
            <div><strong>Loading activity...</strong><span>Fetching notifications</span></div>
          </article>
          <article v-else-if="!store.recentActivity.length" class="activity-item">
            <span class="activity-dot" aria-hidden="true"></span>
            <div><strong>No recent activity</strong><span>Notifications endpoint returned 0 items</span></div>
          </article>
          <article v-for="activity in store.recentActivity" :key="`${activity.title}-${activity.time}`" class="activity-item">
            <span class="activity-dot" aria-hidden="true"></span>
            <div><strong>{{ activity.title }}</strong><span>{{ activity.time }}</span></div>
          </article>
        </div>
      </section>
    </div>

    <div v-if="wizardOpen" class="modal-backdrop" @click.self="closeWizard">
      <section class="modal-card stripe-onboarding-modal" role="dialog" aria-modal="true" aria-labelledby="stripe-onboarding-title">
        <header class="modal-card-header">
          <div>
            <h2 id="stripe-onboarding-title">{{ wizardTitle }}</h2>
            <p>Step {{ wizardStep }} of 3</p>
            <div class="onboarding-progress" aria-hidden="true">
              <span
                v-for="step in 3"
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
              Continue to Stripe to authorize Junior Bay for the {{ environmentLabel.toLowerCase() }} environment.
              No API keys need to be copied or pasted.
            </p>
            <div class="keys-status-banner info">
              Stripe will send Junior Bay a secure OAuth token after approval. The token is encrypted before it is stored.
            </div>
            <button
              type="button"
              class="primary-action onboarding-link"
              :disabled="stripeKeys.connectStarting"
              @click="beginStripeOAuth"
            >
              {{ stripeKeys.connectStarting ? "Opening Stripe..." : "Continue with Stripe" }}
            </button>
          </div>

          <div v-else-if="wizardStep === 2" class="onboarding-step">
            <p>Junior Bay has refreshed the Stripe connection status for {{ environmentLabel.toLowerCase() }}.</p>
            <div v-if="isConnected" class="keys-status-banner success">
              Stripe account connected{{ connectAccountId ? `: ${connectAccountId}` : "" }}.
            </div>
            <div v-else class="keys-status-banner warning">
              Waiting for Stripe authorization to complete.
            </div>
            <button type="button" class="secondary-action" :disabled="stripeKeys.connectLoading" @click="refreshConnectStatus()">
              {{ stripeKeys.connectLoading ? "Refreshing..." : "Refresh Status" }}
            </button>
            <button v-if="isConnected" type="button" class="primary-action" @click="wizardStep = 3">
              Next
            </button>
          </div>

          <div v-else class="onboarding-step">
            <p>
              Do you want to configure the {{ otherEnvironmentLabel }} environment now?
            </p>
            <div class="onboarding-actions-row">
              <button type="button" class="primary-action" @click="configureOtherEnvironment">
                Configure {{ otherEnvironmentLabel }}
              </button>
              <button type="button" class="secondary-action" @click="closeWizard">
                Not now
              </button>
            </div>
          </div>

          <div v-if="wizardError" class="keys-status-banner error">{{ wizardError }}</div>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useDashboardStore } from "../stores/dashboard";
import { useStripeKeysStore } from "../stores/stripeKeys";

const props = defineProps({
  environmentLabel: {
    type: String,
    default: "Test",
  },
  activeEnvironment: {
    type: String,
    default: "test",
  },
});

const emit = defineEmits(["switch-environment"]);
const store = useDashboardStore();
const stripeKeys = useStripeKeysStore();
const wizardOpen = ref(false);
const wizardStep = ref(1);
const wizardError = ref("");

const connectDocument = computed(() => stripeKeys.connectCard?.stripe_connect || {});
const connectStatus = computed(() => String(connectDocument.value.connect_status || "not_connected"));
const connectAccountId = computed(() => (
  connectDocument.value.connect_account_id
  || connectDocument.value.stripe_account_id
  || connectDocument.value.account_id
  || ""
));
const isConnected = computed(() => connectStatus.value === "connected" || Boolean(connectAccountId.value));
const isRestricted = computed(() => connectStatus.value === "restricted");
const otherEnvironment = computed(() => (props.activeEnvironment === "live" ? "test" : "live"));
const otherEnvironmentLabel = computed(() => (otherEnvironment.value === "live" ? "Live" : "Test"));

const setupWarning = computed(() => {
  if (isRestricted.value) {
    return {
      title: `Your ${props.environmentLabel.toLowerCase()} Stripe account is restricted.`,
      body: " Resolve the Stripe requirement before accepting payments.",
    };
  }
  if (!isConnected.value) {
    return {
      title: "Your Stripe account is not connected.",
      body: " You won't be able to accept payments until setup is complete.",
    };
  }
  return null;
});

const wizardTitle = computed(() => {
  if (wizardStep.value === 1) return `Authorize ${props.environmentLabel} Stripe`;
  if (wizardStep.value === 2) return "Confirm your Stripe connection";
  return `Configure ${otherEnvironmentLabel.value} environment`;
});

function openWizard() {
  wizardError.value = "";
  wizardStep.value = isConnected.value ? 3 : 1;
  wizardOpen.value = true;
}

function closeWizard() {
  wizardOpen.value = false;
  wizardError.value = "";
}

async function refreshConnectStatus(mode = props.activeEnvironment) {
  stripeKeys.verifyMode = mode === "live" ? "live" : "test";
  await stripeKeys.loadConnectCard();
}

async function beginStripeOAuth() {
  wizardError.value = "";
  stripeKeys.verifyMode = props.activeEnvironment === "live" ? "live" : "test";
  await stripeKeys.startConnect({ path: "existing" });
  if (stripeKeys.connectError) wizardError.value = stripeKeys.connectError;
}

function configureOtherEnvironment() {
  closeWizard();
  emit("switch-environment", otherEnvironment.value);
  window.setTimeout(() => {
    wizardStep.value = 1;
    wizardOpen.value = true;
  }, 0);
}

async function handleConnectReturn() {
  const params = new URLSearchParams(window.location.search);
  const result = params.get("stripe_connect");
  if (!result) return;

  const returnedMode = params.get("mode") === "live" ? "live" : params.get("mode") === "test" ? "test" : props.activeEnvironment;
  if (returnedMode !== props.activeEnvironment) emit("switch-environment", returnedMode);
  await refreshConnectStatus(returnedMode);

  wizardOpen.value = true;
  if (result === "connected") {
    wizardStep.value = 2;
    stripeKeys.message = "Stripe Connect account linked.";
    stripeKeys.messageTone = "success";
  } else {
    wizardStep.value = 1;
    wizardError.value = params.get("message") || "Stripe Connect authorization failed.";
  }

  const cleanUrl = `${window.location.origin}${window.location.pathname}${window.location.hash || ""}`;
  window.history.replaceState({}, document.title, cleanUrl);
}

async function loadDashboardConnectState() {
  stripeKeys.resetForCurrentTenant();
  stripeKeys.verifyMode = props.activeEnvironment === "live" ? "live" : "test";
  await stripeKeys.loadConnectCard();
}

onMounted(() => {
  if (!store.loaded) store.load();
  loadDashboardConnectState().then(handleConnectReturn).catch(() => {});
});

watch(
  () => props.activeEnvironment,
  () => {
    loadDashboardConnectState().catch(() => {});
  },
);
</script>
