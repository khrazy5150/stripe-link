<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Offers</h1>
        <p>Configure offers for your clients</p>
      </div>
    </header>

    <section class="dashboard-card offer-management-card">
      <header class="dashboard-card-header">
        <h2>Offer Configuration</h2>
        <div class="button-row">
          <button class="secondary-action" type="button" @click="openOfferModal()">+ Add Offer</button>
          <button class="secondary-action" type="button" :disabled="offersLoading" @click="loadOffers">
            {{ offersLoading ? "Loading..." : "Load Offers" }}
          </button>
          <button class="primary-action" type="button" disabled>Save All</button>
        </div>
      </header>

      <div class="offer-card-body">
        <div v-if="offersError" class="keys-status-banner error">{{ offersError }}</div>
        <div v-else-if="offersMessage" class="keys-status-banner">{{ offersMessage }}</div>

        <div v-if="!offers.length" class="offer-empty-state">
          {{ offersLoaded ? 'No offers found. Click "+ Add Offer" to configure one.' : 'Click "Load Offers" to see offers.' }}
        </div>

        <div v-else class="offer-grid">
          <article v-for="offer in offers" :key="offer.offer_id" class="offer-card">
            <div class="offer-card-media">
              <img v-if="offerImage(offer)" :src="offerImage(offer)" :alt="offer.name" />
              <div v-else class="offer-card-placeholder" aria-hidden="true">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 12v7.5A1.5 1.5 0 0 1 18.5 21h-13A1.5 1.5 0 0 1 4 19.5V12m16 0H4m16 0h-4.5A3.5 3.5 0 0 0 19 8.5 2.5 2.5 0 0 0 14.5 7L12 12m-8 0h4.5A3.5 3.5 0 0 1 5 8.5 2.5 2.5 0 0 1 9.5 7L12 12m0 0v9" />
                </svg>
              </div>
            </div>
            <div class="offer-card-copy">
              <div class="offer-card-heading">
                <h3>{{ offer.name }}</h3>
                <div class="offer-card-menu" @click.stop>
                  <button
                    type="button"
                    class="offer-kebab-button"
                    aria-label="Offer actions"
                    :aria-expanded="openOfferMenuId === offer.offer_id"
                    @click="toggleOfferMenu(offer.offer_id)"
                  >
                    ⋮
                  </button>
                  <div v-if="openOfferMenuId === offer.offer_id" class="offer-action-menu" role="menu">
                    <button type="button" role="menuitem" @click="viewOffer(offer)">
                      <svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.25 12s3.5-6 9.75-6 9.75 6 9.75 6-3.5 6-9.75 6-9.75-6-9.75-6Z" />
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                      </svg>
                      <span>View</span>
                    </button>
                    <button type="button" role="menuitem" @click="editOffer(offer)">
                      <svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m16.862 4.487 1.688-1.688a1.875 1.875 0 1 1 2.652 2.652L8.625 18.028 3.75 19.5l1.472-4.875L16.862 4.487Z" />
                      </svg>
                      <span>Edit</span>
                    </button>
                    <button type="button" class="danger" role="menuitem" @click="requestDeleteOffer(offer)">
                      <svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 7h12m-9 0V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7m-7 0 .75 12A2 2 0 0 0 10.75 21h2.5a2 2 0 0 0 2-2L16 7M10 11v6m4-6v6" />
                      </svg>
                      <span>Delete</span>
                    </button>
                  </div>
                </div>
              </div>
              <p><strong>Type:</strong> {{ derivedOfferTypeLabel(offer) }}</p>
              <p><strong>Products:</strong> {{ productSummary(offer) }}</p>
              <div class="offer-card-footer">
                <span class="offer-intent-badge" :class="offer.product_intent">{{ intentLabel(offer.product_intent) }}</span>
              </div>
            </div>
          </article>
        </div>
      </div>
    </section>

    <div v-if="showOfferModal" class="modal-backdrop" @click.self="closeOfferModal">
      <section class="modal-card offer-modal" role="dialog" aria-modal="true" aria-labelledby="offerModalTitle">
        <header class="modal-card-header">
          <h2 id="offerModalTitle">{{ editingOfferId ? "Edit Offer" : "Create New Offer" }}</h2>
          <button type="button" class="modal-close" aria-label="Close create offer modal" @click="closeOfferModal">×</button>
        </header>

        <form class="offer-form" @submit.prevent="createOffer">
          <section class="offer-form-section">
            <label class="offer-field">
              <span>1. Select Products <strong>*</strong></span>
              <button type="button" class="secondary-action stretch" @click="openProductSelector">
                Select Products Visually
              </button>
            </label>

            <div class="selected-products-list">
              <div v-if="!selectedProducts.length" class="selected-products-empty">No products selected</div>
              <template v-else>
                <button
                  v-for="product in selectedProducts"
                  :key="productId(product)"
                  type="button"
                  class="selected-product-badge"
                  @click="removeSelectedProduct(productId(product))"
                >
                  <span>{{ product.name || "Untitled Product" }}</span>
                  <span aria-hidden="true">×</span>
                </button>
              </template>
            </div>

            <div v-if="selectedProducts.length" class="offer-field">
              <span>Detected Offer Type</span>
              <div class="offer-type-row">
                <span class="offer-type-badge">{{ detectedOfferTypeLabel }}</span>
                <small>{{ detectedOfferTypeDescription }}</small>
              </div>
            </div>
          </section>

          <section v-if="selectedProducts.length" class="offer-form-section">
            <div class="offer-two-column">
              <label class="offer-field">
                <span>Offer Label <strong>*</strong></span>
                <input v-model.trim="form.name" type="text" placeholder="Auto-generated from products..." required />
                <small>Auto-generated label (you can modify it)</small>
              </label>

              <label class="offer-field">
                <span>Slug <strong>*</strong></span>
                <input v-model.trim="form.slug" class="font-mono" type="text" placeholder="auto-generated-from-label" required />
                <small>URL-friendly identifier</small>
              </label>
            </div>

            <div class="detected-offer-type">
              <span>{{ detectedOfferTypeLabel }}</span>
              <strong>{{ detectedOfferTypeDescription }}</strong>
            </div>
          </section>

          <section v-if="selectedProducts.length" class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3>Offer Items</h3>
                <p>Choose fixed prices or customer-selectable price options.</p>
              </div>
            </header>

            <div class="offer-items-list">
              <article v-for="product in selectedProducts" :key="productId(product)" class="offer-item-editor">
                <header>
                  <div>
                    <h4>{{ product.name || "Untitled Product" }}</h4>
                    <p>{{ product.product_id }}</p>
                  </div>
                  <button class="secondary-action compact" type="button" @click="removeSelectedProduct(productId(product))">Remove</button>
                </header>

                <div class="offer-three-column">
                  <label class="offer-field">
                    <span>Item Mode</span>
                    <select v-model="itemConfig(product).mode">
                      <option value="fixed">Fixed price</option>
                      <option value="selectable">Buyer chooses</option>
                    </select>
                  </label>

                  <label v-if="itemConfig(product).mode === 'fixed'" class="offer-field">
                    <span>Price</span>
                    <select v-model="itemConfig(product).price_id">
                      <option v-for="price in productPrices(product)" :key="price.price_id" :value="price.price_id">
                        {{ priceOptionLabel(price) }}
                      </option>
                    </select>
                  </label>

                  <label v-if="itemConfig(product).mode === 'fixed'" class="offer-field">
                    <span>Line Quantity</span>
                    <input v-model.number="itemConfig(product).quantity" min="1" type="number" />
                  </label>
                </div>

                <div v-if="itemConfig(product).mode === 'selectable'" class="selectable-price-list">
                  <div class="selectable-price-heading">
                    <span>Selectable Prices</span>
                    <small>Default price must be one of the selected options.</small>
                  </div>
                  <label v-for="price in productPrices(product)" :key="price.price_id" class="selectable-price-row">
                    <input
                      type="checkbox"
                      :checked="itemConfig(product).selectable_price_ids.includes(price.price_id)"
                      @change="toggleSelectablePrice(product, price.price_id)"
                    />
                    <span>{{ priceOptionLabel(price) }}</span>
                    <input
                      v-model.trim="itemConfig(product).labels[price.price_id]"
                      type="text"
                      placeholder="Label"
                      aria-label="Selectable price label"
                    />
                    <input
                      v-model.trim="itemConfig(product).badges[price.price_id]"
                      type="text"
                      placeholder="Badge"
                      aria-label="Selectable price badge"
                    />
                    <label class="default-price-choice">
                      <input v-model="itemConfig(product).default_price_id" type="radio" :value="price.price_id" />
                      <span>Default</span>
                    </label>
                    <div
                      class="selectable-price-image-controls"
                      :class="{ 'has-image-preview': itemConfig(product).price_image_urls[price.price_id] }"
                    >
                      <div
                        v-if="itemConfig(product).price_image_urls[price.price_id]"
                        class="selectable-price-image-preview"
                      >
                        <img
                          :src="itemConfig(product).price_image_urls[price.price_id]"
                          :alt="`${priceOptionLabel(price)} image preview`"
                        />
                      </div>
                      <input
                        :ref="(el) => setPriceImageInput(product, price.price_id, el)"
                        type="file"
                        accept="image/*"
                        hidden
                        @change="handlePriceImagePicked(product, price.price_id, $event)"
                      />
                      <button
                        class="secondary-action compact"
                        type="button"
                        :disabled="Boolean(itemConfig(product).price_image_uploading[price.price_id])"
                        @click.prevent="triggerPriceImageUpload(product, price.price_id)"
                      >
                        {{ itemConfig(product).price_image_uploading[price.price_id] ? "Uploading..." : "Upload Image" }}
                      </button>
                      <input
                        v-model.trim="itemConfig(product).price_image_urls[price.price_id]"
                        type="url"
                        placeholder="Optional price image URL"
                        aria-label="Selectable price image URL"
                      />
                    </div>
                    <div v-if="itemConfig(product).price_image_errors[price.price_id]" class="price-image-error">
                      {{ itemConfig(product).price_image_errors[price.price_id] }}
                    </div>
                  </label>
                </div>
              </article>
            </div>
          </section>

          <section v-if="selectedProducts.length" class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3>Discount</h3>
                <p>Coupons are Stripe-first. Display-only discounts still live on products/prices.</p>
              </div>
            </header>

            <div class="offer-three-column">
              <label class="offer-field">
                <span>Discount Mode</span>
                <select v-model="form.discount.mode" :disabled="productIntent === 'lead_gen'">
                  <option value="none">No Discount</option>
                  <option value="auto">Auto Discount</option>
                  <option value="coupon_code">Coupon Code</option>
                </select>
              </label>

              <div v-if="form.discount.mode === 'coupon_code'" class="offer-field">
                <span>Coupon <strong>*</strong></span>
                <div class="coupon-select-row">
                  <input :value="selectedCouponLabel" class="font-mono" type="text" placeholder="Select a coupon" readonly required />
                  <button class="secondary-action compact" type="button" @click="openCouponSelector">
                    Select Coupon
                  </button>
                </div>
              </div>

              <label v-if="form.discount.mode === 'auto'" class="offer-field">
                <span>Discount Type</span>
                <select v-model="form.discount.type">
                  <option value="percent">Percent</option>
                  <option value="fixed">Fixed Amount</option>
                </select>
              </label>

              <label v-if="form.discount.mode === 'auto'" class="offer-field">
                <span>Value <strong>*</strong></span>
                <input v-model.number="form.discount.value" min="0" type="number" required />
              </label>

              <label v-if="form.discount.mode === 'auto'" class="offer-field">
                <span>Duration</span>
                <select v-model="form.discount.duration">
                  <option value="once">Once</option>
                  <option value="repeating">Repeating</option>
                  <option value="forever">Forever</option>
                </select>
              </label>

              <label v-if="form.discount.mode === 'auto' && form.discount.duration === 'repeating'" class="offer-field">
                <span>Duration Months</span>
                <input v-model.number="form.discount.duration_months" min="1" type="number" />
              </label>
            </div>
          </section>

          <section v-if="selectedProducts.length && productIntent === 'transaction'" class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3>Checkout</h3>
                <p>Payment and subscription behavior comes from checkout mode and selected prices.</p>
              </div>
            </header>

            <div class="offer-three-column">
              <label class="offer-field">
                <span>Phone Number Collection</span>
                <select v-model="form.checkout.phone_number_collection">
                  <option value="inherit">Inherit from tenant settings</option>
                  <option value="enabled">Enabled</option>
                  <option value="disabled">Disabled</option>
                </select>
              </label>

              <label class="checkbox-row offer-checkbox-inline">
                <input v-model="form.checkout.allow_promotion_codes" type="checkbox" />
                <span>Allow promotion codes</span>
              </label>

              <label v-if="form.checkout.allow_promotion_codes" class="offer-field">
                <span>Promotion Code <strong>*</strong></span>
                <input v-model.trim="form.checkout.promotion_code" class="font-mono" type="text" placeholder="SAVE10" required />
              </label>
            </div>
          </section>

          <div v-if="formError" class="keys-status-banner error">{{ formError }}</div>

          <details v-if="latestDraftOffer" class="offer-json-preview">
            <summary>Generated offer JSON</summary>
            <pre>{{ JSON.stringify(latestDraftOffer, null, 2) }}</pre>
          </details>

          <footer class="modal-footer">
            <button class="secondary-action" type="button" @click="closeOfferModal">Cancel</button>
            <button class="primary-action" type="submit">{{ editingOfferId ? "Update Offer" : "Create Offer" }}</button>
          </footer>
        </form>
      </section>
    </div>

    <div v-if="selectedOfferDetails" class="modal-backdrop" @click.self="closeOfferDetails">
      <section class="modal-card offer-details-modal" role="dialog" aria-modal="true" aria-labelledby="offerDetailsTitle">
        <header class="modal-card-header">
          <h2 id="offerDetailsTitle">{{ selectedOfferDetails.name }}</h2>
          <button type="button" class="modal-close" aria-label="Close offer details" @click="closeOfferDetails">×</button>
        </header>
        <div class="offer-details-body">
          <div class="offer-details-summary">
            <span class="offer-intent-badge" :class="selectedOfferDetails.product_intent">
              {{ intentLabel(selectedOfferDetails.product_intent) }}
            </span>
            <span>{{ derivedOfferTypeLabel(selectedOfferDetails) }}</span>
            <span>{{ productSummary(selectedOfferDetails) || "No products" }}</span>
          </div>
          <pre>{{ JSON.stringify(selectedOfferDetails, null, 2) }}</pre>
        </div>
        <footer class="modal-footer">
          <button class="secondary-action" type="button" @click="closeOfferDetails">Close</button>
          <button class="primary-action" type="button" @click="editOffer(selectedOfferDetails)">Edit</button>
        </footer>
      </section>
    </div>

    <div v-if="pendingDeleteOffer" class="modal-backdrop" @click.self="pendingDeleteOffer = null">
      <section class="modal-card confirm-card" role="dialog" aria-modal="true" aria-labelledby="confirmOfferDeleteTitle">
        <header class="confirm-icon danger">×</header>
        <h2 id="confirmOfferDeleteTitle">Delete offer?</h2>
        <p>Delete "{{ pendingDeleteOffer.name || "this offer" }}"?</p>
        <div class="confirm-actions">
          <button type="button" class="secondary-action" @click="pendingDeleteOffer = null">Cancel</button>
          <button type="button" class="primary-action" :disabled="deletingOffer" @click="deleteOffer">Delete</button>
        </div>
      </section>
    </div>

    <div v-if="showProductSelector" class="modal-backdrop offer-selector-backdrop" @click.self="closeProductSelector">
      <section class="modal-card offer-product-selector-modal" role="dialog" aria-modal="true" aria-labelledby="productSelectorTitle">
        <header class="modal-card-header">
          <h2 id="productSelectorTitle">Select Products for Offer</h2>
          <button type="button" class="modal-close" aria-label="Close product selector" @click="closeProductSelector">×</button>
        </header>

        <div class="offer-product-selector-body">
          <input v-model.trim="productSearch" class="offer-product-search" type="search" placeholder="Search products..." />

          <div v-if="productStore.error" class="keys-status-banner error">{{ productStore.error }}</div>
          <div v-if="selectorError" class="keys-status-banner error">{{ selectorError }}</div>
          <div v-if="!productStore.error && !productStore.loaded" class="selector-load-state">
            <p>{{ productStore.loading ? "Loading products..." : "Products will appear here once loaded." }}</p>
          </div>

          <div v-else-if="!productStore.error && !selectorProducts.length" class="selector-load-state">
            No products found.
          </div>

          <div v-else-if="!productStore.error" class="offer-product-grid">
            <button
              v-for="product in selectorProducts"
              :key="productId(product)"
              type="button"
              class="offer-product-card"
              :class="{ selected: draftSelectedProductIds.has(productId(product)), incompatible: isIncompatibleDraftProduct(product) }"
              :disabled="isIncompatibleDraftProduct(product)"
              @click="toggleDraftProduct(productId(product))"
            >
              <div class="offer-product-image">
                <img v-if="product.images?.[0]" :src="product.images[0]" :alt="product.name || 'Product image'" />
                <span v-else>{{ productInitial(product) }}</span>
                <span class="offer-product-check" aria-hidden="true">✓</span>
              </div>
              <span class="offer-product-intent" :class="productIntentFor(product)">
                {{ productIntentLabel(product) }}
              </span>
              <span class="offer-product-name">{{ product.name || "Untitled Product" }}</span>
              <strong>{{ priceText(product) }}</strong>
            </button>
          </div>
        </div>

        <footer class="modal-footer">
          <button class="secondary-action" type="button" @click="closeProductSelector">Cancel</button>
          <button class="primary-action" type="button" @click="applyProductSelection">
            {{ draftSelectedProductIds.size ? `${draftSelectedProductIds.size} selected` : "Apply Selection" }}
          </button>
        </footer>
      </section>
    </div>

    <div v-if="showCouponSelector" class="modal-backdrop offer-selector-backdrop" @click.self="closeCouponSelector">
      <section class="modal-card coupon-selector-modal" role="dialog" aria-modal="true" aria-labelledby="couponSelectorTitle">
        <header class="modal-card-header">
          <h2 id="couponSelectorTitle">Select Coupon for Offer</h2>
          <button type="button" class="modal-close" aria-label="Close coupon selector" @click="closeCouponSelector">×</button>
        </header>

        <div class="offer-product-selector-body">
          <input v-model.trim="couponSearch" class="offer-product-search" type="search" placeholder="Search coupons..." />

          <div v-if="couponStore.error" class="keys-status-banner error">{{ couponStore.error }}</div>
          <div v-if="!couponStore.error && couponStore.loading" class="selector-load-state">
            Loading coupons...
          </div>
          <div v-else-if="!couponStore.error && couponStore.loaded && !couponSelectorCoupons.length" class="selector-load-state">
            No coupons found. Create a coupon before attaching one to an offer.
          </div>

          <div v-else-if="!couponStore.error" class="coupon-selector-grid">
            <button
              v-for="coupon in couponSelectorCoupons"
              :key="coupon.coupon_id"
              type="button"
              class="coupon-selector-card"
              :class="{ selected: form.discount.coupon_id === coupon.coupon_id }"
              @click="selectCoupon(coupon)"
            >
              <span class="coupon-code-pill">{{ coupon.code }}</span>
              <strong>{{ coupon.name || coupon.code }}</strong>
              <small>{{ formatCouponDiscount(coupon) }}</small>
              <span>{{ couponExpiry(coupon) }}</span>
            </button>
          </div>
        </div>

        <footer class="modal-footer">
          <button class="secondary-action" type="button" @click="closeCouponSelector">Cancel</button>
          <button class="primary-action" type="button" :disabled="!form.discount.coupon_id" @click="closeCouponSelector">
            {{ form.discount.coupon_id ? "1 selected" : "Apply Selection" }}
          </button>
        </footer>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import { apiRequest, getApiEnvironment, getTenantId } from "../api/client";
