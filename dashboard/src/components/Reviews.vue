<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Reviews</h1>
        <p>First-party product reviews. Approved reviews render on the page and power your star rating in search.</p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load()">
          {{ store.loading ? "Loading…" : "Reload" }}
        </button>
      </div>
    </header>

    <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
    <div v-else-if="store.message" class="keys-status-banner">{{ store.message }}</div>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Add a review</h2></header>
      <div class="dashboard-card-body">
        <p class="field-note">
          Enter a genuine review a customer gave you. Only add real reviews — fabricated ratings violate Google's
          guidelines. Reviews aggregate across all approved ones; low ratings count too (no cherry-picking).
        </p>
        <label class="offer-field">
          <span>Review of</span>
          <select v-model="form.target_type">
            <option value="product">A product</option>
            <option value="business">The business (store)</option>
          </select>
        </label>
        <div class="offer-two-column">
          <label v-if="form.target_type === 'product'" class="offer-field">
            <span>Product</span>
            <select v-model="form.product_id">
              <option value="">Choose a product…</option>
              <option v-for="p in products" :key="p.product_id" :value="p.product_id">{{ p.name || p.product_id }}</option>
            </select>
          </label>
          <label v-else class="offer-field">
            <span>Business (Site)</span>
            <select v-model="form.site_id">
              <option value="">Choose a Site…</option>
              <option v-for="s in sitesStore.sites" :key="s.site_id" :value="s.site_id">{{ s.name || s.site_id }}</option>
            </select>
          </label>
          <label class="offer-field">
            <span>Rating</span>
            <select v-model.number="form.rating">
              <option v-for="n in 5" :key="n" :value="n">{{ "★".repeat(n) + "☆".repeat(5 - n) }} ({{ n }})</option>
            </select>
          </label>
        </div>
        <div class="offer-two-column">
          <label class="offer-field"><span>Reviewer name</span><input v-model.trim="form.author" type="text" placeholder="Jane D." /></label>
          <label class="offer-field"><span>Date (optional)</span><input v-model="form.review_date" type="date" /></label>
        </div>
        <label class="offer-field"><span>Title (optional)</span><input v-model.trim="form.title" type="text" placeholder="Works great" /></label>
        <label class="offer-field"><span>Review</span><textarea v-model.trim="form.body" rows="3" placeholder="What the customer said…" /></label>
        <label class="offer-field">
          <span>Publish state</span>
          <select v-model="form.status">
            <option value="approved">Approved (renders on the page)</option>
            <option value="pending">Pending (hold for review)</option>
          </select>
        </label>
        <div class="button-row">
          <button class="primary-action" type="button" :disabled="!canSubmit || store.saving" @click="submit">
            {{ store.saving ? "Adding…" : "Add review" }}
          </button>
        </div>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>Reviews <span class="review-count-note">{{ store.liveCount }} live · {{ store.pendingCount }} pending</span></h2>
        <label class="refunds-filter">
          Status
          <select v-model="store.filterStatus">
            <option value="all">All</option>
            <option v-for="s in REVIEW_STATUSES" :key="s" :value="s">{{ reviewStatusLabel(s) }}</option>
          </select>
        </label>
      </header>
      <div class="dashboard-card-body">
        <div v-if="!store.filteredReviews.length" class="product-empty-state">
          {{ store.loaded ? "No reviews in this view." : "Loading…" }}
        </div>
        <div v-else class="reviews-grid">
          <article v-for="review in store.filteredReviews" :key="review.review_id" class="review-card">
            <header class="review-card-head">
              <span class="review-stars">{{ "★".repeat(review.rating) + "☆".repeat(5 - review.rating) }}</span>
              <span class="product-status" :class="reviewStatusClass(review.status)">{{ reviewStatusLabel(review.status) }}</span>
              <span v-if="review.source === 'gbp'" class="product-status inactive">Google · display-only</span>
            </header>
            <p class="review-meta">
              <strong>{{ review.author || "Anonymous" }}</strong>
              <span>· {{ productName(review) }}</span>
              <span v-if="review.review_date">· {{ review.review_date }}</span>
            </p>
            <p v-if="review.title" class="review-title">{{ review.title }}</p>
            <p class="review-body">{{ review.body }}</p>
            <!-- NO Approve, Reject or Delete. A tenant who could keep the good ones and remove the bad
                 ones would make the star rating a claim about a set they chose, and that is the claim
                 this system exists to make honest (plans/REVIEWS.md "Review integrity"). Only a real
                 buyer can write one, every one publishes, and removal belongs to the author or to the
                 platform. A verified review you dislike is still true.
                 Reporting is the one lever that remains, and it changes nothing about the review. -->
            <div class="review-card-foot">
              <span v-if="review.verified_purchase" class="review-verified">✓ Verified purchase</span>
              <span v-if="store.reportedIds.includes(review.review_id)" class="review-reported">
                Reported — still published while the platform looks at it
              </span>
              <button
                v-else-if="reportingId !== review.review_id"
                class="link-muted"
                type="button"
                @click="openReport(review)"
              >
                Report a problem
              </button>
            </div>

            <div v-if="reportingId === review.review_id" class="review-report-form">
              <p class="field-note">
                Tell us what is wrong with this review. <strong>It stays published</strong> while the
                platform looks at it — reporting is not a way to take a review down, and a review you
                simply disagree with is not a problem we can act on.
              </p>
              <label class="offer-field">
                <span>Reason</span>
                <select v-model="reportForm.reason">
                  <option value="">Choose a reason…</option>
                  <option v-for="r in store.reportReasons" :key="r.value" :value="r.value">{{ r.label }}</option>
                </select>
              </label>
              <label class="offer-field">
                <span>What is wrong{{ reportForm.reason === "other" ? "" : " (optional)" }}</span>
                <textarea v-model.trim="reportForm.detail" rows="2" placeholder="Anything that helps us judge it…" />
              </label>
              <div class="button-row">
                <button class="primary-action" type="button" :disabled="!canReport || store.saving" @click="sendReport">
                  {{ store.saving ? "Sending…" : "Send report" }}
                </button>
                <button class="secondary-action" type="button" @click="closeReport">Cancel</button>
              </div>
            </div>
          </article>
        </div>
      </div>
    </section>

  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { apiRequest } from "../api/client";
