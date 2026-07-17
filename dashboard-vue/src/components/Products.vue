<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Products</h1>
        <p>Manage your Stripe products and pricing</p>
      </div>
    </header>

    <section class="dashboard-card product-management-card">
      <header class="dashboard-card-header">
        <h2>Product Management</h2>
        <div class="button-row">
          <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load">
            {{ store.loading ? "Loading..." : "Load Products" }}
          </button>
          <button class="primary-action" type="button" @click="openCreateModal">+ Create New Product</button>
        </div>
      </header>

      <div class="product-filter-bar">
        <label>
          Search
          <input v-model.trim="store.filters.search" type="search" placeholder="Name, tag, category, keyword..." @focus="store.ensureLoaded()" />
        </label>
        <label>
          Product Type
          <select v-model="store.filters.productType" @focus="store.ensureLoaded()">
            <option value="">All Types</option>
            <option value="physical">Physical</option>
            <option value="digital">Digital</option>
            <option value="service">Service</option>
          </select>
        </label>
        <label>
          Status
          <select v-model="store.filters.status" @focus="store.ensureLoaded()">
            <option value="active">Active</option>
            <option value="archived">Archived</option>
            <option value="all">All</option>
          </select>
        </label>
        <div class="product-filter-actions">
          <button type="button" class="secondary-action" @click="store.resetFilters">Reset</button>
        </div>
      </div>

      <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
      <div v-else class="keys-status-banner">{{ statusMessage }}</div>

      <div v-if="!store.filteredProducts.length" class="product-empty-state">
        {{ store.loading ? "Loading products..." : store.loaded ? "No products match the current filters." : "Click Load Products to see products." }}
      </div>

      <div v-else class="product-card-list">
        <ListCard
          v-for="product in store.filteredProducts"
          :key="product.product_id"
          :image="product.images?.[0] || ''"
          :icon-color-key="product.product_id"
          :title="product.name || 'Untitled Product'"
          :description="product.description"
          :status-label="lifecycleStatus(product) === 'archived' ? 'Archived' : 'Active'"
          :status-tone="lifecycleStatus(product)"
          :archived="lifecycleStatus(product) === 'archived'"
        >
          <template #icon>
            <component v-if="product.lead_capture?.action" :is="leadIcon(product.lead_capture.action)" />
            <span v-else>{{ productInitial(product) }}</span>
          </template>
          <template #subtitle>
            <strong>{{ priceText(product) }}</strong>
            <span v-if="compareAtText(product)" class="product-card-compare">Regular {{ compareAtText(product) }}</span>
          </template>
          <template #actions>
            <button type="button" class="secondary-action" @click="openEditModal(product)">Edit</button>
            <button type="button" class="secondary-action" @click="selectedProduct = product">Details</button>
            <button type="button" class="secondary-action" :disabled="store.savingStatus" @click="confirmStatusChange(product)">
              {{ lifecycleStatus(product) === "archived" ? "Restore" : "Archive" }}
            </button>
          </template>
          <template #footer>
            <div v-if="lifecycleStatus(product) === 'archived'" class="product-archived-label">Archived</div>
          </template>
        </ListCard>
      </div>
    </section>

    <div v-if="selectedProduct" class="modal-backdrop" @click.self="selectedProduct = null">
      <section class="modal-card product-details-modal" role="dialog" aria-modal="true" aria-labelledby="productDetailsTitle">
        <header class="modal-card-header">
          <h2 id="productDetailsTitle">Product Details</h2>
          <button type="button" class="modal-close" aria-label="Close product details" @click="selectedProduct = null">×</button>
        </header>
        <div class="product-details-body">
          <div class="product-details-summary">
            <div
              class="product-details-image"
              :class="{ placeholder: !selectedProduct.images?.[0], 'lead-icon-placeholder': !selectedProduct.images?.[0] && selectedProduct.lead_capture?.action }"
              :style="placeholderStyle(selectedProduct)"
            >
              <img v-if="selectedProduct.images?.[0]" :src="selectedProduct.images[0]" :alt="selectedProduct.name || 'Product image'" />
              <component v-else-if="selectedProduct.lead_capture?.action" :is="leadIcon(selectedProduct.lead_capture.action)" />
              <span v-else>{{ productInitial(selectedProduct) }}</span>
            </div>
            <div>
              <h3>{{ selectedProduct.name || "Untitled Product" }}</h3>
              <p>{{ selectedProduct.description || "No description provided." }}</p>
            </div>
          </div>
          <dl class="product-details-grid">
            <div><dt>Product ID</dt><dd>{{ selectedProduct.product_id }}</dd></div>
            <div><dt>Status</dt><dd>{{ lifecycleStatus(selectedProduct) === "archived" ? "Archived" : "Active" }}</dd></div>
            <div><dt>Type</dt><dd>{{ selectedProduct.product_type || "N/A" }}</dd></div>
            <div><dt>Category</dt><dd>{{ selectedProduct.product_category || "N/A" }}</dd></div>
            <div><dt>Default Price</dt><dd>{{ priceText(selectedProduct) }}</dd></div>
            <div><dt>Prices</dt><dd>{{ selectedProduct.prices?.length || 0 }}</dd></div>
          </dl>
          <div class="product-stripe-sync">
            <div class="product-stripe-sync-status">
              <span class="product-sync-label">Stripe</span>
              <span class="product-status" :class="syncBadgeClass(selectedProduct)">{{ syncBadgeText(selectedProduct) }}</span>
              <small v-if="selectedProduct.sync?.error" class="text-muted">{{ selectedProduct.sync.error }}</small>
              <small v-else-if="selectedProduct.stripe_product_id" class="text-muted font-mono">{{ selectedProduct.stripe_product_id }}</small>
            </div>
            <div class="button-row">
              <button
                v-if="selectedProduct.stripe_product_id" type="button" class="secondary-action"
                :disabled="syncing" @click="checkDrift(selectedProduct)"
              >Check drift</button>
              <button type="button" class="secondary-action" :disabled="syncing" @click="syncProduct(selectedProduct)">
                {{ syncing ? "Syncing…" : (selectedProduct.stripe_product_id ? "Re-sync to Stripe" : "Sync to Stripe") }}
              </button>
            </div>
          </div>
          <div v-if="selectedProduct.digital_asset" class="product-details-digital">
            <span class="product-sync-label">Download file</span>
            <span class="font-mono">{{ selectedProduct.digital_asset.filename }}</span>
          </div>
          <div class="product-details-tags">
            <span v-if="!selectedProduct.tags?.length" class="text-muted">No tags</span>
            <template v-else>
              <span v-for="tag in selectedProduct.tags" :key="tag" class="product-tag-pill">{{ tag }}</span>
            </template>
          </div>
          <details class="product-json-details">
            <summary>Raw JSON</summary>
            <pre>{{ JSON.stringify(selectedProduct, null, 2) }}</pre>
          </details>
        </div>
      </section>
    </div>

    <ConfirmDialog
      :open="!!pendingStatusProduct"
      :danger="pendingStatus === 'archived'"
      :title="pendingStatus === 'archived' ? 'Archive product?' : 'Restore product?'"
      :confirm-label="pendingStatus === 'archived' ? 'Archive' : 'Restore'"
      :busy="store.savingStatus"
      @cancel="pendingStatusProduct = null"
      @confirm="applyStatusChange"
    >
      {{ pendingStatus === "archived" ? "Archive" : "Restore" }} "{{ pendingStatusProduct?.name || "this product" }}"?
    </ConfirmDialog>

    <div v-if="showCreateModal" class="modal-backdrop" @click.self="closeCreateModal">
      <section class="modal-card product-create-modal" role="dialog" aria-modal="true" aria-labelledby="createProductTitle">
        <header class="modal-card-header">
          <h2 id="createProductTitle">{{ editingProduct ? "Edit Product" : "Create New Product" }}</h2>
          <button type="button" class="modal-close" aria-label="Close create product modal" @click="closeCreateModal">×</button>
        </header>

        <form class="product-create-body" @submit.prevent="saveProduct">
          <div v-if="formError" class="keys-status-banner error">{{ formError }}</div>

          <label>
            Product Name <span class="required">*</span>
            <input v-model.trim="form.name" required autocomplete="off" placeholder="e.g. Premium Widget" />
          </label>

          <label>
            Description
            <textarea v-model.trim="form.description" rows="4" placeholder="Describe your product..."></textarea>
          </label>

          <div class="modal-inline-grid">
            <label>
              Type
              <select v-model="form.product_type">
                <option value="physical">Physical - Requires shipping</option>
                <option value="digital">Digital - No shipping</option>
                <option value="service">Service - Opens booking flow</option>
              </select>
              <span class="field-note">Determines fulfillment behavior and address collection at checkout.</span>
            </label>
            <!-- Autocomplete over the shared, growing taxonomy (plans/PRODUCT_CATEGORY_AUTOCOMPLETE.md).
                 Suggestions are scoped to the product type; typing something new is allowed and becomes the
                 tenant's category immediately (only shared with others once enough tenants use it). -->
            <label class="category-autocomplete">
              Product Category <span class="required">*</span>
              <input
                v-model="categoryQuery"
                type="text"
                placeholder="Search or type a category"
                autocomplete="off"
                @focus="onCategoryFocus"
                @input="onCategoryInput"
                @blur="onCategoryBlur"
                @keydown.enter.prevent="commitCategoryFreeText"
              />
              <ul v-if="showCategoryMenu && categorySuggestions.length" class="category-menu">
                <li
                  v-for="suggestion in categorySuggestions"
                  :key="suggestion.key"
                  :class="{ 'is-selected': suggestion.key === form.product_category }"
                  @mousedown.prevent="pickCategory(suggestion)"
                >
                  <span>{{ suggestion.label }}</span>
                  <span v-if="suggestion.source === 'yours'" class="category-tag">your category</span>
                </li>
              </ul>
              <span class="field-note">Pick a suggestion or type your own. New categories become suggestions for others once several sellers use them.</span>
            </label>
          </div>

          <!-- Both feed the landing page's structured data (schema.org sku / itemCondition). Condition is
               asked rather than assumed: the markup is a machine-readable claim, so it may only state what
               the seller actually told us. -->
          <div class="modal-inline-grid">
            <label>
              SKU
              <input v-model.trim="form.sku" type="text" placeholder="Generated automatically" @input="skuTouched = true" />
              <span class="field-note">Generated from the product name and its ID, and kept stable after that. Edit it only if you have your own stock keeping unit.</span>
            </label>
            <label>
              Condition
              <select v-model="form.condition">
                <option value="new">New</option>
                <option value="refurbished">Refurbished</option>
                <option value="used">Used</option>
                <option value="damaged">Damaged</option>
              </select>
              <span class="field-note">Stated in search results. Only change this if you are not selling new goods.</span>
            </label>
          </div>

          <div class="modal-inline-grid">
            <label>
              Enable Payment Gateway
              <select v-model="form.canonical" :disabled="form.product_intent === 'lead_gen'">
                <option value="false">No</option>
                <option value="true">Yes</option>
              </select>
              <span class="field-note">When enabled, this product can be synced to Stripe.</span>
            </label>
            <label>
              Intent
              <select v-model="form.product_intent">
                <option value="transaction">I want a payment</option>
                <option value="lead_gen">I want to capture a lead</option>
              </select>
              <span class="field-note">Choose whether this product collects payment or captures lead information.</span>
            </label>
          </div>

          <section v-if="form.product_type === 'digital' && form.product_intent === 'transaction'" class="digital-asset-field">
            <div class="field-heading"><span>Download File</span></div>
            <div v-if="form.digital_asset && form.digital_asset.filename" class="digital-asset-current">
              <span class="font-mono">📎 {{ form.digital_asset.filename }}</span>
              <button type="button" class="secondary-action" @click="form.digital_asset = null">Remove</button>
            </div>
            <label v-else class="digital-asset-picker">
              <input type="file" :disabled="uploadingAsset" @change="onDigitalFileChange" />
              <span>{{ uploadingAsset ? "Uploading…" : "Choose a file to deliver after purchase" }}</span>
            </label>
            <span class="field-note">Buyers receive a secure, purchase-verified download link in their receipt email.</span>
          </section>

          <div v-if="form.product_intent === 'lead_gen'" class="lead-action-toast">
            <span class="lead-action-info" aria-hidden="true">i</span>
            <div>
              <strong>Lead capture action:</strong>
              <span>{{ form.lead_capture.label }}</span>
              <em v-if="leadTargetPreview">{{ leadTargetPreview }}</em>
            </div>
            <button class="secondary-action" type="button" @click="showLeadPicker = true">Choose action</button>
          </div>

          <section class="product-tags-field">
            <div class="field-heading">
              <span>Tags</span>
              <button type="button" class="secondary-action" @click="tagInputVisible = true">+ Add Tag</button>
            </div>
            <input
              v-if="tagInputVisible"
              v-model.trim="tagInput"
              placeholder="Type a tag and press Enter"
              autocomplete="off"
              @keydown.enter.prevent="addTag"
              @blur="hideEmptyTagInput"
            />
            <div class="product-tag-list">
              <span v-for="tag in form.tags" :key="tag" class="product-tag-pill dismissible">
                {{ tag }}
                <button type="button" :aria-label="`Remove ${tag} tag`" @click="removeTag(tag)">×</button>
              </span>
            </div>
            <span class="field-note">Product name and category are automatically added as tags. Add custom tags here.</span>
          </section>

          <section v-if="form.product_intent === 'transaction'" class="modal-form-section">
            <PricingCard
              :prices="form.prices"
              v-model:default-index="form.default_price_index"
              :product-type="form.product_type"
              subtitle="Product owns the canonical price list. Labels and bundle presentation are set in Offers."
            />
          </section>

          <section v-if="form.product_intent === 'transaction'" class="modal-form-section">
            <h3>Refund Policy</h3>
            <label>Policy Source
              <select v-model="form.refund_source">
                <option value="user_preference_default">Use user preference default</option>
                <option value="tenant_default">Use tenant default</option>
                <option value="product_override">Override for this product</option>
              </select>
            </label>
          </section>

          <section v-if="form.product_intent === 'transaction'" class="modal-form-section">
            <h3>Image URLs</h3>
            <div class="info-toast">Image Limit: Maximum of 8 images allowed per product.</div>
            <input ref="imageFileInput" type="file" accept="image/*" multiple hidden @change="handlePickedImages" />
            <div
              class="upload-dropzone product-upload-dropzone"
              :class="{ dragging: imageDragActive }"
              role="button"
              tabindex="0"
              @click="imageFileInput?.click()"
              @keydown.enter.prevent="imageFileInput?.click()"
              @keydown.space.prevent="imageFileInput?.click()"
              @dragover.prevent="imageDragActive = true"
              @dragleave.prevent="imageDragActive = false"
              @drop.prevent="handleDroppedImages"
            >
              <strong>Click to upload or drag and drop</strong>
              <small>PNG, JPG, WEBP up to 10MB</small>
            </div>
            <div v-if="form.uploaded_images.length" class="product-image-previews">
              <figure v-for="url in form.uploaded_images" :key="url" class="product-image-preview">
                <img :src="url" alt="Uploaded product image" />
                <figcaption>{{ shortImageName(url) }}</figcaption>
              </figure>
            </div>
            <div v-if="uploadStatus" class="upload-status" :class="uploadStatusKind">{{ uploadStatus }}</div>
            <label>Paste image URLs, one per line
              <textarea v-model.trim="form.images" rows="3" placeholder="https://example.com/image1.jpg"></textarea>
            </label>
          </section>

          <section v-if="form.product_intent === 'transaction' && form.product_type === 'physical'" class="modal-form-section">
            <label class="switch-row variant-toggle">
              <input v-model="form.size_enabled" type="checkbox" @change="ensureSizeVariant" />
              <span><strong>Item Size</strong><small>Enable size variants, such as S, M, L, XL.</small></span>
            </label>
            <div v-if="form.size_enabled" class="variant-options">
              <div class="variant-row-list">
                <div v-for="(size, index) in form.sizes" :key="size.form_id" class="variant-item-row">
                  <input v-model.trim="size.label" class="variant-label-input" :aria-label="`Size ${index + 1} label`" maxlength="10" placeholder="S" />
                  <input v-model.trim="size.description" :aria-label="`Size ${index + 1} description`" placeholder="e.g., Waist: 30-32in, Hips: 37-39in" />
                  <button type="button" class="variant-remove-button" :aria-label="`Remove size ${index + 1}`" @click="removeSizeVariant(index)">×</button>
                </div>
              </div>
              <button type="button" class="secondary-action" @click="addSizeVariant">+ New Size</button>
            </div>

            <label class="switch-row variant-toggle">
              <input v-model="form.color_enabled" type="checkbox" @change="ensureColorVariant" />
              <span><strong>Item Color</strong><small>Enable color variants, such as Black, White, Navy.</small></span>
            </label>
            <div v-if="form.color_enabled" class="variant-options">
              <div class="variant-row-list">
                <div v-for="(color, index) in form.colors" :key="color.form_id" class="variant-item-row color-variant-row">
                  <input v-model.trim="color.label" class="variant-label-input" :aria-label="`Color ${index + 1} label`" maxlength="20" placeholder="Black" />
                  <input v-model="color.hex_color" class="variant-color-preview" type="color" :aria-label="`Color ${index + 1} swatch`" />
                  <input v-model.trim="color.description" :aria-label="`Color ${index + 1} description`" placeholder="e.g., Jet black finish" />
                  <button type="button" class="variant-remove-button" :aria-label="`Remove color ${index + 1}`" @click="removeColorVariant(index)">×</button>
                </div>
              </div>
              <button type="button" class="secondary-action" @click="addColorVariant">+ New Color</button>
            </div>

            <h3>Package Dimensions</h3>
            <div class="modal-dimensions-grid">
              <label>Length (inches)<input v-model.number="form.length_in" type="number" min="0" step="0.1" /></label>
              <label>Width (inches)<input v-model.number="form.width_in" type="number" min="0" step="0.1" /></label>
              <label>Height (inches)<input v-model.number="form.height_in" type="number" min="0" step="0.1" /></label>
              <label>Weight (pounds)<input v-model.number="form.weight_lb" type="number" min="0" step="0.1" /></label>
            </div>
          </section>

          <footer class="product-modal-footer">
            <button class="secondary-action" type="button" @click="closeCreateModal">Cancel</button>
            <button class="primary-action" type="submit" :disabled="store.savingStatus">
              {{ store.savingStatus ? "Saving..." : "Save Product" }}
            </button>
          </footer>
        </form>
      </section>
    </div>

    <div v-if="showLeadPicker" class="modal-backdrop" @click.self="showLeadPicker = false">
      <section class="modal-card lead-picker-modal" role="dialog" aria-modal="true" aria-labelledby="leadPickerTitle">
        <header class="modal-card-header">
          <div>
            <h2 id="leadPickerTitle">Choose a lead capture action</h2>
            <p>Select one action type for this product.</p>
          </div>
          <button type="button" class="modal-close" aria-label="Close lead action picker" @click="showLeadPicker = false">×</button>
        </header>
        <div class="lead-picker-body">
          <button
            v-for="action in leadActions"
            :key="action.action"
            class="lead-action-card"
            :class="{ selected: draftLeadAction.action === action.action }"
            type="button"
            @click="draftLeadAction = { ...action, target: '', platform: 'other' }"
          >
            <span class="lead-action-icon" :class="action.tone"><component :is="leadIcon(action.action)" /></span>
            <strong>{{ action.label }}</strong>
            <small>{{ action.description }}</small>
            <span v-if="draftLeadAction.action === action.action" class="lead-selected-check">✓</span>
          </button>
        </div>
        <div v-if="leadTargetLabel" class="lead-target-fields">
          <label>{{ leadTargetLabel }}
            <input v-model.trim="draftLeadAction.target" :placeholder="leadTargetPlaceholder" />
          </label>
        </div>
        <footer class="product-modal-footer">
          <p>Selected: <strong>{{ draftLeadAction.label }}</strong></p>
          <div class="lead-picker-actions">
            <button class="secondary-action" type="button" @click="showLeadPicker = false">Cancel</button>
            <button class="primary-action" type="button" @click="applyLeadAction">Apply selection</button>
          </div>
        </footer>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, h, nextTick, ref, watch } from "vue";
