<template>
  <section class="dashboard-card" aria-labelledby="promo-heading">
    <header class="dashboard-card-header">
      <div>
        <h2 id="promo-heading">Search campaigns</h2>
        <p>Build and manage Google Search campaigns in Test mode. Test campaigns can’t serve ads, and Junior Bay management fees are disabled.</p>
      </div>
      <button v-if="!form && !campaign && canCreate" class="primary-action" type="button" @click="openForm()">
        New test campaign
      </button>
    </header>
    <div class="dashboard-card-body promo-body">
      <p v-if="error" class="promo-error" role="alert">{{ error }}</p>
      <p v-if="notice" role="status">{{ notice }}</p>
      <p v-if="loading">Loading campaigns…</p>

      <template v-else-if="form">
        <h3>{{ campaign ? 'Edit campaign draft' : 'Set up a campaign' }}</h3>
        <p v-if="!destinations.length">Publish a landing page linked to an offer to start a campaign.</p>
        <form v-else class="promo-body" @submit.prevent="save">
          <fieldset :disabled="busy" class="promo-fields">
            <label class="offer-field">
              <span>Test advertiser</span>
              <select v-model="form.account_id" required :disabled="Boolean(campaign)" @change="resetStartDate">
                <option v-for="account in advertisers" :key="account.account_id" :value="account.account_id">
                  {{ account.account_id }} · {{ account.time_zone }}
                </option>
              </select>
            </label>
            <label class="offer-field">
              <span>Published landing page</span>
              <select v-model="form.page_id" required>
                <option disabled value="">Choose a page</option>
                <option v-for="page in destinations" :key="page.pageId" :value="page.pageId">
                  {{ page.name }} · {{ page.offerName }}
                </option>
              </select>
            </label>
            <label class="offer-field">
              <span>Goal</span>
              <select v-model="form.objective">
                <option v-for="(label, key) in objectives" :key="key" :value="key">{{ label }}</option>
              </select>
            </label>
            <label class="offer-field">
              <span>Average daily budget (USD)</span>
              <input v-model.trim="form.budget" required inputmode="decimal">
              <small>Maximum for your Ads plan is {{ formatUsd(budgetCap) }}.</small>
            </label>
            <label class="offer-field">
              <span>Experiment start date</span>
              <input v-model="form.start_date" type="date" :min="accountToday" :max="addCalendarDays(accountToday, 30)" required>
              <small>Dates use the advertiser’s time zone, {{ accountZone }}.</small>
            </label>
            <label class="offer-field">
              <span>Experiment duration</span>
              <select v-model.number="days">
                <option v-for="option in ESTIMATE_DAYS" :key="option" :value="option">{{ option }} days</option>
              </select>
            </label>
            <p v-if="form.start_date" class="promo-full">
              Planned last day is {{ addCalendarDays(form.start_date, days - 1) }}.
              Junior Bay starts it at midnight on the start date and requests a stop at midnight after the last day.
              Google also ends it on its own after the last day.
            </p>
            <div class="offer-field promo-full">
              <span id="promo-places-label">Where ads show</span>
              <ul class="promo-chips" aria-labelledby="promo-places-label">
                <li v-for="(place, index) in form.locations" :key="place.id" class="promo-chip">
                  {{ place.name }}
                  <button type="button" class="promo-chip-remove" :aria-label="`Remove ${place.name}`" @click="form.locations.splice(index, 1)">×</button>
                </li>
                <li v-if="!form.locations.length">Choose at least one place.</li>
              </ul>
              <div class="promo-place-search">
                <input v-model.trim="placeQuery" type="search" aria-label="Search for a place" placeholder="City, county, state or country" @keydown.enter.prevent="searchPlaces">
                <button class="secondary-action" type="button" :disabled="!placeQuery || !form.account_id || placeBusy" @click="searchPlaces">Search</button>
              </div>
              <ul v-if="placeResults.length" class="promo-place-results">
                <li v-for="place in placeResults" :key="place.id">
                  <button type="button" class="secondary-action" :disabled="form.locations.some((item) => item.id === place.id)" @click="addPlace(place)">
                    Add {{ place.name }} · {{ place.type }}
                  </button>
                </li>
              </ul>
              <small>Ads show to people who are in, or regularly in, these places. Not to people elsewhere who only search about them.</small>
            </div>
            <template v-if="campaign">
              <label v-for="field in creativeFields" :key="field.key" class="offer-field promo-full">
                <span>{{ field.label }}</span>
                <textarea v-model="form[field.key]" :required="field.min > 0" rows="3" />
                <small>{{ field.hint ? `${field.hint} ` : "" }}{{ field.min ? `Enter ${field.min}–${field.max} lines` : `Up to ${field.max} lines` }}, up to {{ field.length }} characters each.</small>
              </label>
              <label class="promo-consent promo-full">
                <input v-model="form.search_partners" type="checkbox">
                <span>Also show on Google search partner sites. Partners add reach, usually at a lower conversion rate.</span>
              </label>
              <label class="offer-field">
                <span>Maximum cost per click bid (USD)</span>
                <input v-model.trim="form.bid" required inputmode="decimal">
              </label>
            </template>
          </fieldset>
          <AdsBudgetSummary v-if="budgetMicros > 0" v-model:days="days" :amount-micros="budgetMicros" />
          <div class="promo-actions">
            <button class="primary-action" type="submit" :disabled="busy">Save and review draft</button>
            <button class="secondary-action" type="button" :disabled="busy" @click="cancelForm">Cancel</button>
          </div>
        </form>
        <button v-if="!destinations.length" class="secondary-action" type="button" @click="cancelForm">Back</button>
      </template>

      <template v-else-if="campaign">
        <div class="promo-actions">
          <button class="secondary-action" type="button" :disabled="busy" @click="back">All campaigns</button>
          <button class="secondary-action" type="button" :disabled="busy" @click="refreshCampaign">Refresh status</button>
        </div>
        <div>
          <h3>{{ campaign.state === 'draft' ? 'Review campaign draft' : 'Campaign details' }}</h3>
          <p>{{ campaignStatus(campaign) }} · Revision {{ campaign.revision }}</p>
        </div>
        <dl class="promo-fields promo-facts">
          <div><dt>Test advertiser</dt><dd>{{ campaign.account_id }}</dd></div>
          <div><dt>Goal</dt><dd>{{ objectives[campaign.draft.objective] }}</dd></div>
          <div class="promo-full">
            <dt>Landing page</dt>
            <dd><a :href="campaign.draft.final_url || campaign.destination.url" target="_blank" rel="noopener noreferrer">{{ campaign.draft.final_url || campaign.destination.url }}</a></dd>
          </div>
          <div><dt>Placement</dt><dd>Google Search</dd></div>
          <div class="promo-full">
            <dt>Where ads show</dt>
            <dd v-if="settings.locations">{{ settings.locations.map((place) => place.name).join("; ") }} · people in or regularly in these places</dd>
            <dd v-else>Every location Google serves. This campaign was created before location targeting.</dd>
          </div>
          <div v-if="'search_partners' in settings"><dt>Search partners</dt><dd>{{ settings.search_partners ? "On" : "Off" }}</dd></div>
          <div><dt>Tracking</dt><dd>{{ experiment ? 'Junior Bay landing page and paid order attribution' : 'Unavailable for this draft' }}</dd></div>
          <template v-if="experiment">
            <div><dt>{{ campaign.state === "draft" ? "Proposed window" : "Approved window" }}</dt><dd>{{ experiment.start_date }} through {{ experiment.last_date }} · {{ experiment.time_zone }}</dd></div>
            <div><dt>Scheduled stop</dt><dd>{{ formatExperimentTime(experiment.stops_at, experiment.time_zone) }}</dd></div>
          </template>
          <div><dt>Bid</dt><dd>{{ formatUsd(settings.cpc_bid_micros) }} maximum per click</dd></div>
          <div v-if="campaign.state !== 'draft'"><dt>If changed in Google Ads</dt><dd>{{ campaign.auto_pause_on_change ? 'Pause automatically and email you' : 'Email you' }}</dd></div>
          <div v-if="settings.keywords.length" class="promo-full"><dt>Exact match keywords</dt><dd>{{ settings.keywords.join(', ') }}</dd></div>
          <div v-if="settings.phrase_keywords?.length" class="promo-full"><dt>Phrase match keywords</dt><dd>{{ settings.phrase_keywords.join(', ') }}</dd></div>
          <div v-if="settings.negative_keywords?.length" class="promo-full"><dt>Negative keywords</dt><dd>{{ settings.negative_keywords.join(', ') }}</dd></div>
        </dl>
        <div class="promo-preview">
          <h4>Responsive search ad assets</h4>
          <p>Google can combine these headlines and descriptions in different ways.</p>
          <ul><li v-for="(headline, index) in settings.headlines" :key="index"><strong>{{ headline }}</strong></li></ul>
          <ul><li v-for="(description, index) in settings.descriptions" :key="index">{{ description }}</li></ul>
        </div>
        <AdsBudgetSummary v-model:days="days" :adjustable="!experiment" :amount-micros="campaign.draft.budget.amount_micros" />
        <p v-if="driftMessage(campaign)" class="promo-error" role="alert">
          Changed in Google Ads. {{ driftMessage(campaign) }}
          <a href="https://ads.google.com/aw/campaigns" target="_blank" rel="noopener noreferrer">Open Google Ads</a>
          <span v-if="campaign.provider_campaign_id"> and check campaign {{ campaign.provider_campaign_id }} in advertiser {{ campaign.account_id }}.</span>
        </p>
        <p v-if="needsStopConfirmation" class="promo-error" role="alert">
          The scheduled end has passed. Google Ads has yet to confirm the stop. Junior Bay will keep checking.
          <a v-if="campaign.provider_campaign_id" href="https://ads.google.com/aw/campaigns" target="_blank" rel="noopener noreferrer">Open Google Ads</a>
          <span v-if="campaign.provider_campaign_id"> and check campaign {{ campaign.provider_campaign_id }} in advertiser {{ campaign.account_id }}.</span>
        </p>

        <p v-if="failureJob" class="promo-error" role="status">
          Google Ads operation {{ failureJob.state === 'needs_reconciliation' ? 'needs a status check' : 'did not complete' }}.
          <span v-if="failureJob.provider_request_id">Google request ID {{ failureJob.provider_request_id }}.</span>
        </p>
        <template v-if="campaign.state === 'draft' && canApprove && experiment && !windowEnded && !approvalRejected">
          <label class="promo-consent">
            <input v-model="confirmed" type="checkbox" :disabled="busy">
            <span>I approve revision {{ campaign.revision }}, including its ad assets, destination, {{ formatUsd(campaign.draft.budget.amount_micros) }} average daily budget, and {{ experiment.days }}-day window. This creates a paused test campaign that Junior Bay starts {{ startPhrase }}.</span>
          </label>
          <label class="promo-consent">
            <input v-model="autoPause" type="checkbox" :disabled="busy">
            <span>Pause this campaign if its budget is raised or replaced, or it is turned back on, in Google Ads. Junior Bay checks every 15 minutes while it runs and emails you either way.</span>
          </label>
          <div class="promo-actions">
            <button class="primary-action" type="button" :disabled="busy || !confirmed" @click="command('approve')">
              Approve and create paused
            </button>
            <button class="secondary-action" type="button" :disabled="busy" @click="openForm(campaign)">Edit draft</button>
          </div>
        </template>
        <div v-else class="promo-actions">
          <button v-if="campaign.state === 'draft' && canEdit" class="secondary-action" type="button" :disabled="busy" @click="openForm(campaign)">Edit draft</button>
          <button v-if="canLaunch" class="primary-action" type="button" :disabled="busy" @click="command('launch')">
            Launch test campaign
          </button>
          <button v-if="canPause" class="secondary-action" type="button" :disabled="busy" @click="command('pause')">Pause campaign</button>
          <button v-if="canCancelStart" class="secondary-action" type="button" :disabled="busy" @click="command('pause')">Don't start automatically</button>
          <button v-if="campaign.state === 'reconcile_required' && !campaign.pause_pending" class="secondary-action" type="button" :disabled="busy" @click="command('reconcile')">
            Check Google Ads status
          </button>
        </div>
        <p v-if="['draft', 'paused'].includes(campaign.state) && !canApprove">{{ availabilityMessage }}</p>
        <p v-else-if="campaign.state === 'draft' && approvalRejected">Save a new revision before approving this campaign again.</p>
        <p v-else-if="campaign.state === 'draft' && (!experiment || windowEnded)">Edit the draft to add a current experiment window.</p>
        <p v-if="campaign.start_blocked && !campaign.launch_requested_at" class="promo-error" role="alert">
          The scheduled start did not go through. {{ campaign.start_blocked.message }}
          Junior Bay tries again every 15 minutes until the approved window ends.
        </p>
        <p v-else-if="campaign.start_scheduled && !campaign.launch_requested_at">
          Starts automatically {{ startPhrase }}.
        </p>
        <p v-else-if="campaign.state === 'paused' && !campaign.launch_requested_at && experiment && !windowEnded">
          Automatic start is off. Launch the test campaign yourself during the approved window.
        </p>
        <p v-else-if="campaign.state === 'paused' && !campaign.launch_requested_at && (!experiment || windowEnded)">
          Create and approve a campaign with current experiment dates to start a run.
        </p>
        <p v-else-if="campaign.pause_confirmed_at && campaign.launch_requested_at">Create and approve a new campaign to run another experiment.</p>
        <AdsExperimentSummary v-if="experiment && campaign.launch_requested_at" :campaign="campaign" :refresh-key="attributionRefresh" />
      </template>

      <template v-else>
        <p v-if="!canCreate && !error">{{ availabilityMessage }}</p>
        <p v-else-if="!campaigns.length && !error">No test campaigns yet.</p>
        <button v-if="error && !campaigns.length" class="secondary-action" type="button" :disabled="busy" @click="load">Retry</button>
        <button v-if="policy?.available && !advertisers.length" class="secondary-action" type="button" @click="$emit('manage-accounts')">
          Manage Google Ads accounts
        </button>
        <ul v-if="campaigns.length" class="promo-list">
          <li v-for="item in campaigns" :key="item.campaign_id">
            <div>
              <strong>{{ item.configuration.settings.headlines[0] }}</strong>
              <span>{{ campaignStatus(item) }} · {{ formatUsd(item.draft.budget.amount_micros) }} average daily budget</span>
              <span v-if="awaitsStop(item)" class="promo-error">Scheduled stop awaiting confirmation</span>
              <span v-if="item.provider_drift" class="promo-error">Changed in Google Ads. Review needed</span>
              <span v-if="item.start_blocked && !item.launch_requested_at" class="promo-error">Scheduled start blocked</span>
            </div>
            <button class="secondary-action" type="button" :disabled="busy" @click="openCampaign(item.campaign_id)">
              {{ item.state === 'draft' ? 'Review draft' : 'View campaign' }}
            </button>
          </li>
        </ul>
      </template>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import AdsBudgetSummary from "./AdsBudgetSummary.vue";
