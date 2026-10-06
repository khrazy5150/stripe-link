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

    <!-- A TABLE, not cards. These figures are one statement that adds up -- revenue, then what was taken
         out, then what is left -- and a row of cards says they are eight unrelated numbers. Read down the
         column and the arithmetic is visible; laid out as cards it is not. -->
    <table v-if="summary" class="data-table reports-table">
      <thead>
        <tr>
          <th scope="col">Figure</th>
          <th scope="col" class="reports-num">{{ periodLabel }}</th>
          <th v-if="previous" scope="col" class="reports-num">Period before</th>
          <th v-if="previous" scope="col" class="reports-num">Change</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.label" :class="row.tone">
          <th scope="row">
            {{ row.label }}
            <small v-if="row.note">{{ row.note }}</small>
          </th>
          <td class="reports-num">{{ money(row.value) }}</td>
          <td v-if="previous" class="reports-num reports-muted">{{ money(row.was) }}</td>
          <td v-if="previous" class="reports-num"
              :class="row.delta === 0 ? '' : (row.delta > 0 ? 'is-up' : 'is-down')">
            <template v-if="row.delta === 0">&mdash;</template>
            <template v-else>{{ row.delta > 0 ? "+" : "−" }}{{ money(Math.abs(row.delta)) }}</template>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- The one figure a tenant could act wrongly on. Shipping cost exists only once a label is bought,
         so a period where most orders have not shipped reports a margin computed from the few that have.
         Said beside the number, never silently corrected. -->
    <p v-if="shippingCaveat" class="keys-status-banner warning is-prose">{{ shippingCaveat }}</p>

    <!-- WHAT SOLD. Grouped from the LINES of each sale, never from the entry's primary product: that
         names one product while the gross is the whole order, so a bump's revenue lands on the headline
         product and the bump reads as having never sold. -->
    <section v-if="sold.length" class="reports-section">
      <h2>What sold</h2>
      <table class="data-table reports-table">
        <thead>
          <tr>
            <th scope="col">Product</th>
            <th scope="col" class="reports-num">Revenue</th>
            <th scope="col" class="reports-num">Units</th>
            <th scope="col" class="reports-num">Orders</th>
            <th scope="col" class="reports-num">Avg / order</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in sold" :key="row.key">
            <th scope="row">
              {{ row.name }}
              <small v-if="row.bump_gross">{{ money(row.bump_gross) }} of this as an order bump</small>
            </th>
            <td class="reports-num">{{ money(row.gross) }}</td>
            <td class="reports-num">{{ row.units }}</td>
            <td class="reports-num">{{ row.orders }}</td>
            <td class="reports-num reports-muted">{{ money(Math.round(row.gross / row.orders)) }}</td>
          </tr>
          <!-- Sales with no breakdown, named rather than spread across products or quietly dropped: a
               product table whose rows do not add up to the money table is worse than one that says
               which part it cannot place. -->
          <tr v-if="unitemised" class="reports-muted">
            <th scope="row">
              Not itemised
              <small>Sales recorded before line detail existed.</small>
            </th>
            <td class="reports-num">{{ money(unitemised) }}</td>
            <td class="reports-num">&mdash;</td>
            <td class="reports-num">&mdash;</td>
            <td class="reports-num">&mdash;</td>
          </tr>
        </tbody>
        <tfoot>
          <tr class="is-total">
            <th scope="row">Merchandise + postage = gross</th>
            <td class="reports-num">{{ money(soldTotal + unitemised) }}</td>
            <td class="reports-num" colspan="3">+ {{ money(summary.shipping_revenue) }} shipping</td>
          </tr>
        </tfoot>
      </table>
    </section>

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


// The statement, in the order it adds up: what came in, what was taken out, what is left.
const LINES = [
  { label: "Gross", pick: (s) => (s.totals || {}).gross,
    note: "Everything the buyer paid, postage included." },
  { label: "Merchandise", pick: (s) => s.merchandise_revenue,
    note: "Gross minus what was charged to post it." },
  { label: "Shipping collected", pick: (s) => s.shipping_revenue },
  { label: "Stripe fees", pick: (s) => (s.totals || {}).stripe_fee, tone: "is-cost" },
  { label: "Platform fees", pick: (s) => (s.totals || {}).platform_fee, tone: "is-cost" },
  { label: "Shipping paid", pick: (s) => (s.totals || {}).shipping_cost, tone: "is-cost",
    note: "Labels bought so far." },
  { label: "Net", pick: (s) => s.net, tone: "is-total",
    note: "Gross after Stripe and platform fees." },
  { label: "Profit", pick: (s) => s.profit, tone: "is-total",
    note: "Net after postage and cost of goods." },
];

const rows = computed(() => {
  const now = summary.value;
  if (!now) return [];
  return LINES.map((line) => {
    const value = Number(line.pick(now) || 0);
    const was = previous.value ? Number(line.pick(previous.value) || 0) : 0;
    return { label: line.label, note: line.note, tone: line.tone, value, was, delta: value - was };
  });
});

const periodLabel = computed(() => spec.value.label);

// Presented, not derived: the rollup is the server's, so money is added up in exactly one place.
const sold = computed(() => ((summary.value?.what_sold || {}).products || [])
  .map((row) => ({ ...row, key: row.product_id || row.name, name: row.name || row.product_id })));
const unitemised = computed(() => Number((summary.value?.what_sold || {}).unitemised_gross || 0));
const soldTotal = computed(() => sold.value.reduce((sum, row) => sum + Number(row.gross || 0), 0));

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