import { apiRequest } from "../api/client";
import { defaultProductPrice, formatMoney, useProductsStore } from "../stores/products";
import { humanizeCategory, normalizeCategory, searchCategories } from "../utils/categories";
import { defaultPriceForm, priceFormFromDocument } from "../utils/priceForm";
import { idColorStyle } from "../utils/iconColor";
import PricingCard from "./shared/PricingCard.vue";
import ConfirmDialog from "./shared/ConfirmDialog.vue";
import ListCard from "./shared/ListCard.vue";

const store = useProductsStore();
const selectedProduct = ref(null);
const pendingStatusProduct = ref(null);
const pendingStatus = ref("archived");
const editingProduct = ref(null);
// A SKU is an identifier, so it is generated once and then left alone. It follows the name only while a NEW
// product is still being named; once the product exists, renaming it must never re-identify it.
const skuTouched = ref(false);
const showCreateModal = ref(false);
const showLeadPicker = ref(false);
const tagInputVisible = ref(false);
const tagInput = ref("");
const formError = ref("");
const imageFileInput = ref(null);
const imageDragActive = ref(false);
const uploadStatus = ref("");
const uploadStatusKind = ref("");
const syncing = ref(false);
const uploadingAsset = ref(false);

const leadActions = [
  { action: "capture_email", label: "Capture email", description: "Collect the visitor's email address.", tone: "blue" },
  { action: "capture_phone", label: "Capture phone", description: "Collect the visitor's phone number.", tone: "green" },
  { action: "capture_email_phone", label: "Capture email + phone", description: "Collect both primary contact channels.", tone: "purple" },
  { action: "call_number", label: "Call a number", description: "Prompt the visitor to call directly.", tone: "amber" },
  { action: "external_url", label: "Go to URL", description: "Send the visitor to an external page.", tone: "red" },
  { action: "open_form", label: "Open a form", description: "Link to a quiz, application, or survey.", tone: "lime" },
  { action: "social_redirect", label: "Social page", description: "Direct the visitor to a social profile.", tone: "pink" },
];