import AdsExperimentSummary from "./AdsExperimentSummary.vue";
import {
  fetchAdsCampaign, fetchAdsCampaigns, fetchAdsDestinationOptions, fetchAdsLocations, queueAdsAction, saveAdsDraft,
} from "../api/attention";
import {
  ESTIMATE_DAYS, PROMO_DEFAULT_MICROS, addCalendarDays, campaignStatus, dateInZone, driftMessage, formatExperimentTime,
  formatUsd, usdToMicros,
} from "../utils/adsPromo";

const props = defineProps({ accounts: { type: Array, required: true } });
defineEmits(["manage-accounts"]);

const objectives = { traffic: "Website visits", leads: "Leads", sales: "Sales" };
const creativeFields = [
  { key: "headlines", label: "Headlines", min: 3, max: 15, length: 30 },
  { key: "descriptions", label: "Descriptions", min: 2, max: 4, length: 90 },
  { key: "keywords", label: "Exact match keywords", min: 0, max: 100, length: 80, hint: "Searches for exactly this, or close variants." },
  { key: "phrase_keywords", label: "Phrase match keywords", min: 0, max: 100, length: 80, hint: "Searches that include this phrase." },
  { key: "negative_keywords", label: "Negative keywords", min: 0, max: 100, length: 80, hint: "Searches that include any of these never show your ad." },
];
const KEYWORD_FIELDS = ["keywords", "phrase_keywords"];
const campaigns = ref([]);
const campaign = ref(null);
const policy = ref(null);
const destinations = ref([]);
const form = ref(null);
const days = ref(14);
const now = ref(Date.now() / 1000);
const attributionRefresh = ref(0);
const loading = ref(true);
const busy = ref(false);
const confirmed = ref(false);
const autoPause = ref(false);
const error = ref("");
const notice = ref("");
const observedJob = ref(null);
const placeQuery = ref("");
const placeResults = ref([]);
const placeBusy = ref(false);
const requests = new Map();
const pendingStates = new Set(["preparing", "launch_pending", "reconciling"]);
let timer;
let clockTimer;
let pollId = 0;
let unmounted = false;

