<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Coupons</h1>
        <p>Manage Stripe-backed coupons and promotion codes</p>
      </div>
    </header>

    <section class="dashboard-card coupon-management-card">
      <header class="dashboard-card-header">
        <h2>Coupon Management</h2>
        <div class="button-row">
          <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load({ status: 'all' })">
            {{ store.loading ? "Loading..." : "Load Coupons" }}
          </button>
          <button class="primary-action" type="button" @click="openCreateModal">+ Create Coupon</button>
        </div>
      </header>

      <div class="product-filter-bar">
        <label>
          Search
          <input v-model.trim="store.filters.search" type="search" placeholder="Name, code, coupon ID..." />
        </label>
        <label>
          Status
          <select v-model="store.filters.status">
            <option value="usable">Usable</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="expired">Expired</option>
            <option value="fully_redeemed">Fully Redeemed</option>
            <option value="all">All</option>
          </select>
        </label>
        <div class="product-filter-actions">
          <button type="button" class="primary-action" @click="store.applyFilters">Apply</button>
          <button type="button" class="secondary-action" @click="resetFilters">Reset</button>
        </div>
      </div>

      <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
      <div v-else class="keys-status-banner">{{ store.message }}</div>

      <div v-if="!store.filteredCoupons.length" class="product-empty-state">
        {{ store.loaded ? "No coupons found. Create a coupon before attaching one to an offer." : "Click Load Coupons to see coupons." }}
      </div>

      <div v-else class="coupon-card-grid">
        <article v-for="coupon in store.filteredCoupons" :key="coupon.coupon_id" class="coupon-card">
          <header>
            <div>
              <h3>{{ coupon.name || coupon.code }}</h3>
              <p class="font-mono">{{ coupon.code }}</p>
            </div>
            <span class="product-status" :class="couponStatus(coupon)">{{ statusLabel(couponStatus(coupon)) }}</span>
          </header>
          <strong class="coupon-discount">{{ formatCouponDiscount(coupon) }}</strong>
          <dl class="coupon-detail-list">
            <div><dt>Coupon ID</dt><dd>{{ coupon.coupon_id }}</dd></div>
            <div><dt>Expires</dt><dd>{{ couponExpiry(coupon) }}</dd></div>
            <div><dt>Redemptions</dt><dd>{{ redemptionText(coupon) }}</dd></div>
          </dl>
          <div class="product-card-actions">
            <button type="button" class="secondary-action" @click="openEditModal(coupon)">Edit</button>
            <button type="button" class="secondary-action" @click="selectedCoupon = coupon">Details</button>
          </div>
        </article>
      </div>
    </section>

    <div v-if="showCouponModal" class="modal-backdrop" @click.self="closeCouponModal">
      <section class="modal-card coupon-modal" role="dialog" aria-modal="true" aria-labelledby="couponModalTitle">
        <header class="modal-card-header">
          <h2 id="couponModalTitle">{{ editingCoupon ? "Edit Coupon" : "Create Coupon" }}</h2>
          <button type="button" class="modal-close" aria-label="Close coupon modal" @click="closeCouponModal">×</button>
        </header>

        <form class="coupon-form" @submit.prevent="saveCoupon">
          <div v-if="formError" class="keys-status-banner error">{{ formError }}</div>

          <section class="offer-form-section">
            <div class="offer-two-column">
              <label class="offer-field">
                <span>Coupon Name <strong>*</strong></span>
                <input v-model.trim="form.name" type="text" placeholder="Save 10%" required />
              </label>
              <label class="offer-field">
                <span>Promotion Code <strong>*</strong></span>
                <input v-model.trim="form.code" class="font-mono uppercase-input" type="text" placeholder="SAVE10" required />
                <small>Use uppercase letters, numbers, underscores, or hyphens.</small>
              </label>
            </div>

          </section>

          <section class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3>Discount</h3>
                <p>Coupon documents represent Stripe coupon and promotion-code state.</p>
              </div>
            </header>
            <div class="offer-three-column">
              <label class="offer-field">
                <span>Discount Type</span>
                <select v-model="form.discount_type">
                  <option value="percent">Percent</option>
                  <option value="fixed">Fixed Amount</option>
                </select>
              </label>
              <label class="offer-field">
                <span>Value <strong>*</strong></span>
                <input v-model.number="form.value" min="0" type="number" step="0.01" required />
              </label>
              <label v-if="form.discount_type === 'fixed'" class="offer-field">
                <span>Currency</span>
                <select v-model="form.currency">
                  <option value="usd">USD</option>
                </select>
              </label>
            </div>
            <div class="offer-three-column">
              <label class="offer-field">
                <span>Duration</span>
                <select v-model="form.duration">
                  <option value="once">Once</option>
                  <option value="repeating">Repeating</option>
                  <option value="forever">Forever</option>
                </select>
              </label>
              <label v-if="form.duration === 'repeating'" class="offer-field">
                <span>Duration Months</span>
                <input v-model.number="form.duration_months" min="1" type="number" />
              </label>
            </div>
          </section>

          <section class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3>Restrictions</h3>
                <p>Expired and fully redeemed coupons are hidden from offer selection.</p>
              </div>
            </header>
            <div class="offer-three-column">
              <label class="offer-field">
                <span>Expires On</span>
                <input v-model="form.expires_on" type="date" />
              </label>
              <label class="offer-field">
                <span>Max Redemptions</span>
                <input v-model.number="form.max_redemptions" min="1" type="number" />
              </label>
              <label class="offer-field">
                <span>Max Per Customer</span>
                <input v-model.number="form.max_redemptions_per_customer" min="1" type="number" />
              </label>
            </div>
            <div class="offer-three-column">
              <label class="offer-field">
                <span>Minimum Amount</span>
                <input v-model.number="form.minimum_amount" min="0" type="number" step="0.01" />
              </label>
              <label v-if="form.minimum_amount" class="offer-field">
                <span>Minimum Currency</span>
                <select v-model="form.minimum_amount_currency">
                  <option value="usd">USD</option>
                </select>
              </label>
              <label class="checkbox-row offer-checkbox-inline">
                <input v-model="form.first_time_only" type="checkbox" />
                <span>First-time customers only</span>
              </label>
            </div>
          </section>

          <footer class="modal-footer">
            <button class="secondary-action" type="button" @click="closeCouponModal">Cancel</button>
            <button class="primary-action" type="submit" :disabled="store.saving">
              {{ store.saving ? "Saving..." : "Save Coupon" }}
            </button>
          </footer>
        </form>
      </section>
    </div>

    <div v-if="selectedCoupon" class="modal-backdrop" @click.self="selectedCoupon = null">
      <section class="modal-card product-details-modal" role="dialog" aria-modal="true" aria-labelledby="couponDetailsTitle">
        <header class="modal-card-header">
          <h2 id="couponDetailsTitle">Coupon Details</h2>
          <button type="button" class="modal-close" aria-label="Close coupon details" @click="selectedCoupon = null">×</button>
        </header>
        <div class="product-details-body">
          <dl class="product-details-grid">
            <div><dt>Coupon ID</dt><dd>{{ selectedCoupon.coupon_id }}</dd></div>
            <div><dt>Code</dt><dd>{{ selectedCoupon.code }}</dd></div>
            <div><dt>Status</dt><dd>{{ statusLabel(couponStatus(selectedCoupon)) }}</dd></div>
            <div><dt>Discount</dt><dd>{{ formatCouponDiscount(selectedCoupon) }}</dd></div>
          </dl>
          <details class="product-json-details">
            <summary>Raw JSON</summary>
            <pre>{{ JSON.stringify(selectedCoupon, null, 2) }}</pre>
          </details>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import { ref } from "vue";