import { formatCouponDiscount, useCouponsStore } from "../stores/coupons";
import { defaultProductPrice, formatMoney, useProductsStore } from "../stores/products";

const productStore = useProductsStore();
const couponStore = useCouponsStore();
const showOfferModal = ref(false);
const showProductSelector = ref(false);
const showCouponSelector = ref(false);
const productSearch = ref("");
const couponSearch = ref("");
const selectedProductIds = ref([]);
const draftSelectedProductIds = ref(new Set());
const formError = ref("");
const selectorError = ref("");
const offers = ref([]);
const offersLoading = ref(false);
const offersLoaded = ref(false);
const offersError = ref("");
const offersMessage = ref("");
const latestDraftOffer = ref(null);
const openOfferMenuId = ref("");
const editingOfferId = ref("");
const selectedOfferDetails = ref(null);
const pendingDeleteOffer = ref(null);
const deletingOffer = ref(false);
const form = reactive(defaultOfferForm());
const itemConfigs = reactive({});
const priceImageInputs = new Map();
let productsLoadPromise = null;

const activeProducts = computed(() => productStore.products.filter((product) => product.status !== "archived" && product.active !== false));
const productsById = computed(() => new Map(productStore.products.map((product) => [productId(product), product])));
const selectedProducts = computed(() => activeProducts.value.filter((product) => selectedProductIds.value.includes(productId(product))));
const selectorProducts = computed(() => {
  const term = productSearch.value.toLowerCase();
  if (!term) return activeProducts.value;
  return activeProducts.value.filter((product) => [
    product.name,
    product.description,
    product.product_id,
    product.product_category,
    ...(Array.isArray(product.tags) ? product.tags : []),
  ].filter(Boolean).join(" ").toLowerCase().includes(term));
});
const couponSelectorCoupons = computed(() => {
  const term = couponSearch.value.toLowerCase();
  const coupons = couponStore.usableCoupons;
  if (!term) return coupons;
  return coupons.filter((coupon) => [
    coupon.name,
    coupon.code,
    coupon.coupon_id,
    coupon.stripe_coupon_id,
    coupon.stripe_promo_code_id,
    coupon.discount?.type,
  ].filter(Boolean).join(" ").toLowerCase().includes(term));
});
const selectedCouponLabel = computed(() => {
  if (!form.discount.coupon_id) return "";
  const coupon = couponStore.coupons.find((item) => item.coupon_id === form.discount.coupon_id);
  if (!coupon) return form.discount.coupon_id;
  return `${coupon.code} - ${coupon.name || formatCouponDiscount(coupon)}`;
});
const detectedOfferType = computed(() => detectOfferType(selectedProducts.value));
const productIntent = computed(() => {
  const intents = new Set(selectedProducts.value.map(productIntentFor));
  return intents.size === 1 ? [...intents][0] : "mixed";
});
const draftSelectedIntent = computed(() => {
  const selectedDraftProducts = activeProducts.value.filter((product) => draftSelectedProductIds.value.has(productId(product)));
  const intents = new Set(selectedDraftProducts.map(productIntentFor));
  return intents.size === 1 ? [...intents][0] : "";
});
const detectedOfferTypeLabel = computed(() => {
  const labels = {
    single_product: "SINGLE OFFER",
    bundle: "BUNDLE",
  };
  return labels[detectedOfferType.value] || "OFFER";
});
const detectedOfferTypeDescription = computed(() => {
  const descriptions = {
    single_product: "One product or one customer-selectable product family",
    bundle: "Multiple products sold together in one offer",
  };
  return descriptions[detectedOfferType.value] || "";
});