import { useReviewsStore, REVIEW_STATUSES, reviewStatusLabel, reviewStatusClass } from "../stores/reviews";
import { useSitesStore } from "../stores/sites";

const store = useReviewsStore();
const sitesStore = useSitesStore();
const products = ref([]);

const form = reactive({ target_type: "product", product_id: "", site_id: "", rating: 5, author: "", title: "", body: "", review_date: "", status: "approved" });
const canSubmit = computed(() =>
  !!form.author && !!form.body && (form.target_type === "business" ? !!form.site_id : !!form.product_id));

const reportingId = ref("");
const reportForm = reactive({ reason: "", detail: "" });
const canReport = computed(() =>
  !!reportForm.reason && (reportForm.reason !== "other" || !!reportForm.detail));

function openReport(review) {
  reportingId.value = review.review_id;
  Object.assign(reportForm, { reason: "", detail: "" });
}

function closeReport() {
  reportingId.value = "";
}

async function sendReport() {
  if (!canReport.value) return;
  const sent = await store.report(reportingId.value, { ...reportForm });
  if (sent) closeReport();
}

function productName(review) {
  const id = review.target?.id;
  if (review.target?.type === "business") return sitesStore.sites.find((s) => s.site_id === id)?.name || "your store";
  return products.value.find((p) => p.product_id === id)?.name || id || "product";
}

async function submit() {
  if (!canSubmit.value) return;
  const target = form.target_type === "business"
    ? { type: "business", id: form.site_id }
    : { type: "product", id: form.product_id };
  try {
    await store.create({
      target,
      rating: form.rating,
      author: form.author,
      body: form.body,
      title: form.title || undefined,
      review_date: form.review_date || undefined,
      status: form.status,
      source: "manual",
    });
    Object.assign(form, { rating: 5, author: "", title: "", body: "", review_date: "", status: "approved" });
  } catch {
    /* store surfaces the error */
  }
}

onMounted(async () => {
  store.ensureLoaded();
  sitesStore.ensureLoaded();
  try {
    const body = await apiRequest("/products");
    products.value = Array.isArray(body.products) ? body.products : [];
  } catch {
    products.value = [];
  }
});
</script>

<style scoped>
.review-count-note { font-size: 1.3rem; font-weight: 600; color: var(--muted); margin-left: 0.6rem; }
.reviews-grid { display: grid; gap: 1.2rem; }
.review-card { border: 1px solid var(--line); border-radius: 10px; padding: 1.2rem 1.4rem; }
.review-card-head { display: flex; align-items: center; gap: 0.8rem; flex-wrap: wrap; }
.review-stars { color: #f59e0b; letter-spacing: 0.08em; font-size: 1.6rem; }
.review-meta { margin: 0.6rem 0 0; color: var(--muted); display: flex; gap: 0.5rem; flex-wrap: wrap; }
.review-meta strong { color: var(--text); }
.review-title { margin: 0.6rem 0 0; font-weight: 700; }
.review-body { margin: 0.4rem 0 0.9rem; line-height: 1.5; }
.link-danger { background: none; border: none; color: #dc2626; cursor: pointer; font: inherit; }
.link-danger:hover { text-decoration: underline; }
.review-card-foot { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
.review-reported { color: var(--muted); font-size: 1.3rem; }
/* Muted, not red. Reporting is a legitimate action with a dull outcome, and a danger-coloured button
   would read as the delete button this screen deliberately no longer has. */
.link-muted { background: none; border: none; color: var(--muted); cursor: pointer; font: inherit; padding: 0; text-decoration: underline; }
.link-muted:hover { color: var(--text); }
.review-report-form { margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--line); }
</style>
