<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Reports</h1>
        <p>What you sold, what it cost, and what is left.</p>
      </div>
      <div class="reports-controls">
        <!-- Chips, not a select. Six windows that a tenant switches between constantly should be one
             click each, and the current one should be visible without opening anything. -->
        <div class="period-chips" role="group" aria-label="Reporting period">
          <button v-for="p in PERIODS" :key="p.key" type="button" class="period-chip"
                  :class="{ 'is-active': period === p.key }" :aria-pressed="period === p.key"
                  :disabled="busy" @click="period = p.key; load()">
            {{ p.label }}
          </button>
        </div>
        <button type="button" class="secondary-action" :disabled="busy" @click="load">
          {{ busy ? "Loading…" : "Reload" }}
        </button>
      </div>
    </header>

    <div v-if="error" class="keys-status-banner error is-prose">{{ error }}</div>

    <!-- THE THREE FIGURES SOMEBODY OPENS THIS SCREEN FOR, before the statement that derives them.
         A report is scanned before it is read: what came in, what is left after the platforms take
         their share, and what is actually mine. The table below still shows the arithmetic -- this is
         the answer, not a replacement for the working. -->
    <div v-if="summary" class="reports-headline">
      <article v-for="card in headline" :key="card.label" class="reports-figure"
               :class="{ 'is-lead': card.lead }">
        <span class="reports-figure-label">{{ card.label }}</span>
        <strong class="reports-figure-value" :class="{ 'is-unknown': !card.known }">
          {{ card.known ? money(card.value) : "—" }}
        </strong>
        <span v-if="card.scope" class="reports-figure-scope">{{ card.scope }}</span>
        <span v-else-if="card.known && previous" class="reports-figure-change"
              :class="card.delta === 0 ? '' : (card.delta > 0 ? 'is-up' : 'is-down')">
          <template v-if="card.delta === 0">No change</template>
          <template v-else>{{ card.delta > 0 ? "▲" : "▼" }} {{ money(Math.abs(card.delta)) }}</template>
          <span class="reports-figure-versus">vs previous</span>
        </span>
        <span v-else-if="card.hint" class="reports-figure-scope">{{ card.hint }}</span>
      </article>
    </div>

    <!-- A TABLE, not cards. These figures are one statement that adds up -- revenue, then what was taken
         out, then what is left -- and a row of cards says they are eight unrelated numbers. Read down the
         column and the arithmetic is visible; laid out as cards it is not. -->
    <!-- On a panel, like the figures above it. Edge-to-edge rows had nothing holding them and the
         Change column ran off the right of the screen; a surface gives the statement its own margins
         and somewhere to scroll sideways on a narrow one. -->
    <div v-if="summary" class="reports-panel">
    <table class="data-table reports-table">
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
          <td class="reports-num">
            <template v-if="row.known">{{ money(row.value) }}</template>
            <span v-else class="reports-unknown" title="Not enough information">&mdash;</span>
          </td>
          <td v-if="previous" class="reports-num reports-muted">
            <template v-if="row.wasKnown">{{ money(row.was) }}</template>
            <span v-else class="reports-unknown">&mdash;</span>
          </td>
          <td v-if="previous" class="reports-num"
              :class="!row.deltaKnown || row.delta === 0 ? '' : (row.delta > 0 ? 'is-up' : 'is-down')">
            <template v-if="!row.deltaKnown">&mdash;</template>
            <template v-else-if="row.delta === 0">&mdash;</template>
            <template v-else>{{ row.delta > 0 ? "+" : "−" }}{{ money(Math.abs(row.delta)) }}</template>
          </td>
        </tr>
      </tbody>
    </table>
    </div>

    <!-- The one figure a tenant could act wrongly on. Shipping cost exists only once a label is bought,
         so a period where most orders have not shipped reports a margin computed from the few that have.
         Said beside the number, never silently corrected. -->
    <p v-if="shippingCaveat" class="keys-status-banner warning is-prose">{{ shippingCaveat }}</p>

    <!-- WHAT SOLD. Grouped from the LINES of each sale, never from the entry's primary product: that
         names one product while the gross is the whole order, so a bump's revenue lands on the headline
         product and the bump reads as having never sold. -->
    <section v-if="sold.length" class="reports-section">
      <h2>What sold</h2>
      <div class="reports-panel">
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
              <!-- Share of revenue, as a bar. "What sold" is a RANKING, and a column of numbers makes
                   the reader do the comparison the screen exists to do for them. Width only -- no
                   second colour, because the bar is context for the figure beside it, not a rival. -->
              <span class="reports-share" aria-hidden="true">
                <span class="reports-share-fill" :style="{ width: row.share + '%' }"></span>
              </span>
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
      </div>
    </section>

    <p v-if="summary && !entryCount" class="field-hint">No sales in this period.</p>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { apiRequest } from "../api/client";
