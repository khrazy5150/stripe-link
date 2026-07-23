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
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Product</span>
            <select v-model="form.product_id">
              <option value="">Choose a product…</option>
              <option v-for="p in products" :key="p.product_id" :value="p.product_id">{{ p.name || p.product_id }}</option>
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
            <div class="button-row">
              <button v-if="review.status !== 'approved'" class="secondary-action compact" type="button" @click="store.moderate(review, 'approved')">Approve</button>
              <button v-if="review.status !== 'rejected'" class="secondary-action compact" type="button" @click="store.moderate(review, 'rejected')">Reject</button>
              <button class="link-danger compact" type="button" @click="askDelete(review)">Delete</button>
            </div>
          </article>
        </div>
      </div>
    </section>

    <ConfirmDialog
      :open="!!pendingDelete"
      danger
      title="Delete review?"
      confirm-label="Delete"
      @cancel="pendingDelete = null"
      @confirm="confirmDelete"
    >
      Delete the review by "{{ pendingDelete?.author || 'this customer' }}"? This can't be undone.
    </ConfirmDialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { apiRequest } from "../api/client";
import { useReviewsStore, REVIEW_STATUSES, reviewStatusLabel, reviewStatusClass } from "../stores/reviews";
import ConfirmDialog from "./shared/ConfirmDialog.vue";

const store = useReviewsStore();
const products = ref([]);
const pendingDelete = ref(null);

const form = reactive({ product_id: "", rating: 5, author: "", title: "", body: "", review_date: "", status: "approved" });
const canSubmit = computed(() => !!form.product_id && !!form.author && !!form.body);

function productName(review) {
  const id = review.target?.id;
  return products.value.find((p) => p.product_id === id)?.name || id || "product";
}

async function submit() {
  if (!canSubmit.value) return;
  try {
    await store.create({
      target: { type: "product", id: form.product_id },
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

function askDelete(review) {
  pendingDelete.value = review;
}
async function confirmDelete() {
  const review = pendingDelete.value;
  pendingDelete.value = null;
  if (review) await store.remove(review);
}

onMounted(async () => {
  store.ensureLoaded();
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
</style>