const advertisers = computed(() => props.accounts.filter((item) => item.connected && item.test_account && item.currency === "USD"));
const accountZone = computed(() => advertisers.value.find((item) => item.account_id === form.value?.account_id)?.time_zone);
const accountToday = computed(() => dateInZone(accountZone.value, new Date(now.value * 1000)));
const experiment = computed(() => campaign.value?.draft.experiment);
const windowEnded = computed(() => Boolean(experiment.value && now.value >= experiment.value.stops_at));
const windowOpen = computed(() => Boolean(experiment.value && now.value >= experiment.value.starts_at && !windowEnded.value));
const needsStopConfirmation = computed(() => campaign.value && awaitsStop(campaign.value));
const budgetCap = computed(() => policy.value?.max_average_daily_budget_micros || 0);
const budgetMicros = computed(() => usdToMicros(form.value?.budget));
const canCreate = computed(() => policy.value?.available && advertisers.value.length > 0);
const canEdit = computed(() => policy.value?.available && advertisers.value.some((item) => item.account_id === campaign.value?.account_id));
const canApprove = computed(() => canEdit.value && campaign.value.draft.budget.amount_micros <= budgetCap.value);
const canLaunch = computed(() => campaign.value.state === "paused" && canApprove.value && windowOpen.value
  && !campaign.value.launch_requested_at && !campaign.value.pause_pending && !campaign.value.provider_drift);
