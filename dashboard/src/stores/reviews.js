import { defineStore } from "pinia";
import { apiRequest } from "../api/client";
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
    // Offered by the server with the list, so the form can never show a reason the validator refuses --
    // and so "low rating" cannot appear on a screen a merchant reads.
    reportReasons: [],
    // Reviews reported in THIS session. The review document carries no mark, deliberately: a report must
    // not change the review in any way a buyer could see.
    reportedIds: [],
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
        this.reportReasons = Array.isArray(body.report_reasons) ? body.report_reasons : [];
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
    // NO moderate() and NO remove(). A tenant who could approve the good reviews and reject the bad
    // ones would make the star rating a claim about a set they chose (plans/REVIEWS.md "Review
    // integrity"). Only a real buyer can write one, every one publishes, and removal belongs to the
    // author -- through the link in their own confirmation -- or to the platform.
    //
    // `report` is the one lever that remains, and it is not a disguised version of those: it writes a
    // report into the platform's queue and leaves the review exactly where it is.
    async report(reviewId, { reason, detail = "" }) {
      this.saving = true;
      this.error = "";
      try {
        await apiRequest("/reviews", {
          method: "POST",
          body: { action: "report", review_id: reviewId, reason, detail },
        });
        if (!this.reportedIds.includes(reviewId)) this.reportedIds = [...this.reportedIds, reviewId];
        // Says what did NOT happen, because that is the part a merchant will otherwise assume wrongly.
        this.message = "Reported. The review stays published while the platform looks at it.";
        return true;
      } catch (error) {
        this.error = error.message || "Failed to send the report.";
        return false;
      } finally {
        this.saving = false;
      }
    },

  },
});