const defaultLeadAction = { ...leadActions[0], target: "", platform: "other" };
const draftLeadAction = ref({ ...defaultLeadAction });
const form = ref(defaultProductForm());
const hydratingForm = ref(false);

const statusMessage = computed(() => {
  if (!store.loaded) return store.message;
  return `${store.shownCount} of ${store.products.length} product${store.products.length === 1 ? "" : "s"} shown.`;
});

// --- Product Category autocomplete (plans/PRODUCT_CATEGORY_AUTOCOMPLETE.md) ---------------------------
// form.product_category stores the normalized KEY; categoryQuery is the label the tenant sees/types.
const categoryQuery = ref("");
const categorySuggestions = ref([]);
const showCategoryMenu = ref(false);
let categorySearchTimer = null;

function initCategoryQuery() {
  // Show the stored key's label. The proper server label arrives when the menu first opens; humanize is a
  // fine placeholder (e.g. "dietary_supplement" -> "Dietary Supplement").
  categoryQuery.value = form.value.product_category ? humanizeCategory(form.value.product_category) : "";
}

async function fetchCategorySuggestions() {
  categorySuggestions.value = await searchCategories(categoryQuery.value, form.value.product_type);
}

function onCategoryFocus() {
  showCategoryMenu.value = true;
  fetchCategorySuggestions();
}

