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
          <input v-model.trim="store.filters.search" type="search" placeholder="Name, code, coupon ID..." @focus="store.ensureLoaded()" />
        </label>
        <label>
          Status
          <select v-model="store.filters.status" @focus="store.ensureLoaded()">
            <option value="usable">Usable</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="expired">Expired</option>
            <option value="fully_redeemed">Fully Redeemed</option>
            <option value="all">All</option>
          </select>
        </label>
        <div class="product-filter-actions">
          <button type="button" class="secondary-action" @click="resetFilters">Reset</button>
        </div>
      </div>

      <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
      <div v-else class="keys-status-banner">{{ store.statusMessage }}</div>

      <div v-if="!store.filteredCoupons.length" class="product-empty-state">
        {{ store.loading ? "Loading coupons..." : store.loaded ? "No coupons found. Create a coupon before attaching one to an offer." : "Click Load Coupons to see coupons." }}
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
            <button type="button" class="secondary-action" @click="openGrantsModal(coupon)">Send to customers</button>
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
                <p>
                    The coupon and its code are created at Stripe when you save.
                    <strong>The discount, the code and how long it lasts can't be changed afterwards</strong> —
                    customers may already be holding this one, and a discount you promised has to keep
                    working until it expires. You can rename it, or turn it off. To offer something
                    different, turn this one off and create another.
                  </p>
              </div>
            </header>
            <div class="offer-three-column">
              <label class="offer-field">
                <span>Discount Type</span>
                <select v-model="form.discount_type" @change="onDiscountTypeChange">
                  <option value="percent">Percent</option>
                  <option value="fixed">Fixed Amount</option>
                  <option value="tiered">Spend threshold</option>
                </select>
              </label>
              <label v-if="form.discount_type !== 'tiered'" class="offer-field">
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

            <div v-if="form.discount_type === 'tiered'" class="coupon-tier-editor">
              <p class="field-note">
                Spend more, save more. The customer gets the <strong>best</strong> tier their cart reaches
                &mdash; not the first one. This discount is worked out when they check out, so it isn't
                stored at Stripe and can't be issued as personal codes.
              </p>
              <div v-for="(tier, index) in form.tiers" :key="index" class="coupon-tier-row">
                <label class="offer-field">
                  <span>Spend at least</span>
                  <input v-model.number="tier.min_spend" min="0" type="number" step="0.01"
                         :disabled="Boolean(editingCoupon)" />
                </label>
                <label class="offer-field">
                  <span>Get % off</span>
                  <input v-model.number="tier.percent" min="1" max="100" type="number" step="1"
                         :disabled="Boolean(editingCoupon)" />
                </label>
                <button
                  v-if="!editingCoupon && form.tiers.length > 1"
                  type="button"
                  class="secondary-action"
                  @click="form.tiers.splice(index, 1)"
                >Remove</button>
              </div>
              <button v-if="!editingCoupon" type="button" class="secondary-action" @click="addTier">
                + Add tier
              </button>
            </div>

            <div v-if="form.discount_type !== 'tiered'" class="offer-three-column">
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
                <h3>What it discounts</h3>
                <p v-if="editingCoupon">
                  Fixed when the coupon was created — like the discount itself.
                </p>
                <p v-else>
                  By default this discounts everything in the cart. Pick products to discount only those,
                  and leave the rest at full price.
                  <strong>This can't be changed later</strong>, so a bundle whose qualifying items change
                  needs a new coupon.
                </p>
              </div>
              <button
                v-if="!editingCoupon"
                type="button"
                class="secondary-action"
                :disabled="productsStore.loading"
                @click="loadProductsForScope"
              >
                {{ productsStore.loading ? "Loading..." : "Load Products" }}
              </button>
            </header>

            <p v-if="!form.applies_to_product_ids.length" class="field-note">
              Discounts the whole cart.
            </p>
            <div v-if="scopeProducts.length" class="coupon-scope-list">
              <label
                v-for="product in scopeProducts"
                :key="product.product_id"
                class="coupon-scope-row"
                :class="{ 'is-unavailable': !product.stripe_product_id }"
              >
                <input
                  type="checkbox"
                  :value="product.product_id"
                  :checked="form.applies_to_product_ids.includes(product.product_id)"
                  :disabled="Boolean(editingCoupon) || !product.stripe_product_id"
                  @change="toggleScopeProduct(product.product_id)"
                />
                <span>{{ product.name || product.product_id }}</span>
                <small v-if="!product.stripe_product_id">
                  Not synced to Stripe yet — open and save the product first.
                </small>
              </label>
            </div>
            <p v-else-if="productsStore.loaded" class="field-note">No products to choose from.</p>
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
                <input v-model.number="form.max_redemptions_per_customer" min="1" type="number" disabled />
                  <span class="field-note">
                    Not available on a shared code — everyone holding it is the same anonymous buyer
                    until they pay, so there is no customer to count against. Use
                    <strong>Send to customers</strong> on a saved coupon: each named customer gets their
                    own code, and the limit applies to them.
                  </span>
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

    <div v-if="grantsCoupon" class="modal-backdrop" @click.self="closeGrantsModal">
      <section class="modal-card coupon-modal" role="dialog" aria-modal="true" aria-labelledby="couponGrantsTitle">
        <header class="modal-card-header">
          <h2 id="couponGrantsTitle">Send “{{ grantsCoupon.name || grantsCoupon.code }}” to customers</h2>
          <button type="button" class="modal-close" aria-label="Close" @click="closeGrantsModal">×</button>
        </header>

        <div class="coupon-form">
          <div v-if="grantsError" class="keys-status-banner error">{{ grantsError }}</div>
          <div v-else-if="grantsMessage" class="keys-status-banner">{{ grantsMessage }}</div>

          <section class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3>Who gets a code</h3>
                <p>
                  Each customer gets their <strong>own</strong> code, locked to them at Stripe — a code
                  forwarded to a friend is worthless to the friend. Paste one email per line; a name
                  beside it is used for your mail merge.
                </p>
              </div>
            </header>
            <label class="offer-field">
              <span>Customers</span>
              <textarea
                v-model="grantForm.recipients"
                rows="6"
                placeholder="ada@example.com&#10;Bo Diddley <bo@example.com>"
              ></textarea>
              <small>{{ recipientCount }} address{{ recipientCount === 1 ? "" : "es" }} recognised.</small>
            </label>
            <div class="offer-two-column">
              <label class="offer-field">
                <span>Landing page URL</span>
                <input v-model.trim="grantForm.landingUrl" type="url" placeholder="https://shop.example.com/sale" />
                <small>The published page holding this coupon. Each code is added to this link.</small>
              </label>
              <label class="offer-field">
                <span>Uses per customer</span>
                <input v-model.number="grantForm.maxRedemptions" min="1" type="number" placeholder="unlimited" />
                <small>Optional. Leave empty to let them use it as often as they like.</small>
              </label>
            </div>
          </section>

          <section v-if="grants.length" class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3>Codes issued</h3>
                <p>Export the CSV and merge <code>redeem_url</code> into your email.</p>
              </div>
              <button type="button" class="secondary-action" @click="downloadGrantsCsv">Export CSV</button>
            </header>
            <div class="coupon-grant-table-wrap">
              <table class="coupon-grant-table">
                <thead>
                  <tr><th>Customer</th><th>Code</th><th>Used</th><th></th></tr>
                </thead>
                <tbody>
                  <tr v-for="grant in grants" :key="grant.grant_id" :class="{ 'is-revoked': grant.status !== 'active' }">
                    <td>{{ grant.name ? `${grant.name} <${grant.email}>` : grant.email }}</td>
                    <td class="font-mono">{{ grant.code }}</td>
                    <td>{{ Number(grant.redemption_count || 0) > 0 ? "Yes" : "No" }}</td>
                    <td>
                      <button
                        type="button"
                        class="secondary-action"
                        :disabled="revoking === grant.grant_id"
                        @click="toggleGrant(grant)"
                      >
                        {{ revoking === grant.grant_id
                          ? "Saving..."
                          : grant.status === "active" ? "Revoke" : "Restore" }}
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <footer class="modal-footer">
            <button class="secondary-action" type="button" @click="closeGrantsModal">Close</button>
            <button
              class="primary-action"
              type="button"
              :disabled="issuing || !recipientCount"
              @click="issueGrants"
            >
              {{ issuing ? "Issuing..." : `Issue ${recipientCount || ""} code${recipientCount === 1 ? "" : "s"}` }}
            </button>
          </footer>
        </div>
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
import { computed, ref } from "vue";
import { couponIsUsable, formatCouponDiscount, parseRecipients, useCouponsStore } from "../stores/coupons";
import { useProductsStore } from "../stores/products";