const canPause = computed(() => campaign.value?.has_provider_campaign && !campaign.value.pause_pending
  && ["enabled", "launch_pending", "reconcile_required"].includes(campaign.value.state));
const canCancelStart = computed(() => campaign.value?.start_scheduled && campaign.value.state === "paused"
  && campaign.value.has_provider_campaign && !campaign.value.launch_requested_at && !campaign.value.pause_pending);
const startPhrase = computed(() => (windowOpen.value
  ? "as soon as it is ready in Google Ads"
  : `at ${formatExperimentTime(experiment.value.starts_at, experiment.value.time_zone)}`));
const settings = computed(() => campaign.value?.configuration.settings);
const failureJob = computed(() => {
  const job = observedJob.value || campaign.value?.last_job;
  return job && job.revision === campaign.value?.revision
    && !["queued", "processing", "completed"].includes(job.state) ? job : null;
});
const approvalRejected = computed(() => failureJob.value?.action === "approve");
const availabilityMessage = computed(() => {
  if (!policy.value) return "Campaigns are unavailable in this environment.";
  if (!policy.value.has_launch_entitlement) return "Your account needs an active Ads entitlement to create or launch test campaigns.";
  if (!policy.value.available) return "Campaign creation is unavailable in this environment.";
  if (campaign.value && !canEdit.value) return "Reconnect this test advertiser to edit, approve, or launch the campaign.";
  if (campaign.value) return "This campaign’s average daily budget exceeds your current plan limit.";
  return "Connect and select a USD Google Ads test advertiser to create a campaign.";
});