function onCategoryInput() {
  showCategoryMenu.value = true;
  clearTimeout(categorySearchTimer);
  categorySearchTimer = setTimeout(fetchCategorySuggestions, 180);
}

function pickCategory(suggestion) {
  form.value.product_category = suggestion.key;
  categoryQuery.value = suggestion.label;
  showCategoryMenu.value = false;
}

// Typed text with no pick becomes the tenant's own category: store the normalized key so it dedups with
// existing entries (and matches what the server records). An exact-label match to a suggestion picks it.
function commitCategoryFreeText() {
  const typed = categoryQuery.value.trim();
  showCategoryMenu.value = false;
  if (!typed) {
    form.value.product_category = "";
    return;
  }
  const exact = categorySuggestions.value.find((s) => s.label.toLowerCase() === typed.toLowerCase());
  if (exact) {
    pickCategory(exact);
    return;
  }
  form.value.product_category = normalizeCategory(typed);
}

function onCategoryBlur() {
  // Delay so a mousedown on a suggestion (which fires before blur) can win.
  setTimeout(() => { if (showCategoryMenu.value || categoryQuery.value) commitCategoryFreeText(); }, 150);
}

const leadTargetLabel = computed(() => leadTargetLabelFor(draftLeadAction.value.action));

const leadTargetPlaceholder = computed(() => {
  if (draftLeadAction.value.action === "call_number") return "+12065550100";
  if (draftLeadAction.value.action === "external_url") return "https://example.com";
  if (draftLeadAction.value.action === "open_form") return "form_...";
  if (draftLeadAction.value.action === "social_redirect") return "https://instagram.com/example";
  return "";
});