watch(selectedProducts, (products) => {
  syncItemConfigs(products);
  if (!products.length) return;
  const label = generateOfferLabel(products, detectedOfferType.value);
  if (!form.name || !form.userEditedName) {
    form.name = label;
    form.slug = slugify(label);
  }
}, { immediate: true });

watch(() => form.name, (value, oldValue) => {
  if (!oldValue || value === generateOfferLabel(selectedProducts.value, detectedOfferType.value)) return;
  form.userEditedName = true;
  if (!form.userEditedSlug) form.slug = slugify(value);
});

watch(() => form.slug, (value, oldValue) => {
  if (oldValue && value !== slugify(form.name)) form.userEditedSlug = true;
});

watch(productIntent, (intent) => {
  if (intent === "lead_gen") form.discount.mode = "none";
});

function defaultOfferForm() {
  return {
    name: "",
    slug: "",
    discount: {
      mode: "none",
      coupon_id: "",
      type: "percent",
      value: 0,
      duration: "once",
      duration_months: 1,
      first_time_only: false,
    },
    checkout: {
      phone_number_collection: "inherit",
      allow_promotion_codes: false,
      promotion_code: "",
    },
    userEditedName: false,
    userEditedSlug: false,
  };
}

function resetForm() {
  Object.assign(form, defaultOfferForm());
  editingOfferId.value = "";
  selectedProductIds.value = [];
  draftSelectedProductIds.value = new Set();
  formError.value = "";
  latestDraftOffer.value = null;
  Object.keys(itemConfigs).forEach((key) => delete itemConfigs[key]);
  priceImageInputs.clear();
  showCouponSelector.value = false;
  couponSearch.value = "";
}

