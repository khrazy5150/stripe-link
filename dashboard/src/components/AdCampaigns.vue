<template>
  <UnderConstruction v-if="mode !== 'test' || locked" feature="Ad Campaigns"
    :description="locked ? 'We’re building a place to manage your paid ad campaigns.'
      : 'Live campaigns open once Google approves production access. Switch to Test to try a campaign with a Google Ads test account.'"
    :logo-url="logoUrl" />
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
              <button class="secondary-action" type="button" :disabled="busy || Boolean(leaving)" @click="prepareDisconnect(connection.connection_id)">
                Disconnect
              </button>
            </div>
            <div v-if="leaving?.connectionId === connection.connection_id" class="ads-confirm" role="alertdialog" aria-labelledby="disconnect-heading">
              <h3 id="disconnect-heading">Disconnect this Google connection?</h3>
              <p>
                Junior Bay will no longer be able to read, start or pause campaigns in
                {{ leaving.accounts.length === 1 ? 'advertiser' : 'advertisers' }} {{ leaving.accounts.join(', ') || 'on this connection' }}.
                Disconnecting doesn't stop ads in Google. A campaign that is still running keeps spending until it is paused in Google Ads.
              </p>
              <template v-if="leaving.toPause.length">
                <p>Junior Bay will pause these first, wait for Google Ads to confirm, and then disconnect:</p>
                <ul class="ads-list">
                  <li v-for="item in leaving.toPause" :key="item.campaign_id">{{ describe(item) }}</li>
                </ul>
              </template>
              <p v-else>Your campaigns stay in Google Ads, paused.</p>
              <p v-if="leaving.preparing.length" class="ads-warning">
                {{ leaving.preparing.map(describe).join(', ') }} {{ leaving.preparing.length === 1 ? 'is' : 'are' }} still being created in Google Ads. Wait a minute, then try again.
              </p>
              <p v-if="leaving.progress" role="status">{{ leaving.progress }}</p>
              <div class="ads-actions">
                <button class="primary-action" type="button" :disabled="busy || leaving.preparing.length > 0" @click="confirmDisconnect">
                  {{ leaving.toPause.length ? `Pause ${leaving.toPause.length === 1 ? 'campaign' : `${leaving.toPause.length} campaigns`} and disconnect` : 'Disconnect' }}
                </button>
                <button class="secondary-action" type="button" :disabled="busy" @click="leaving = null">Cancel</button>
              </div>
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
  attentionConfigured, disconnectGoogleAds, fetchAdAccounts, fetchAdsCampaign, fetchAdsCampaigns, fetchGoogleAdsCandidates, queueAdsAction,
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

const leaving = ref(null);
const SERVING = new Set(["enabled", "launch_pending", "reconcile_required", "reconciling"]);
const SETTLE_CHECKS = 30;
const SETTLE_INTERVAL_MS = 3000;

function describe(item) {
  const name = item.configuration?.settings?.headlines?.[0] || "Campaign";
  return item.provider_campaign_id ? `${name} (Google campaign ${item.provider_campaign_id})` : name;
}

function settled(item) {
  return ["paused", "removed"].includes(item.state) && !item.pause_pending;
}

// Disconnecting removes Junior Bay's access, not the ads. Anything that can still serve, or is scheduled
// to start, is paused first while Junior Bay can still reach Google; the server refuses otherwise.
function prepareDisconnect(connectionId) {
  return run(async () => {
    await refresh();
    const accountIds = accounts.value.filter((account) => account.connection_id === connectionId).map((account) => account.account_id);
    const { campaigns } = await fetchAdsCampaigns();
    const mine = campaigns.filter((item) => accountIds.includes(item.account_id));
    const scheduled = (item) => item.start_scheduled && item.state === "paused" && !item.launch_requested_at;
    leaving.value = {
      connectionId,
      accounts: accountIds,
      toPause: mine.filter((item) => item.has_provider_campaign && (SERVING.has(item.state) || item.pause_pending || scheduled(item))),
      preparing: mine.filter((item) => item.state === "preparing"),
      progress: "",
    };
  });
}

function confirmDisconnect() {
  const plan = leaving.value;
  return run(async () => {
    for (const item of plan.toPause) {
      if (item.pause_pending || item.state === "reconciling") continue;
      await queueAdsAction(item.campaign_id, "pause", item.revision, crypto.randomUUID());
    }
    let pending = plan.toPause;
    for (let check = 0; pending.length && check < SETTLE_CHECKS; check += 1) {
      plan.progress = `Waiting for Google Ads to confirm ${pending.length === 1 ? "the pause" : `${pending.length} pauses`}…`;
      await new Promise((resolve) => setTimeout(resolve, SETTLE_INTERVAL_MS));
      const fresh = await Promise.all(pending.map((item) => fetchAdsCampaign(item.campaign_id)));
      pending = fresh.map((result) => result.campaign).filter((item) => !settled(item));
    }
    if (pending.length) {
      plan.progress = "";
      throw new Error(`Google Ads hasn't confirmed the pause for ${pending.map(describe).join(", ")}, so Junior Bay is still connected and keeps trying. `
        + "Those ads can keep running until they're paused. Pause them in Google Ads (ads.google.com), or try Disconnect again in a few minutes.");
    }
    try {
      await disconnectGoogleAds(plan.connectionId);
    } catch (failure) {
      if (failure.code === "ads_campaigns_running") throw new Error(failure.message);
      throw failure;
    }
    if (candidateConnection.value === plan.connectionId) candidateConnection.value = "";
    leaving.value = null;
    notice.value = plan.toPause.length
      ? `Google Ads access was disconnected. Paused first: ${plan.toPause.map(describe).join(", ")}.`
      : "Google Ads access was disconnected. Your campaigns stay in Google Ads, paused.";
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
.ads-confirm { display: grid; gap: .75rem; margin-top: .75rem; padding: 1rem; border: 1px solid var(--border, #d0d5dd); border-radius: 8px; }
.ads-confirm h3 { margin: 0; font-size: 1rem; }
.ads-warning { color: var(--danger, #b91c1c); }
</style>