function awaitsStop(item) {
  return Boolean(item.launch_requested_at && item.draft.experiment?.stops_at <= now.value && !item.pause_confirmed_at);
}

function resetStartDate() {
  form.value.start_date = accountToday.value;
}

function requestId(key) {
  if (!requests.has(key)) requests.set(key, crypto.randomUUID());
  return requests.get(key);
}

async function run(action) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    await action();
  } catch (failure) {
    error.value = failure.message || "Advertising is temporarily unavailable.";
  } finally {
    busy.value = false;
  }
}

async function load() {
  loading.value = true;
  try {
    const result = await fetchAdsCampaigns();
    campaigns.value = result.campaigns;
    policy.value = result.promo;
  } catch (failure) {
    error.value = failure.code === "ads_not_entitled" ? failure.message : "Could not load Search campaigns. Try again shortly.";
  } finally {
    loading.value = false;
  }
}

function updateCampaign(item) {
  if (campaign.value?.revision !== item.revision || item.state !== "draft") confirmed.value = false;
  campaign.value = item;
  const index = campaigns.value.findIndex((entry) => entry.campaign_id === item.campaign_id);
  if (index === -1) campaigns.value.unshift(item);
  else campaigns.value[index] = item;
}

function openCampaign(id) {
  return run(async () => {
    const result = await fetchAdsCampaign(id);
    days.value = result.campaign.draft.experiment?.days || 14;
    observedJob.value = null;
    updateCampaign(result.campaign);
    if (pendingStates.has(result.campaign.state) || result.campaign.pause_pending) schedulePoll(id);
  });
}

