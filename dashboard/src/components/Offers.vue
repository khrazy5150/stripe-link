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

        <div class="offer-status-filter">
          <label>
            <span>Search</span>
            <input
              v-model.trim="offerSearchQuery"
              type="search"
              placeholder="Name, slug, product..."
              @focus="ensureOffersLoaded()"
            />
          </label>
          <label>
            <span>Status</span>
            <select v-model="offerStatusFilter" @focus="ensureOffersLoaded()">
              <option value="active">Active</option>
              <option value="archived">Archived</option>
              <option value="all">All</option>
            </select>
          </label>
        </div>

        <div v-if="!offers.length" class="offer-empty-state">
          {{ offersLoading ? "Loading offers..." : offersLoaded ? 'No offers found. Click "+ Add Offer" to configure one.' : 'Click "Load Offers" to see offers.' }}
        </div>
        <div v-else-if="!visibleOffers.length" class="offer-empty-state">
          No {{ offerStatusFilter === 'all' ? '' : offerStatusFilter }} offers to show.
        </div>

        <div v-else class="product-card-list">
          <ListCard
            v-for="offer in visibleOffers"
            :key="offer.offer_id"
            :image="offerImage(offer)"
            :icon-color-key="offer.offer_id"
            :title="offer.name"
            :archived="offer.status === 'archived'"
          >
            <template #icon>
              <svg class="offer-card-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 12v7.5A1.5 1.5 0 0 1 18.5 21h-13A1.5 1.5 0 0 1 4 19.5V12m16 0H4m16 0h-4.5A3.5 3.5 0 0 0 19 8.5 2.5 2.5 0 0 0 14.5 7L12 12m-8 0h4.5A3.5 3.5 0 0 1 5 8.5 2.5 2.5 0 0 1 9.5 7L12 12m0 0v9" />
              </svg>
            </template>
            <template #badge>
              <span class="offer-intent-badge" :class="offer.product_intent">{{ intentLabel(offer.product_intent) }}</span>
            </template>
            <template #description>
              <p><strong>Type:</strong> {{ derivedOfferTypeLabel(offer) }}</p>
              <p :title="itemSummaryTitle(offer)"><strong>Items:</strong> {{ itemSummary(offer) }}</p>
            </template>
            <template #actions>
              <button type="button" class="secondary-action" @click="viewOffer(offer)">View</button>
              <button type="button" class="secondary-action" @click="editOffer(offer)">Edit</button>
              <button type="button" class="secondary-action" @click="setOfferStatus(offer, offer.status === 'archived' ? 'active' : 'archived')">
                {{ offer.status === "archived" ? "Restore" : "Archive" }}
              </button>
              <button
                v-if="offer.status === 'archived'"
                type="button"
                class="secondary-action danger-action"
                @click="requestDeleteOffer(offer)"
              >
                Delete
              </button>
            </template>
          </ListCard>
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
              <span>1. Select Items <strong>*</strong></span>
              <button type="button" class="secondary-action stretch" @click="openProductSelector">
                Select Items Visually
              </button>
              <small>Pick every product in this offer — landing items plus any order-bump / upsell / downsell products. Each product's role is inferred from its pricing context (set in Products), so there's nothing more to configure here.</small>
            </label>

            <div class="selected-products-list">
              <div v-if="!selectedItems.length" class="selected-products-empty">No items selected</div>
              <template v-else>
                <button
                  v-for="item in selectedItems"
                  :key="item.kind + ':' + item.id"
                  type="button"
                  class="selected-product-badge"
                  @click="removeSelectedItem(item)"
                >
                  <span>{{ item.name }}</span>
                  <span aria-hidden="true">×</span>
                </button>
              </template>
            </div>

            <div v-if="landingProducts.length" class="offer-field">
              <span>Detected Offer Type</span>
              <div class="offer-type-row">
                <span class="offer-type-badge">{{ detectedOfferTypeLabel }}</span>
                <small>{{ detectedOfferTypeDescription }}</small>
              </div>
            </div>
          </section>

          <section v-if="hasService" class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3>Service Options</h3>
                <p>Choose whether the customer pays first then books, or books first and pays via invoice.</p>
              </div>
            </header>
            <div class="offer-three-column">
              <label class="offer-field">
                <span>Booking flow</span>
                <select v-model="form.service_booking_flow">
                  <option value="pay_then_book">Pay first, then book</option>
                  <option value="book_then_pay">Book first, pay later</option>
                </select>
              </label>
              <label v-if="scheduledServiceCount > 1" class="offer-field">
                <span>Scheduling</span>
                <select v-model="form.service_booking_mode">
                  <option value="single_visit">One combined visit</option>
                  <option value="separate_visits">Separate visits</option>
                </select>
              </label>
            </div>
          </section>

          <section v-if="selectedProducts.length || hasService" class="offer-form-section">
            <div class="offer-two-column">
              <label class="offer-field">
                <span>Offer Label <strong>*</strong></span>
                <input v-model.trim="form.name" type="text" placeholder="Name this offer..." required @input="onLabelInput" />
                <small>Auto-generated label (you can modify it)</small>
              </label>

              <label class="offer-field">
                <span>Slug <strong>*</strong></span>
                <input v-model.trim="form.slug" class="font-mono" type="text" placeholder="auto-generated-from-label" required @input="form.userEditedSlug = true" />
                <small v-if="slugCollisionResolved && !form.userEditedSlug">URL-friendly identifier — another offer already uses that slug, so this one was numbered. Edit it if you'd rather choose.</small>
                <small v-else>URL-friendly identifier</small>
              </label>
            </div>

            <label class="offer-field">
              <span>Brand</span>
              <select v-model="form.brand">
                <option value="">No brand — use business, then product name</option>
                <option v-for="brand in profileBrands" :key="brand" :value="brand">{{ brand }}</option>
                <option v-if="form.brand && !profileBrands.includes(form.brand)" :value="form.brand">{{ form.brand }}</option>
              </select>
              <small>Optional. The brand shown on the landing page. Manage your brands in Profile → Business.</small>
            </label>

            <div v-if="landingProducts.length" class="detected-offer-type">
              <span>{{ detectedOfferTypeLabel }}</span>
              <strong>{{ detectedOfferTypeDescription }}</strong>
            </div>
          </section>

          <section v-if="landingProducts.length" class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3>Offer Items</h3>
                <p>Choose fixed prices or customer-selectable price options.</p>
              </div>
            </header>

            <div class="offer-items-list">
              <article v-for="product in landingProducts" :key="productId(product)" class="offer-item-editor">
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
                      <option v-for="price in landingPrices(product)" :key="price.price_id" :value="price.price_id">
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
                  <label v-for="price in landingPrices(product)" :key="price.price_id" class="selectable-price-row">
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

          <section v-if="landingProducts.length" class="offer-form-section">
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

          <section v-if="landingProducts.length && productIntent === 'transaction'" class="offer-form-section">
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

          <section v-if="landingProducts.length && productIntent === 'transaction'" class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3>Purchase Flow</h3>
                <p>Read-only. Every step is inferred from your selected products' pricing contexts (set in Products → pricing context) — nothing to choose here.</p>
              </div>
            </header>

            <PurchaseFlowDiagram :offer-name="form.name" :stages="offerFunnelStages" />
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
            <span>{{ itemSummary(selectedOfferDetails) || "No items" }}</span>
          </div>
          <!-- The card line collapses the funnel to counts, and its full breakdown is a hover TITLE, which a
               touch device cannot show. View is the mobile path to the same information, so the flow is
               rendered here in full — same component the Edit form uses, fed from the saved document. -->
          <section v-if="detailsFunnelStages.length" class="offer-details-funnel">
            <h3>Purchase Flow</h3>
            <PurchaseFlowDiagram :offer-name="selectedOfferDetails.name" :stages="detailsFunnelStages" />
          </section>
          <pre>{{ JSON.stringify(selectedOfferDetails, null, 2) }}</pre>
        </div>
        <footer class="modal-footer">
          <button class="secondary-action" type="button" @click="closeOfferDetails">Close</button>
          <button class="primary-action" type="button" @click="editOffer(selectedOfferDetails)">Edit</button>
        </footer>
      </section>
    </div>

    <ConfirmDialog
      :open="!!pendingDeleteOffer"
      danger
      title="Delete offer?"
      confirm-label="Delete"
      :busy="deletingOffer"
      @cancel="pendingDeleteOffer = null"
      @confirm="deleteOffer"
    >
      Delete "{{ pendingDeleteOffer?.name || "this offer" }}"?
    </ConfirmDialog>

    <div v-if="showProductSelector" class="modal-backdrop offer-selector-backdrop" @click.self="closeProductSelector">
      <section class="modal-card offer-product-selector-modal" role="dialog" aria-modal="true" aria-labelledby="productSelectorTitle">
        <header class="modal-card-header">
          <h2 id="productSelectorTitle">Select Items for Offer</h2>
          <button type="button" class="modal-close" aria-label="Close item selector" @click="closeProductSelector">×</button>
        </header>

        <div class="offer-product-selector-body">
          <input v-model.trim="productSearch" class="offer-product-search" type="search" placeholder="Search items..." />

          <div v-if="productStore.error" class="keys-status-banner error">{{ productStore.error }}</div>
          <div v-if="selectorError" class="keys-status-banner error">{{ selectorError }}</div>
          <div v-if="!productStore.error && !productStore.loaded" class="selector-load-state">
            <p>{{ productStore.loading ? "Loading products..." : "Products will appear here once loaded." }}</p>
          </div>

          <div v-else-if="!productStore.error && !selectorItems.length" class="selector-load-state">
            No items found.
          </div>

          <div v-else-if="!productStore.error" class="offer-product-grid">
            <button
              v-for="product in selectorItems"
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
import { computed, onMounted, reactive, ref, watch } from "vue";
import { apiRequest, getStripeMode, getTenantId, toAssetCdnUrl } from "../api/client";
import { formatCouponDiscount, useCouponsStore } from "../stores/coupons";
import { defaultProductPrice, formatMoney, useProductsStore } from "../stores/products";
import { useServicesStore } from "../stores/services";
import { useProfileStore } from "../stores/profile";
import { sanitizeSlug, slugTokens, uniqueSlug } from "../composables/slugs";
import { itemSummary as offerItemSummary, itemSummaryTitle as offerItemSummaryTitle, searchableItemText } from "../composables/offerItems";
import { stagesFromSavedOffer } from "../composables/purchaseFlow";
import ConfirmDialog from "./shared/ConfirmDialog.vue";
import ListCard from "./shared/ListCard.vue";
import PurchaseFlowDiagram from "./PurchaseFlowDiagram.vue";