import { couponIsUsable, formatCouponDiscount, useCouponsStore } from "../stores/coupons";

const store = useCouponsStore();
const showCouponModal = ref(false);
const editingCoupon = ref(null);
const selectedCoupon = ref(null);
const formError = ref("");
const form = ref(defaultCouponForm());

function defaultCouponForm() {
  return {
    coupon_id: "",
    name: "",
    code: "",
    status: "active",
    stripe_coupon_id: "",
    stripe_promo_code_id: "",
    discount_type: "percent",
    value: 0,
    currency: "usd",
    duration: "once",
    duration_months: 1,
    expires_on: "",
    max_redemptions: "",
    max_redemptions_per_customer: "",
    first_time_only: false,
    minimum_amount: "",
    minimum_amount_currency: "usd",
    redemption_count: 0,
    applies_to_offer_ids: [],
    created_at: null,
  };
}

function openCreateModal() {
  editingCoupon.value = null;
  form.value = defaultCouponForm();
  formError.value = "";
  showCouponModal.value = true;
}

function openEditModal(coupon) {
  editingCoupon.value = coupon;
  form.value = formFromCoupon(coupon);
  formError.value = "";
  showCouponModal.value = true;
}

function closeCouponModal() {
  showCouponModal.value = false;
  editingCoupon.value = null;
}