const leadTargetPreview = computed(() => form.value.lead_capture.target || "");

watch(() => form.value.product_type, () => {
  if (hydratingForm.value) return;
  form.value.product_category = "";
  form.value.sku = "";
  form.value.condition = "new";
});

watch(() => form.value.product_intent, (intent) => {
  if (intent === "lead_gen") form.value.canonical = "false";
});

function lifecycleStatus(product) {
  return product?.status === "archived" || product?.active === false ? "archived" : "active";
}

function priceText(product) {
  const price = defaultProductPrice(product);
  return price ? formatMoney(price.unit_amount, price.currency) : "No price";
}

function compareAtText(product) {
  const price = defaultProductPrice(product);
  return price?.compare_at_unit_amount ? formatMoney(price.compare_at_unit_amount, price.currency) : "";
}

function productInitial(product) {
  return (product?.name || "P").slice(0, 1).toUpperCase();
}

function placeholderStyle(product) {
  return product?.lead_capture?.action ? idColorStyle(product.product_id || product.name || "") : {};
}

function leadIcon(action) {
  const paths = {
    capture_email: "M4.5 6.75h15v10.5h-15V6.75Zm0 0L12 12l7.5-5.25",
    capture_phone: "M7.5 4.5h3l1.5 4-2 1.25a10 10 0 0 0 4.25 4.25l1.25-2 4 1.5v3a2 2 0 0 1-2.25 2c-7-.5-12.25-5.75-12.75-12.75A2 2 0 0 1 7.5 4.5Z",
    capture_email_phone: "M7.5 4.5h9v15h-9v-15Zm2.25 3h4.5m-4.5 3h4.5m-4.5 3h2.25",
    call_number: "M7.5 4.5h3l1.5 4-2 1.25a10 10 0 0 0 4.25 4.25l1.25-2 4 1.5v3a2 2 0 0 1-2.25 2c-7-.5-12.25-5.75-12.75-12.75A2 2 0 0 1 7.5 4.5Zm7.5 1.5a4.5 4.5 0 0 1 3 3m-3-5.25A6.75 6.75 0 0 1 20.25 9",
    external_url: "M8.25 8.25h-3v10.5h10.5v-3m-4.5-3 7.5-7.5m0 0h-4.5m4.5 0v4.5",
    open_form: "M6.75 4.5h6l4.5 4.5v10.5H6.75v-15Zm6 0V9h4.5m-7.5 3h4.5m-4.5 3h4.5",
    social_redirect: "M7.5 12a2.25 2.25 0 1 1-4.5 0 2.25 2.25 0 0 1 4.5 0Zm13.5-5.25a2.25 2.25 0 1 1-4.5 0 2.25 2.25 0 0 1 4.5 0Zm0 10.5a2.25 2.25 0 1 1-4.5 0 2.25 2.25 0 0 1 4.5 0ZM7.1 11l9.3-3.25M7.1 13l9.3 3.25",
  };
  return {
    render() {
      return h("svg", { fill: "none", stroke: "currentColor", viewBox: "0 0 24 24", class: "product-card-placeholder-icon", "aria-hidden": "true" }, [
        h("path", { "stroke-linecap": "round", "stroke-linejoin": "round", "stroke-width": "2", d: paths[action] || paths.capture_email }),
      ]);
    },
  };
}