function openOfferModal(offer = null) {
  resetForm();
  if (offer) loadOfferIntoForm(offer);
  showOfferModal.value = true;
}

function closeOfferModal() {
  showOfferModal.value = false;
  showProductSelector.value = false;
  showCouponSelector.value = false;
}

async function openProductSelector() {
  draftSelectedProductIds.value = new Set(selectedProductIds.value);
  productSearch.value = "";
  selectorError.value = "";
  showProductSelector.value = true;
  if (!productStore.loaded && !productStore.loading) {
    await productStore.load();
  }
}

function closeProductSelector() {
  showProductSelector.value = false;
  selectorError.value = "";
}

async function openCouponSelector() {
  couponSearch.value = "";
  showCouponSelector.value = true;
  if (!couponStore.loaded && !couponStore.loading) {
    await couponStore.load({ status: "all" });
  }
}

function closeCouponSelector() {
  showCouponSelector.value = false;
}

function applyProductSelection() {
  if (!draftSelectionIsCompatible()) {
    selectorError.value = "An offer cannot mix transaction products with lead generation products.";
    return;
  }
  selectedProductIds.value = [...draftSelectedProductIds.value];
  showProductSelector.value = false;
  selectorError.value = "";
}

function toggleDraftProduct(id) {
  const next = new Set(draftSelectedProductIds.value);
  if (next.has(id)) next.delete(id);
  else {
    const product = activeProducts.value.find((item) => productId(item) === id);
    if (!product) return;
    const selectedIntent = draftSelectedIntent.value;
    const nextIntent = productIntentFor(product);
    if (selectedIntent && selectedIntent !== nextIntent) {
      selectorError.value = `Cannot add ${product.name || "this product"} because ${productIntentLabel(product).toLowerCase()} products cannot be mixed with ${intentLabel(selectedIntent).toLowerCase()} products.`;
      return;
    }
    selectorError.value = "";
    next.add(id);
  }
  draftSelectedProductIds.value = next;
}

