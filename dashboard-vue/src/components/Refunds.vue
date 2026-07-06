<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Refunds</h1>
        <p>Review refund requests and issue Stripe refunds to customers.</p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load()">
          {{ store.loading ? "Loading…" : "Reload" }}
        </button>
      </div>
    </header>

    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>Refund Requests</h2>
        <label class="refunds-filter">
          Status
          <select v-model="store.filterStatus">
            <option value="open">Open</option>
            <option value="new">New</option>
            <option value="manual_review">Manual review</option>
            <option value="approved">Approved</option>
            <option value="refunded">Refunded</option>
            <option value="rejected">Rejected</option>
            <option value="all">All</option>
          </select>
        </label>
      </header>
      <div class="dashboard-card-body">
        <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
        <div v-else class="keys-status-banner">{{ store.message }}</div>

        <div v-if="!store.filteredRequests.length" class="product-empty-state">
          {{ store.loaded ? "No refund requests in this view." : "Loading…" }}
        </div>

        <div v-else class="coupon-card-grid">
          <article v-for="request in store.filteredRequests" :key="request.refund_request_id" class="coupon-card">
            <header>
              <div>
                <h3>{{ request.customer?.name || request.customer?.email || "Customer" }}</h3>
                <p class="font-mono">{{ request.order_id || "—" }}</p>
              </div>
              <span class="product-status" :class="refundStatusClass(request.status)">{{ refundStatusLabel(request.status) }}</span>
            </header>
            <dl class="coupon-detail-list">
              <div><dt>Amount</dt><dd>{{ formatMoneyCents(refundRequestedAmount(request), request.amount?.currency) }}</dd></div>
              <div><dt>Email</dt><dd>{{ request.customer?.email || "—" }}</dd></div>
              <div v-if="request.reason"><dt>Reason</dt><dd>{{ request.reason }}</dd></div>
              <div v-if="request.refund?.stripe_refund_id"><dt>Stripe refund</dt><dd class="font-mono">{{ request.refund.stripe_refund_id }}</dd></div>
            </dl>
            <div class="product-card-actions">
              <button
                v-if="canApprove(request)" type="button" class="primary-action"
                :disabled="busy(request)" @click="store.approve(request)"
              >Approve</button>
              <button
                v-if="request.status === 'approved'" type="button" class="primary-action"
                :disabled="busy(request)" @click="confirmExecute(request)"
              >{{ busy(request) ? "Issuing…" : "Issue refund" }}</button>
              <button
                v-if="canReject(request)" type="button" class="danger-action"
                :disabled="busy(request)" @click="rejectRequest(request)"
              >Reject</button>
            </div>
          </article>
        </div>
      </div>
    </section>
  </section>
</template>

<script setup>
import {
  useRefundsStore,
  refundStatusLabel,
  refundStatusClass,
  refundRequestedAmount,
  formatMoneyCents,
} from "../stores/refunds";

const store = useRefundsStore();
store.load();

function busy(request) {
  return store.saving === request.refund_request_id;
}
function canApprove(request) {
  return ["new", "manual_review"].includes(request.status);
}
function canReject(request) {
  return ["new", "manual_review", "approved"].includes(request.status);
}

async function rejectRequest(request) {
  const reason = window.prompt("Reason for rejection (optional):");
  if (reason === null) return;
  try {
    await store.reject(request, reason.trim());
  } catch {
    /* store surfaces the error banner */
  }
}

async function confirmExecute(request) {
  const amount = formatMoneyCents(refundRequestedAmount(request), request.amount?.currency);
  if (!window.confirm(`Issue a Stripe refund of ${amount} to ${request.customer?.email || "the customer"}? This cannot be undone.`)) return;
  try {
    await store.execute(request);
  } catch {
    /* store surfaces the error banner */
  }
}
</script>