function defaultProductForm() {
  return {
    product_id: "",
    stripe_product_id: null,
    stripe_mode: "",
    status: "active",
    created_at: null,
    name: "",
    description: "",
    product_type: "physical",
    product_category: "",
    sku: "",
    condition: "new",
    canonical: "false",
    product_intent: "transaction",
    tags: [],
    prices: [defaultPriceForm()],
    default_price_index: 0,
    refund_source: "user_preference_default",
    refund_window: "30_days",
    refund_condition: "unused",
    refund_return_method: "no_return_customer_keeps",
    refund_short_label: "30-day money-back",
    refund_full_policy: "Refunds are available within 30 days of delivery in unused condition.",
    images: "",
    uploaded_images: [],
    digital_asset: null,
    size_enabled: false,
    color_enabled: false,
    sizes: [],
    colors: [],
    length_in: 10,
    width_in: 8,
    height_in: 4,
    weight_lb: 1,
    lead_capture: { ...defaultLeadAction },
  };
}

function variantFormId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function defaultSizeVariant() {
  return {
    form_id: variantFormId("size"),
    label: "",
    description: "",
  };
}

function defaultColorVariant() {
  return {
    form_id: variantFormId("color"),
    label: "",
    hex_color: "#000000",
    description: "",
  };
}

function ensureSizeVariant() {
  if (form.value.size_enabled && !form.value.sizes.length) addSizeVariant();
}

function ensureColorVariant() {
  if (form.value.color_enabled && !form.value.colors.length) addColorVariant();
}

function addSizeVariant() {
  form.value.sizes.push(defaultSizeVariant());
}

function addColorVariant() {
  form.value.colors.push(defaultColorVariant());
}

function removeSizeVariant(index) {
  form.value.sizes.splice(index, 1);
  if (!form.value.sizes.length) form.value.size_enabled = false;
}

function removeColorVariant(index) {
  form.value.colors.splice(index, 1);
  if (!form.value.colors.length) form.value.color_enabled = false;
}

// Auto-SKU while a new product is being named. Guarded three ways so it can never re-identify a product:
// only when creating, only if the tenant hasn't typed their own, and never once the product exists.
watch(() => form.value.name, (name) => {
  if (editingProduct.value || skuTouched.value) return;
  form.value.sku = generateSku(name, ensureProductId());
});

function openCreateModal() {
  editingProduct.value = null;
  skuTouched.value = false;
  form.value = defaultProductForm();
  initCategoryQuery();
  draftLeadAction.value = { ...defaultLeadAction };
  formError.value = "";
  uploadStatus.value = "";
  uploadStatusKind.value = "";
  tagInput.value = "";
  tagInputVisible.value = false;
  showCreateModal.value = true;
}

async function openEditModal(product) {
  editingProduct.value = product;
  hydratingForm.value = true;
  skuTouched.value = false;
  form.value = productFormFromDocument(product);
  // Products created before SKUs existed get one now, from the same name+id inputs a new product would use.
  if (!form.value.sku) form.value.sku = generateSku(product.name, product.product_id);
  initCategoryQuery();
  draftLeadAction.value = { ...form.value.lead_capture };
  formError.value = "";
  uploadStatus.value = "";
  uploadStatusKind.value = "";
  tagInput.value = "";
  tagInputVisible.value = false;
  showCreateModal.value = true;
  await nextTick();
  hydratingForm.value = false;
}

function closeCreateModal() {
  showCreateModal.value = false;
  showLeadPicker.value = false;
  editingProduct.value = null;
}

