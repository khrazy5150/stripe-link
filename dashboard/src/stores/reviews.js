import { defineStore } from "pinia";
import { apiRequest, getTenantId } from "../api/client";

export const REVIEW_STATUSES = ["pending", "approved", "rejected"];

export function reviewStatusLabel(status) {
  return { pending: "Pending", approved: "Approved", rejected: "Rejected" }[status] || status || "Pending";
}
export function reviewStatusClass(status) {
  return { approved: "active", pending: "warning", rejected: "archived" }[status] || "inactive";
}

export const useReviewsStore = defineStore("reviews", {
  state: () => ({
    reviews: [],
    loading: false,
    loaded: false,
    saving: false,
    error: "",
    message: "",
    filterStatus: "all",
  }),
  getters: {
    filteredReviews(state) {
      if (state.filterStatus === "all") return state.reviews;
      return state.reviews.filter((r) => r.status === state.filterStatus);
    },
    // Only these render / feed AggregateRating (matches the backend markup_eligible rule).
    liveCount(state) {
      return state.reviews.filter((r) => r.status === "approved" && r.source !== "gbp").length;
    },
    pendingCount(state) {
      return state.reviews.filter((r) => r.status === "pending").length;
    },
  },
  actions: {
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/reviews");
        this.reviews = Array.isArray(body.reviews) ? body.reviews : [];
        this.loaded = true;
      } catch (error) {
        this.error = error.message || "Failed to load reviews.";
      } finally {
        this.loading = false;
      }
    },
    async ensureLoaded() {
      if (!this.loaded && !this.loading) await this.load();
    },
    async create(review) {
      this.saving = true;
      this.error = "";
      try {
        const body = await apiRequest("/reviews", { method: "POST", body: review });
        const saved = body.review || review;
        this.reviews = [saved, ...this.reviews];
        this.message = `Review by ${saved.author || "customer"} added.`;
        return saved;
      } catch (error) {
        this.error = error.message || "Failed to add the review.";
        throw error;
      } finally {
        this.saving = false;
      }
    },
    async moderate(review, status) {
      this.error = "";
      try {
        const body = await apiRequest(`/reviews/${encodeURIComponent(review.review_id)}/status`, {
          method: "PATCH",
          body: { tenant_id: review.tenant_id || getTenantId(), status },
        });
        const saved = body.review || { ...review, status };
        const index = this.reviews.findIndex((r) => r.review_id === saved.review_id);
        if (index >= 0) this.reviews.splice(index, 1, saved);
        return saved;
      } catch (error) {
        this.error = error.message || "Failed to update the review.";
      }
    },
    async remove(review) {
      this.error = "";
      try {
        const query = new URLSearchParams({ tenant_id: review.tenant_id || getTenantId() });
        await apiRequest(`/reviews/${encodeURIComponent(review.review_id)}?${query.toString()}`, { method: "DELETE" });
        this.reviews = this.reviews.filter((r) => r.review_id !== review.review_id);
      } catch (error) {
        this.error = error.message || "Failed to delete the review.";
      }
    },
  },
});
