import { defineStore } from "pinia";
import { apiRequest } from "../api/client";

export function formatMoneyCents(cents, currency = "usd") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: String(currency || "usd").toUpperCase() })
    .format(Number(cents || 0) / 100);
}

export function refundStatusLabel(status) {
  return {
    new: "New",
    manual_review: "Manual review",
    approved: "Approved",
    // The leg between approval and the money going back (plans/ORDER_FULFILMENT.md R1).
    return_pending: "Waiting for return",
    return_in_transit: "Return in transit",
    return_received: "Return received",
    rejected: "Rejected",
    refunded: "Refunded",
    closed: "Closed",
  }[status] || status || "New";
}

export function refundStatusClass(status) {
  return {
    new: "inactive",
    manual_review: "warning",
    approved: "active",
    return_pending: "warning",
    return_in_transit: "warning",
    return_received: "active",
    rejected: "archived",
    refunded: "active",
    closed: "inactive",
  }[status] || "inactive";
}

export function refundRequestedAmount(request) {
  const amount = request?.amount || {};
  const requested = Number(amount.requested_amount || 0);
  if (requested > 0) return requested;
  // What a refund RETURNS, which is not always what was paid: a net_guaranteed tip charged the supporter
  // the fees on top and only the gift reached the creator, so the server refunds the gift. The dialog has
  // to state the figure the server will actually send. Falls back to paid_amount for requests created
  // before the ceiling was recorded, where the two were always equal anyway.
  const ceiling = Number(amount.refundable_amount || 0);
  return ceiling > 0 ? ceiling : Number(amount.paid_amount || 0);
}

export function refundKeepsFees(request) {
  // True when the charge was larger than what comes back -- the supporter covered the fees on top, so the
  // "you refund what they paid" sentence would be wrong here.
  const amount = request?.amount || {};
  const paid = Number(amount.paid_amount || 0);
  const ceiling = Number(amount.refundable_amount || 0);
  return ceiling > 0 && paid > ceiling;
}

export const useRefundsStore = defineStore("refunds", {
  state: () => ({
    requests: [],
    loading: false,
    loaded: false,
    saving: "",
    error: "",
    message: "Loading refund requests…",
    filterStatus: "open",
  }),

  getters: {
    filteredRequests(state) {
      if (state.filterStatus === "all") return state.requests;
      if (state.filterStatus === "open") {
        return state.requests.filter((r) => ["new", "manual_review", "approved",
          "return_pending", "return_in_transit", "return_received"].includes(r.status));
      }
      return state.requests.filter((r) => r.status === state.filterStatus);
    },
  },

  actions: {
    reset() {
      this.requests = [];
      this.loading = false;
      this.loaded = false;
      this.error = "";
      this.message = "Loading refund requests…";
      this.filterStatus = "open";
    },

    async load() {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/notifications/refund-requests");
        this.requests = Array.isArray(body.refund_requests) ? body.refund_requests : [];
        this.loaded = true;
        this.message = this.requests.length
          ? `${this.requests.length} refund request${this.requests.length === 1 ? "" : "s"}.`
          : "No refund requests yet.";
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
      } finally {
        this.loading = false;
      }
    },

    async act(request, action, body) {
      this.saving = request.refund_request_id;
      this.error = "";
      try {
        const result = await apiRequest(`/refunds/${encodeURIComponent(request.refund_request_id)}/${action}`, {
          method: "POST",
          body,
        });
        if (result.refund_request) this._replace(result.refund_request);
        this.message = {
          approve: "Request approved.",
          reject: "Request rejected.",
          execute: "Refund issued.",
          received: "Return received — you can issue the refund now.",
        }[action] || "Updated.";
        return result;
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
        throw error;
      } finally {
        this.saving = "";
      }
    },

    markReturnReceived(request, body) {
      return this.act(request, "received", body || {});
    },

    approve(request) {
      return this.act(request, "approve");
    },
    reject(request, reason) {
      return this.act(request, "reject", reason ? { reason } : undefined);
    },
    execute(request) {
      return this.act(request, "execute");
    },

    _replace(request) {
      const index = this.requests.findIndex((item) => item.refund_request_id === request.refund_request_id);
      if (index >= 0) this.requests.splice(index, 1, request);
      else this.requests.unshift(request);
    },
  },
});