function openForm(item) {
  return run(async () => {
    destinations.value = await fetchAdsDestinationOptions();
    confirmed.value = false;
    days.value = item?.draft.experiment?.days || 14;
    form.value = {
      account_id: item?.account_id || advertisers.value[0]?.account_id || "",
      page_id: item?.destination.page_id || (destinations.value.length === 1 ? destinations.value[0].pageId : ""),
      objective: item?.draft.objective || "traffic",
      budget: String((item?.draft.budget.amount_micros ?? Math.min(PROMO_DEFAULT_MICROS, budgetCap.value)) / 1_000_000),
      bid: item ? String(settings.value.cpc_bid_micros / 1_000_000) : "",
      locations: item ? [...(settings.value.locations || [])] : [],
      search_partners: Boolean(item && settings.value.search_partners),
    };
    resetStartDate();
    if (item?.draft.experiment?.start_date >= accountToday.value) form.value.start_date = item.draft.experiment.start_date;
    for (const field of creativeFields) form.value[field.key] = item ? (settings.value[field.key] || []).join("\n") : "";
    placeResults.value = [];
    placeQuery.value = "";
    if (item) await proposeSitePlace(); // a new form proposes one when its page is set (watch below)
  });
}

// Proposes the chosen page's own Site location, which the tenant can remove or widen. Never overwrites a
// choice already made, and a failed lookup leaves the picker empty rather than guessing.
async function proposeSitePlace() {
  const page = destinations.value.find((entry) => entry.pageId === form.value?.page_id);
  if (!form.value || form.value.locations.length || !page?.place || !form.value.account_id) return;
  placeQuery.value = page.place;
  try {
    const { locations } = await fetchAdsLocations(form.value.account_id, page.place);
    const match = locations.find((place) => place.type === "City") || locations[0];
    if (match && form.value && !form.value.locations.length) form.value.locations.push({ id: match.id, name: match.name });
    placeResults.value = locations;
  } catch {
    placeResults.value = [];
  }
}