function removeSelectedProduct(id) {
  selectedProductIds.value = selectedProductIds.value.filter((productIdValue) => productIdValue !== id);
}

async function loadOffers() {
  offersLoading.value = true;
  offersError.value = "";
  offersMessage.value = "";
  try {
    const body = await apiRequest("/offers");
    offers.value = (Array.isArray(body.offers) ? body.offers : []).map(offerCardModel);
    offersLoaded.value = true;
    offersMessage.value = offers.value.length
      ? `${offers.value.length} offer${offers.value.length === 1 ? "" : "s"} loaded.`
      : "";
    ensureProductsLoaded().catch(() => {});
  } catch (error) {
    offersError.value = error.message || "Failed to load offers.";
  } finally {
    offersLoading.value = false;
  }
}

function toggleOfferMenu(offerId) {
  openOfferMenuId.value = openOfferMenuId.value === offerId ? "" : offerId;
}

function viewOffer(offer) {
  selectedOfferDetails.value = offer;
  openOfferMenuId.value = "";
}

function closeOfferDetails() {
  selectedOfferDetails.value = null;
}

async function editOffer(offer) {
  selectedOfferDetails.value = null;
  openOfferMenuId.value = "";
  offersError.value = "";
  try {
    await ensureProductsLoaded();
  } catch (error) {
    offersError.value = error.message || "Failed to load products for this offer.";
    return;
  }
  openOfferModal(offer);
}

function requestDeleteOffer(offer) {
  openOfferMenuId.value = "";
  pendingDeleteOffer.value = offer;
}

async function deleteOffer() {
  if (!pendingDeleteOffer.value) return;
  const offer = pendingDeleteOffer.value;
  const offerName = offer?.name || "this offer";
  offersError.value = "";
  offersMessage.value = "";
  deletingOffer.value = true;
  try {
    await apiRequest(`/offers/${encodeURIComponent(offer.offer_id)}`, { method: "DELETE" });
    offers.value = offers.value.filter((item) => item.offer_id !== offer.offer_id);
    pendingDeleteOffer.value = null;
    offersMessage.value = `${offerName} was deleted.`;
  } catch (error) {
    offersError.value = error.message || "Failed to delete offer.";
  } finally {
    deletingOffer.value = false;
  }
}

async function ensureProductsLoaded() {
  if (productStore.loaded) return;
  if (productsLoadPromise) return productsLoadPromise;
  if (productStore.loading) {
    await waitForProductsLoaded();
    return;
  }
  productsLoadPromise = productStore.load().finally(() => {
    productsLoadPromise = null;
  });
  return productsLoadPromise;
}

async function waitForProductsLoaded() {
  while (productStore.loading) {
    await sleep(50);
  }
  if (!productStore.loaded && productStore.error) {
    throw new Error(productStore.error);
  }
}