const productStore = useProductsStore();
const couponStore = useCouponsStore();
const servicesStore = useServicesStore();
const profileStore = useProfileStore();
profileStore.ensureLoaded();
const profileBrands = computed(() => profileStore.brands);
function serviceObjFor(serviceId) {
  return servicesStore.services.find((s) => s.service_id === serviceId) || null;
}
function servicePricesFor(serviceId) {
  const s = serviceObjFor(serviceId);
  if (!s) return [];
  if (Array.isArray(s.prices) && s.prices.length) return s.prices;
  // Legacy single-price service: synthesize the same price_id the backend adapter uses
  // (domain/service_pricing._legacy_price_to_price -> `svcprice_{service_id}`) so it resolves.
  if (s.price) return [{ price_id: `svcprice_${s.service_id}`, ...s.price }];
  return [];
}
const serviceRows = computed(() => (form.services || []).filter((r) => r.service_id && r.price_id));
const hasService = computed(() => serviceRows.value.length > 0);
// no_booking services never book; only scheduled ones need a single/separate-visit choice.
const scheduledServiceCount = computed(() =>
  serviceRows.value.filter((r) => (serviceObjFor(r.service_id)?.fulfillment_mode || "scheduled") !== "no_booking").length,
);
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
const editingOfferId = ref("");
const selectedOfferDetails = ref(null);
const pendingDeleteOffer = ref(null);
const deletingOffer = ref(false);
const offerStatusFilter = ref("active");
const offerSearchQuery = ref("");
// Search matches the offer's own fields AND everything in it -- names and ids, landing and funnel. Without
// the item text a tenant cannot find "the offer with the Protein Shaker in it" by any route on this screen
// (plans/OFFER_ITEM_VISIBILITY.md).
function offerSearchText(offer) {
  return [offer.name, offer.slug, offer.offer_type, offer.product_intent, searchableItemText(offer, resolveItemName)]
    .filter(Boolean).join(" ").toLowerCase();
}
const visibleOffers = computed(() => {
  const isArchived = (o) => o.status === "archived";
  let list = offers.value;
  if (offerStatusFilter.value === "active") list = list.filter((o) => !isArchived(o));
  else if (offerStatusFilter.value === "archived") list = list.filter(isArchived);
  const search = offerSearchQuery.value.trim().toLowerCase();
  if (search) list = list.filter((o) => offerSearchText(o).includes(search));
  return list;
});