async function saveCoupon() {
  formError.value = "";
  const code = String(form.value.code || "").trim().toUpperCase();
  if (!/^[A-Z0-9_-]+$/.test(code)) {
    formError.value = "Promotion code must contain only uppercase letters, numbers, underscores, or hyphens.";
    return;
  }
  if (form.value.discount_type === "percent" && Number(form.value.value || 0) > 100) {
    formError.value = "Percent coupons cannot exceed 100%.";
    return;
  }
  form.value.code = code;
  try {
    await store.saveCoupon(form.value);
    closeCouponModal();
  } catch (error) {
    formError.value = error.message;
  }
}

function resetFilters() {
  store.filters.search = "";
  store.filters.status = "usable";
  store.applyFilters();
}

function formFromCoupon(coupon) {
  const discount = coupon.discount || {};
  const restrictions = coupon.restrictions || {};
  return {
    ...defaultCouponForm(),
    coupon_id: coupon.coupon_id || "",
    name: coupon.name || coupon.code || "",
    code: coupon.code || "",
    status: coupon.status || "active",
    stripe_coupon_id: coupon.stripe_coupon_id || "",
    stripe_promo_code_id: coupon.stripe_promo_code_id || "",
    discount_type: discount.type || "percent",
    value: discount.type === "fixed" ? Number(discount.value || 0) / 100 : Number(discount.value || 0),
    currency: discount.currency || "usd",
    duration: discount.duration || "once",
    duration_months: discount.duration_months || 1,
    expires_on: dateInputValue(restrictions.expires_at),
    max_redemptions: restrictions.max_redemptions || "",
    max_redemptions_per_customer: restrictions.max_redemptions_per_customer || "",
    first_time_only: Boolean(restrictions.first_time_only),
    minimum_amount: restrictions.minimum_amount ? Number(restrictions.minimum_amount) / 100 : "",
    minimum_amount_currency: restrictions.minimum_amount_currency || "usd",
    redemption_count: coupon.redemption_count || 0,
    applies_to_offer_ids: Array.isArray(coupon.applies_to_offer_ids) ? [...coupon.applies_to_offer_ids] : [],
    created_at: coupon.created_at || null,
  };
}

function dateInputValue(epoch) {
  if (!epoch) return "";
  const date = new Date(Number(epoch) * 1000);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 10);
}

function couponStatus(coupon) {
  return couponIsUsable(coupon) ? coupon.status : coupon.status === "active" ? "expired" : coupon.status;
}

function statusLabel(status) {
  return String(status || "active").replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function couponExpiry(coupon) {
  const expiresAt = coupon?.restrictions?.expires_at;
  if (!expiresAt) return "Never";
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(new Date(Number(expiresAt) * 1000));
}

function redemptionText(coupon) {
  const count = Number(coupon?.redemption_count || 0);
  const max = coupon?.restrictions?.max_redemptions;
  return max ? `${count} of ${max}` : `${count}`;
}
</script>
