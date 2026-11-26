<template>
  <section class="experiment-summary" aria-labelledby="experiment-summary-heading">
    <h4 id="experiment-summary-heading">Experiment results</h4>
    <p v-if="campaign.pause_confirmed_at">Google confirmed the stop on {{ formatExperimentTime(campaign.pause_confirmed_at, experiment.time_zone) }}.</p>
    <p v-if="campaign.activation_confirmed_at">Google confirmed activation on {{ formatExperimentTime(campaign.activation_confirmed_at, experiment.time_zone) }}. Test accounts cannot serve ads.</p>
    <p v-else>Google has yet to confirm activation.</p>
    <p v-if="activationDelay > 0">Time from launch request to confirmed activation was {{ activationDelay }} minutes.</p>
    <p v-if="report?.last_synced_at">
      Google Ads · {{ report.from_date }} through {{ report.through_date }} · {{ report.time_zone }}.
      Last synced {{ formatExperimentTime(report.last_synced_at, report.time_zone) }}.
    </p>
    <p v-if="report?.status === 'stale'">The latest sync failed. The previous Google Ads report is shown below.</p>
    <p v-else-if="report?.status === 'unavailable'">Google Ads reporting is temporarily unavailable. Junior Bay will retry.</p>
    <p v-else-if="!report?.last_synced_at">Waiting for the first Google Ads report.</p>
    <p v-if="report?.last_synced_at && !report.settled">Google Ads may revise recent activity. Junior Bay refreshes results for seven days after a confirmed stop.</p>
    <template v-if="daily.length">
      <dl class="experiment-metrics">
        <div><dt>Google Ads cost</dt><dd>{{ formatUsd(totals.cost) }}</dd></div>
        <div><dt>Impressions</dt><dd>{{ totals.impressions.toLocaleString() }}</dd></div>
        <div><dt>Clicks</dt><dd>{{ totals.clicks.toLocaleString() }}</dd></div>
        <div><dt>Click-through rate</dt><dd>{{ totals.impressions ? (100 * totals.clicks / totals.impressions).toFixed(2) + '%' : '—' }}</dd></div>
        <div><dt>Average cost per click</dt><dd>{{ totals.clicks ? formatUsd(Math.round(totals.cost / totals.clicks)) : '—' }}</dd></div>
      </dl>
      <div v-if="firstImpression" class="experiment-delay">
        <p>Google recorded impressions from {{ firstImpression }} through {{ lastImpression }}.</p>
      </div>
      <div class="experiment-table">
        <table>
          <caption>Daily Google Ads activity</caption>
          <thead><tr><th scope="col">Date</th><th scope="col">Impressions</th><th scope="col">Clicks</th><th scope="col">Cost</th></tr></thead>
          <tbody>
            <tr v-for="row in daily" :key="row.day">
              <th scope="row">{{ row.day }}</th><td>{{ row.impressions }}</td><td>{{ row.clicks }}</td><td>{{ formatUsd(row.cost_micros) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
    <p v-else-if="report?.last_synced_at">Google returned no activity for this period. Sandbox results can verify the workflow and contain no evidence of ad performance.</p>

    <h4>Junior Bay landing page attribution</h4>
    <p>Arrivals and paid orders come from the campaign’s unique tracking link. They may include manual test visits.</p>
    <p v-if="attributionLoading">Checking landing page attribution…</p>
    <dl v-else-if="attribution" class="experiment-metrics">
      <div><dt>Tracked arrivals</dt><dd>{{ attribution.arrivals ?? 'Unavailable' }}</dd></div>
      <div><dt>Attributed paid orders</dt><dd>{{ attribution.conversions }}</dd></div>
    </dl>
    <p v-else>{{ attributionError ? 'Landing page attribution is temporarily unavailable.' : 'No measurements have been recorded for this link yet.' }}</p>
    <p>Google conversion actions, lead and booking attribution, and return on ad spend are unavailable in this test workflow.</p>
  </section>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { fetchAdsPageAttribution } from "../api/attention";
import { formatExperimentTime, formatUsd } from "../utils/adsPromo";

const props = defineProps({
  campaign: { type: Object, required: true },
  refreshKey: { type: Number, required: true },
});

const experiment = computed(() => props.campaign.draft.experiment);
const report = computed(() => props.campaign.report);
const daily = computed(() => report.value?.days || []);
const totals = computed(() => daily.value.reduce((sum, row) => ({
  cost: sum.cost + row.cost_micros,
  impressions: sum.impressions + row.impressions,
  clicks: sum.clicks + row.clicks,
}), { cost: 0, impressions: 0, clicks: 0 }));
const impressionDays = computed(() => daily.value.filter((row) => row.impressions > 0));
const firstImpression = computed(() => impressionDays.value[0]?.day);
const lastImpression = computed(() => impressionDays.value.at(-1)?.day);
const activationDelay = computed(() => Math.floor(
  (props.campaign.activation_confirmed_at - props.campaign.launch_requested_at) / 60,
));
const attribution = ref(null);
const attributionError = ref(false);
const attributionLoading = ref(false);

watch(
  [
    () => props.campaign.destination.page_id,
    () => props.campaign.destination.source,
    () => props.campaign.report?.last_synced_at,
    () => props.refreshKey,
  ],
  async ([pageId, source], _, onCleanup) => {
    let cancelled = false;
    onCleanup(() => { cancelled = true; });
    attribution.value = null;
    attributionError.value = false;
    attributionLoading.value = Boolean(source);
    if (!source) return;
    try {
      const data = await fetchAdsPageAttribution(pageId, source);
      if (!cancelled) attribution.value = data;
    } catch {
      if (!cancelled) attributionError.value = true;
    } finally {
      if (!cancelled) attributionLoading.value = false;
    }
  },
  { immediate: true },
);
</script>

<style scoped>
.experiment-summary { display: grid; gap: 1rem; border-top: 1px solid var(--line); padding-top: 1.6rem; }
.experiment-summary :is(h4, p, dl) { margin: 0; }
.experiment-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr)); gap: 1rem; }
.experiment-metrics dt { color: var(--muted); }
.experiment-metrics dd { margin: .25rem 0 0; font-size: 1.8rem; font-weight: 700; }
.experiment-table { overflow-x: auto; }
.experiment-table table { width: 100%; border-collapse: collapse; text-align: start; }
.experiment-table :is(th, td, caption) { padding: .65rem; text-align: start; }
.experiment-table :is(th, td) { border-bottom: 1px solid var(--line); }
</style>
