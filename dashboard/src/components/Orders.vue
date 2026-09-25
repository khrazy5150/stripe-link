<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Orders</h1>
        <p>Sales recorded from completed checkouts and one-click upsells</p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="loading" @click="load">
          {{ loading ? "Loading..." : "Reload" }}
        </button>
      </div>
    </header>

    <section class="dashboard-card">
      <div class="product-filter-bar">
        <label>
          Search
          <input v-model.trim="filters.customer" type="search" placeholder="Customer name or email..." @input="onFilterInput" @keyup.enter="load" />
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
        <span class="orders-secondary">Buying labels arrives next — for now, mark them shipped one at a time.</span>
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
              <th v-if="showFulfilment" scope="col" class="orders-col-select">
                <input type="checkbox" :checked="allEligibleSelected" :disabled="!eligibleIds.length"
                       :aria-label="allEligibleSelected ? 'Clear selection' : 'Select all shippable orders'"
                       @change="toggleAll" />
              </th>
              <th scope="col" class="orders-col-order">
                <button type="button" class="orders-sort" @click="sortBy('created_at')">
                  Order <span class="orders-sort-caret">{{ caret("created_at") }}</span>
                </button>
              </th>
              <th scope="col">
                <button type="button" class="orders-sort" @click="sortBy('customer')">
                  Customer <span class="orders-sort-caret">{{ caret("customer") }}</span>
                </button>
              </th>
              <th scope="col">Items</th>
              <th v-if="showFulfilment" scope="col">Fulfilment</th>
              <th v-if="showFulfilment" scope="col" class="orders-col-rate">Rate</th>
              <th scope="col" class="orders-col-money">
                <button type="button" class="orders-sort" @click="sortBy('amount_total')">
                  Total <span class="orders-sort-caret">{{ caret("amount_total") }}</span>
                </button>
              </th>
              <th scope="col">Status</th>
              <th scope="col"><span class="visually-hidden">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="order in visibleOrders" :key="order.order_id"
                :class="{ 'orders-row-selected': selected_.has(order.order_id) }">
              <td v-if="showFulfilment" class="orders-col-select">
                <input type="checkbox" :checked="selected_.has(order.order_id)"
                       :disabled="!order.fulfilment?.eligible"
                       :title="order.fulfilment?.eligible ? '' : (order.fulfilment?.reasons || []).join(' ')"
                       :aria-label="`Select order ${order.order_id}`"
                       @change="toggleOne(order)" />
              </td>
              <td class="orders-col-order">
                <div class="orders-primary">{{ order.product?.name || itemsSummary(order) }}</div>
                <button type="button" class="orders-id font-mono" :title="`${order.order_id} — click to copy`"
                        @click="copyId(order.order_id)">{{ elideId(order.order_id) }}</button>
                <div class="orders-secondary">{{ formatDate(order.created_at) }}</div>
              </td>
              <td>
                <div class="orders-primary">{{ order.customer?.name || order.customer?.email || "—" }}</div>
                <div v-if="destinationSummary(order)" class="orders-secondary">{{ destinationSummary(order) }}</div>
              </td>
              <td>{{ itemsSummary(order) }}</td>
              <td v-if="showFulfilment" class="orders-col-fulfilment">
                <template v-if="order.fulfilment?.status === 'shipped'">
                  <span class="product-status active">Shipped</span>
                  <div v-if="order.fulfilment.shipment?.tracking_number" class="orders-secondary">
                    <a v-if="order.fulfilment.shipment.tracking_url" :href="order.fulfilment.shipment.tracking_url"
                       target="_blank" rel="noopener">{{ order.fulfilment.shipment.tracking_number }}</a>
                    <span v-else>{{ order.fulfilment.shipment.tracking_number }}</span>
                  </div>
                </template>
                <template v-else-if="order.fulfilment?.status === 'ready'">
                  <span class="product-status active">Ready to ship</span>
                </template>
                <template v-else>
                  <div class="orders-secondary">{{ (order.fulfilment?.reasons || []).join(" ") || "—" }}</div>
                  <!-- The ONLY gate with a call to action: the tenant can fix a missing measurement. -->
                  <button v-for="item in order.fulfilment?.needs_measurement || []" :key="item.product_id"
                          type="button" class="link-action" @click="measureProduct(item)">
                    + Add package info for {{ item.name }}
                  </button>
                </template>
              </td>
              <td class="orders-col-money">
                <div class="orders-primary">{{ formatMoney(order.amount_total, order.currency) }}</div>
                <div v-if="Number(order.amount_refunded) > 0" class="orders-secondary">
                  −{{ formatMoney(order.amount_refunded, order.currency) }} refunded
                </div>
              </td>
              <td>
                <span class="product-status" :class="statusBadgeClass(orderStatus(order))">
                  {{ statusLabel(orderStatus(order)) }}
                </span>
              </td>
              <td v-if="showFulfilment" class="orders-col-rate">
                <template v-if="rates[order.order_id]?.loading">
                  <span class="orders-secondary">Getting rates…</span>
                </template>
                <template v-else-if="rates[order.order_id]?.error">
                  <span class="orders-rate-error">{{ rates[order.order_id].error }}</span>
                </template>
                <template v-else-if="rates[order.order_id]?.selected">
                  <select class="orders-rate-select" :value="chosenRateId(order)"
                          :aria-label="`Shipping rate for order ${order.order_id}`"
                          @change="chooseRate(order, $event.target.value)">
                    <option v-for="rate in rates[order.order_id].rates" :key="rate.rate_id" :value="rate.rate_id">
                      {{ rate.carrier }} {{ rate.service }} — {{ money(rate.amount, rate.currency) }}{{ rate.estimated_days ? ` · ${rate.estimated_days}d` : "" }}
                    </option>
                  </select>
                  <div class="orders-secondary">
                    <template v-if="overrides[order.order_id]">you chose this</template>
                    <template v-else>{{ rates[order.order_id].selection_reason }}</template>
                  </div>
                  <div v-if="rates[order.order_id].withheld && !overrides[order.order_id]"
                       class="orders-rate-error">Above your limit — choose a rate to continue.</div>
                </template>
                <template v-else-if="order.fulfilment?.status === 'ready'">
                  <!-- Rated on demand, never for the whole page: each lookup is a provider round trip. -->
                  <button type="button" class="link-action" @click="quote(order)">Get rates</button>
                </template>
                <span v-else class="orders-secondary">—</span>
              </td>
              <td class="orders-col-actions">
                <button v-if="showFulfilment && order.fulfilment?.status === 'ready'" type="button"
                        class="secondary-action" @click="shipping = order">Mark shipped</button>
                <button type="button" class="secondary-action" @click="selected = order">Details</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-if="copied" class="orders-copied" role="status">Copied {{ elideId(copied) }}</p>
    </section>

    <MarkShippedModal v-if="shipping" :order="shipping" :carriers="carriers" :saving="shippingSaving"
                      :error="shippingError" @close="shipping = null" @shipped="submitShipped" />

    <div v-if="selected" class="modal-backdrop" @click.self="selected = null">
      <section class="modal-card product-details-modal" role="dialog" aria-modal="true" aria-labelledby="orderDetailsTitle">
        <header class="modal-card-header">
          <h2 id="orderDetailsTitle">Order Details</h2>
          <button type="button" class="modal-close" aria-label="Close order details" @click="selected = null">×</button>
        </header>
        <div class="product-details-body">
          <dl class="product-details-grid">
            <div><dt>Order ID</dt><dd class="font-mono">{{ selected.order_id }}</dd></div>
            <div><dt>Status</dt><dd>{{ statusLabel(orderStatus(selected)) }}</dd></div>
            <div><dt>Amount</dt><dd>{{ formatMoney(selected.amount_total, selected.currency) }}</dd></div>
            <div v-if="Number(selected.amount_refunded) > 0"><dt>Refunded</dt><dd>{{ formatMoney(selected.amount_refunded, selected.currency) }}</dd></div>
            <div v-if="Number(selected.amount_refunded) > 0"><dt>Refundable</dt><dd>{{ formatMoney(selected.refundable_amount, selected.currency) }}</dd></div>
            <div><dt>Date</dt><dd>{{ formatDate(selected.created_at) }}</dd></div>
            <div><dt>Customer</dt><dd>{{ selected.customer?.name || "—" }}</dd></div>
            <div><dt>Email</dt><dd>{{ selected.customer?.email || "—" }}</dd></div>
            <div><dt>Product</dt><dd>{{ selected.product?.name || "—" }}</dd></div>
            <div><dt>Type</dt><dd>{{ statusLabel(selected.line_item_type || "checkout") }}</dd></div>
          </dl>
          <template v-if="selected.fees">
            <h3 class="details-subheading">Fees</h3>
            <dl class="product-details-grid">
              <div><dt>Gross</dt><dd>{{ formatMoney(selected.fees.tenant_keyed_amount, selected.currency) }}</dd></div>
              <div><dt>Stripe Fee</dt><dd>{{ formatMoney(selected.fees.stripe_fee, selected.currency) }}</dd></div>
              <div><dt>Platform Fee</dt><dd>{{ formatMoney(selected.fees.platform_fee, selected.currency) }}</dd></div>
              <div><dt>Net Payout</dt><dd>{{ formatMoney(selected.fees.net_payout, selected.currency) }}</dd></div>
            </dl>
          </template>
          <details class="product-json-details">
            <summary>Raw JSON</summary>
            <pre>{{ JSON.stringify(selected, null, 2) }}</pre>
          </details>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, inject, reactive, ref } from "vue";
import { apiRequest } from "../api/client";
import { formatMoney } from "../stores/products";
import { formatEpochDate, statusLabel } from "../utils/format";
import MarkShippedModal from "./orders/MarkShippedModal.vue";
import {
  destinationSummary,
  elideId,
  itemsSummary,
  orderStatus,
  sortOrders,
  statusBadgeClass,
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

const visibleOrders = computed(() => sortOrders(orders.value, sort.key, sort.direction));

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

// The fulfilment columns exist only for a tenant this feature is relevant to. A tenant selling downloads
// should never learn that a shipping module exists by finding empty columns in their sales list.
const showFulfilment = computed(() =>
  shippingConfigured.value || orders.value.some((o) => o.fulfilment?.status === "shipped"
    || o.fulfilment?.status === "ready" || (o.fulfilment?.needs_measurement || []).length));

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