import { formatMoney } from "../stores/products";

const PERIODS = [
  // SHORT WINDOWS FIRST. 30 days was the shortest, which is coarse for a seller checking daily -- and
  // it is the window that hides a freshly-costed sale behind a month of older uncosted ones.
  { key: "today", label: "Today", days: 1, calendarDay: true },
  { key: "7d", label: "Last 7 days", days: 7 },
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

/**
 * The epoch bounds for a period, and for the equivalent period before it.
 *
 * "Today" is a CALENDAR day — local midnight to now — and every other window is rolling. That
 * distinction is the whole point of this function: `days: 1` meant the last 24 hours, so a chip
 * labelled "Today" was reaching back into most of yesterday and reporting yesterday's subscription
 * renewals as today's sales (reported 2026-10-12, where it made "2 of 4" need explaining).
 *
 * Local midnight, not UTC: a tenant's "today" is the one on their own wall, and the ledger stores
 * epoch seconds so the browser is the only place that knows which that is.
 */
function windowFor(spec) {
  const now = Math.floor(Date.now() / 1000);
  if (spec.calendarDay) {
    const midnight = new Date();
    midnight.setHours(0, 0, 0, 0);
    const from = Math.floor(midnight.getTime() / 1000);
    // Yesterday, midnight to midnight — a whole day against a part of one, which is the honest
    // comparison for "so far today" and is what every sales dashboard means by it.
    return { from, previousFrom: from - 86400, previousTo: from - 1 };
  }
  if (!spec.days) return { from: null, previousFrom: null, previousTo: null };
  const from = now - spec.days * 86400;
  return { from, previousFrom: now - spec.days * 2 * 86400, previousTo: from - 1 };
}

async function load() {
  busy.value = true;
  error.value = "";
  try {
    const { from, previousFrom, previousTo } = windowFor(spec.value);
    const body = await fetchWindow(from, null);
    summary.value = body.summary || null;
    entryCount.value = Number(body.count || 0);
    currency.value = (body.entries || [])[0]?.currency || "usd";
    // The SAME length of time immediately before, so a comparison is like for like. Skipped for
    // all-time, which has nothing before it.
    previous.value = previousFrom
      ? (await fetchWindow(previousFrom, previousTo)).summary || null
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
  // SPLIT, because `totals.shipping_cost` now holds both outbound and return labels and this row said
  // "Labels bought so far" while being the figure `Shipping collected` is meant to be read against. A
  // tenant comparing the two would have been told their postage pricing was losing money whenever a
  // buyer sent something back (plans/MONEY_ACROSS_SILOS.md P3).
  { label: "Shipping paid", pick: (s) => s.shipping_revenue_cost, tone: "is-cost",
    note: "Outbound labels bought so far — compare with Shipping collected." },
  // Its own row, because "my postage pricing is wrong" and "returns are eating me" are different
  // problems with different fixes. Hidden until there is one: a permanent £0 row teaches a tenant to
  // stop reading the statement.
  { label: "Return labels", pick: (s) => s.return_shipping_cost, tone: "is-cost",
    hide: (s) => !Number(s.return_shipping_cost || 0),
    note: "Return postage you paid for. Not part of shipping margin." },
  { label: "Net", pick: (s) => s.net, tone: "is-total",
    note: "Gross after Stripe and platform fees." },
  // TAX COLLECTED, which the statement could not previously explain. `summarize` has returned
  // `tax_liability` since tax was first captured, and nothing displayed it -- while `gross` INCLUDES the
  // tax the buyer paid and `profit` subtracts it again. So Net exceeded Profit by an amount with no row
  // behind it, which is the one thing a statement must never do.
  //
  // NEGATIVE, like the other rows that leave the tenant, and placed between Net and Profit so the
  // arithmetic reads downward. It is a LIABILITY, not a cost of doing business: the tenant is holding
  // someone else's money, and calling it either income or an expense would be wrong in a way an
  // accountant would notice.
  //
  // Hidden until there is some, for the reason the return-labels row is: a permanent $0 row teaches a
  // tenant to stop reading the statement. Nothing in this codebase enables Stripe Tax yet, so today it
  // is always hidden -- the point is that it appears by itself the day a tenant turns tax on.
  { label: "Sales tax collected", pick: (s) => -Math.abs(Number((s.totals || {}).tax || 0)),
    tone: "is-cost",
    hide: (s) => !Number((s.totals || {}).tax || 0),
    note: "Held on behalf of the tax authority — not your income." },
  // PROFIT IS WITHHELD RATHER THAN GUESSED. `cogs` was a declared ledger component that nothing ever
  // supplied, so this row has been showing `net` under the word "Profit" since Reports shipped -- the
  // same shape as the Dashboard's "Net Revenue" summing gross. Now the server says whether every sale in
  // the period had a recorded cost, and a period containing one uncosted sale has no profit figure to
  // show: the arithmetic would be short by an unknown amount and inflated in the flattering direction.
  // PROFIT, scoped when it has to be. All-or-nothing cost a tenant a month of silence: start recording
  // costs today and the figure still hides behind every older uncosted sale in the window, because an
  // entry already written can never gain a cost. The partial answer is shown WITH its scope instead,
  // which is the same shape as the shipping-coverage caveat two rows down.
  { label: "Profit", pick: (s) => (s.profit_known ? s.profit : s.costed_profit), tone: "is-total",
    known: (s) => Boolean(s.profit_known) || s.costed_profit != null,
    note: (s) => (s.profit_known
      ? "Net after postage and cost of goods."
      : `On ${s.costed_sales} of ${s.sale_count} sales — the rest have no cost recorded yet.`),
    unknownNote: () => 'No costs recorded yet. Add "What this costs you" to your products.' },
];

const rows = computed(() => {
  const now = summary.value;
  if (!now) return [];
  // A line may not apply to this tenant at all. `hide` is absent on every other line, which reads as
  // always-shown.
  return LINES.filter((line) => !(line.hide && line.hide(now))).map((line) => {
    const value = Number(line.pick(now) || 0);
    const was = previous.value ? Number(line.pick(previous.value) || 0) : 0;
    // A row may refuse to state its value. `known` is absent on every other line, which reads as
    // knowable -- only a line that can be unsupportable has to say so.
    const known = line.known ? line.known(now) : true;
    const wasKnown = line.known ? (previous.value ? line.known(previous.value) : false) : true;
    return {
      label: line.label,
      note: known
        ? (typeof line.note === "function" ? line.note(now) : line.note)
        : (line.unknownNote ? line.unknownNote(now) : line.note),
      tone: line.tone, value, was, delta: value - was, known, wasKnown,
      // A delta between two figures is meaningless if either is unknown, and showing one would imply
      // both were measured.
      deltaKnown: known && wasKnown,
    };
  });
});

// The three figures the headline band shows. Derived from the same summary the table reads, so the
// band and the statement can never disagree -- the Dashboard learned that lesson the hard way when its
// revenue card summed a different source than the table beneath it.
const headline = computed(() => {
  const now = summary.value;
  if (!now) return [];
  const was = previous.value;
  const delta = (pick) => (was ? Number(pick(now) || 0) - Number(pick(was) || 0) : 0);
  const scoped = !now.profit_known && now.costed_profit != null;
  return [
    { label: "Gross", value: (now.totals || {}).gross, known: true,
      delta: delta((s) => (s.totals || {}).gross) },
    { label: "Net", value: now.net, known: true, delta: delta((s) => s.net),
      hint: "After Stripe and platform fees" },
    { label: "Profit", lead: true,
      value: now.profit_known ? now.profit : now.costed_profit,
      known: now.profit_known || now.costed_profit != null,
      delta: delta((s) => (s.profit_known ? s.profit : s.costed_profit) || 0),
      // The scope replaces the change, deliberately: comparing a partial figure with a period whose
      // coverage was different is a number nobody can act on.
      scope: scoped ? `On ${now.costed_sales} of ${now.sale_count} sales` : "",
      hint: 'Add "What this costs you" to your products' },
  ];
});

const periodLabel = computed(() => spec.value.label);

// Presented, not derived: the rollup is the server's, so money is added up in exactly one place.
const sold = computed(() => {
  const products = (summary.value?.what_sold || {}).products || [];
  // Share is against the BIGGEST seller, not against total revenue: the question a ranking answers is
  // "how does this compare with the leader", and scaling to the total leaves every bar a stub as soon
  // as a tenant has a dozen products.
  const leader = products.reduce((top, row) => Math.max(top, Number(row.gross || 0)), 0);
  return products.map((row) => ({
    ...row,
    key: row.product_id || row.name,
    name: row.name || row.product_id,
    share: leader > 0 ? Math.max(2, Math.round((Number(row.gross || 0) / leader) * 100)) : 0,
  }));
});
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

<style scoped>
.reports-unknown {
  opacity: 0.55;
}
</style>