const store = useCouponsStore();
const productsStore = useProductsStore();
const showCouponModal = ref(false);
const editingCoupon = ref(null);
const selectedCoupon = ref(null);
const formError = ref("");
const form = ref(defaultCouponForm());

// Targeted codes: one per named customer (plans/COUPONS_COMPLETION.md C5).
const grantsCoupon = ref(null);
const grants = ref([]);
const grantsError = ref("");
const grantsMessage = ref("");
const issuing = ref(false);
const revoking = ref("");
const grantForm = ref({ recipients: "", landingUrl: "", maxRedemptions: "" });
const recipientCount = computed(() => parseRecipients(grantForm.value.recipients).length);

async function openGrantsModal(coupon) {
  grantsCoupon.value = coupon;
  grants.value = [];
  grantsError.value = "";
  grantsMessage.value = "";
  grantForm.value = { recipients: "", landingUrl: "", maxRedemptions: "" };
  try {
    grants.value = await store.loadGrants(coupon.coupon_id);
  } catch (error) {
    grantsError.value = error.message;
  }
}

function closeGrantsModal() {
  grantsCoupon.value = null;
}

async function issueGrants() {
  issuing.value = true;
  grantsError.value = "";
  grantsMessage.value = "";
  try {
    const result = await store.issueGrants(grantsCoupon.value.coupon_id, {
      recipients: parseRecipients(grantForm.value.recipients),
      landingUrl: grantForm.value.landingUrl,
      maxRedemptions: grantForm.value.maxRedemptions,
      onProgress: ({ issued, remaining }) => {
        grantsMessage.value = `${issued} issued, ${remaining} to go...`;
      },
    });
    grants.value = await store.loadGrants(grantsCoupon.value.coupon_id);
    grantForm.value.recipients = "";
    const parts = [`${result.issued.length} new code${result.issued.length === 1 ? "" : "s"}`];
    if (result.skipped.length) parts.push(`${result.skipped.length} already had one`);
    if (result.failures.length) parts.push(`${result.failures.length} failed`);
    grantsMessage.value = `${parts.join(", ")}. Export the CSV to send them.`;
    if (result.failures.length) {
      grantsError.value = result.failures.map((failure) => `${failure.email}: ${failure.error}`).join(" · ");
    }
  } catch (error) {
    grantsError.value = error.message;
  } finally {
    issuing.value = false;
  }
}