async function searchPlaces() {
  if (!placeQuery.value || !form.value?.account_id || placeBusy.value) return;
  placeBusy.value = true;
  try {
    placeResults.value = (await fetchAdsLocations(form.value.account_id, placeQuery.value)).locations;
    if (!placeResults.value.length) error.value = `Google Ads found no place called “${placeQuery.value}”.`;
  } catch (failure) {
    error.value = failure.message || "Google Ads could not search places just now.";
  } finally {
    placeBusy.value = false;
  }
}

function addPlace(place) {
  if (form.value.locations.length >= 10) {
    error.value = "Choose up to 10 places.";
    return;
  }
  if (!form.value.locations.some((item) => item.id === place.id)) form.value.locations.push({ id: place.id, name: place.name });
}

watch(() => form.value?.page_id, () => { if (form.value && !campaign.value) proposeSitePlace(); });

function cancelForm() {
  error.value = "";
  notice.value = "";
  form.value = null;
  days.value = experiment.value?.days || 14;
}

function save() {
  return run(async () => {
    const page = destinations.value.find((entry) => entry.pageId === form.value.page_id);
    if (!page) throw new Error("Choose a published landing page.");
    if (!budgetMicros.value || budgetMicros.value > budgetCap.value) {
      throw new Error(`Enter an average daily budget above $0 and up to ${formatUsd(budgetCap.value)}.`);
    }
    if (!form.value.locations.length) throw new Error("Choose at least one place where ads show.");
    const body = {
      account_id: form.value.account_id,
      page_id: page.pageId,
      offer_id: page.offerId,
      objective: form.value.objective,
      average_daily_budget_micros: budgetMicros.value,
      experiment: { start_date: form.value.start_date, days: days.value },
      locations: form.value.locations,
    };
    const current = campaign.value;
    if (current) {
      const bid = usdToMicros(form.value.bid);
      if (!bid || bid > budgetMicros.value) throw new Error("Enter a bid above $0 and within the average daily budget.");
      body.revision = current.revision;
      delete body.locations;
      body.search = { cpc_bid_micros: bid, locations: form.value.locations, search_partners: form.value.search_partners };
      for (const { key, label, min, max, length } of creativeFields) {
        const lines = form.value[key].split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
        if (lines.length < min || lines.length > max || lines.some((line) => [...line].length > length)) {
          throw new Error(`${label} requires ${min}–${max} lines with up to ${length} characters per line.`);
        }
        body.search[key] = lines;
      }
      if (!KEYWORD_FIELDS.some((key) => body.search[key].length)) throw new Error("Enter at least one exact or phrase match keyword.");
    }
    const key = JSON.stringify(body);
    if (!current) body.request_id = requestId(key);
    const result = await saveAdsDraft(body, current?.campaign_id);
    requests.delete(key);
    form.value = null;
    observedJob.value = null;
    updateCampaign(result.campaign);
    notice.value = "Draft saved.";
  });
}

function command(action) {
  return run(async () => {
    const { campaign_id: id, revision } = campaign.value;
    const key = `${id}:${revision}:${action}`;
    const options = action === "approve" ? { auto_pause_on_change: autoPause.value } : {};
    const { job } = await queueAdsAction(id, action, revision, requestId(key), options);
    requests.delete(key);
    observedJob.value = job;
    confirmed.value = false;
    autoPause.value = false;
    notice.value = "Action queued. Waiting for Google Ads confirmation.";
    updateCampaign({
      ...campaign.value,
      state: { approve: "preparing", launch: "launch_pending", reconcile: "reconciling" }[action] || campaign.value.state,
      pause_pending: action === "pause",
    });
    schedulePoll(id, job.job_id);
  });
}

function stopPolling() {
  clearTimeout(timer);
  pollId += 1;
}

