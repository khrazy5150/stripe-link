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
          <svg class="icon" fill="currentColor" viewBox="0 0 24 24">
            <path fill-rule="evenodd" clip-rule="evenodd" d="M7.502 6h7.128A3.375 3.375 0 0 1 18 9.375v9.375a3 3 0 0 0 3-3V6.108c0-1.505-1.125-2.811-2.664-2.94a48.972 48.972 0 0 0-.673-.05A3 3 0 0 0 15 1.5h-1.5a3 3 0 0 0-2.663 1.618c-.225.015-.45.032-.673.05C8.662 3.295 7.554 4.542 7.502 6ZM13.5 3A1.5 1.5 0 0 0 12 4.5h4.5A1.5 1.5 0 0 0 15 3h-1.5Z" />
            <path fill-rule="evenodd" clip-rule="evenodd" d="M3 9.375C3 8.339 3.84 7.5 4.875 7.5h9.75c1.036 0 1.875.84 1.875 1.875v11.25c0 1.035-.84 1.875-1.875 1.875h-9.75A1.875 1.875 0 0 1 3 20.625V9.375ZM6 12a.75.75 0 0 1 .75-.75h.008a.75.75 0 0 1 .75.75v.008a.75.75 0 0 1-.75.75H6.75a.75.75 0 0 1-.75-.75V12Zm2.25 0a.75.75 0 0 1 .75-.75h3.75a.75.75 0 0 1 0 1.5H9a.75.75 0 0 1-.75-.75ZM6 15a.75.75 0 0 1 .75-.75h.008a.75.75 0 0 1 .75.75v.008a.75.75 0 0 1-.75.75H6.75a.75.75 0 0 1-.75-.75V15Zm2.25 0a.75.75 0 0 1 .75-.75h3.75a.75.75 0 0 1 0 1.5H9a.75.75 0 0 1-.75-.75ZM6 18a.75.75 0 0 1 .75-.75h.008a.75.75 0 0 1 .75.75v.008a.75.75 0 0 1-.75.75H6.75a.75.75 0 0 1-.75-.75V18Zm2.25 0a.75.75 0 0 1 .75-.75h3.75a.75.75 0 0 1 0 1.5H9a.75.75 0 0 1-.75-.75Z" />
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
          <svg class="icon" fill="currentColor" viewBox="0 0 24 24">
            <path fill-rule="evenodd" clip-rule="evenodd" d="M10.464 8.746c.227-.18.497-.311.786-.394v2.795a2.252 2.252 0 0 1-.786-.393c-.394-.313-.546-.681-.546-1.004 0-.323.152-.691.546-1.004ZM12.75 15.662v-2.824c.347.085.664.228.921.421.427.32.579.686.579.991 0 .305-.152.671-.579.991a2.534 2.534 0 0 1-.921.42Z" />
            <path fill-rule="evenodd" clip-rule="evenodd" d="M12 2.25c-5.385 0-9.75 4.365-9.75 9.75s4.365 9.75 9.75 9.75 9.75-4.365 9.75-9.75S17.385 2.25 12 2.25ZM12.75 6a.75.75 0 0 0-1.5 0v.816a3.836 3.836 0 0 0-1.72.756c-.712.566-1.112 1.35-1.112 2.178 0 .829.4 1.612 1.113 2.178.502.4 1.102.647 1.719.756v2.978a2.536 2.536 0 0 1-.921-.421l-.879-.66a.75.75 0 0 0-.9 1.2l.879.66c.533.4 1.169.645 1.821.75V18a.75.75 0 0 0 1.5 0v-.81a4.124 4.124 0 0 0 1.821-.749c.745-.559 1.179-1.344 1.179-2.191 0-.847-.434-1.632-1.179-2.191a4.122 4.122 0 0 0-1.821-.75V8.354c.29.082.559.213.786.393l.415.33a.75.75 0 0 0 .933-1.175l-.415-.33a3.836 3.836 0 0 0-1.719-.755V6Z" />
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
          <svg class="icon" fill="currentColor" viewBox="0 0 24 24">
            <path d="M4.5 6.375a4.125 4.125 0 1 1 8.25 0 4.125 4.125 0 0 1-8.25 0ZM14.25 8.625a3.375 3.375 0 1 1 6.75 0 3.375 3.375 0 0 1-6.75 0ZM1.5 19.125a7.125 7.125 0 0 1 14.25 0v.003l-.001.119a.75.75 0 0 1-.363.63 13.067 13.067 0 0 1-6.761 1.873c-2.472 0-4.786-.684-6.76-1.873a.75.75 0 0 1-.364-.63l-.001-.122ZM17.25 19.128l-.001.144a2.25 2.25 0 0 1-.233.96 10.088 10.088 0 0 0 5.06-1.01.75.75 0 0 0 .42-.643 4.875 4.875 0 0 0-6.957-4.611 8.586 8.586 0 0 1 1.71 5.157v.003Z" />
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
          <svg class="icon" fill="currentColor" viewBox="0 0 24 24">
            <path fill-rule="evenodd" clip-rule="evenodd" d="M12.378 1.602a.75.75 0 0 0-.756 0L3 6.632l9 5.25 9-5.25-8.622-5.03ZM21.75 7.93l-9 5.25v9l8.628-5.032a.75.75 0 0 0 .372-.648V7.93ZM11.25 22.18v-9l-9-5.25v8.57a.75.75 0 0 0 .372.648l8.628 5.033Z" />
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
  if (!stripeKeys.connectLoaded || stripeKeys.connectLoading || stripeKeys.connectError) return null;
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
