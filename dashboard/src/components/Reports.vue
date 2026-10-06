<template>
  <section class="screen">
    <header class="screen-header">
      <div>
        <h1>Reports</h1>
        <p class="screen-subtitle">What you sold, what it cost, and what is left.</p>
      </div>
      <div class="reports-controls">
        <label>Period
          <select v-model="period" @change="load">
            <option v-for="p in PERIODS" :key="p.key" :value="p.key">{{ p.label }}</option>
          </select>
        </label>
        <button type="button" class="secondary-action" :disabled="busy" @click="load">
          {{ busy ? "Loading…" : "Reload" }}
        </button>
      </div>
    </header>

    <div v-if="error" class="keys-status-banner error is-prose">{{ error }}</div>

    <!-- MONEY, in the order a tenant reads it: what came in, what was taken out, what is left. Each
         figure is the ledger's own -- nothing here adds money up a second time. -->
    <div v-if="summary" class="reports-grid">
      <article v-for="card in cards" :key="card.label" class="reports-card" :class="card.tone">
        <p class="reports-card-label">{{ card.label }}</p>
        <p class="reports-card-value">{{ money(card.value) }}</p>
        <p v-if="card.note" class="reports-card-note">{{ card.note }}</p>
        <p v-if="card.delta !== null && card.delta !== undefined" class="reports-card-delta"
           :class="card.delta >= 0 ? 'is-up' : 'is-down'">
          {{ card.delta >= 0 ? "▲" : "▼" }} {{ money(Math.abs(card.delta)) }} vs {{ previousLabel }}
        </p>
      </article>
    </div>

    <!-- The one figure a tenant could act wrongly on. Shipping cost exists only once a label is bought,
         so a period where most orders have not shipped reports a margin computed from the few that have.
         Said beside the number, never silently corrected. -->
    <p v-if="shippingCaveat" class="keys-status-banner warning is-prose">{{ shippingCaveat }}</p>

    <p v-if="summary && !entryCount" class="field-hint">No sales in this period.</p>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { apiRequest } from "../api/client";
import { formatMoney } from "../stores/products";

const PERIODS = [
  { key: "30d", label: "Last 30 days", days: 30 },
  { key: "90d", label: "Last 90 days", days: 90 },
  { key: "12m", label: "Last 12 months", days: 365 },
  { key: "all", label: "All time", days: null },
];

const period = ref("30d");
const busy = ref(false);
const error = ref("");
const summary = ref(null);
const previous = ref(null);
const entryCount = ref(0);
const currency = ref("usd");

const money = (cents) => formatMoney(Number(cents || 0), currency.value);
const spec = computed(() => PERIODS.find((p) => p.key === period.value) || PERIODS[0]);
const previousLabel = computed(() => (spec.value.days ? "the period before" : ""));

async function fetchWindow(from, to) {
  const params = {};
  if (from) params.from = String(from);
  if (to) params.to = String(to);
  return apiRequest("/ledger", { params });
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    const now = Math.floor(Date.now() / 1000);
    const days = spec.value.days;
    const from = days ? now - days * 86400 : null;
    const body = await fetchWindow(from, null);
    summary.value = body.summary || null;
    entryCount.value = Number(body.count || 0);
    currency.value = (body.entries || [])[0]?.currency || "usd";
    // The SAME length of time immediately before, so a comparison is like for like. Skipped for
    // all-time, which has nothing before it.
    previous.value = days
      ? (await fetchWindow(now - days * 2 * 86400, from - 1)).summary || null
      : null;
  } catch (err) {
    error.value = err.message || "Could not load the ledger.";
    summary.value = null;
  } finally {
    busy.value = false;
  }
}

function delta(key, getter) {
  if (!previous.value) return null;
  return getter(summary.value) - getter(previous.value);
}

const cards = computed(() => {
  const s = summary.value;
  if (!s) return [];
  const totals = s.totals || {};
  const gross = (x) => Number((x.totals || {}).gross || 0);
  return [
    { label: "Gross", value: totals.gross, tone: "is-headline", delta: delta("gross", gross),
      note: "Everything the buyer paid, postage included." },
    { label: "Merchandise", value: s.merchandise_revenue,
      note: "Gross minus what was charged to post it." },
    { label: "Shipping collected", value: s.shipping_revenue },
    { label: "Stripe fees", value: totals.stripe_fee, tone: "is-cost" },
    { label: "Platform fees", value: totals.platform_fee, tone: "is-cost" },
    { label: "Shipping paid", value: totals.shipping_cost, tone: "is-cost",
      note: "Labels bought so far." },
    { label: "Net", value: s.net, tone: "is-headline",
      note: "Gross after Stripe and platform fees." },
    { label: "Profit", value: s.profit, tone: "is-headline",
      note: "Net after postage and cost of goods." },
  ];
});

// Never a figure whose basis is partial without saying so.
const shippingCaveat = computed(() => {
  const coverage = summary.value?.shipping_cost_coverage;
  if (!coverage || !coverage.sales) return "";
  if (coverage.shipped >= coverage.sales) return "";
  return `Shipping paid covers ${coverage.shipped} of ${coverage.sales} sales — the rest have no label `
    + "bought yet, so shipping margin reads higher than it will finish.";
});

onMounted(load);
</script>
