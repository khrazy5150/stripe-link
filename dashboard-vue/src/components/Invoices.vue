<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Invoices</h1>
        <p>Local invoice records for completed checkouts and custom invoices</p>
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
          <input v-model.trim="filters.customer" type="search" placeholder="Customer name or email..." @keyup.enter="load" />
        </label>
        <label>
          Status
          <select v-model="filters.status">
            <option value="">All</option>
            <option value="paid">Paid</option>
            <option value="open">Open</option>
            <option value="void">Void</option>
          </select>
        </label>
        <div class="product-filter-actions">
          <button type="button" class="primary-action" @click="load">Apply</button>
          <button type="button" class="secondary-action" @click="resetFilters">Reset</button>
        </div>
      </div>

      <div v-if="error" class="keys-status-banner error">{{ error }}</div>
      <div v-else class="keys-status-banner">{{ message }}</div>

      <div v-if="!invoices.length" class="product-empty-state">
        {{ loaded ? "No invoices found." : "Loading invoices..." }}
      </div>

      <div v-else class="coupon-card-grid">
        <article v-for="invoice in invoices" :key="invoice.invoice_id" class="coupon-card">
          <header>
            <div>
              <h3>{{ invoice.customer?.name || invoice.customer?.email || "Invoice" }}</h3>
              <p class="font-mono">{{ invoice.invoice_id }}</p>
            </div>
            <span class="product-status" :class="invoice.status">{{ statusLabel(invoice.status) }}</span>
          </header>
          <strong class="coupon-discount">{{ formatMoney(invoice.amounts?.total, invoice.amounts?.currency) }}</strong>
          <dl class="coupon-detail-list">
            <div><dt>Line Items</dt><dd>{{ invoice.line_items?.length || 0 }}</dd></div>
            <div><dt>Paid</dt><dd>{{ formatMoney(invoice.amounts?.amount_paid, invoice.amounts?.currency) }}</dd></div>
            <div><dt>Date</dt><dd>{{ formatDate(invoice.created_at) }}</dd></div>
          </dl>
          <div class="product-card-actions">
            <button type="button" class="secondary-action" @click="selected = invoice">Details</button>
          </div>
        </article>
      </div>
    </section>

    <div v-if="selected" class="modal-backdrop" @click.self="selected = null">
      <section class="modal-card product-details-modal" role="dialog" aria-modal="true" aria-labelledby="invoiceDetailsTitle">
        <header class="modal-card-header">
          <h2 id="invoiceDetailsTitle">Invoice Details</h2>
          <button type="button" class="modal-close" aria-label="Close invoice details" @click="selected = null">×</button>
        </header>
        <div class="product-details-body">
          <dl class="product-details-grid">
            <div><dt>Invoice ID</dt><dd class="font-mono">{{ selected.invoice_id }}</dd></div>
            <div><dt>Status</dt><dd>{{ statusLabel(selected.status) }}</dd></div>
            <div><dt>Customer</dt><dd>{{ selected.customer?.name || "—" }}</dd></div>
            <div><dt>Email</dt><dd>{{ selected.customer?.email || "—" }}</dd></div>
            <div><dt>Date</dt><dd>{{ formatDate(selected.created_at) }}</dd></div>
          </dl>
          <template v-if="selected.line_items?.length">
            <h3 class="details-subheading">Line Items</h3>
            <dl class="product-details-grid">
              <div v-for="(item, index) in selected.line_items" :key="index">
                <dt>{{ item.description || "Item" }} ×{{ item.quantity || 1 }}</dt>
                <dd>{{ formatMoney(item.unit_amount, selected.amounts?.currency) }}</dd>
              </div>
            </dl>
          </template>
          <template v-if="selected.amounts">
            <h3 class="details-subheading">Amounts</h3>
            <dl class="product-details-grid">
              <div><dt>Subtotal</dt><dd>{{ formatMoney(selected.amounts.subtotal, selected.amounts.currency) }}</dd></div>
              <div><dt>Total</dt><dd>{{ formatMoney(selected.amounts.total, selected.amounts.currency) }}</dd></div>
              <div><dt>Amount Paid</dt><dd>{{ formatMoney(selected.amounts.amount_paid, selected.amounts.currency) }}</dd></div>
              <div><dt>Amount Due</dt><dd>{{ formatMoney(selected.amounts.amount_due, selected.amounts.currency) }}</dd></div>
              <div v-if="selected.amounts.net_payout != null"><dt>Net Payout</dt><dd>{{ formatMoney(selected.amounts.net_payout, selected.amounts.currency) }}</dd></div>
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

const invoices = ref([]);
const loaded = ref(false);
const loading = ref(false);
const error = ref("");
const message = ref("");
const selected = ref(null);
const filters = reactive({ customer: "", status: "" });

const formatDate = formatEpochDate;

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const body = await apiRequest("/invoices", { params: { status: filters.status, customer: filters.customer } });
    invoices.value = Array.isArray(body.invoices) ? body.invoices : [];
    loaded.value = true;
    message.value = invoices.value.length ? `${invoices.value.length} invoice${invoices.value.length === 1 ? "" : "s"}.` : "";
  } catch (err) {
    error.value = err.message || "Failed to load invoices.";
  } finally {
    loading.value = false;
  }
}

function resetFilters() {
  filters.customer = "";
  filters.status = "";
  load();
}

load();
</script>