async function createOffer() {
  formError.value = "";
  const result = buildOfferDocument();
  if (result.error) {
    formError.value = result.error;
    return;
  }
  latestDraftOffer.value = result.offer;
  try {
    const body = await apiRequest("/offers", { method: "POST", body: result.offer });
    const savedOffer = offerCardModel(body.offer || result.offer);
    offers.value = editingOfferId.value
      ? offers.value.map((offer) => offer.offer_id === editingOfferId.value ? savedOffer : offer)
      : [savedOffer, ...offers.value];
    offersLoaded.value = true;
    offersMessage.value = `${result.offer.name} was ${editingOfferId.value ? "updated" : "saved"}.`;
    showOfferModal.value = false;
  } catch (error) {
    formError.value = error.message || "Failed to save offer.";
  }
}

function buildOfferDocument() {
  if (!selectedProducts.value.length) return { error: "Select at least one product for this offer." };
  if (!form.name || !form.slug) return { error: "Offer label and slug are required." };
  if (productIntent.value === "mixed") return { error: "An offer cannot mix transaction and lead generation products." };
  const checkoutMode = inferredCheckoutMode();
  if (checkoutMode === "mixed") return { error: "An offer cannot mix one-time and recurring prices." };
  if (form.discount.mode === "coupon_code" && !form.discount.coupon_id) return { error: "Select a coupon or choose No Discount." };
  if (form.checkout.allow_promotion_codes && !form.checkout.promotion_code) return { error: "Promotion code is required when promotion codes are enabled." };

  const now = Math.floor(Date.now() / 1000);
  const offerId = editingOfferId.value || localId("offer");
  const items = [];
  for (const product of selectedProducts.value) {
    const config = itemConfig(product);
    const prices = productPrices(product);
    if (!prices.length) return { error: `${product.name || product.product_id} has no prices to attach to this offer.` };

    if (config.mode === "fixed") {
      if (!config.price_id) return { error: `Choose a fixed price for ${product.name || product.product_id}.` };
      items.push(cleanObject({
        product_id: productId(product),
        price_id: config.price_id,
        quantity: Math.max(1, Number(config.quantity || 1)),
      }));
    } else {
      const selectedPriceIds = config.selectable_price_ids.filter((priceId) => prices.some((price) => price.price_id === priceId));
      if (!selectedPriceIds.length) return { error: `Choose at least one selectable price for ${product.name || product.product_id}.` };
      if (!selectedPriceIds.includes(config.default_price_id)) return { error: `Default price for ${product.name || product.product_id} must be selected.` };
      items.push(cleanObject({
        product_id: productId(product),
        selectable_prices: selectedPriceIds.map((priceId) => {
          const price = prices.find((item) => item.price_id === priceId);
          return cleanObject({
            price_id: priceId,
            quantity: price?.quantity || 1,
            label: config.labels[priceId] || selectablePriceDefaultLabel(price),
            badge: config.badges[priceId],
            image_url: config.price_image_urls[priceId],
            display_discount_pct: displayDiscountPct(price),
          });
        }),
        default_price_id: config.default_price_id,
      }));
    }
  }
  const priceContexts = selectedPriceContexts();

  const offer = cleanObject({
    schema_version: "2026-05-29",
    document_type: "offer",
    tenant_id: getTenantId(),
    offer_id: offerId,
    slug: form.slug,
    name: form.name,
    status: "active",
    product_intent: productIntent.value,
    stripe_mode: getApiEnvironment(),
    items,
    discount: buildDiscountBlock(),
    eligibility: {
      requires_prior_purchase: priceContexts.some((context) => ["upsell", "downsell", "order_bump"].includes(context)),
      allowed_price_contexts: priceContexts,
      starts_at: null,
      ends_at: null,
    },
    presentation: {
      headline: form.name,
      cta_label: "Buy Now",
    },
    checkout: productIntent.value === "transaction" ? {
      mode: checkoutMode,
      phone_number_collection: form.checkout.phone_number_collection,
      allow_promotion_codes: Boolean(form.checkout.allow_promotion_codes),
      metadata: {
        offer_id: offerId,
      },
    } : undefined,
    sync: {
      status: "pending",
      last_synced_at: null,
      error: null,
    },
    created_at: now,
    updated_at: now,
  });
  return { offer };
}

function loadOfferIntoForm(offer) {
  editingOfferId.value = offer.offer_id;
  form.name = offer.name || "";
  form.slug = offer.slug || slugify(offer.name);
  form.userEditedName = true;
  form.userEditedSlug = true;
  form.discount = {
    ...defaultOfferForm().discount,
    ...(offer.discount || {}),
    type: offer.discount?.type || "percent",
    value: Number(offer.discount?.value || 0),
    duration: offer.discount?.duration || "once",
    duration_months: Number(offer.discount?.duration_months || 1),
    first_time_only: Boolean(offer.discount?.first_time_only),
  };
  form.checkout = {
    ...defaultOfferForm().checkout,
    ...(offer.checkout || {}),
  };

  const items = Array.isArray(offer.items) ? offer.items : [];
  selectedProductIds.value = items.map((item) => item.product_id).filter(Boolean);
  Object.keys(itemConfigs).forEach((key) => delete itemConfigs[key]);

  items.forEach((item) => {
    const product = productsById.value.get(item.product_id);
    if (!product) return;
    const config = itemConfig(product);
    if (Array.isArray(item.selectable_prices) && item.selectable_prices.length) {
      config.mode = "selectable";
      config.selectable_price_ids = item.selectable_prices.map((price) => price.price_id).filter(Boolean);
      config.default_price_id = item.default_price_id || config.selectable_price_ids[0] || "";
      config.labels = Object.fromEntries(item.selectable_prices.map((price) => [price.price_id, price.label || selectablePriceDefaultLabel(price)]));
      config.badges = Object.fromEntries(item.selectable_prices.map((price) => [price.price_id, price.badge || ""]));
      config.price_image_urls = Object.fromEntries(item.selectable_prices.map((price) => [price.price_id, price.image_url || ""]));
    } else {
      config.mode = "fixed";
      config.price_id = item.price_id || "";
      config.quantity = Number(item.quantity || 1);
    }
  });
}