// Load on first interaction so filtering "just works" without clicking Load Offers first (mirrors Products).
function ensureOffersLoaded() {
  if (!offersLoaded.value && !offersLoading.value) loadOffers();
}

// Auto-load on mount so the list is fresh immediately, and reloads on an env switch (this view is keyed on
// the environment → Vue remounts → this re-runs). The "Load Offers" button remains for a manual refresh.
onMounted(() => {
  ensureOffersLoaded();
  // The list needs the catalog too: item NAMES on each card, and offerImage's product-image fallback,
  // which already read productsById but never had it populated on this screen.
  if (!productStore.loaded && !productStore.loading) productStore.load();
  if (!servicesStore.loaded && !servicesStore.loading) servicesStore.load();
});
const form = reactive(defaultOfferForm());
const itemConfigs = reactive({});
const priceImageInputs = new Map();
let productsLoadPromise = null;

const activeProducts = computed(() => productStore.products.filter((product) => product.status !== "archived" && product.active !== false));
const productsById = computed(() => new Map(productStore.products.map((product) => [productId(product), product])));
const selectedProducts = computed(() => activeProducts.value.filter((product) => selectedProductIds.value.includes(productId(product))));

// The offer INFERS every product's role from its pricing contexts — the tenant assigns contexts once on the
// Products screen and never re-decides bumps/upsells/downsells per offer (plans/OFFER_MODEL_REDESIGN.md §6).
// A product's presence in the offer + its contexts fully determine WHERE it appears:
//   standard/sale/flash_sale -> landing card · order_bump -> checkout bump · upsell/downsell -> post-purchase.
// A product may fill several roles at once (e.g. standard + order_bump = a landing card that can also be bumped).
const FUNNEL_CONTEXTS = ["order_bump", "upsell", "downsell"];
function contextPrice(product, context) {
  return (product.prices || []).find((price) => (price.context || "standard") === context) || null;
}
// Only the FIRST price in a funnel context is used per product (contextPrice above). Count them so the funnel
// can warn a tenant when extras are being silently ignored — multiple upsells belong on multiple products.
function contextPriceCount(product, context) {
  return (product.prices || []).filter((price) => (price.context || "standard") === context).length;
}
function contextSynced(product, context) {
  return Boolean(contextPrice(product, context)?.stripe_price_id);
}
function formatContextAmount(product, context) {
  const price = contextPrice(product, context);
  return price ? `$${(Number(price.unit_amount || 0) / 100).toFixed(2)}` : "";
}
// Landing prices are the non-funnel (display) contexts — what a product can be sold for on the landing page.
function landingPrices(product) {
  return productPrices(product).filter((price) => !FUNNEL_CONTEXTS.includes(price.context || "standard"));
}
// Only products with a landing price are landing items. A product priced ONLY as a bump/upsell/downsell is a
// funnel-only product (selected in Select Items, but never rendered as a landing card).
const landingProducts = computed(() => selectedProducts.value.filter((product) => landingPrices(product).length > 0));

// Inferred funnel roles — read-only, derived from the selected products' contexts (§6).
const inferredOrderBumps = computed(() => selectedProducts.value.filter((product) => contextPrice(product, "order_bump")));
const inferredUpsells = computed(() => selectedProducts.value.filter((product) => contextPrice(product, "upsell")));
// Sequence for ≤ MAX_SEQUENTIAL_UPSELLS upsell slots; a forced carousel of ALL upsells above it (§6).
const MAX_SEQUENTIAL_UPSELLS = 3;
const inferredUpsellStrategy = computed(() => (inferredUpsells.value.length > MAX_SEQUENTIAL_UPSELLS ? "carousel" : "sequence"));