function productFormFromDocument(product) {
  const base = defaultProductForm();
  const productType = product.product_type || "physical";
  const prices = Array.isArray(product.prices) && product.prices.length
    ? product.prices.map((price) => priceFormFromDocument(price))
    : [defaultPriceForm()];
  const defaultPriceIndex = Math.max(0, prices.findIndex((price) => price.price_id === product.default_price_id));
  const refundPolicy = product.refund_policy || {};
  const fulfillment = product.fulfillment || {};
  const dimensions = fulfillment.dimensions || {};
  const images = Array.isArray(product.images) ? product.images : [];
  const variants = product.variants || {};
  const leadCapture = leadActionFromDocument(product.lead_capture);
  return {
    ...base,
    product_id: product.product_id || "",
    stripe_product_id: product.stripe_product_id || null,
    stripe_mode: product.stripe_mode || "",
    status: lifecycleStatus(product),
    created_at: product.created_at || null,
    name: product.name || "",
    description: product.description || "",
    product_type: productType,
    product_category: product.product_category || "",
    sku: product.sku || "",
    condition: product.condition || "new",
    canonical: product.canonical ? "true" : "false",
    product_intent: product.lead_capture ? "lead_gen" : product.product_intent || "transaction",
    tags: customTagsFromProduct(product),
    prices,
    default_price_index: defaultPriceIndex >= 0 ? defaultPriceIndex : 0,
    refund_source: refundPolicy.source || base.refund_source,
    refund_window: refundPolicy.refund_window || base.refund_window,
    refund_condition: refundPolicy.condition || base.refund_condition,
    refund_return_method: refundPolicy.return_method || base.refund_return_method,
    refund_short_label: refundPolicy.short_label || base.refund_short_label,
    refund_full_policy: refundPolicy.full_policy || base.refund_full_policy,
    uploaded_images: images,
    images: "",
    digital_asset: product.digital_asset || null,
    size_enabled: Boolean(variants.size_enabled || variants.sizes?.length),
    color_enabled: Boolean(variants.color_enabled || variants.colors?.length),
    sizes: variantSizesFromDocument(variants.sizes),
    colors: variantColorsFromDocument(variants.colors),
    length_in: dimensions.length_in ?? base.length_in,
    width_in: dimensions.width_in ?? base.width_in,
    height_in: dimensions.height_in ?? base.height_in,
    weight_lb: fulfillment.weight_lb ?? base.weight_lb,
    lead_capture: leadCapture,
  };
}

function variantSizesFromDocument(values = []) {
  return values.map((value) => {
    if (typeof value === "string") return { ...defaultSizeVariant(), label: value, description: "" };
    return {
      ...defaultSizeVariant(),
      label: value?.label || "",
      description: value?.description || "",
    };
  });
}

function variantColorsFromDocument(values = []) {
  return values.map((value) => {
    if (typeof value === "string") return { ...defaultColorVariant(), label: value, hex_color: "#000000", description: "" };
    return {
      ...defaultColorVariant(),
      label: value?.label || "",
      hex_color: value?.hex_color || "#000000",
      description: value?.description || "",
    };
  });
}

function leadActionFromDocument(leadCapture) {
  if (!leadCapture) return { ...defaultLeadAction };
  const definition = leadActions.find((action) => action.action === leadCapture.action) || leadActions[0];
  const target = leadCapture.target || {};
  return {
    ...definition,
    title: leadCapture.title || definition.label,
    description: leadCapture.description || definition.description,
    target: target.value || target.form_id || "",
    platform: target.platform || "other",
  };
}

function customTagsFromProduct(product) {
  const autoTags = new Set([
    normalizeTag(product.name),
    ...normalizeTag(product.name).split(" ").filter((part) => part.length > 2),
    product.product_category === "other" ? "" : normalizeTag(product.product_category),
  ].filter(Boolean));
  return (product.tags || []).map(normalizeTag).filter((tag) => tag && !autoTags.has(tag));
}

function normalizeTag(value) {
  return String(value || "").trim().toLowerCase().replace(/[_-]+/g, " ").replace(/\s+/g, " ");
}

function addTag() {
  const tag = normalizeTag(tagInput.value);
  if (tag && !form.value.tags.includes(tag)) form.value.tags.push(tag);
  tagInput.value = "";
}

function hideEmptyTagInput() {
  if (!tagInput.value) tagInputVisible.value = false;
}

function removeTag(tag) {
  form.value.tags = form.value.tags.filter((item) => item !== tag);
}

function applyLeadAction() {
  form.value.lead_capture = { ...draftLeadAction.value };
  showLeadPicker.value = false;
}

function leadTargetLabelFor(action) {
  if (action === "call_number") return "Phone number";
  if (action === "external_url") return "Destination URL";
  if (action === "open_form") return "Form ID";
  if (action === "social_redirect") return "Social profile URL";
  return "";
}

function validateProductForm() {
  if (!form.value.name.trim()) return "Product name is required.";
  if (!form.value.product_category) return "Choose a product category.";
  if (form.value.product_intent === "lead_gen" && leadTargetLabelFor(form.value.lead_capture.action) && !form.value.lead_capture.target) {
    return `${form.value.lead_capture.label} requires a target.`;
  }
  if (form.value.product_intent === "transaction" && form.value.prices.some((price) => Number(price.quantity || 0) < 1)) return "Each price quantity must be at least 1.";
  return "";
}

async function saveProduct() {
  formError.value = validateProductForm();
  if (formError.value) return;
  try {
    await store.createProduct(form.value);
    closeCreateModal();
  } catch (error) {
    formError.value = error.message;
  }
}

function ensureProductId() {
  if (!form.value.product_id) {
    const alpha = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
    form.value.product_id = "local_" + Array.from({ length: 11 }, () => alpha[Math.floor(Math.random() * alpha.length)]).join("");
  }
  return form.value.product_id;
}

async function onDigitalFileChange(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  uploadingAsset.value = true;
  formError.value = "";
  try {
    form.value.digital_asset = await store.uploadDigitalAsset(ensureProductId(), file);
  } catch (error) {
    formError.value = `Upload failed: ${error.message}`;
  } finally {
    uploadingAsset.value = false;
    event.target.value = "";
  }
}

async function syncProduct(product) {
  syncing.value = true;
  try {
    const body = await store.syncToStripe(product);
    if (body?.product) selectedProduct.value = body.product;
  } catch {
    /* store surfaces the error banner */
  } finally {
    syncing.value = false;
  }
}