// Revoking one recipient does NOT end the campaign — every other code keeps working, which is the whole
// difference between this and turning the coupon off.
async function toggleGrant(grant) {
  revoking.value = grant.grant_id;
  grantsError.value = "";
  try {
    const next = grant.status === "active" ? "inactive" : "active";
    const updated = await store.setGrantStatus(grantsCoupon.value.coupon_id, grant.code, next);
    const index = grants.value.findIndex((row) => row.grant_id === grant.grant_id);
    if (index >= 0) grants.value.splice(index, 1, updated);
    grantsMessage.value = next === "inactive"
      ? `${grant.email}'s code no longer works.`
      : `${grant.email}'s code works again.`;
  } catch (error) {
    grantsError.value = error.message;
  } finally {
    revoking.value = "";
  }
}

async function downloadGrantsCsv() {
  grantsError.value = "";
  try {
    const text = await store.exportGrantsCsv(grantsCoupon.value.coupon_id);
    const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${grantsCoupon.value.code || grantsCoupon.value.coupon_id}-codes.csv`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    grantsError.value = error.message;
  }
}

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
    applies_to_product_ids: [],
    // Spend-threshold ladder (Option B). Entered in whole currency, converted to minor units on save.
    tiers: [{ min_spend: null, percent: null }],
    created_at: null,
  };
}

// Product scope (Option A). The catalogue is loaded on demand rather than with the screen: most coupons
// discount everything, and the Products index is the biggest payload the dashboard fetches.
const scopeProducts = computed(() => {
  const chosen = new Set(form.value.applies_to_product_ids || []);
  return (productsStore.products || []).filter(
    (product) => product.status !== "archived" || chosen.has(product.product_id),
  );
});

async function loadProductsForScope() {
  if (!productsStore.loaded) await productsStore.load();
}

function toggleScopeProduct(productId) {
  const chosen = form.value.applies_to_product_ids || [];
  form.value.applies_to_product_ids = chosen.includes(productId)
    ? chosen.filter((id) => id !== productId)
    : [...chosen, productId];
}

function addTier() {
  form.value.tiers.push({ min_spend: null, percent: null });
}

function onDiscountTypeChange() {
  // A spend ladder is worked out per checkout, so it has no Stripe object for a later cycle to reuse —
  // the server refuses anything but "once", and the form should not offer what the server refuses.
  if (form.value.discount_type === "tiered") form.value.duration = "once";
  if (form.value.discount_type === "tiered" && !form.value.tiers.length) addTier();
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
  // A scoped coupon has to be able to SHOW what it covers, even though it cannot be changed.
  if (form.value.applies_to_product_ids.length) loadProductsForScope();
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
    tiers: Array.isArray(discount.tiers) && discount.tiers.length
      ? discount.tiers.map((tier) => ({
        min_spend: Number(tier.min_subtotal || 0) / 100,
        percent: Number(tier.percent || 0),
      }))
      : [{ min_spend: null, percent: null }],
    expires_on: dateInputValue(restrictions.expires_at),
    max_redemptions: restrictions.max_redemptions || "",
    max_redemptions_per_customer: restrictions.max_redemptions_per_customer || "",
    first_time_only: Boolean(restrictions.first_time_only),
    minimum_amount: restrictions.minimum_amount ? Number(restrictions.minimum_amount) / 100 : "",
    minimum_amount_currency: restrictions.minimum_amount_currency || "usd",
    redemption_count: coupon.redemption_count || 0,
    applies_to_offer_ids: Array.isArray(coupon.applies_to_offer_ids) ? [...coupon.applies_to_offer_ids] : [],
    applies_to_product_ids: Array.isArray(coupon.applies_to_product_ids) ? [...coupon.applies_to_product_ids] : [],
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