function schedulePoll(id, jobId, attempt = 0) {
  if (unmounted) return;
  stopPolling();
  const checkId = pollId;
  timer = setTimeout(async () => {
    if (checkId !== pollId) return;
    if (busy.value) {
      schedulePoll(id, jobId, attempt);
      return;
    }
    try {
      const result = await fetchAdsCampaign(id, jobId);
      if (checkId !== pollId) return;
      if (busy.value) {
        schedulePoll(id, jobId, attempt);
        return;
      }
      updateCampaign(result.campaign);
      if (result.job) observedJob.value = result.job;
      if (!pendingStates.has(result.campaign.state) && !result.campaign.pause_pending) {
        notice.value = campaignStatus(result.campaign);
        return;
      }
      if (attempt < 14) schedulePoll(id, jobId, attempt + 1);
      else notice.value = "Google Ads confirmation is still pending. Use Refresh status to check again.";
    } catch {
      if (checkId === pollId) {
        if (attempt < 14) schedulePoll(id, jobId, attempt + 1);
        else notice.value = "Could not refresh the campaign. Use Refresh status to try again.";
      }
    }
  }, 2000);
}

function refreshCampaign() {
  return run(async () => {
    const id = campaign.value.campaign_id;
    const jobId = observedJob.value?.job_id;
    stopPolling();
    const result = await fetchAdsCampaign(id, jobId);
    updateCampaign(result.campaign);
    attributionRefresh.value += 1;
    if (result.job) observedJob.value = result.job;
    if (pendingStates.has(result.campaign.state) || result.campaign.pause_pending) schedulePoll(id, jobId);
  });
}

function back() {
  stopPolling();
  campaign.value = null;
  observedJob.value = null;
  confirmed.value = false;
  notice.value = "";
  error.value = "";
  return load();
}

async function refreshExperiment() {
  now.value = Date.now() / 1000;
  const current = campaign.value;
  if (!current?.launch_requested_at || current.report?.settled || busy.value || form.value
    || pendingStates.has(current.state) || current.pause_pending) return;
  try {
    const result = await fetchAdsCampaign(current.campaign_id);
    if (unmounted || current !== campaign.value || busy.value) return;
    updateCampaign(result.campaign);
  } catch {
    // Keep the last successful view during a background refresh.
  }
}

onMounted(() => {
  load();
  clockTimer = setInterval(refreshExperiment, 60000);
});
onBeforeUnmount(() => {
  unmounted = true;
  clearInterval(clockTimer);
  stopPolling();
});
</script>

<style scoped>
.dashboard-card-header { flex-wrap: wrap; }
.promo-body { display: grid; gap: 1.6rem; }
.promo-body :is(h3, h4, p, dl) { margin: 0; }
.promo-actions { display: flex; flex-wrap: wrap; align-items: center; gap: .8rem; }
.promo-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 24rem), 1fr)); gap: 1.4rem; min-width: 0; padding: 0; border: 0; }
.promo-full { grid-column: 1 / -1; }
.promo-chips { display: flex; flex-wrap: wrap; gap: .5rem; margin: .4rem 0; padding: 0; list-style: none; }
.promo-chip { display: inline-flex; align-items: center; gap: .4rem; padding: .25rem .6rem; border: 1px solid var(--border, #d0d5dd); border-radius: 999px; }
.promo-chip-remove { border: 0; background: none; cursor: pointer; font-size: 1.1rem; line-height: 1; padding: 0 .1rem; }
.promo-place-search { display: flex; gap: .6rem; }
.promo-place-search input { flex: 1; }
.promo-place-results { display: flex; flex-wrap: wrap; gap: .5rem; margin: .5rem 0; padding: 0; list-style: none; }
.promo-facts dt { color: var(--muted); }
.promo-facts dd { margin: .25rem 0 0; overflow-wrap: anywhere; }
.promo-preview { padding: 1.6rem; border: 1px solid var(--line); border-radius: var(--radius-md); }
.promo-preview ul { padding-inline-start: 1.8rem; margin-bottom: 0; }
.promo-list { display: grid; gap: .8rem; list-style: none; padding: 0; margin: 0; }
.promo-list li { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .8rem; padding: 1.2rem; border: 1px solid var(--line); border-radius: var(--radius-md); }
.promo-list span { display: block; color: var(--muted); }
.promo-consent { display: flex; align-items: baseline; gap: .8rem; }
.promo-error { color: var(--danger, #b91c1c); }
</style>
