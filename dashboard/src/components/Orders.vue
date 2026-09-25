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

      <div v-if="!orders.length" class="product-empty-state">
        {{ loaded ? "No orders found." : "Loading orders..." }}
      </div>

      <!-- A fulfilment table, not a card grid: twelve orders to post must be visible and comparable at
           once. Horizontal scroll lives on the wrapper so the PAGE never scrolls sideways. -->
      <div v-else class="orders-table-wrap">
        <table class="orders-table">
          <thead>
            <tr>
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
            <tr v-for="order in visibleOrders" :key="order.order_id">
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
              <td class="orders-col-actions">
                <button type="button" class="secondary-action" @click="selected = order">Details</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-if="copied" class="orders-copied" role="status">Copied {{ elideId(copied) }}</p>
    </section>

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
import { computed, reactive, ref } from "vue";
import { apiRequest } from "../api/client";
import { formatMoney } from "../stores/products";
import { formatEpochDate, statusLabel } from "../utils/format";
import {
  destinationSummary,
  elideId,
  itemsSummary,
  orderStatus,
  sortOrders,
  statusBadgeClass,
} from "./orders/orderDisplay";

const orders = ref([]);
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
