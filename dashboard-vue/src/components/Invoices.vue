<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Invoices</h1>
        <p>Create and send payable invoices, and review invoice records</p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="loading" @click="load">
          {{ loading ? "Loading..." : "Reload" }}
        </button>
        <button class="primary-action" type="button" @click="openCreate">+ Create Invoice</button>
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
            <option value="draft">Draft</option>
            <option value="open">Open</option>
            <option value="paid">Paid</option>
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
        {{ loaded ? "No invoices found. Create one to get started." : "Loading invoices..." }}
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
          <strong class="coupon-discount">{{ formatMoney(invoiceTotal(invoice), invoiceCurrency(invoice)) }}</strong>
          <dl class="coupon-detail-list">
            <div><dt>Line Items</dt><dd>{{ invoice.line_items?.length || 0 }}</dd></div>
            <div><dt>Date</dt><dd>{{ formatDate(invoice.created_at) }}</dd></div>
          </dl>
          <div v-if="invoice.payment?.hosted_invoice_url" class="invoice-pay-link">
            <a :href="invoice.payment.hosted_invoice_url" target="_blank" rel="noopener">Pay page</a>
            <button type="button" class="secondary-action compact" @click="copyLink(invoice.payment.hosted_invoice_url)">Copy link</button>
          </div>
          <div class="product-card-actions">
            <button
              v-if="canSend(invoice)"
              type="button"
              class="primary-action"
              :disabled="sending === invoice.invoice_id"
              @click="send(invoice)"
            >
              {{ sending === invoice.invoice_id ? "Sending…" : invoice.status === "draft" ? "Finalize &amp; send" : "Resend" }}
            </button>
            <button type="button" class="secondary-action" @click="selected = invoice">Details</button>
          </div>
        </article>
      </div>
    </section>

    <!-- Create invoice -->
    <div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false">
      <section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="invoiceCreateTitle">
        <header class="modal-card-header">
          <h2 id="invoiceCreateTitle">Create Invoice</h2>
          <button type="button" class="modal-close" aria-label="Close" @click="showCreate = false">×</button>
        </header>
        <form class="coupon-form" @submit.prevent="saveInvoice">
          <div v-if="formError" class="keys-status-banner error">{{ formError }}</div>

          <section class="offer-form-section">
            <div class="offer-two-column">
              <label class="offer-field"><span>Customer Name</span><input v-model.trim="form.name" type="text" /></label>
              <label class="offer-field"><span>Customer Email <strong>*</strong></span><input v-model.trim="form.email" type="email" required /></label>
            </div>
            <label class="offer-field"><span>Customer Phone (optional)</span><input v-model.trim="form.phone" type="tel" /></label>
          </section>

          <section class="offer-form-section">
            <header class="offer-section-header">
              <div><h3>Line Items</h3><p>Add from a service or enter custom items.</p></div>
            </header>
            <div class="offer-three-column">
              <label class="offer-field">
                <span>Add from service</span>
                <select v-model="serviceToAdd">
                  <option value="">Select service…</option>
                  <option v-for="s in services.services" :key="s.service_id" :value="s.service_id">{{ s.name }}</option>
                </select>
              </label>
              <div class="offer-field services-form-actions" style="align-self:end">
                <button type="button" class="secondary-action" :disabled="!serviceToAdd" @click="addServiceLine">Add service</button>
                <button type="button" class="secondary-action" @click="addCustomLine">Add custom item</button>
              </div>
            </div>
            <table v-if="form.line_items.length" class="dashboard-table services-table">
              <thead><tr><th>Description</th><th>Qty</th><th>Price</th><th></th></tr></thead>
              <tbody>
                <tr v-for="(item, index) in form.line_items" :key="index">
                  <td><input v-model.trim="item.description" type="text" placeholder="Description" /></td>
                  <td><input v-model.number="item.quantity" type="number" min="1" style="width:5rem" /></td>
                  <td><input v-model.number="item.amount" type="number" min="0" step="0.01" style="width:8rem" /></td>
                  <td><button type="button" class="secondary-action compact" @click="form.line_items.splice(index, 1)">Remove</button></td>
                </tr>
              </tbody>
            </table>
            <p v-else class="product-empty-state">No line items yet.</p>
          </section>

          <section class="offer-form-section">
            <label class="offer-field"><span>Memo (optional)</span><textarea v-model.trim="form.memo" rows="2"></textarea></label>
          </section>

          <footer class="modal-footer">
            <button class="secondary-action" type="button" @click="showCreate = false">Cancel</button>
            <button class="primary-action" type="submit" :disabled="saving">{{ saving ? "Saving…" : "Save draft" }}</button>
          </footer>
        </form>
      </section>
    </div>

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
            <div v-if="selected.payment?.hosted_invoice_url"><dt>Pay page</dt><dd><a :href="selected.payment.hosted_invoice_url" target="_blank" rel="noopener">Open</a></dd></div>
          </dl>
          <template v-if="selected.line_items?.length">
            <h3 class="details-subheading">Line Items</h3>
            <dl class="product-details-grid">
              <div v-for="(item, index) in selected.line_items" :key="index">
                <dt>{{ item.description || "Item" }} ×{{ item.quantity || 1 }}</dt>
                <dd>{{ formatMoney(item.unit_amount, invoiceCurrency(selected)) }}</dd>
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
import { onMounted, reactive, ref } from "vue";
import { apiRequest, getApiEnvironment, getTenantId } from "../api/client";
import { formatMoney, useProductsStore } from "../stores/products";
import { useServicesStore } from "../stores/services";
import { formatEpochDate, statusLabel } from "../utils/format";