// Intent = a friendly, DERIVED label over placement.surface (no new stored field) — it names WHY a product is
// at its stage. primary=main buy · cross_sell=order bump · upgrade=upsell · recovery=downsell.
// Pricing-option chips for a landing product (standard / N quantity tiers / subscription / sale / flash).
function landingPricingChips(product) {
  const config = itemConfig(product);
  const prices = landingPrices(product);
  const chips = [];
  const tierCount = (config.selectable_price_ids || []).length;
  chips.push(config.mode === "selectable" && tierCount > 1 ? `${tierCount} quantity tiers` : "standard");
  if (prices.some((price) => ["recurring", "subscription"].includes(price.pricing_model))) chips.push("subscription");
  const contexts = new Set(prices.map((price) => price.context || "standard"));
  if (contexts.has("sale")) chips.push("sale");
  if (contexts.has("flash_sale")) chips.push("flash sale");
  return chips;
}

// The offer's purchase flow as staged nodes — a visual funnel over the SAME inferred data (§6). Read-only.
const offerFunnelStages = computed(() => {
  const stages = [];
  const landing = landingProducts.value.map((product) => ({
    key: productId(product), intent: "primary", product, chips: landingPricingChips(product),
  }));
  if (landing.length) stages.push({ key: "landing", label: "Landing page", hint: "what the customer buys", items: landing });

  const bumps = inferredOrderBumps.value.map((product) => ({
    key: productId(product), intent: "cross_sell", product,
    amount: formatContextAmount(product, "order_bump"), synced: contextSynced(product, "order_bump"),
    extra: contextPriceCount(product, "order_bump") > 1 ? contextPriceCount(product, "order_bump") : 0,
  }));
  if (bumps.length) stages.push({ key: "checkout", label: "At checkout", hint: "Stripe order bump", items: bumps });

  const upsells = inferredUpsells.value.map((product) => ({
    key: productId(product), intent: "upgrade", product,
    amount: formatContextAmount(product, "upsell"), synced: contextSynced(product, "upsell"),
    extra: contextPriceCount(product, "upsell") > 1 ? contextPriceCount(product, "upsell") : 0,
    downsell: contextPrice(product, "downsell")
      ? {
          amount: formatContextAmount(product, "downsell"), synced: contextSynced(product, "downsell"),
          extra: contextPriceCount(product, "downsell") > 1 ? contextPriceCount(product, "downsell") : 0,
        }
      : null,
  }));
  if (upsells.length) stages.push({
    key: "post_purchase", label: "After purchase",
    hint: inferredUpsellStrategy.value === "carousel" ? `carousel · ${upsells.length} upsells` : "one at a time",
    items: upsells,
  });
  return stages;
});

// Funnel stages for the read-only View modal. The BUILDER is shared with the Landing Pages flow view
// (composables/purchaseFlow.js) — both describe a saved offer, and they previously read different fields.
// offerFunnelStages above stays separate on purpose: it describes an offer being composed, not a saved one.
const detailsFunnelStages = computed(() => {
  const offer = selectedOfferDetails.value;
  if (!offer) return [];
  return stagesFromSavedOffer(offer, {
    resolveProduct: (id) => productsById.value.get(id) || null,
    formatAmount: (amount, currency) => formatMoney(amount, currency),
  });
});

function funnelEntriesFromProducts(context, requireUpsell = false) {
  return selectedProducts.value
    .filter((product) => contextPrice(product, context) && (!requireUpsell || contextPrice(product, "upsell")))
    .map((product) => ({ product_id: productId(product), price_id: contextPrice(product, context).price_id }));
}
function buildFunnelBlock() {
  const block = {};
  const orderBumps = funnelEntriesFromProducts("order_bump");
  if (orderBumps.length) block.order_bumps = orderBumps;
  const upsells = funnelEntriesFromProducts("upsell");
  if (upsells.length) block.upsells = upsells;
  // Downsell = the SAME product's downsell-context price, the in-place second-chance when its upsell is
  // declined; require an upsell so a downsell-only product is never surfaced (documented gap, §6). Pairing by
  // product_id.
  const downsells = funnelEntriesFromProducts("downsell", true);
  if (downsells.length) block.downsells = downsells;
  return Object.keys(block).length ? block : undefined;
}

// Mirror of domain/opportunities.opportunities_from_offer's legacy mapping (plans/OFFER_MODEL_REDESIGN.md):
// normalize items[] + funnel.* into one purchase_opportunities[] so the offer carries the new model directly.
// Built from the SAME items/funnel we still write, so the Python read-side adapter (which prefers this array)
// sees identical data — dual-write during migration; P4 drops the legacy fields.
function buildPurchaseOpportunities(items, funnel) {
  const opportunities = [];
  (items || []).forEach((item, index) => {
    opportunities.push({
      ...item,
      opportunity_id: `opp_landing_primary_${index}`,
      stage: "landing",
      placement: { surface: "primary", group: "main_offer", order: index, strategy: "" },
    });
  });
  const funnelStage = {
    order_bumps: ["checkout", "order_bump", "single"],
    upsells: ["post_purchase", "upsell", "sequence"],
    downsells: ["post_purchase", "downsell", "single"],
  };
  Object.entries(funnelStage).forEach(([key, [stage, surface, strategy]]) => {
    (funnel?.[key] || []).forEach((entry, index) => {
      opportunities.push({
        opportunity_id: `opp_${stage}_${surface}_${index}`,
        stage,
        placement: { surface, group: surface, order: index, strategy },
        product_id: entry.product_id || "",
        price_id: entry.price_id || "",
        quantity: 1,
      });
    });
  });
  return opportunities;
}

