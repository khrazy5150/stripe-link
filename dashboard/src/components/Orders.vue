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

      <div v-else class="coupon-card-grid">
        <article v-for="order in orders" :key="order.order_id" class="coupon-card">
          <header>
            <div>
              <h3>{{ order.product?.name || "Checkout" }}</h3>
              <p class="font-mono">{{ order.order_id }}</p>
            </div>
            <span class="product-status" :class="paymentBadgeClass(orderStatus(order))">{{ statusLabel(orderStatus(order)) }}</span>
          </header>
          <strong class="coupon-discount">{{ formatMoney(order.amount_total, order.currency) }}</strong>
          <dl class="coupon-detail-list">
            <div><dt>Customer</dt><dd>{{ order.customer?.name || order.customer?.email || "—" }}</dd></div>
            <div v-if="Number(order.amount_refunded) > 0"><dt>Refunded</dt><dd>{{ formatMoney(order.amount_refunded, order.currency) }}</dd></div>
            <div><dt>Date</dt><dd>{{ formatDate(order.created_at) }}</dd></div>
          </dl>
          <div class="product-card-actions">
            <button type="button" class="secondary-action" @click="selected = order">Details</button>
          </div>
        </article>
      </div>
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
import { reactive, ref } from "vue";
import { apiRequest } from "../api/client";
import { formatMoney } from "../stores/products";
import { formatEpochDate, statusLabel } from "../utils/format";

const orders = ref([]);
const loaded = ref(false);
const loading = ref(false);
const error = ref("");
const message = ref("");
const selected = ref(null);
const filters = reactive({ customer: "", status: "" });

const formatDate = formatEpochDate;

function orderStatus(order) {
  return order?.payment_status || order?.status || "paid";
}

function paymentBadgeClass(status) {
  return {
    paid: "active",
    completed: "active",
    partially_refunded: "warning",
    refunded: "inactive",
    disputed: "archived",
    cancelled: "archived",
  }[status] || "inactive";
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