async function checkDrift(product) {
  syncing.value = true;
  try {
    const body = await store.checkDrift(product);
    if (body?.product) selectedProduct.value = body.product;
  } catch {
    /* store surfaces the error banner */
  } finally {
    syncing.value = false;
  }
}

function syncBadgeText(product) {
  if (product?.sync?.status === "drift") return "Drift";
  if (product?.sync?.status === "failed") return "Sync failed";
  if (product?.sync?.status === "success" || product?.stripe_product_id) return "Synced";
  return "Not synced";
}

function syncBadgeClass(product) {
  if (product?.sync?.status === "drift") return "warning";
  if (product?.sync?.status === "failed") return "archived";
  if (product?.sync?.status === "success" || product?.stripe_product_id) return "active";
  return "inactive";
}

async function handlePickedImages(event) {
  await handleImageFiles(Array.from(event.target.files || []));
  event.target.value = "";
}

async function handleDroppedImages(event) {
  imageDragActive.value = false;
  await handleImageFiles(Array.from(event.dataTransfer?.files || []));
}

async function handleImageFiles(files) {
  if (!files.length) return;
  const validFiles = files.filter((file) => file.type.startsWith("image/") && file.size <= 10 * 1024 * 1024);
  const rejected = files.length - validFiles.length;
  if (rejected) {
    uploadStatus.value = `${rejected} file${rejected === 1 ? "" : "s"} skipped. Use image files up to 10MB.`;
    uploadStatusKind.value = "error";
  }
  const remainingSlots = 8 - imageUrlList().length;
  if (remainingSlots <= 0) {
    uploadStatus.value = "Stripe products support a maximum of 8 images.";
    uploadStatusKind.value = "error";
    return;
  }
  const uploadFiles = validFiles.slice(0, remainingSlots);
  if (!uploadFiles.length) return;
  uploadStatusKind.value = "uploading";
  uploadStatus.value = `Uploading ${uploadFiles.length} image${uploadFiles.length === 1 ? "" : "s"}...`;
  let completed = 0;
  for (const file of uploadFiles) {
    try {
      const url = await uploadProductImage(file);
      addUploadedImage(url);
      completed += 1;
      uploadStatus.value = `Uploaded ${completed}/${uploadFiles.length} image${uploadFiles.length === 1 ? "" : "s"}...`;
    } catch (error) {
      uploadStatus.value = `Failed to upload ${file.name}: ${error.message}`;
      uploadStatusKind.value = "error";
      return;
    }
  }
  uploadStatus.value = `Uploaded ${completed} image${completed === 1 ? "" : "s"}.`;
  uploadStatusKind.value = "success";
}

async function uploadProductImage(file) {
  const presigned = await apiRequest("/upload/multiple", {
    method: "POST",
    body: {
      fileName: file.name,
      contentType: file.type,
      basePrefix: "products",
      targetBucket: "images.juniorbay.net",
    },
  });
  const formData = new FormData();
  Object.entries(presigned.upload?.fields || {}).forEach(([key, value]) => formData.append(key, value));
  formData.append("file", file);
  const uploadResponse = await fetch(presigned.upload.url, { method: "POST", body: formData });
  if (!uploadResponse.ok) throw new Error("Failed to upload file");
  return pollProductImageUrl(presigned.id);
}

async function pollProductImageUrl(imageId) {
  const deadline = Date.now() + 180000;
  let delay = 1200;
  while (Date.now() < deadline) {
    await sleep(delay);
    delay = Math.min(8000, Math.ceil(delay * 1.35));
    const body = await apiRequest(`/upload/status/${encodeURIComponent(imageId)}`).catch(() => ({}));
    if (body.status === "failed") throw new Error("Image processing failed");
    for (const url of productImageUrlCandidates(body.urls || {})) {
      if (await imageUrlLoads(url)) return url;
    }
  }
  throw new Error("Timed out waiting for processed image");
}

function productImageUrlCandidates(urls) {
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
  if (!url) return Promise.resolve(false);
  return new Promise((resolve) => {
    const image = new Image();
    let done = false;
    const finish = (ok) => {
      if (done) return;
      done = true;
      image.onload = null;
      image.onerror = null;
      resolve(ok);
    };
    image.onload = () => finish(true);
    image.onerror = () => finish(false);
    image.src = `${url}${url.includes("?") ? "&" : "?"}_probe=${Date.now()}`;
    setTimeout(() => finish(false), timeoutMs);
  });
}

function addUploadedImage(url) {
  if (!url) return;
  form.value.uploaded_images = [...new Set([...form.value.uploaded_images, url])].slice(0, 8);
  form.value.images = [...new Set([...String(form.value.images || "").split(/\n+/).map((line) => line.trim()).filter(Boolean), url])].slice(0, 8).join("\n");
}

function imageUrlList() {
  return [...new Set([
    ...form.value.uploaded_images,
    ...String(form.value.images || "").split(/\n+/).map((line) => line.trim()).filter(Boolean),
  ])];
}

function shortImageName(url) {
  try {
    const parsed = new URL(url);
    return parsed.pathname.split("/").filter(Boolean).pop() || parsed.hostname;
  } catch {
    return url;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function confirmStatusChange(product) {
  pendingStatusProduct.value = product;
  pendingStatus.value = lifecycleStatus(product) === "archived" ? "active" : "archived";
}

async function applyStatusChange() {
  if (!pendingStatusProduct.value) return;
  await store.setStatus(pendingStatusProduct.value, pendingStatus.value);
  pendingStatusProduct.value = null;
}
</script>