function buildDiscountBlock() {
  if (productIntent.value === "lead_gen") return { mode: "none" };
  if (form.checkout.allow_promotion_codes) {
    return {
      mode: "promotion_code",
      promotion_code: form.checkout.promotion_code,
      coupon_id: form.discount.mode === "coupon_code" ? form.discount.coupon_id : undefined,
    };
  }
  if (form.discount.mode === "none") return { mode: "none" };
  if (form.discount.mode === "coupon_code") {
    return {
      mode: "coupon_code",
      coupon_id: form.discount.coupon_id,
    };
  }
  const discount = {
    mode: "auto",
    type: form.discount.type,
    value: Number(form.discount.value || 0),
    duration: form.discount.duration,
    first_time_only: Boolean(form.discount.first_time_only),
  };
  if (form.discount.type === "fixed") discount.currency = inferredCurrency();
  if (form.discount.duration === "repeating") discount.duration_months = Math.max(1, Number(form.discount.duration_months || 1));
  return discount;
}

function syncItemConfigs(products) {
  const productIds = new Set(products.map(productId));
  Object.keys(itemConfigs).forEach((id) => {
    if (!productIds.has(id)) delete itemConfigs[id];
  });
  products.forEach((product) => {
    itemConfig(product);
  });
}

function itemConfig(product) {
  const id = productId(product);
  if (!itemConfigs[id]) {
    const prices = productPrices(product);
    const defaultPrice = defaultProductPrice(product) || prices[0] || {};
    itemConfigs[id] = {
      mode: prices.length > 1 ? "selectable" : "fixed",
      price_id: defaultPrice.price_id || "",
      quantity: 1,
      selectable_price_ids: prices.map((price) => price.price_id).filter(Boolean),
      default_price_id: defaultPrice.price_id || prices[0]?.price_id || "",
      labels: Object.fromEntries(prices.map((price) => [price.price_id, selectablePriceDefaultLabel(price)])),
      badges: {},
      price_image_urls: {},
      price_image_uploading: {},
      price_image_errors: {},
    };
  }
  return itemConfigs[id];
}

function toggleSelectablePrice(product, priceId) {
  const config = itemConfig(product);
  if (config.selectable_price_ids.includes(priceId)) {
    config.selectable_price_ids = config.selectable_price_ids.filter((id) => id !== priceId);
    if (config.default_price_id === priceId) config.default_price_id = config.selectable_price_ids[0] || "";
  } else {
    config.selectable_price_ids.push(priceId);
    if (!config.default_price_id) config.default_price_id = priceId;
  }
}

function selectCoupon(coupon) {
  form.discount.coupon_id = coupon.coupon_id;
  showCouponSelector.value = false;
}

function couponExpiry(coupon) {
  const expiresAt = coupon?.restrictions?.expires_at;
  if (!expiresAt) return "Never expires";
  return `Expires ${new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(new Date(Number(expiresAt) * 1000))}`;
}

function setPriceImageInput(product, priceId, element) {
  const key = priceImageInputKey(product, priceId);
  if (element) priceImageInputs.set(key, element);
  else priceImageInputs.delete(key);
}

function triggerPriceImageUpload(product, priceId) {
  priceImageInputs.get(priceImageInputKey(product, priceId))?.click();
}

async function handlePriceImagePicked(product, priceId, event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  const config = itemConfig(product);
  config.price_image_errors[priceId] = "";
  if (!file.type.startsWith("image/") || file.size > 10 * 1024 * 1024) {
    config.price_image_errors[priceId] = "Use an image file up to 10MB.";
    return;
  }
  config.price_image_uploading[priceId] = true;
  try {
    config.price_image_urls[priceId] = await uploadOfferPriceImage(file);
  } catch (error) {
    config.price_image_errors[priceId] = error.message || "Image upload failed.";
  } finally {
    config.price_image_uploading[priceId] = false;
  }
}

function priceImageInputKey(product, priceId) {
  return `${productId(product)}:${priceId}`;
}

async function uploadOfferPriceImage(file) {
  const presigned = await apiRequest("/upload/multiple", {
    method: "POST",
    body: {
      fileName: file.name,
      contentType: file.type,
      basePrefix: "offers",
      targetBucket: "images.juniorbay.net",
    },
  });
  const formData = new FormData();
  Object.entries(presigned.upload?.fields || {}).forEach(([key, value]) => formData.append(key, value));
  formData.append("file", file);
  const uploadResponse = await fetch(presigned.upload.url, { method: "POST", body: formData });
  if (!uploadResponse.ok) throw new Error("Failed to upload file");
  return pollOfferImageUrl(presigned.id);
}

async function pollOfferImageUrl(imageId) {
  const deadline = Date.now() + 180000;
  let delay = 1200;
  while (Date.now() < deadline) {
    await sleep(delay);
    delay = Math.min(8000, Math.ceil(delay * 1.35));
    const body = await apiRequest(`/upload/status/${encodeURIComponent(imageId)}`).catch(() => ({}));
    if (body.status === "failed") throw new Error("Image processing failed");
    for (const url of imageUrlCandidates(body.urls || {})) {
      if (await imageUrlLoads(url)) return url;
    }
  }
  throw new Error("Timed out waiting for processed image");
}

function imageUrlCandidates(urls) {
  return [...new Set([
    urls.small?.webp,
    urls.small?.jpg,
    urls.medium?.webp,
    urls.medium?.jpg,
    urls.large?.webp,
    urls.large?.jpg,
    urls.original,
  ].filter(Boolean).map(cdnImageUrl))];
}

function cdnImageUrl(url) {
  return String(url || "").replace("images.juniorbay.net", "images.juniorbay.com");
}

