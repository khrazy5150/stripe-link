<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Orders</h1>
        <p>Sales recorded from completed checkouts and one-click upsells</p>
      </div>
      <div class="button-row">
        <button v-if="shippingConfigured && uncheckedCount" class="secondary-action" type="button"
                :disabled="checkingAddresses" @click="checkAddresses()">
          {{ checkingAddresses ? "Checking…" : `Check ${uncheckedCount} address${uncheckedCount === 1 ? "" : "es"}` }}
        </button>
        <button class="secondary-action" type="button" :disabled="exporting || !orders.length" @click="exportCsv">
          {{ exporting ? "Exporting…" : "Export CSV" }}
        </button>
        <button v-if="handoverGroups.length" class="secondary-action" type="button"
                :disabled="handing" @click="handoverKind = 'pickups'">Schedule pickup</button>
        <button v-if="handoverGroups.length" class="primary-action" type="button"
                :disabled="handing" @click="handoverKind = 'manifests'">Create manifest</button>
        <button class="secondary-action" type="button" :disabled="loading" @click="load">
          {{ loading ? "Loading..." : "Reload" }}
        </button>
      </div>
    </header>

    <section class="dashboard-card">
      <div class="product-filter-bar">
        <label>
          Search
          <input v-model.trim="filters.customer" type="search" placeholder="Customer, email, or order reference..." @input="onFilterInput" @keyup.enter="load" />
        </label>
        <label>
          Status
          <select v-model="filters.status" @change="load">
            <option value="">All</option>
            <option value="paid">Paid</option>
            <option value="refunded">Refunded</option>
            <option value="pending">Pending</option>
          </select>
        </label>
        <div class="product-filter-actions">
          <button type="button" class="secondary-action" @click="resetFilters">Reset</button>
        </div>
      </div>

      <div v-if="error" class="keys-status-banner error">{{ error }}</div>
      <div v-else class="keys-status-banner">{{ message }}</div>

      <!-- The TENANT gate: it blocks every row, so it is said once here rather than forty times in the
           table. Only shown to tenants who have started setting shipping up at all. -->
      <div v-if="shippingConfigured && shippingReadiness.length" class="keys-status-banner warning">
        <strong>Before you can buy labels:</strong>
        <ul><li v-for="item in shippingReadiness" :key="item">{{ item }}</li></ul>
      </div>

      <div v-if="selectedIds.length" class="orders-bulk-bar">
        <span>{{ selectedIds.length }} selected</span>
        <span v-if="buyableIds.length" class="orders-bulk-total">
          {{ buyableIds.length }} ready — {{ money(selectedTotal) }}
        </span>
        <span v-else class="orders-secondary">Getting rates…</span>
        <button type="button" class="primary-action" :disabled="!buyableIds.length || buying"
                @click="confirmBuy = true">
          {{ buying ? `Printing ${buyProgress.done}/${buyProgress.total}…` : `Print ${buyableIds.length} label${buyableIds.length === 1 ? "" : "s"}` }}
        </button>
      </div>

      <div v-if="buyResults.length" class="keys-status-banner" :class="buyFailures.length ? 'warning' : 'success'">
        <strong>{{ buyResults.length - buyFailures.length }} bought, {{ buyFailures.length }} failed.</strong>
        <ul v-if="buyFailures.length">
          <li v-for="row in buyFailures" :key="row.order_id">{{ elideId(row.order_id) }} — {{ row.error }}</li>
        </ul>
      </div>

      <div v-if="!orders.length" class="product-empty-state">
        {{ loaded ? "No orders found." : "Loading orders..." }}
      </div>

      <!-- A fulfilment table, not a card grid: twelve orders to post must be visible and comparable at
           once. Horizontal scroll lives on the wrapper so the PAGE never scrolls sideways. -->
      <div v-else class="orders-table-wrap">
        <table class="orders-table">
          <thead>
            <tr>
              <th scope="col" class="orders-col-select">
                <input type="checkbox" :checked="allEligibleSelected" :disabled="!eligibleIds.length"
                       :aria-label="allEligibleSelected ? 'Clear selection' : 'Select every shippable order'"
                       @change="toggleAll" />
              </th>
              <th scope="col" class="orders-col-customer">
                <button type="button" class="orders-sort" @click="sortBy('customer')">
                  Customer <span class="orders-sort-caret">{{ caret("customer") }}</span>
                </button>
              </th>
              <th scope="col">Status</th>
              <th scope="col" class="orders-col-money">
                <button type="button" class="orders-sort" @click="sortBy('amount_total')">
                  Paid <span class="orders-sort-caret">{{ caret("amount_total") }}</span>
                </button>
              </th>
              <th scope="col">Carrier</th>
              <th scope="col">
                <button type="button" class="orders-sort" @click="sortBy('created_at')">
                  Order <span class="orders-sort-caret">{{ caret("created_at") }}</span>
                </button>
              </th>
              <th scope="col">Fulfilled</th>
              <th scope="col" class="orders-col-money">Rate</th>
              <th scope="col" class="orders-col-actions">Action</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="order in visibleOrders" :key="order.order_id"
                class="orders-row" :class="{ 'orders-row-selected': selected_.has(order.order_id) }"
                tabindex="0" @click="openDetail(order, $event)" @keyup.enter="selected = order">
              <td class="orders-col-select">
                <!-- One row per thing that SHIPS, not per thing that was charged. The expander reveals
                     the boxes this group actually needs -- as few as the items allow, which is the
                     packer's answer and the same one the buyer's postage was priced from. -->
                <button v-if="order.fulfilment_group" type="button" class="orders-group-toggle"
                        :aria-expanded="expanded.has(order.order_id)"
                        :title="`${order.fulfilment_group.order_ids.length} orders — ${parcelsOf(order).length} parcel(s)`"
                        @click.stop="toggleGroup(order)">{{ expanded.has(order.order_id) ? "−" : "+" }}</button>
                <!-- Only a shippable, unshipped order can join a bulk print. The reason a box is
                     unavailable is in its tooltip and, at length, in the Status cell. -->
                <input type="checkbox" :checked="selected_.has(order.order_id)"
                       :disabled="!order.fulfilment?.eligible"
                       :title="order.fulfilment?.eligible ? '' : (order.fulfilment?.reasons || []).join(' ')"
                       :aria-label="`Select order for ${order.customer?.name || order.order_id}`"
                       @change="toggleOne(order)" />
              </td>

              <td class="orders-col-customer">
                <div class="orders-primary">{{ order.customer?.name || order.customer?.email || "—" }}</div>
                <div v-if="destinationSummary(order)" class="orders-place">{{ destinationSummary(order) }}</div>
              </td>

              <td>
                <span class="product-status" :class="order.delivery?.badge">{{ order.delivery?.label }}</span>
                <div v-if="order.delivery?.note" class="orders-place">{{ order.delivery.note }}</div>
                <button v-for="item in order.fulfilment?.needs_measurement || []" :key="item.product_id"
                        type="button" class="link-action" @click="measureProduct(item)">
                  + Add package info
                </button>
              </td>

              <td class="orders-col-money">
                <div>{{ formatMoney(order.amount_total, order.currency) }}</div>
                <div v-if="Number(order.amount_refunded) > 0" class="orders-place">
                  −{{ formatMoney(order.amount_refunded, order.currency) }} refunded
                </div>
              </td>

              <td class="orders-col-carrier">
                <template v-if="carrierOf(order)">
                  <div>{{ carrierOf(order) }}</div>
                  <a v-if="order.fulfilment?.shipment?.tracking_url" class="orders-place"
                     :href="order.fulfilment.shipment.tracking_url" target="_blank" rel="noopener" @click.stop>
                    {{ order.fulfilment.shipment.tracking_number }}
                  </a>
                </template>
                <!-- Not yet shipped: the rate dropdown is how a carrier gets chosen. -->
                <select v-else-if="rates[order.order_id]?.selected" class="orders-rate-select"
                        :value="chosenRateId(order)" :aria-label="`Carrier for ${order.order_id}`"
                        @click.stop @change="chooseRate(order, $event.target.value)">
                  <option v-for="rate in rates[order.order_id].rates" :key="rate.rate_id" :value="rate.rate_id">
                    {{ rate.carrier }} {{ rate.service }}{{ rate.estimated_days ? ` · ${rate.estimated_days}d` : "" }}
                  </option>
                </select>
                <span v-else-if="rates[order.order_id]?.loading" class="orders-place">Getting rates…</span>
                <span v-else-if="rates[order.order_id]?.error" class="orders-rate-error">{{ rates[order.order_id].error }}</span>
                <button v-else-if="order.fulfilment?.eligible" type="button" class="link-action"
                        @click.stop="quote(order)">Get rates</button>
                <span v-else class="orders-place">—</span>
              </td>

              <td>
                <div>{{ formatDate(order.created_at) }}</div>
                <!-- The reference beneath the date, the way the destination sits beneath the customer.
                     Searchable, and short enough not to need a column of its own. -->
                <button type="button" class="orders-id font-mono" title="Click to copy the order reference"
                        @click.stop="copyId(order.short_ref || order.order_id)">
                  {{ order.short_ref || shortOrderRef(order.order_id) }}
                </button>
              </td>
              <td>{{ fulfilledOn(order) || "—" }}</td>

              <td class="orders-col-money">
                <template v-if="order.fulfilment?.shipment?.cost?.amount">
                  {{ formatMoney(order.fulfilment.shipment.cost.amount, order.fulfilment.shipment.cost.currency) }}
                </template>
                <template v-else-if="rateFor(order.order_id)">
                  {{ formatMoney(rateFor(order.order_id).amount, rateFor(order.order_id).currency) }}
                </template>
                <span v-else class="orders-place">—</span>
              </td>

              <td class="orders-col-actions">
                <a v-if="order.fulfilment?.shipment?.label_url" class="secondary-action"
                   :href="order.fulfilment.shipment.label_url" target="_blank" rel="noopener" @click.stop>
                  Label
                </a>
                <button v-else type="button" class="primary-action orders-label-button"
                        :disabled="!canLabel(order) || buying"
                        :title="labelTitle(order)"
                        @click.stop="labelOne(order)">Label</button>
                <!-- MarkShippedModal, its submit handler and POST /orders/{id}/ship all existed; nothing
                     ever set `shipping` to an order, so the whole manual path was unreachable from the
                     screen. A tenant who posts parcels themselves — or whose label purchase fails — had
                     no way to tell a buyer their order was on its way (reported 2026-10-05). -->
                <button v-if="!order.fulfilment?.shipment" type="button" class="link-action orders-mark-shipped"
                        title="Already posted it yourself? Record it and send the buyer their tracking."
                        @click.stop="shipping = order">Mark shipped</button>
              </td>
            </tr>
            <!-- ONE LINE, ONE LABEL. Each parcel names its box and what goes in it, so the row reads like
                 a packing slip rather than a count the tenant has to go and look up. -->
            <tr v-if="order.fulfilment_group && expanded.has(order.order_id)" :key="`${order.order_id}-parcels`"
                class="orders-parcel-row">
              <td></td>
              <td colspan="7">
                <p class="orders-parcel-intro">
                  {{ order.fulfilment_group.order_ids.length }} orders to one address &mdash;
                  {{ parcelsOf(order).length }}
                  {{ parcelsOf(order).length === 1 ? "parcel" : "parcels" }}.
                  <span v-if="groupMembers(order).length">
                    Includes {{ groupMembers(order).slice(1).length }} post-purchase
                    {{ groupMembers(order).slice(1).length === 1 ? "upsell" : "upsells" }}, already paid
                    for and shipping free with this box.
                  </span>
                </p>
                <div v-for="(parcel, i) in parcelsOf(order)" :key="i" class="orders-parcel">
                  <div class="orders-parcel-what">
                    <strong>{{ parcel.box || "Custom box" }}</strong>
                    <span class="orders-parcel-contents">{{ (parcel.contents || []).join(", ") }}</span>
                  </div>
                  <button type="button" class="primary-action orders-label-button"
                          :disabled="buying"
                          @click.stop="labelParcel(order, i)">
                    {{ parcelRate(order, i) ? `Buy ${money(parcelRate(order, i).amount)}` : "Get rate" }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-if="copied" class="orders-copied" role="status">Copied {{ elideId(copied) }}</p>
    </section>

    <!-- One click here spends real money on every selected order, so the total and the carrier-adjustment
         warning are shown at the point of spending rather than in a help page. -->
    <div v-if="confirmBuy" class="modal-backdrop" @click.self="confirmBuy = false">
      <section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="buyLabelsTitle">
        <header class="modal-card-header">
          <h2 id="buyLabelsTitle">Buy {{ buyableIds.length }} label{{ buyableIds.length === 1 ? "" : "s" }}</h2>
          <button type="button" class="modal-close" aria-label="Close" @click="confirmBuy = false">×</button>
        </header>
        <div class="product-details-body">
          <p><strong>{{ money(selectedTotal) }}</strong> will be charged to your carrier account now.</p>
          <p class="field-hint">
            This is what the carrier quoted for the parcels below. A carrier that re-weighs or re-measures
            a parcel bills the difference back to you later — so a wrong box size shows up as a surcharge
            weeks after the order shipped.
          </p>
          <ul class="orders-buy-list">
            <li v-for="row in buyableRows" :key="row.order.order_id">
              {{ row.order.customer?.name || elideId(row.order.order_id) }} —
              {{ row.rate.carrier }} {{ row.rate.service }}
              <strong>{{ money(row.rate.amount, row.rate.currency) }}</strong>
            </li>
          </ul>
          <div class="button-row">
            <button type="button" class="primary-action" :disabled="buying" @click="buySelected">
              {{ buying ? "Buying…" : `Buy ${buyableIds.length} label${buyableIds.length === 1 ? "" : "s"}` }}
            </button>
            <button type="button" class="secondary-action" :disabled="buying" @click="confirmBuy = false">Cancel</button>
          </div>
        </div>
      </section>
    </div>

    <MarkShippedModal v-if="shipping" :order="shipping" :carriers="carriers" :saving="shippingSaving"
                      :error="shippingError" @close="shipping = null" @shipped="submitShipped" />

    <div v-if="handoverKind" class="modal-backdrop" @click.self="handoverKind = ''">
      <section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="handoverTitle">
        <header class="modal-card-header">
          <h2 id="handoverTitle">{{ handoverKind === "pickups" ? "Schedule a pickup" : "Create a manifest" }}</h2>
          <button type="button" class="modal-close" aria-label="Close" @click="handoverKind = ''">×</button>
        </header>
        <div class="product-details-body">
          <p class="field-hint">
            A carrier collects — and scans — one carrier's parcels from one address on one day, so choose
            which batch this is for.
          </p>
          <label>
            Batch
            <select v-model="handoverBatch">
              <option v-for="group in handoverGroups" :key="`${group.carrier}-${group.ship_date}`"
                      :value="`${group.carrier}|${group.ship_date}`">
                {{ group.carrier.toUpperCase() }} — {{ group.ship_date }} — {{ group.transactions.length }}
                label{{ group.transactions.length === 1 ? "" : "s" }} ({{ money(group.total) }})
              </option>
            </select>
          </label>
          <div v-if="handoverKind === 'pickups'" class="offer-two-column">
            <label>Ready at <input v-model="pickup.start_time" type="datetime-local" /></label>
            <label>Closes at <input v-model="pickup.end_time" type="datetime-local" /></label>
          </div>
          <p v-if="handoverKind === 'pickups'" class="field-hint">
            Carriers need a window, and most have a same-day cutoff. Labels you marked shipped yourself
            are not included — the carrier has no label of ours to scan for those.
          </p>
          <p v-if="handoverError" class="keys-status-banner error">{{ handoverError }}</p>
          <div class="button-row">
            <button type="button" class="primary-action" :disabled="handing || !handoverBatch" @click="submitHandover">
              {{ handing ? "Sending…" : (handoverKind === "pickups" ? "Schedule pickup" : "Create manifest") }}
            </button>
            <button type="button" class="secondary-action" :disabled="handing" @click="handoverKind = ''">Cancel</button>
          </div>
        </div>
      </section>
    </div>

    <OrderDetailDrawer v-if="selected" :order="selected" @close="selected = null" @copy="copyId" />

  </section>
</template>

<script setup>
import { computed, inject, reactive, ref } from "vue";
import { apiRequest } from "../api/client";
import { formatMoney } from "../stores/products";
import { formatEpochDate } from "../utils/format";
import MarkShippedModal from "./orders/MarkShippedModal.vue";
import OrderDetailDrawer from "./orders/OrderDetailDrawer.vue";
import {
  destinationSummary,
  elideId,
  shortOrderRef,
  sortOrders,
} from "./orders/orderDisplay";

const orders = ref([]);
const carriers = ref([]);
const shippingReadiness = ref([]);
const shippingConfigured = ref(false);
const loaded = ref(false);
const loading = ref(false);
const error = ref("");
const message = ref("");
const selected = ref(null);
const filters = reactive({ customer: "", status: "" });

const formatDate = formatEpochDate;

// The SERVER already sorts newest-first, and re-sorting in the browser only reorders what was fetched --
// which is the honest scope of a column sort on a list that is not paginated yet. When paging arrives this
// has to move to the query, and the caret must stop implying it sorted everything.
const sort = reactive({ key: "created_at", direction: "desc" });

// An upsell is its own ORDER because it is its own charge, but it is not its own PARCEL -- it ships in
// the buyer's existing box, which is why it was charged $0 for postage. Listing it as a peer is how a
// funnel that collected $6.20 was offered $18.20 of labels (plans/FULFILMENT_GROUPS.md). It appears under
// its parent's expander instead.
const visibleOrders = computed(() =>
  sortOrders(orders.value.filter((o) => !o.ships_with), sort.key, sort.direction));

// Expanded groups, by parent order id.
const expanded = ref(new Set());
function toggleGroup(order) {
  const next = new Set(expanded.value);
  next.has(order.order_id) ? next.delete(order.order_id) : next.add(order.order_id);
  expanded.value = next;
}
const ordersById = computed(() =>
  Object.fromEntries(orders.value.map((o) => [o.order_id, o])));
function groupMembers(order) {
  return (order.fulfilment_group?.order_ids || [])
    .map((id) => ordersById.value[id]).filter(Boolean);
}
function parcelsOf(order) {
  return order.fulfilment_group?.parcels || [];
}

// Rates are cached per PARCEL, not per order: a group needing two boxes gets two quotes and two labels,
// and keying them together would show the second box the first box's price.
const parcelRates = ref({});
const parcelKey = (order, index) => `${order.order_id}#${index}`;
function parcelRate(order, index) {
  return parcelRates.value[parcelKey(order, index)]?.selected || null;
}

async function labelParcel(order, index) {
  const key = parcelKey(order, index);
  const cached = parcelRates.value[key];
  if (!cached?.selected) {
    // The tenant sees the price before it is spent, never after -- the same two-step the single-order
    // button uses, because a label is money that cannot be un-spent by refreshing the page.
    try {
      const body = await apiRequest("/shipping/rates", {
        method: "POST", body: { order_id: order.order_id, parcel_index: index },
      });
      parcelRates.value = { ...parcelRates.value, [key]: {
        selected: body.selected || null, parcel: body.parcel || null,
      } };
      if (!body.selected) message.value = "No rate came back for that parcel.";
    } catch (err) {
      message.value = err.message || "No rates.";
    }
    return;
  }
  buying.value = true;
  try {
    await apiRequest("/shipping/labels", {
      method: "POST",
      body: {
        order_id: order.order_id,
        parcel_index: index,
        rate_id: cached.selected.rate_id,
        parcel: cached.parcel,
        amount: cached.selected.amount,
        currency: cached.selected.currency,
      },
    });
    message.value = "Label bought. The buyer was sent their tracking.";
    await load();
  } catch (err) {
    message.value = err.message || "Could not buy that label.";
  } finally {
    buying.value = false;
  }
}

function sortBy(key) {
  if (sort.key === key) {
    sort.direction = sort.direction === "asc" ? "desc" : "asc";
    return;
  }
  sort.key = key;
  // Money and dates read newest/largest first; a name reads A-Z. Matching the expectation of each column
  // saves a second click on the one people actually want.
  sort.direction = key === "customer" ? "asc" : "desc";
}

function caret(key) {
  if (sort.key !== key) return "";
  return sort.direction === "asc" ? "▲" : "▼";
}

// Every column is unconditional now: the author's design is a fulfilment table, and a digital-only tenant
// reads "Not Shippable" down the Status column, which is a true and useful answer rather than an empty
// one. `shippingConfigured` still gates the BANNER and the batch actions, which are genuinely irrelevant
// to a tenant with no provider.

const selected_ = ref(new Set());

const eligibleIds = computed(() =>
  visibleOrders.value.filter((o) => o.fulfilment?.eligible).map((o) => o.order_id));

const selectedIds = computed(() => [...selected_.value]);

const allEligibleSelected = computed(() =>
  eligibleIds.value.length > 0 && eligibleIds.value.every((id) => selected_.value.has(id)));

function toggleOne(order) {
  const next = new Set(selected_.value);
  if (next.has(order.order_id)) next.delete(order.order_id);
  else if (order.fulfilment?.eligible) {
    next.add(order.order_id);
    if (!rates.value[order.order_id]) quote(order);
  }
  selected_.value = next;
}

// Select-all takes only the ELIGIBLE rows. Selecting forty and being told afterwards that four of them
// could not ship is the behaviour this avoids.
function toggleAll() {
  if (allEligibleSelected.value) {
    selected_.value = new Set();
    return;
  }
  selected_.value = new Set(eligibleIds.value);
  // Sequential on purpose: a provider round trip per order, and forty at once is how a rate limit is hit.
  quoteMissing(eligibleIds.value);
}

async function quoteMissing(ids) {
  for (const id of ids) {
    if (rates.value[id]) continue;
    const order = orders.value.find((o) => o.order_id === id);
    if (order) await quote(order);
  }
}

// The shell's navigation, which carries a payload so the destination does not have to guess why it was
// opened. This app has no vue-router; App.vue provides this.
const navigateTo = inject("navigateTo", null);

function measureProduct(item) {
  if (navigateTo) navigateTo("products", { edit: item.product_id });
}

// Rates are fetched when a row is SELECTED or asks for them -- never for a whole page. Every lookup is a
// provider shipment creation: a network call per order, rate-limited and slow, and rating forty rows
// nobody has acted on makes the screen feel broken.
const rates = ref({});
const overrides = ref({});

const money = (cents, currency) => formatMoney(cents, currency || "usd");

function chosenRateId(order) {
  const entry = rates.value[order.order_id];
  return overrides.value[order.order_id] || entry?.selected?.rate_id || "";
}

function chooseRate(order, rateId) {
  // An override is remembered so a later bulk action does not quietly revert the tenant's choice.
  overrides.value = { ...overrides.value, [order.order_id]: rateId };
}

async function quote(order) {
  const id = order.order_id;
  rates.value = { ...rates.value, [id]: { loading: true } };
  try {
    const body = await apiRequest("/shipping/rates", { method: "POST", body: { order_id: id } });
    rates.value = { ...rates.value, [id]: {
      rates: body.rates || [],
      selected: body.selected || null,
      selection_reason: body.selection_reason || "",
      withheld: Boolean(body.withheld),
      parcel: body.parcel || null,
    } };
  } catch (err) {
    rates.value = { ...rates.value, [id]: { error: err.message || "No rates." } };
  }
}

// --- buying ---------------------------------------------------------------------------------------
const confirmBuy = ref(false);
const buying = ref(false);
const buyProgress = reactive({ done: 0, total: 0 });
const buyResults = ref([]);

function rateFor(orderId) {
  const entry = rates.value[orderId];
  if (!entry?.rates?.length) return null;
  const chosen = overrides.value[orderId];
  if (chosen) return entry.rates.find((r) => r.rate_id === chosen) || null;
  // A withheld rate is deliberately NOT bought without the tenant choosing it: it is over their ceiling.
  return entry.withheld ? null : entry.selected;
}

const buyableRows = computed(() => selectedIds.value
  .map((id) => ({ order: orders.value.find((o) => o.order_id === id), rate: rateFor(id) }))
  .filter((row) => row.order && row.rate));

const buyableIds = computed(() => buyableRows.value.map((row) => row.order.order_id));

const selectedTotal = computed(() =>
  buyableRows.value.reduce((total, row) => total + Number(row.rate.amount || 0), 0));

const buyFailures = computed(() => buyResults.value.filter((row) => row.error));

// Bulk is the CLIENT driving a one-order endpoint: twenty purchases cannot fit in one request, and a
// timeout mid-batch would leave the tenant not knowing which labels were bought. Sequential, past
// failures, with a per-row outcome.
async function buySelected() {
  confirmBuy.value = false;
  buying.value = true;
  buyResults.value = [];
  const rows = buyableRows.value;
  buyProgress.done = 0;
  buyProgress.total = rows.length;
  for (const row of rows) {
    const id = row.order.order_id;
    try {
      await apiRequest("/shipping/labels", {
        method: "POST",
        body: {
          order_id: id,
          rate_id: row.rate.rate_id,
          parcel: rates.value[id]?.parcel,
          amount: row.rate.amount,
          currency: row.rate.currency,
        },
      });
      buyResults.value = [...buyResults.value, { order_id: id }];
    } catch (err) {
      buyResults.value = [...buyResults.value, { order_id: id, error: err.message || "Failed." }];
    }
    buyProgress.done += 1;
  }
  buying.value = false;
  selected_.value = new Set();
  await load();
}

const shipping = ref(null);
const shippingSaving = ref(false);
const shippingError = ref("");

async function submitShipped(form) {
  const order = shipping.value;
  if (!order) return;
  shippingSaving.value = true;
  shippingError.value = "";
  try {
    const body = await apiRequest(`/orders/${encodeURIComponent(order.order_id)}/ship`, {
      method: "POST",
      body: form,
    });
    shipping.value = null;
    // The parcel shipped even when the email did not, so say which happened rather than implying both.
    const notified = body?.notification || {};
    message.value = notified.sent
      ? `Marked shipped. ${order.customer?.email || "The buyer"} was notified.`
      : "Marked shipped — but the buyer could NOT be notified. Open the order to resend.";
    await load();
  } catch (err) {
    shippingError.value = err.message || "Failed to mark shipped.";
  } finally {
    shippingSaving.value = false;
  }
}

// --- export, pickups and manifests ------------------------------------------------------------------
const handoverGroups = ref([]);
const handoverKind = ref("");
const handoverBatch = ref("");
const handoverError = ref("");
const handing = ref(false);
const exporting = ref(false);
const pickup = reactive({ start_time: "", end_time: "" });

async function exportCsv() {
  exporting.value = true;
  try {
    const csv = await apiRequest("/orders", {
      params: { status: filters.status, customer: filters.customer, format: "csv" },
      raw: true,
    });
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `orders-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    error.value = err.message || "Export failed.";
  } finally {
    exporting.value = false;
  }
}

async function submitHandover() {
  const [carrier, shipDate] = String(handoverBatch.value || "").split("|");
  if (!carrier || !shipDate) return;
  handing.value = true;
  handoverError.value = "";
  try {
    const body = { carrier, ship_date: shipDate };
    if (handoverKind.value === "pickups") {
      // A carrier needs a real window; sending a blank one gets refused at their end, not ours.
      body.start_time = new Date(pickup.start_time).toISOString();
      body.end_time = new Date(pickup.end_time).toISOString();
    }
    const result = await apiRequest(`/shipping/${handoverKind.value}`, { method: "POST", body });
    message.value = handoverKind.value === "pickups"
      ? `Pickup confirmed (${result.pickup?.confirmation_code || "booked"}) for ${result.shipments} parcel(s).`
      : `Manifest created for ${result.shipments} parcel(s).`;
    handoverKind.value = "";
    await load();
  } catch (err) {
    handoverError.value = err.message || "The carrier refused that batch.";
  } finally {
    handing.value = false;
  }
}

// A row is clickable, but the controls inside it are not the row. Without this, Mark shipped would also
// open the drawer behind its own modal.
function openDetail(order, event) {
  if (event?.target?.closest("button, a, input, select, label")) return;
  selected.value = order;
}

// --- the row's cells ---------------------------------------------------------------------------------

function carrierOf(order) {
  const shipment = order?.fulfilment?.shipment;
  if (!shipment) return "";
  // The service already names the carrier ("USPS Ground Advantage"), so showing both repeats it.
  return shipment.service || shipment.carrier || "";
}

function fulfilledOn(order) {
  const shipment = order?.fulfilment?.shipment;
  const stamp = shipment?.shipped_at || shipment?.purchased_at;
  return stamp ? formatDate(stamp) : "";
}

// Ready AND rated: a label cannot be bought without a rate to buy, and a rate withheld by the tenant's
// own ceiling has to be chosen by hand first.
function canLabel(order) {
  return Boolean(order?.fulfilment?.eligible && rateFor(order.order_id));
}

function labelTitle(order) {
  if (!order?.fulfilment?.eligible) return (order?.fulfilment?.reasons || []).join(" ");
  if (!rates.value[order.order_id]) return "Get rates first";
  if (rates.value[order.order_id]?.withheld) return "This rate is above your limit — choose one";
  return "";
}

async function labelOne(order) {
  if (!rates.value[order.order_id]) {
    await quote(order);
    return; // the tenant sees the rate before it is bought, never after
  }
  selected_.value = new Set([order.order_id]);
  await buySelected();
}

// --- address deliverability --------------------------------------------------------------------------
// Asked ONCE per address, in one bounded batch, never per render: a verdict does not change between two
// loads of the same list, and a call per row would make the page crawl.
const checkingAddresses = ref(false);

async function checkAddresses({ silent = false } = {}) {
  if (checkingAddresses.value || !shippingConfigured.value) return;
  checkingAddresses.value = true;
  try {
    const body = await apiRequest("/orders/validate-addresses", { method: "POST", body: {} });
    // Say what happened. The button removes itself once nothing is unchecked, so without this the whole
    // interaction is "I clicked something and it vanished".
    message.value = describeCheck(body);
    if (body?.checked) await load();
  } catch (err) {
    // A failed check leaves every order exactly as it was -- unchecked, not undeliverable. Only say so
    // when the tenant asked; doing it on load and shouting about an outage helps nobody.
    if (!silent) error.value = err.message || "Could not check addresses.";
  } finally {
    checkingAddresses.value = false;
  }
}

function describeCheck(body) {
  const checked = Number(body?.checked || 0);
  if (!checked) return "No addresses needed checking.";
  const tally = body?.summary || {};
  const parts = [];
  if (tally.deliverable) parts.push(`${tally.deliverable} deliverable`);
  if (tally.undeliverable) parts.push(`${tally.undeliverable} undeliverable`);
  // "Could not check" is not "will not deliver" and must not read like it.
  if (tally.unknown) parts.push(`${tally.unknown} the carrier could not confirm`);
  const suggestions = Number(body?.suggestions || 0);
  const tail = suggestions
    ? ` The carrier suggests a more precise address for ${suggestions} — open the order to see it.`
    : "";
  return `Checked ${checked} address${checked === 1 ? "" : "es"}: ${parts.join(", ")}.${tail}`;
}

const uncheckedCount = computed(() =>
  orders.value.filter((o) => o.shipping_address && !o.address_validation).length);

const copied = ref("");
let copyTimer = null;

async function copyId(orderId) {
  try {
    await navigator.clipboard.writeText(String(orderId || ""));
    copied.value = orderId;
    clearTimeout(copyTimer);
    copyTimer = setTimeout(() => { copied.value = ""; }, 2000);
  } catch {
    // Clipboard is permission-gated and blocked outright in some embeddings. The id is in the title
    // attribute either way, so a failure costs the reader nothing worth reporting.
  }
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const body = await apiRequest("/orders", { params: { status: filters.status, customer: filters.customer } });
    orders.value = Array.isArray(body.orders) ? body.orders : [];
    carriers.value = Array.isArray(body.carriers) ? body.carriers : [];
    shippingReadiness.value = Array.isArray(body.shipping_readiness) ? body.shipping_readiness : [];
    shippingConfigured.value = Boolean(body.shipping_configured);
    handoverGroups.value = Array.isArray(body.handover_groups) ? body.handover_groups : [];
    if (handoverGroups.value.length && !handoverBatch.value) {
      const first = handoverGroups.value[0];
      handoverBatch.value = `${first.carrier}|${first.ship_date}`;
    }
    // A reload must not leave an order selected that is no longer selectable -- it has just shipped.
    const stillEligible = new Set(orders.value.filter((o) => o.fulfilment?.eligible).map((o) => o.order_id));
    selected_.value = new Set([...selected_.value].filter((id) => stillEligible.has(id)));
    loaded.value = true;
    message.value = orders.value.length ? `${orders.value.length} order${orders.value.length === 1 ? "" : "s"}.` : "";
  } catch (err) {
    error.value = err.message || "Failed to load orders.";
  } finally {
    loading.value = false;
  }
}

// These screens filter SERVER-SIDE (load() sends the filters as query params), so a filter change means a
// re-fetch. Debounce the text field so it's not one request per keystroke; the status dropdown fetches on
// change. No Apply button — the list stays in sync with the filters.
let filterTimer = null;
function onFilterInput() {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(load, 400);
}

function resetFilters() {
  filters.customer = "";
  filters.status = "";
  load();
}

load();
</script>