function serviceSelectorCard(service) {
  // Shape a service into a product-compatible card so the visual selector + its helpers
  // (productId/priceText/productIntentFor/defaultProductPrice) work unchanged. Services are transactional.
  const prices = servicePricesFor(service.service_id);
  return {
    __service: true,
    product_id: service.service_id,
    service_id: service.service_id,
    name: service.name || "Untitled Service",
    description: service.description || "",
    images: service.presentation?.hero_image_url ? [service.presentation.hero_image_url] : [],
    product_intent: "transaction",
    prices,
    default_price_id: service.default_price_id || prices[0]?.price_id || "",
  };
}
const activeServices = computed(() => servicesStore.services.filter((service) => service.active !== false));
// Products and services are both "items"; the visual selector treats them as one list.
const selectorItems = computed(() => {
  const items = [...activeProducts.value, ...activeServices.value.map(serviceSelectorCard)];
  const term = productSearch.value.toLowerCase();
  if (!term) return items;
  return items.filter((item) => [
    item.name, item.description, item.product_id, item.service_id, item.product_category,
    ...(Array.isArray(item.tags) ? item.tags : []),
  ].filter(Boolean).join(" ").toLowerCase().includes(term));
});
const selectedItems = computed(() => [
  ...selectedProducts.value.map((product) => ({ id: productId(product), name: product.name || "Untitled Product", kind: "product" })),
  ...serviceRows.value.map((row) => ({ id: row.service_id, name: serviceObjFor(row.service_id)?.name || "Service", kind: "service" })),
]);
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
const detectedOfferType = computed(() => detectOfferType(landingProducts.value));
const productIntent = computed(() => {
  const intents = new Set(selectedProducts.value.map(productIntentFor));
  return intents.size === 1 ? [...intents][0] : "mixed";
});
const draftSelectedIntent = computed(() => {
  const selectedDraftItems = selectorItems.value.filter((item) => draftSelectedProductIds.value.has(productId(item)));
  const intents = new Set(selectedDraftItems.map(productIntentFor));
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

// SEO-descriptive slug preview — a JS MIRROR of the server's smart_offer_slug (src/handlers/offers.py). The
// server is authoritative on save; this just shows the tenant the slug they'll get, so it must stay in parity.
// single product -> [brand] + product name; bundle w/ shared category -> [brand] + category + "bundle"; bundle
// mixed -> [brand] + top-2 product names + "bundle".

function smartOfferSlug() {
  const products = landingProducts.value || [];
  const brandTokens = slugTokens(form.brand || profileStore.businessName || "", 2);
  let core = [], suffix = [];
  if (products.length <= 1) {
    core = slugTokens(products[0]?.name || form.name || "offer", 5);
  } else {
    const cats = products.map((p) => String(p.product_category || "").trim().toLowerCase());
    const shared = cats.length && cats.every((c) => c) && new Set(cats).size === 1;
    if (shared) core = slugTokens(cats[0]);
    else products.slice(0, 2).forEach((p) => { core = core.concat(slugTokens(p.name, 3)); });
    suffix = ["bundle"];
  }
  const seen = new Set(), tokens = [];
  [...brandTokens, ...core].forEach((t) => { if (!seen.has(t)) { seen.add(t); tokens.push(t); } });
  return tokens.slice(0, 6 - suffix.length).concat(suffix).join("-") || "offer";
}
function humanizeCat(machine) {
  return String(machine || "").toLowerCase().split(/[^a-z0-9]+/).filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}
// JS MIRROR of the server's label_from_model (domain/semantic.py) — reads the SAME model as the slug, so the
// label and slug can't diverge and a bundle gets a representative label, not just product #1.
function smartOfferLabel() {
  const products = landingProducts.value || [];
  if (products.length <= 1) {
    const serviceName = serviceRows.value[0] ? (serviceObjFor(serviceRows.value[0].service_id)?.name || "") : "";
    return products[0]?.name || serviceName || form.name || "Offer";
  }
  const cats = products.map((p) => String(p.product_category || "").trim().toLowerCase());
  const shared = cats.length && cats.every((c) => c) && new Set(cats).size === 1;
  if (shared) return humanizeCat(cats[0]) + " Bundle";
  return [products[0]?.name, products[1]?.name].filter(Boolean).join(" + ") + " Bundle";
}

// A typed label re-derives the slug (server mirror: handlers/offers.py sends the name as the slug source
// when the tenant renamed but left the slug auto). Uses the field's own @input like the other edit flags --
// a value-compare watcher races the programmatic auto-fills. Never touches a slug the tenant typed, and
// loadOfferIntoForm marks an existing offer's slug edited, so published URLs stay put.
function onLabelInput() {
  form.userEditedName = true;
  if (!form.userEditedSlug) form.slug = uniqueSlugPreview(sanitizeSlug(form.name));
}
// Collision preview needs NO network call: offers.value already holds every offer for this tenant in this
// Stripe mode, and offerCardModel keeps the whole document, slug included. The server still decides on
// save -- it must, since another tab could claim the slug in between. This only stops the modal showing a
// slug the tenant will not actually get. Rules live in composables/slugs.js (mirrored from domain/slugs.py
// and parity-tested against it), NOT re-implemented here.
const slugCollisionResolved = ref(false);
function uniqueSlugPreview(base) {
  const self = String(editingOfferId.value || "");
  const taken = new Set(
    (offers.value || [])
      .filter((offer) => String(offer?.offer_id || "") !== self)
      .map((offer) => String(offer?.slug || "")),
  );
  const resolved = uniqueSlug(base, taken);
  slugCollisionResolved.value = resolved !== sanitizeSlug(base);
  return resolved;
}

watch(selectedItems, () => {
  syncItemConfigs(landingProducts.value);
  if (!selectedItems.value.length) return;
  if (!form.userEditedName) form.name = smartOfferLabel();
  if (!form.userEditedSlug) form.slug = uniqueSlugPreview(smartOfferSlug());  // product-driven SEO slug/label from the model
}, { immediate: true });

// A tenant edit is flagged by the field's own @input (see the Label/Slug inputs), NOT a value-compare watcher:
// the latter races with these programmatic auto-fills and can wrongly mark the slug "edited", freezing it empty
// (observed on rapid multi-select). Brand changes still re-derive the slug while it's auto.
watch(() => form.brand, () => {
  if (!form.userEditedSlug) form.slug = uniqueSlugPreview(smartOfferSlug());
});

watch(productIntent, (intent) => {
  if (intent === "lead_gen") form.discount.mode = "none";
});

function defaultOfferForm() {
  return {
    name: "",
    slug: "",
    brand: "",
    services: [{ service_id: "", price_id: "" }],
    service_booking_flow: "pay_then_book",
    service_booking_mode: "single_visit",
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
  if (!servicesStore.loaded && !servicesStore.loading) servicesStore.load();
}

function closeOfferModal() {
  showOfferModal.value = false;
  showProductSelector.value = false;
  showCouponSelector.value = false;
}

async function openProductSelector() {
  // Seed the draft from both already-selected products and services (both are items now).
  draftSelectedProductIds.value = new Set([...selectedProductIds.value, ...serviceRows.value.map((row) => row.service_id)]);
  productSearch.value = "";
  selectorError.value = "";
  showProductSelector.value = true;
  if (!productStore.loaded && !productStore.loading) await productStore.load();
  if (!servicesStore.loaded && !servicesStore.loading) servicesStore.load();
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
    selectorError.value = "An offer cannot mix transaction items with lead generation items.";
    return;
  }
  // Split the selection back into products and services (services use their default price).
  const selectedIds = [...draftSelectedProductIds.value];
  const productIdSet = new Set(activeProducts.value.map((product) => productId(product)));
  selectedProductIds.value = selectedIds.filter((id) => productIdSet.has(id));
  const serviceIds = selectedIds.filter((id) => !productIdSet.has(id));
  form.services = serviceIds.length
    ? serviceIds.map((serviceId) => ({
        service_id: serviceId,
        price_id: serviceObjFor(serviceId)?.default_price_id || servicePricesFor(serviceId)[0]?.price_id || "",
      }))
    : [{ service_id: "", price_id: "" }];
  // Booking flow is offer-level (one payment posture); seed it from the first service chosen.
  if (serviceIds.length) form.service_booking_flow = serviceObjFor(serviceIds[0])?.booking_flow || "pay_then_book";
  showProductSelector.value = false;
  selectorError.value = "";
}

function toggleDraftProduct(id) {
  const next = new Set(draftSelectedProductIds.value);
  if (next.has(id)) next.delete(id);
  else {
    const product = selectorItems.value.find((item) => productId(item) === id);
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

function removeSelectedItem(item) {
  if (item.kind === "service") {
    form.services = form.services.filter((row) => row.service_id !== item.id);
    if (!form.services.length) form.services.push({ service_id: "", price_id: "" });
  } else {
    removeSelectedProduct(item.id);
  }
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

function viewOffer(offer) {
  selectedOfferDetails.value = offer;
}

function closeOfferDetails() {
  selectedOfferDetails.value = null;
}

async function editOffer(offer) {
  selectedOfferDetails.value = null;
  offersError.value = "";
  try {
    await ensureProductsLoaded();
  } catch (error) {
    offersError.value = error.message || "Failed to load products for this offer.";
    return;
  }
  openOfferModal(offer);
}

async function setOfferStatus(offer, status) {
  offersError.value = "";
  offersMessage.value = "";
  try {
    const body = await apiRequest(`/offers/${encodeURIComponent(offer.offer_id)}/status`, {
      method: "PATCH",
      body: { tenant_id: offer.tenant_id || getTenantId(), status, updated_at: Math.floor(Date.now() / 1000) },
    });
    const updated = body.offer ? offerCardModel(body.offer) : { ...offer, status };
    offers.value = offers.value.map((item) => (item.offer_id === offer.offer_id ? updated : item));
    offersMessage.value = `${offer.name || "Offer"} was ${status === "archived" ? "archived" : "restored"}.`;
  } catch (error) {
    offersError.value = error.message || "Failed to update the offer.";
  }
}

// Names of non-archived landing pages built on this offer — deleting it would break them (publishing
// raises "Offer not found"). Best-effort: on a fetch failure we return none rather than hard-block.
async function pagesReferencing(offerId) {
  try {
    const body = await apiRequest("/pages");
    const pages = Array.isArray(body.pages) ? body.pages : [];
    return pages
      .filter((page) => page.offer_id === offerId && page.status !== "archived")
      .map((page) => page.name || page.page_id);
  } catch {
    return [];
  }
}

function requestDeleteOffer(offer) {
  pendingDeleteOffer.value = offer; // open the modal instantly; the reference check runs on confirm
}

async function deleteOffer() {
  if (!pendingDeleteOffer.value) return;
  const offer = pendingDeleteOffer.value;
  const offerName = offer?.name || "this offer";
  offersError.value = "";
  offersMessage.value = "";
  deletingOffer.value = true;
  try {
    const pages = await pagesReferencing(offer.offer_id);
    if (pages.length) {
      offersError.value = offersMessage.value =
        `Can't delete "${offerName}" — it's used by ${pages.length} landing page(s): ${pages.join(", ")}. Archive or delete those pages first.`;
      pendingDeleteOffer.value = null;
      return;
    }
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

function primaryOfferItemDisplay() {
  // The first landing item (products come before services) supplies the offer's default hero name/copy/image.
  const product = landingProducts.value[0];
  if (product) {
    return { name: product.name || "", description: product.description || "", image: (product.images || [])[0] || "" };
  }
  const row = serviceRows.value[0];
  if (row) {
    const service = serviceObjFor(row.service_id);
    return { name: service?.name || "", description: service?.description || "", image: service?.presentation?.hero_image_url || "" };
  }
  return { name: "", description: "", image: "" };
}

function primaryCtaContract() {
  // Snapshot the CTA the landing page should render, derived from the primary landing item. The offer is the
  // page's contract, so cta.type (buy/call/email/external/booking) drives which CTA component renders.
  const product = landingProducts.value[0];
  if (product) {
    if ((product.product_intent || "transaction") !== "lead_gen") return { type: "buy", label: "Buy Now" };
    const lc = product.lead_capture || {};
    const target = lc.target?.value || "";
    if (lc.action === "call_number") return { type: "call", label: lc.title || "Call Now", target };
    if (lc.action === "external_url" || lc.action === "social_redirect") {
      // A downloadable file target renders a download CTA; any other URL is an external link.
      if (/\.(pdf|zip|epub|mp3|mp4|mov|docx?|xlsx?|pptx?|csv|png|jpe?g)(\?|#|$)/i.test(target)) {
        return { type: "download", label: lc.title || "Download", target };
      }
      return { type: "external", label: lc.title || "Learn More", target };
    }
    // capture_email / capture_phone / capture_email_phone / open_form -> inline collector (Phase 2)
    return { type: "email", label: lc.title || "Get Started" };
  }
  const row = serviceRows.value[0];
  if (row) {
    const service = serviceObjFor(row.service_id);
    if ((service?.fulfillment_mode || "scheduled") === "no_booking") return { type: "buy", label: "Buy Now" };
    return { type: "booking", label: "Book Now", target: row.service_id };
  }
  return { type: "buy", label: "Buy Now" };
}

function buildOfferDocument() {
  if (!landingProducts.value.length && !hasService.value) {
    return { error: selectedProducts.value.length
      ? "This offer needs at least one product with a landing price (standard/sale/flash) or a service — the selected products are funnel-only."
      : "Select at least one product or service for this offer." };
  }
  if (!form.name || !form.slug) return { error: "Offer label and slug are required." };
  if (selectedProducts.value.length && productIntent.value === "mixed") return { error: "An offer cannot mix transaction and lead generation products." };
  const checkoutMode = landingProducts.value.length ? inferredCheckoutMode() : "payment";
  if (checkoutMode === "mixed") return { error: "An offer cannot mix one-time and recurring prices." };
  if (form.discount.mode === "coupon_code" && !form.discount.coupon_id) return { error: "Select a coupon or choose No Discount." };
  if (form.checkout.allow_promotion_codes && !form.checkout.promotion_code) return { error: "Promotion code is required when promotion codes are enabled." };

  const now = Math.floor(Date.now() / 1000);
  const offerId = editingOfferId.value || localId("offer");
  // Landing items come from landing-priced products only; a funnel-only product (bump/upsell/downsell price,
  // no landing price) is selected in the offer but never a landing card — its role is inferred into funnel.
  const items = [];
  for (const product of landingProducts.value) {
    const config = itemConfig(product);
    const prices = landingPrices(product);
    if (!prices.length) return { error: `${product.name || product.product_id} has no landing price to attach to this offer.` };

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
  // One or more bookable services; the Offer's service_booking_mode coordinates scheduled ones.
  const serviceContexts = [];
  for (const row of serviceRows.value) {
    const servicePrice = servicePricesFor(row.service_id).find((p) => p.price_id === row.price_id);
    serviceContexts.push(servicePrice?.context || "standard");
    items.push(cleanObject({
      service_id: row.service_id,
      price_id: row.price_id,
      quantity: 1,
      booking_flow: form.service_booking_flow || "pay_then_book",
    }));
  }

  const priceContexts = landingProducts.value.length ? selectedPriceContexts() : (serviceContexts.length ? [...new Set(serviceContexts)] : ["standard"]);
  const effectiveIntent = landingProducts.value.length ? productIntent.value : "transaction";
  // Snapshot the primary item's copy/image onto the offer so it is a self-contained contract for the
  // landing page (suggestions the tenant/AI can override later). Only price stays resolved-live.
  const primary = primaryOfferItemDisplay();
  const cta = primaryCtaContract();
  const funnel = effectiveIntent === "transaction" ? buildFunnelBlock() : undefined;
  // The offer carries the normalized model directly (source of truth for the read side) alongside the legacy
  // items/funnel that pre-migration consumers still read (plans/OFFER_MODEL_REDESIGN.md P2b dual-write).
  const purchaseOpportunities = buildPurchaseOpportunities(items, funnel);

  const offer = cleanObject({
    schema_version: "2026-05-29",
    document_type: "offer",
    tenant_id: getTenantId(),
    offer_id: offerId,
    // Leave slug + name empty unless the tenant actually edited them, so the SERVER derives both from one
    // OfferSemanticModel (source of truth; they stay coherent). A manual edit is sent + respected; an existing
    // offer keeps its slug/name server-side (loadOfferIntoForm marks them edited), so URLs + naming stay stable.
    slug: form.userEditedSlug ? form.slug : "",
    name: form.userEditedName ? form.name : "",
    status: "active",
    product_intent: effectiveIntent,
    offer_type: inferOfferType(),
    stripe_mode: getStripeMode(),
    items,
    purchase_opportunities: purchaseOpportunities,
    // Only meaningful with 2+ scheduled services; omit otherwise to keep the document clean.
    service_booking_mode: scheduledServiceCount.value > 1 ? form.service_booking_mode : undefined,
    discount: buildDiscountBlock(),
    eligibility: {
      // order_bump is PRE-purchase (it rides the initial checkout as a Stripe optional_item), so it does NOT
      // require a prior purchase — only upsell/downsell do (plans/SALES_FUNNELS.md P2).
      requires_prior_purchase: priceContexts.some((context) => ["upsell", "downsell"].includes(context)),
      allowed_price_contexts: priceContexts,
      starts_at: null,
      ends_at: null,
    },
    presentation: cleanObject({
      headline: primary.name || form.name,
      subheadline: primary.description || undefined,
      // The brand shown on the page + in the <title>: the tenant's pick, else their business name. The
      // renderer falls back to the platform name when this is absent. Baked so the renderer needs no profile.
      brand: form.brand || profileStore.businessName || undefined,
      hero_image_url: primary.image || undefined,
      cta_label: cta.label || "Buy Now",
      cta: cleanObject({ type: cta.type, label: cta.label, target: cta.target || undefined }),
    }),
    checkout: effectiveIntent === "transaction" ? {
      mode: checkoutMode,
      phone_number_collection: form.checkout.phone_number_collection,
      allow_promotion_codes: Boolean(form.checkout.allow_promotion_codes),
      metadata: {
        offer_id: offerId,
      },
    } : undefined,
    // Order bumps + post-purchase upsells/downsells; omitted when none selected (cleanObject strips undefined).
    funnel,
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
  form.brand = offer.presentation?.brand || "";
  // Bumps/upsells/downsells are not loaded into form state — they're re-inferred from the selected products'
  // pricing contexts on save (plans/OFFER_MODEL_REDESIGN.md §6). loadOfferIntoForm restores the product
  // selection below (from items[]); any funnel roles those products carry re-derive automatically.
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
  // Re-select landing products AND funnel-only products (bump/upsell/downsell products live in offer.funnel,
  // not items[]) so their inferred roles survive a re-save. Roles themselves re-derive from contexts.
  const funnelProductIds = ["order_bumps", "upsells", "downsells"]
    .flatMap((key) => (offer.funnel?.[key] || []).map((entry) => entry.product_id));
  selectedProductIds.value = [...new Set([...items.map((item) => item.product_id), ...funnelProductIds].filter(Boolean))];
  const serviceItems = items.filter((item) => item.service_id);
  if (serviceItems.length) {
    form.services = serviceItems.map((item) => ({ service_id: item.service_id, price_id: item.price_id || "" }));
    form.service_booking_flow = serviceItems[0].booking_flow || "pay_then_book";
    form.service_booking_mode = offer.service_booking_mode || "single_visit";
    if (!servicesStore.loaded && !servicesStore.loading) servicesStore.load();
  }
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
    // Landing tiers exclude funnel-context prices — an order_bump/upsell/downsell price is a role, never a
    // selectable landing price (plans/OFFER_MODEL_REDESIGN.md §6).
    const prices = landingPrices(product);
    const preferred = defaultProductPrice(product);
    const defaultPrice = prices.find((price) => price.price_id === preferred?.price_id) || prices[0] || {};
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
  return toAssetCdnUrl(url);  // upload bucket host -> configured asset CDN (public_asset_base_url)
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
  const selectedDraftItems = selectorItems.value.filter((item) => draftSelectedProductIds.value.has(productId(item)));
  return new Set(selectedDraftItems.map(productIntentFor)).size <= 1;
}

function productInitial(product) {
  return String(product.name || "P").trim().slice(0, 1).toUpperCase();
}

function productPrices(product) {
  return (Array.isArray(product?.prices) ? product.prices : []).filter((price) => price && price.price_id);
}

function selectedOfferPrices() {
  const selectedPrices = [];
  for (const product of landingProducts.value) {
    const config = itemConfig(product);
    const prices = landingPrices(product);
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

// Internal offer name — brainless by default: just the primary item's product name, NO type suffix
// (offer_type is derived now, so "… Single Offer / … Bundle" is gone). Sticky until the tenant edits it.
// This is the tenant's dashboard label only; the customer-facing headline is offer.presentation.headline.
// plans/OFFER_MODEL_REDESIGN.md §7.
function offerLabelForItems() {
  // Name off the primary LANDING item (a funnel-only bump/upsell product never names the offer).
  const product = landingProducts.value[0];
  const serviceName = serviceRows.value[0] ? serviceObjFor(serviceRows.value[0].service_id)?.name : "";
  const name = product?.name || serviceName || "";
  if (!name) return "";
  return String(name).split(" - ")[0].trim() || "Item";
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
  // offer_type is now a real persisted field; only strip the legacy UI-computed display fields.
  const {
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

// Resolve a catalog id to its display name for THIS screen's stores. The composable owns the rules;
// each screen owns its lookup.
function resolveItemName(id) {
  return productsById.value.get(id)?.name || serviceObjFor(id)?.name || "";
}
function itemSummary(offer) {
  return offerItemSummary(offer, resolveItemName);
}
function itemSummaryTitle(offer) {
  return offerItemSummaryTitle(offer, resolveItemName);
}

function inferOfferType() {
  // Offer type is inferred from the LANDING items only (funnel-only bump/upsell products don't count).
  // Multiple landing items -> listicle. One product buyable in 2+ units -> bundle. One product, one price -> single.
  const total = landingProducts.value.length + serviceRows.value.length;
  if (total > 1) return "listicle";
  const product = landingProducts.value[0];
  if (product) {
    const config = itemConfig(product);
    if (config.mode === "selectable" && (config.selectable_price_ids || []).length > 1) return "bundle";
  }
  return "single";
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