const invoices = ref([]);
const loaded = ref(false);
const loading = ref(false);
const error = ref("");
const message = ref("");
const selected = ref(null);
const sending = ref("");
const filters = reactive({ customer: "", status: "" });

const services = useServicesStore();
useProductsStore();
const showCreate = ref(false);
const saving = ref(false);
const formError = ref("");
const serviceToAdd = ref("");
const form = reactive(defaultForm());

const formatDate = formatEpochDate;

onMounted(load);

function defaultForm() {
  return { name: "", email: "", phone: "", memo: "", line_items: [] };
}

function invoiceCurrency(invoice) {
  return invoice.amounts?.currency || invoice.line_items?.[0]?.currency || "usd";
}
function invoiceTotal(invoice) {
  if (invoice.amounts?.total != null) return invoice.amounts.total;
  return (invoice.line_items || []).reduce((sum, i) => sum + (i.unit_amount || 0) * Math.max(1, i.quantity || 1), 0);
}
function canSend(invoice) {
  return ["draft", "open", "uncollectible"].includes(invoice.status);
}

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

function openCreate() {
  Object.assign(form, defaultForm());
  serviceToAdd.value = "";
  formError.value = "";
  showCreate.value = true;
  if (!services.loaded) services.load();
}

function addCustomLine() {
  form.line_items.push({ description: "", quantity: 1, amount: 0 });
}
function addServiceLine() {
  const svc = services.services.find((s) => s.service_id === serviceToAdd.value);
  if (!svc) return;
  form.line_items.push({
    description: svc.name,
    quantity: 1,
    amount: Number(svc.price?.unit_amount || 0) / 100,
    service_id: svc.service_id,
  });
  serviceToAdd.value = "";
}

async function saveInvoice() {
  formError.value = "";
  if (!form.email) { formError.value = "Customer email is required."; return; }
  if (!form.line_items.length) { formError.value = "Add at least one line item."; return; }
  saving.value = true;
  try {
    const invoice = buildInvoiceDocument(form);
    const body = await apiRequest("/invoices", { method: "POST", body: invoice });
    const saved = body.invoice || invoice;
    invoices.value.unshift(saved);
    showCreate.value = false;
  } catch (err) {
    formError.value = err.message || "Failed to save invoice.";
  } finally {
    saving.value = false;
  }
}

async function send(invoice) {
  sending.value = invoice.invoice_id;
  error.value = "";
  try {
    const body = await apiRequest(`/invoices/${encodeURIComponent(invoice.invoice_id)}/send`, { method: "POST", body: {} });
    const updated = body.invoice;
    if (updated) {
      const index = invoices.value.findIndex((i) => i.invoice_id === updated.invoice_id);
      if (index >= 0) invoices.value.splice(index, 1, updated);
    }
    message.value = body.delivered ? "Invoice sent." : "Invoice finalized (email not sent — check the pay link).";
  } catch (err) {
    error.value = err.message || "Failed to send invoice.";
  } finally {
    sending.value = "";
  }
}

function copyLink(url) {
  navigator.clipboard?.writeText(url);
  message.value = "Pay link copied.";
}

function buildInvoiceDocument(f) {
  const now = Math.floor(Date.now() / 1000);
  const currency = "usd";
  const lineItems = f.line_items.map((i) => ({
    type: i.service_id ? "service" : "custom",
    description: String(i.description || "Item"),
    quantity: Math.max(1, Number(i.quantity || 1)),
    unit_amount: Math.max(0, Math.round(Number(i.amount || 0) * 100)),
    currency,
    ...(i.service_id ? { service_id: i.service_id } : {}),
  }));
  const total = lineItems.reduce((sum, i) => sum + i.unit_amount * i.quantity, 0);
  const doc = {
    schema_version: "2026-05-29",
    document_type: "invoice",
    tenant_id: getTenantId(),
    invoice_id: localId("inv"),
    status: "draft",
    collection_method: "send_invoice",
    stripe_mode: getApiEnvironment(),
    customer: { email: f.email, ...(f.name ? { name: f.name } : {}), ...(f.phone ? { phone: f.phone } : {}) },
    line_items: lineItems,
    amounts: { currency, subtotal: total, total, amount_paid: 0, amount_due: total },
    source: { created_from: "dashboard" },
    created_at: now,
    updated_at: now,
  };
  if (f.memo) doc.presentation = { memo: f.memo };
  return doc;
}

function localId(prefix) {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
  const cryptoApi = globalThis.crypto;
  const bytes = cryptoApi?.getRandomValues ? cryptoApi.getRandomValues(new Uint8Array(11)) : null;
  const suffix = Array.from({ length: 11 }, (_, i) => alphabet[(bytes ? bytes[i] : Math.floor(Math.random() * 62)) % alphabet.length]).join("");
  return `${prefix}_${suffix}`;
}
</script>
