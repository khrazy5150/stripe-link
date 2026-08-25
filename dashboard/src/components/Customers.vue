<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Customers</h1>
        <p>People who have purchased, with lifetime value and purchase history</p>
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
          <input v-model.trim="filters.customer" type="search" placeholder="Name, email, or phone..." @input="onFilterInput" @keyup.enter="load" />
        </label>
        <label>
          Product
          <input v-model.trim="filters.product" type="search" placeholder="Product name or ID..." @input="onFilterInput" @keyup.enter="load" />
        </label>
        <div class="product-filter-actions">
          <button type="button" class="secondary-action" @click="resetFilters">Reset</button>
        </div>
      </div>

      <div v-if="error" class="keys-status-banner error">{{ error }}</div>
      <div v-else class="keys-status-banner">{{ message }}</div>

      <div v-if="!customers.length" class="product-empty-state">
        {{ loaded ? "No customers found." : "Loading customers..." }}
      </div>

      <div v-else class="coupon-card-grid">
        <article v-for="customer in customers" :key="customer.customer_id" class="coupon-card">
          <header>
            <div>
              <h3>{{ customer.contact?.name || customer.contact?.email || "Customer" }}</h3>
              <p class="font-mono">{{ customer.contact?.email || customer.customer_id }}</p>
            </div>
          </header>
          <strong class="coupon-discount">{{ formatMoney(lifetimeValue(customer), currency(customer)) }}</strong>
          <dl class="coupon-detail-list">
            <div><dt>Orders</dt><dd>{{ customer.summary?.total_orders ?? 0 }}</dd></div>
            <div><dt>Last Purchase</dt><dd>{{ formatDate(lastPurchase(customer)) }}</dd></div>
            <div><dt>Phone</dt><dd>{{ customer.contact?.phone || "—" }}</dd></div>
          </dl>
          <div class="product-card-actions">
            <button type="button" class="secondary-action" @click="selected = customer">Details</button>
          </div>
        </article>
      </div>
    </section>

    <div v-if="selected" class="modal-backdrop" @click.self="selected = null">
      <section class="modal-card product-details-modal" role="dialog" aria-modal="true" aria-labelledby="customerDetailsTitle">
        <header class="modal-card-header">
          <h2 id="customerDetailsTitle">Customer Details</h2>
          <button type="button" class="modal-close" aria-label="Close customer details" @click="selected = null">×</button>
        </header>
        <div class="product-details-body">
          <dl class="product-details-grid">
            <div><dt>Name</dt><dd>{{ selected.contact?.name || "—" }}</dd></div>
            <div><dt>Email</dt><dd>{{ selected.contact?.email || "—" }}</dd></div>
            <div><dt>Phone</dt><dd>{{ selected.contact?.phone || "—" }}</dd></div>
            <div><dt>Total Orders</dt><dd>{{ selected.summary?.total_orders ?? 0 }}</dd></div>
            <div><dt>Lifetime Value</dt><dd>{{ formatMoney(lifetimeValue(selected), currency(selected)) }}</dd></div>
            <div><dt>Last Purchase</dt><dd>{{ formatDate(lastPurchase(selected)) }}</dd></div>
          </dl>
          <template v-if="selected.transaction_history?.length">
            <h3 class="details-subheading">Recent Transactions</h3>
            <dl class="product-details-grid">
              <div v-for="(txn, index) in selected.transaction_history" :key="txn.transaction_id || index">
                <dt>{{ statusLabel(txn.type) }} · {{ formatDate(txn.created_at) }}</dt>
                <dd>{{ formatMoney(txn.amount, txn.currency || currency(selected)) }}</dd>
              </div>
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

const customers = ref([]);
const loaded = ref(false);
const loading = ref(false);
const error = ref("");
const message = ref("");
const selected = ref(null);
const filters = reactive({ customer: "", product: "" });

const formatDate = formatEpochDate;

// Customer records come from two writers with slightly different field names
// (webhook: lifetime_value/last_order_at; schema/upsell: total_spent/last_purchase_at),
// so read both defensively.
function lifetimeValue(customer) {
  const summary = customer.summary || {};
  return summary.total_spent ?? summary.lifetime_value ?? 0;
}

function lastPurchase(customer) {
  const summary = customer.summary || {};
  return summary.last_purchase_at ?? summary.last_order_at ?? null;
}

function currency(customer) {
  return customer.summary?.currency || "usd";
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const body = await apiRequest("/customers", { params: { customer: filters.customer, product: filters.product } });
    customers.value = Array.isArray(body.customers) ? body.customers : [];
    loaded.value = true;
    message.value = customers.value.length ? `${customers.value.length} customer${customers.value.length === 1 ? "" : "s"}.` : "";
  } catch (err) {
    error.value = err.message || "Failed to load customers.";
  } finally {
    loading.value = false;
  }
}

// Server-side filtering: a filter change means a re-fetch. Debounce the text fields so it's not one request
// per keystroke. No Apply button — the list stays in sync with the filters.
let filterTimer = null;
function onFilterInput() {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(load, 400);
}

function resetFilters() {
  filters.customer = "";
  filters.product = "";
  load();
}

load();
</script>