function imageUrlLoads(url, timeoutMs = 4000) {
  return new Promise((resolve) => {
    const image = new Image();
    const timeout = setTimeout(() => finish(false), timeoutMs);
    function finish(result) {
      clearTimeout(timeout);
      image.onload = null;
      image.onerror = null;
      resolve(result);
    }
    image.onload = () => finish(true);
    image.onerror = () => finish(false);
    image.src = `${url}${url.includes("?") ? "&" : "?"}_probe=${Date.now()}`;
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function productId(product) {
  return product.product_id || product.id || product.stripe_product_id || product.name;
}

function productIntentFor(product) {
  return product?.product_intent || "transaction";
}

function intentLabel(intent) {
  return intent === "lead_gen" ? "Lead generation" : "Transaction";
}

function productIntentLabel(product) {
  return intentLabel(productIntentFor(product));
}

function isIncompatibleDraftProduct(product) {
  const selectedIntent = draftSelectedIntent.value;
  return Boolean(
    selectedIntent
      && !draftSelectedProductIds.value.has(productId(product))
      && productIntentFor(product) !== selectedIntent
  );
}

function draftSelectionIsCompatible() {
  const selectedDraftProducts = activeProducts.value.filter((product) => draftSelectedProductIds.value.has(productId(product)));
  return new Set(selectedDraftProducts.map(productIntentFor)).size <= 1;
}

function productInitial(product) {
  return String(product.name || "P").trim().slice(0, 1).toUpperCase();
}

function productPrices(product) {
  return (Array.isArray(product?.prices) ? product.prices : []).filter((price) => price && price.price_id);
}

function selectedOfferPrices() {
  const selectedPrices = [];
  for (const product of selectedProducts.value) {
    const config = itemConfig(product);
    const prices = productPrices(product);
    if (config.mode === "fixed") {
      const price = prices.find((item) => item.price_id === config.price_id);
      if (price) selectedPrices.push(price);
    } else {
      for (const priceId of config.selectable_price_ids) {
        const price = prices.find((item) => item.price_id === priceId);
        if (price) selectedPrices.push(price);
      }
    }
  }
  return selectedPrices;
}

function selectedPriceContexts() {
  const contexts = selectedOfferPrices().map((price) => price.context || "standard");
  return [...new Set(contexts.length ? contexts : ["standard"])];
}

function inferredCurrency() {
  const currencies = selectedOfferPrices().map((price) => String(price.currency || "usd").toLowerCase());
  return [...new Set(currencies)][0] || "usd";
}

function inferredCheckoutMode() {
  if (productIntent.value !== "transaction") return undefined;
  const models = new Set(selectedOfferPrices().map((price) => price.pricing_model || "one_time"));
  const hasRecurring = models.has("recurring") || models.has("subscription");
  const hasOneTime = [...models].some((model) => !["recurring", "subscription"].includes(model));
  if (hasRecurring && hasOneTime) return "mixed";
  return hasRecurring ? "subscription" : "payment";
}

function priceText(product) {
  const price = defaultProductPrice(product);
  return price ? formatMoney(price.unit_amount, price.currency) : "No price";
}

function priceOptionLabel(price) {
  const quantity = Number(price?.quantity || 1);
  const context = price?.context && price.context !== "standard" ? ` - ${contextLabel(price.context)}` : "";
  return `${quantity} ${quantity === 1 ? "item" : "items"} - ${formatMoney(price?.unit_amount, price?.currency)}${context}`;
}

function selectablePriceDefaultLabel(price) {
  const quantity = Number(price?.quantity || 1);
  return `${quantity} ${quantity === 1 ? "Item" : "Items"}`;
}

function displayDiscountPct(price) {
  const compareAt = Number(price?.compare_at_unit_amount || 0);
  const amount = Number(price?.unit_amount || 0);
  if (!compareAt || compareAt <= amount) return undefined;
  return Math.round(((compareAt - amount) / compareAt) * 100);
}

function detectOfferType(products) {
  if (!products.length) return "single_product";
  if (products.length > 1) return "bundle";
  return "single_product";
}

function generateOfferLabel(products, type) {
  if (!products.length) return "";
  const baseName = String(products[0].name || "Product").split(" - ")[0].trim() || "Product";
  return `${baseName} ${type === "bundle" ? "Bundle" : "Single Offer"}`;
}

function contextLabel(value) {
  const labels = {
    standard: "Standard",
    sale: "Sale",
    flash_sale: "Flash Sale",
    upsell: "Upsell",
    downsell: "Downsell",
    order_bump: "Order Bump",
  };
  return labels[value] || titleCase(value);
}

function titleCase(value) {
  return String(value || "").replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function offerCardModel(offer) {
  const {
    offer_type,
    intentLabel,
    image,
    productSummary,
    ...document
  } = offer || {};
  return document;
}

function offerImage(offer) {
  const items = Array.isArray(offer?.items) ? offer.items : [];
  const firstProduct = productsById.value.get(items[0]?.product_id);
  return offer?.presentation?.image_url || offer?.presentation?.hero_image_url || firstProduct?.images?.[0] || "";
}

function productSummary(offer) {
  const items = Array.isArray(offer?.items) ? offer.items : [];
  return items.map((item) => item.product_id).filter(Boolean).join(", ");
}

function derivedOfferType(offer) {
  const items = Array.isArray(offer?.items) ? offer.items : [];
  if (items.length === 1 && Array.isArray(items[0]?.selectable_prices) && items[0].selectable_prices.length) {
    return "single_product_selector";
  }
  return items.length > 1 ? "bundle" : "single_product";
}

function derivedOfferTypeLabel(offer) {
  return titleCase(derivedOfferType(offer));
}

function slugify(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function cleanObject(value) {
  if (Array.isArray(value)) return value.map(cleanObject);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value)
    .filter(([, item]) => item !== undefined && item !== "")
    .map(([key, item]) => [key, cleanObject(item)]));
}

function localId(prefix = "local") {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
  const cryptoApi = globalThis.crypto;
  const bytes = cryptoApi?.getRandomValues ? cryptoApi.getRandomValues(new Uint8Array(11)) : null;
  const suffix = Array.from({ length: 11 }, (_, index) => alphabet[(bytes ? bytes[index] : Math.floor(Math.random() * 62)) % alphabet.length]).join("");
  return `${prefix}_${suffix}`;
}
</script>
