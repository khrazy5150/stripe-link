<template>
  <UnderConstruction v-if="mode !== 'test' || locked" feature="Ad Campaigns"
    description="We’re building a place to manage your paid ad campaigns." :logo-url="logoUrl" />
  <div v-else class="page ads-page">
    <header class="page-header">
      <div>
        <h1>Ad Campaigns</h1>
        <p>Manage Google Search test campaigns and advertiser connections.</p>
      </div>
    </header>
    <nav class="ads-actions" aria-label="Ad Campaigns">
      <button type="button" :class="view === 'campaigns' ? 'primary-action' : 'secondary-action'" :aria-pressed="view === 'campaigns'" @click="view = 'campaigns'">Campaigns</button>
      <button v-if="!accountsLocked" type="button" :class="view === 'accounts' ? 'primary-action' : 'secondary-action'" :aria-pressed="view === 'accounts'" @click="view = 'accounts'">Google Ads accounts</button>
    </nav>
    <AdsPromoMode v-show="view === 'campaigns'" :accounts="accounts" @manage-accounts="view = 'accounts'" />
    <section v-if="!accountsLocked" v-show="view === 'accounts'" class="dashboard-card" aria-labelledby="accounts-heading">
      <header class="dashboard-card-header"><h2 id="accounts-heading">Google Ads test accounts</h2></header>
      <div class="dashboard-card-body">
        <p v-if="error" role="alert">{{ error }}</p>
        <p v-if="notice" role="status">{{ notice }}</p>

        <button v-if="!flow" class="primary-action" type="button" :disabled="busy" @click="start">
          Connect Google Ads
        </button>
        <div v-else class="ads-actions">
          <a :href="flow.authorization_url" target="_blank" rel="noopener noreferrer">Authorize with Google in a new tab</a>
          <button class="primary-action" type="button" :disabled="busy" @click="finish">Finish connection</button>
          <button class="secondary-action" type="button" :disabled="busy" @click="flow = null">Start over</button>
        </div>

        <ul v-if="activeConnections.length" class="ads-list">
          <li v-for="(connection, index) in activeConnections" :key="connection.connection_id">
            <strong>Google connection {{ index + 1 }}</strong>
            <div class="ads-actions">
              <button class="secondary-action" type="button" :disabled="busy" @click="discover(connection.connection_id)">
                Find test advertisers
              </button>
              <button class="secondary-action" type="button" :disabled="busy" @click="disconnect(connection.connection_id)">
                Disconnect
              </button>
            </div>
            <template v-if="candidateConnection === connection.connection_id">
              <p v-if="!candidates.length">No available test advertisers were found.</p>
              <ul v-else class="ads-list">
                <li v-for="candidate in candidates" :key="candidate.account_id">
                  {{ candidate.account_id }} · {{ candidate.currency }} · {{ candidate.time_zone }}
                  <button class="secondary-action" type="button" :disabled="busy" @click="select(connection.connection_id, candidate)">
                    Use account
                  </button>
                </li>
              </ul>
            </template>
          </li>
        </ul>

        <template v-if="accounts.length">
          <h3>Test advertisers assigned to Junior Bay</h3>
          <ul>
            <li v-for="account in accounts" :key="account.account_id">
              {{ account.account_id }} · {{ account.currency }} · {{ account.time_zone }}
              <span v-if="account.connected === false"> · Reconnect required</span>
            </li>
          </ul>
        </template>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import AdsPromoMode from "./AdsPromoMode.vue";
import UnderConstruction from "./UnderConstruction.vue";
import {
  attentionConfigured, disconnectGoogleAds, fetchAdAccounts, fetchGoogleAdsCandidates,
  fetchGoogleAdsConnections, finishGoogleAdsConnection, selectGoogleAdsAccount, startGoogleAdsConnection,
} from "../api/attention";

const props = defineProps({ mode: String, logoUrl: String });
const locked = ref(!attentionConfigured());
const busy = ref(false);
const view = ref("campaigns");
const accountsLocked = ref(false);
const error = ref("");
const notice = ref("");
const flow = ref(null);
const connections = ref([]);
const accounts = ref([]);
const candidates = ref([]);
const candidateConnection = ref("");
const activeConnections = computed(() => connections.value.filter((connection) => connection.status === "active"));

async function run(action) {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    await action();
  } catch (failure) {
    error.value = failure.message || "Google Ads is temporarily unavailable.";
  } finally {
    busy.value = false;
  }
}

async function refresh() {
  const [connectionResult, accountResult] = await Promise.all([fetchGoogleAdsConnections(), fetchAdAccounts()]);
  connections.value = connectionResult.connections;
  accounts.value = accountResult.accounts;
}

function start() {
  return run(async () => { flow.value = await startGoogleAdsConnection(); });
}

function finish() {
  return run(async () => {
    await finishGoogleAdsConnection(flow.value.connection_id, flow.value.completion_proof);
    flow.value = null;
    notice.value = "Google Ads connected. Find and select a test advertiser.";
    await refresh();
  });
}

function discover(connectionId) {
  return run(async () => {
    const result = await fetchGoogleAdsCandidates(connectionId);
    candidates.value = result.accounts;
    candidateConnection.value = connectionId;
  });
}

function select(connectionId, account) {
  return run(async () => {
    await selectGoogleAdsAccount(connectionId, account);
    notice.value = `Test advertiser ${account.account_id} selected.`;
    await refresh();
  });
}

function disconnect(connectionId) {
  return run(async () => {
    await disconnectGoogleAds(connectionId);
    if (candidateConnection.value === connectionId) candidateConnection.value = "";
    notice.value = "Google Ads access was disconnected in Junior Bay.";
    await refresh();
  });
}

onMounted(() => {
  if (props.mode !== "test" || locked.value) return;
  return run(async () => {
    try {
      await refresh();
    } catch (failure) {
      if (failure.code === "ads_not_entitled") accountsLocked.value = true;
      else {
        view.value = "accounts";
        throw failure;
      }
    }
  });
});
</script>

<style scoped>
.ads-page { display: grid; gap: 1.6rem; }
.ads-page .page-header { margin-bottom: 0; }
.ads-actions { display: flex; flex-wrap: wrap; align-items: center; gap: .75rem; }
.ads-list { display: grid; gap: .75rem; padding-inline-start: 1.25rem; }
</style>
