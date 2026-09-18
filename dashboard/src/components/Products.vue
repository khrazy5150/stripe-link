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
              <!-- Products auto-sync to Stripe on save (plans/SALES_FUNNELS.md P1.5). A manual sync button
                   appears whenever a payment product isn't successfully synced yet — pending (grandfathered,
                   created before auto-sync) or failed — so it never needs a dummy edit-and-save. -->
              <button
                v-if="selectedProduct.stripe_product_id" type="button" class="secondary-action"
                :disabled="syncing" @click="checkDrift(selectedProduct)"
              >Check drift</button>
              <button
                v-if="canSyncProduct(selectedProduct)" type="button" class="secondary-action"
                :disabled="syncing" @click="syncProduct(selectedProduct)"
              >{{ syncing ? "Syncing…" : (selectedProduct.sync?.status === 'failed' ? "Retry sync" : "Sync to Stripe") }}</button>
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

        <!-- CREATE goes through the wizard; EDIT keeps the full form. A wizard is the wrong shape for
             changing something that already exists -- you want every field at once, not a path through three
             of them -- and keeping edit on the old body holds the blast radius of this change down.
             plans/LEAD_GEN_PAGES.md §10. -->
        <form v-if="wizardMode" class="product-create-body" @submit.prevent="onWizardSubmit">
          <div v-if="formError" class="keys-status-banner error">{{ formError }}</div>

          <WizardSteps :steps="wizardStepLabels" :current="wizardStep" />

          <!-- STEP — intent, asked FIRST because it decides which of the next questions are even real, and
               now also HOW MANY there are: selling something has a price list, identifiers and a package;
               a tip jar has none of those and a lead magnet is not sold at all. -->
          <section v-if="wizardStepKey === 'purpose'" class="wizard-panel">
            <p class="wizard-lede">What is your intended purpose for this product?</p>
            <div class="wizard-choice-list">
              <WizardChoiceCard
                v-for="intent in PRODUCT_INTENTS"
                :key="intent.key"
                :title="intent.label"
                :description="intent.description"
                :selected="wizardIntent === intent.key"
                @select="wizardIntent = intent.key"
              />
            </div>
          </section>

          <!-- STEP — what the thing IS. Name, description, type, category, and for something that ships,
               the variants and the box. Nothing about money and nothing about identifiers: those are their
               own steps now, because one screen asking all of it was the screen this wizard replaced. -->
          <section v-if="wizardStepKey === 'details'" class="wizard-panel">
            <label>
              Product Name <span class="required">*</span>
              <input v-model.trim="form.name" required autocomplete="off" :placeholder="intentNamePlaceholder" />
            </label>
            <label>
              Description
              <textarea v-model.trim="form.description" rows="3" placeholder="Describe it in a line or two..."></textarea>
            </label>

            <template v-if="wizardIntent === 'transaction'">
              <div class="modal-inline-grid">
                <label>
                  Type
                  <select v-model="form.product_type">
                    <option value="physical">Physical — requires shipping</option>
                    <option value="digital">Digital — no shipping</option>
                    <option value="service">Service — opens booking flow</option>
                  </select>
                  <span class="field-note">Determines fulfillment behavior and address collection at checkout.</span>
                </label>
                <ProductCategoryField v-model="form.product_category" :product-type="form.product_type" />
              </div>

              <!-- Only for something that ships. A digital download has no box and no size chart, and
                   showing the fields anyway is what made the old single form feel like a tax form. -->
              <section v-if="form.product_type === 'physical'" class="wizard-subsection">
                <ProductVariantsField :form="form" />
              </section>
            </template>

            <template v-else-if="wizardIntent === 'lead_gen'">
              <p class="field-note">
                A lead magnet is never sold, so it has no price, SKU or category — just the action it performs.
              </p>
              <!-- Labelled like every other field on this step. The bare button read as an instruction
                   ("Action: Capture email") rather than as the value of something called Lead Capture
                   Action, which is what it is. -->
              <div class="wizard-field">
                <span class="wizard-field-label">Lead Capture Action <span class="required">*</span></span>
                <button class="secondary-action" type="button" @click="showLeadPicker = true">
                  {{ form.lead_capture.label || "Choose an action…" }}
                </button>
              </div>
              <!-- ONE phone control, the same one the Profile screen uses: country picker, per-country
                   formatting, and a plain E.164 string out. A free-form textbox produced whatever the tenant
                   typed, and a tel: link built from that is only as good as their punctuation. -->
              <label v-if="leadTargetLabel">
                {{ leadTargetLabel }}
                <PhoneInput v-if="leadTargetIsPhone" v-model="form.lead_capture.target" />
                <input v-else v-model.trim="form.lead_capture.target" :placeholder="leadTargetPlaceholder" />
              </label>
            </template>

            <template v-else>
              <p class="field-note">
                A tip jar has no SKU, condition or shipping — nothing about it is a catalogue item, and its
                category is simply “Tip”.
              </p>
              <!-- Fees FIRST, then the amounts: the mode decides what each amount means, and every amount
                   below restates itself when this changes. Asking it afterwards made the tenant type three
                   numbers and then discover they meant something else. -->
              <label>
                Who pays the fees
                <select v-model="form.prices[0].fee_handling">
                  <option value="net_guaranteed">The customer — you keep the full amount</option>
                  <option value="split">Split 50/50</option>
                  <option value="standard">You do — fees come out of the tip</option>
                </select>
                <span class="field-note">
                  Everywhere else, the fees come out of your tip. Here, your customer can cover them.
                </span>
              </label>
              <TipAmountsField :price="form.prices[0]" :product-type="form.product_type" />
            </template>
          </section>

          <!-- STEP — the price list, on its own screen. It carries the pricing model, who pays the fees and
               a live preview of both, which is a decision in its own right rather than a number to type
               beside the product name. -->
          <section v-if="wizardStepKey === 'pricing'" class="wizard-panel">
            <PricingCard
              :prices="form.prices"
              v-model:default-index="form.default_price_index"
              :product-type="form.product_type"
              subtitle="Product owns the canonical price list. Labels and bundle presentation are set in Offers."
            />
          </section>

          <!-- STEP — how the world identifies this product. Optional to a fault: every field here can be
               left blank and the product still sells. -->
          <section v-if="wizardStepKey === 'identifiers'" class="wizard-panel">
            <p class="wizard-lede">How should shoppers and search engines identify this? <em>(optional)</em></p>
            <ProductIdentifiersField :form="form" sku-open @sku-edited="skuTouched = true" />
            <ProductTagsField :tags="form.tags" />
          </section>

          <!-- STEP — an image, optional. Last because it is the one step someone may reasonably skip. -->
          <section v-if="wizardStepKey === 'image'" class="wizard-panel">
            <p class="wizard-lede">Add an image <em>(optional)</em></p>
            <p class="field-note">
              You can skip this and add one later. A page with no image is not broken — it is just plainer.
            </p>
            <ProductImagesField
              :uploaded="form.uploaded_images"
              v-model:urls="form.images"
              :status="uploadStatus"
              :status-kind="uploadStatusKind"
              :crop-busy="cropBusy"
              :can-crop="canCrop"
              :short-name="shortImageName"
              @files="handleImageFiles"
              @crop="croppingUrl = $event"
            />
          </section>

          <footer class="product-modal-footer">
            <button class="secondary-action" type="button" @click="wizardStep === 1 ? closeCreateModal() : wizardBack()">
              {{ wizardStep === 1 ? "Cancel" : "Back" }}
            </button>
            <button class="primary-action" type="submit" :disabled="store.savingStatus || !wizardCanAdvance">
              {{ onLastWizardStep ? (store.savingStatus ? "Saving..." : "Create product") : "Continue" }}
            </button>
          </footer>
        </form>

        <form v-else class="product-create-body" @submit.prevent="saveProduct">
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
            <ProductCategoryField v-model="form.product_category" :product-type="form.product_type" />
          </div>

          <!-- Both feed the landing page's structured data (schema.org sku / itemCondition). Condition is
               asked rather than assumed: the markup is a machine-readable claim, so it may only state what
               the seller actually told us. -->
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

          <ProductIdentifiersField :form="form" @sku-edited="skuTouched = true" />

          <!-- Intent alone decides whether payment is collected: "I want a payment" enables the payment
               gateway (Stripe sync); "capture a lead" turns it off. The old "Enable Payment Gateway" toggle
               is derived from this now — "payment gateway" is jargon business owners shouldn't have to reason
               about. -->
          <label>
            Intent
            <select v-model="form.product_intent">
              <option value="transaction">I want a payment</option>
              <option value="lead_gen">I want to capture a lead</option>
            </select>
            <span class="field-note">Choose whether this product collects payment or captures lead information. Payment products are set up to charge through Stripe automatically.</span>
          </label>

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

          <label v-if="form.product_intent === 'lead_gen' && leadTargetLabelFor(form.lead_capture.action)">
            {{ leadTargetLabelFor(form.lead_capture.action) }}
            <PhoneInput v-if="form.lead_capture.action === 'call_number'" v-model="form.lead_capture.target" />
            <input v-else v-model.trim="form.lead_capture.target"
                   :placeholder="leadTargetPlaceholderFor(form.lead_capture.action)" />
          </label>

          <div v-if="form.product_intent === 'lead_gen'" class="lead-action-toast">
            <span class="lead-action-info" aria-hidden="true">i</span>
            <div>
              <strong>Lead capture action:</strong>
              <span>{{ form.lead_capture.label }}</span>
              <em v-if="leadTargetPreview">{{ leadTargetPreview }}</em>
            </div>
            <button class="secondary-action" type="button" @click="showLeadPicker = true">Choose action</button>
          </div>

          <ProductTagsField :tags="form.tags" />

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
            <ProductImagesField
              heading="Image URLs"
              :uploaded="form.uploaded_images"
              v-model:urls="form.images"
              :status="uploadStatus"
              :status-kind="uploadStatusKind"
              :crop-busy="cropBusy"
              :can-crop="canCrop"
              :short-name="shortImageName"
              @files="handleImageFiles"
              @crop="croppingUrl = $event"
            />
          </section>

          <section v-if="form.product_intent === 'transaction' && form.product_type === 'physical'" class="modal-form-section">
            <ProductVariantsField :form="form" />
          </section>

          <footer class="product-modal-footer">
            <button class="secondary-action" type="button" @click="closeCreateModal">Cancel</button>
            <button class="primary-action" type="submit" :disabled="store.savingStatus">
              {{ store.savingStatus ? "Saving..." : "Save Product" }}
            </button>
          </footer>
        </form>

        <!-- ONE cropper for both bodies (wizard and full form), because both now show image previews and a
             cropper nested inside one of the two <form>s opens nothing from the other. -->
        <ImageCropper
          v-if="croppingUrl"
          :src="cropSourceUrl(croppingUrl)"
          :ratios="imageRatios.asset.product"
          :crop="existingCrop(croppingUrl)"
          title="Crop this product photo"
          :busy="cropBusy"
          @apply="applyProductCrop"
          @cancel="croppingUrl = ''"
        />
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
import { apiRequest, toAssetCdnUrl } from "../api/client";
import { defaultProductPrice, formatMoney, generateSku, normalizeTag, priceSummary, useProductsStore } from "../stores/products";
// The lead-action glyph is shared with the Offers selector, so the same product looks the same on both.
import { leadActionIcon as leadIcon } from "../utils/leadActionIcon";
import PhoneInput from "./PhoneInput.vue";
import TipAmountsField from "./shared/TipAmountsField.vue";
import WizardChoiceCard from "./shared/WizardChoiceCard.vue";
import WizardSteps from "./shared/WizardSteps.vue";
import { dimsFromStatus, recordImageDims } from "../utils/imageDims";
import { cropBox, cropImage } from "../api/uploads";
import ImageCropper from "./shared/ImageCropper.vue";
import imageRatios from "../../../src/stripe_link/image_ratios.json";
import { TIP_MAX, TIP_MIN, TIP_RULES, maxTipPresets, recommendedTipPresets } from "../config/tips";
import { defaultPriceForm, priceFormFromDocument } from "../utils/priceForm";
import { idColorStyle } from "../utils/iconColor";
import PricingCard from "./shared/PricingCard.vue";
import ConfirmDialog from "./shared/ConfirmDialog.vue";
// The product form's blocks, shared by the create WIZARD and the full EDIT form. Two copies of a field that
// talks to the shared taxonomy, or to Stripe's image limit, is how the two quietly stop agreeing.
import ProductCategoryField from "./products/ProductCategoryField.vue";
import ProductIdentifiersField from "./products/ProductIdentifiersField.vue";
import ProductImagesField from "./products/ProductImagesField.vue";
import ProductTagsField from "./products/ProductTagsField.vue";
import ProductVariantsField from "./products/ProductVariantsField.vue";
import { defaultColorVariant, defaultSizeVariant } from "../utils/productVariants";
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

// --- Product creation wizard (plans/LEAD_GEN_PAGES.md §10) ---
// Intent is asked FIRST because it decides which of the later questions are even real: a tip jar has no SKU,
// category, condition or shipping; a lead magnet has no price. Asking everything and hiding most of it is how
// the single form got to 1,200 lines.
//
// "Tip jar" is NOT a third product_intent. It is a transaction product whose price is customer_chooses --
// mapping it that way means Offers, the fee class and the index projection need no new shape
// (plans/PAY_WHAT_YOU_WANT.md §4). The wizard's three answers are a UI vocabulary, not a document field.
// The flow DEPENDS on the intent, because the intent decides which questions are real. Selling something
// has a price list, identifiers and (if it ships) a package; a tip jar has none of those and a lead magnet is
// never sold at all. Steps are addressed by KEY rather than by number so a panel cannot drift onto the wrong
// screen the next time a flow gains or loses one.
const WIZARD_STEP_LABELS = {
  purpose: "Purpose",
  details: "Product details",
  pricing: "Pricing",
  identifiers: "Identifiers",
  image: "Image",
};
const WIZARD_FLOWS = {
  transaction: ["purpose", "details", "pricing", "identifiers", "image"],
  lead_gen: ["purpose", "details", "image"],
  tip_jar: ["purpose", "details", "image"],
};
const PRODUCT_INTENTS = [
  // No icons, deliberately: three tinted glyphs made a list of three sentences read as a toolbar, and the
  // titles already carry the meaning (author, 2026-09-13).
  { key: "transaction", label: "Sell something",
    description: "A product or service people pay a set price for." },
  { key: "lead_gen", label: "Capture a lead",
    description: "A free download, a call, or a link. Never sold." },
  { key: "tip_jar", label: "Receive tips",
    description: "Supporters choose what to pay. You can have them cover the fees." },
];
const wizardMode = ref(false);
const wizardStep = ref(1);
const wizardIntent = ref("transaction");
const wizardFlow = computed(() => WIZARD_FLOWS[wizardIntent.value] || WIZARD_FLOWS.transaction);
const wizardStepLabels = computed(() => wizardFlow.value.map((key) => WIZARD_STEP_LABELS[key]));
const wizardStepKey = computed(() => wizardFlow.value[wizardStep.value - 1] || "purpose");
const onLastWizardStep = computed(() => wizardStep.value >= wizardFlow.value.length);

// Every tip jar is filed under the same category (author, 2026-09-13), so tips group together in the list and
// nobody is asked to invent a taxonomy entry for one. It is a real category, not a blank: the shared taxonomy
// counts DISTINCT tenants before promoting a key to a suggestion, and "tip" is a key that deserves promoting.
const TIP_CATEGORY = "tip";

// Where a lead magnet is filed. Curated, neutral, and public-facing-safe -- see applyWizardIntent.
const LEAD_CATEGORY = "other";

const intentNamePlaceholder = computed(() => ({
  transaction: "e.g. Premium Widget",
  lead_gen: "e.g. Free Starter Guide",
  // Deliberately not the coffee example: it names a competitor (author, 2026-09-13).
  tip_jar: "e.g. Support the cause",
}[wizardIntent.value] || "e.g. Premium Widget"));

// Step 1 needs a choice; step 2 needs a name, and a lead product needs its action -- without one there is
// nothing for the page to do. Everything else on step 2 has a workable default.
const wizardCanAdvance = computed(() => {
  if (wizardStepKey.value === "purpose") return Boolean(wizardIntent.value);
  if (wizardStepKey.value === "pricing") {
    return !form.value.prices.some((price) => price.pricing_model === "recurring" && !price.billing_interval);
  }
  if (wizardStepKey.value === "details") {
    if (!form.value.name.trim()) return false;
    // A category is what files the product in the shared taxonomy, and the Details step now ASKS for one --
    // so it can be required here rather than discovered as a save error pointing at an off-screen field.
    if (wizardIntent.value === "transaction" && !form.value.product_category) return false;
    if (wizardIntent.value === "lead_gen") return Boolean(form.value.lead_capture.action);
    if (wizardIntent.value === "tip_jar") {
      return form.value.prices[0].allow_custom || (form.value.prices[0].presets || []).some((a) => Number(a) > 0);
    }
  }
  return true;
});

function onWizardSubmit() {
  if (onLastWizardStep.value) return saveProduct();
  return wizardNext();
}

function wizardNext() {
  if (!wizardCanAdvance.value) return;
  // Apply the intent as soon as it is chosen, so the next step edits a form that already matches it.
  if (wizardStepKey.value === "purpose") applyWizardIntent();
  wizardStep.value = Math.min(wizardFlow.value.length, wizardStep.value + 1);
}

function wizardBack() {
  wizardStep.value = Math.max(1, wizardStep.value - 1);
}

function applyWizardIntent() {
  const price = form.value.prices[0];
  if (wizardIntent.value === "lead_gen") {
    form.value.product_intent = "lead_gen";
    price.pricing_model = "one_time";
    // A lead magnet FILES ITSELF, the same way a tip jar does. The wizard never shows a category field on
    // this flow -- there is nothing to categorise, nothing is sold -- but `product_category` is required of
    // every product server-side, so without this the wizard produced a document the API rejected with
    // "Product product_category must be a non-empty string": an error naming a field that was never on the
    // screen (author, 2026-09-15).
    //
    // "other" rather than a "lead_gen" key of its own, on the author's preference and for a reason worth
    // keeping: product_category is PUBLIC. It becomes schema.org `category`, a breadcrumb label and the key
    // a Site's category rail groups by. "Other" is meaningless there but harmless; "Lead Gen" would put
    // internal jargon on a buyer-facing label. It is also already curated, so unlike "tip" it needs no
    // exclusion from the suggestion list.
    //
    // hydratingForm suppresses the product_type watcher, which clears the category when the type changes --
    // the same trap the tip branch below hit, where the watcher undid the line that had just run.
    hydratingForm.value = true;
    form.value.product_type = "digital";
    form.value.product_category = LEAD_CATEGORY;
    nextTick(() => { hydratingForm.value = false; });
  } else if (wizardIntent.value === "tip_jar") {
    // A transaction product, priced customer_chooses. Digital because nothing ships and nothing is booked.
    form.value.product_intent = "transaction";
    // hydratingForm suppresses the product_type watcher, which clears the category and SKU when the type
    // changes. Here the type and the category are both set BY the intent, so the watcher would undo the
    // second assignment and the tenant would be asked for a category the wizard never shows -- which is
    // exactly what blocked every tip jar from being created.
    hydratingForm.value = true;
    form.value.product_type = "digital";
    form.value.product_category = TIP_CATEGORY;
    nextTick(() => { hydratingForm.value = false; });
    price.pricing_model = "customer_chooses";
    // The pitch's default: the customer covers the fees, so the creator keeps the full amount. Editable, and
    // the trade-off is visible -- the buyer sees a slightly higher number.
    price.fee_handling = "net_guaranteed";
    // The same ladder the "Use recommended amounts" button writes -- a second hardcoded seed here would be
    // two answers to "what should a new tip jar offer?".
    if (!price.presets.length) {
      price.presets = recommendedTipPresets(false, price.allow_custom !== false, price.currency);
    }
  } else {
    form.value.product_intent = "transaction";
    price.pricing_model = "one_time";
    // Going BACK and picking "Sell something" after one of the self-filing intents must not leave their
    // category behind. Its field is shown on this flow, so inheriting "Tip" from an abandoned pass would
    // pre-fill a category the picker no longer even offers -- and a product for sale filed under "Tip" is
    // wrong in the product list, the breadcrumb and the schema alike.
    if ([TIP_CATEGORY, LEAD_CATEGORY].includes(form.value.product_category)) {
      form.value.product_category = "";
    }
  }
}

const showLeadPicker = ref(false);
const formError = ref("");
const imageFileInput = ref(null);
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

const leadTargetLabel = computed(() => leadTargetLabelFor(draftLeadAction.value.action));
const leadTargetIsPhone = computed(() => draftLeadAction.value.action === "call_number");

// By ACTION rather than off the draft, because the full edit form asks for the same destination without a
// draft in play. The phone case is absent: PhoneInput supplies its own per-country placeholder.
function leadTargetPlaceholderFor(action) {
  if (action === "external_url") return "https://example.com";
  if (action === "social_redirect") return "https://instagram.com/example";
  return "";
}

const leadTargetPlaceholder = computed(() => leadTargetPlaceholderFor(draftLeadAction.value.action));

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
  // priceSummary, not formatMoney: a tip jar has no unit_amount and would otherwise read "No price".
  return priceSummary(defaultProductPrice(product));
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
    brand: "",
    mpn: "",
    gtin: "",
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
    image_assets: {},
    image_crops: {},
    image_dims: {},
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
  draftLeadAction.value = { ...defaultLeadAction };
  formError.value = "";
  uploadStatus.value = "";
  uploadStatusKind.value = "";
  wizardMode.value = true;
  wizardStep.value = 1;
  wizardIntent.value = "transaction";
  showCreateModal.value = true;
}

async function openEditModal(row) {
  // The list holds index ROWS; the editor needs the whole document (refund policy, variants, identifiers,
  // per-price fee data the projection drops). One fetch, for the one product being opened.
  const product = await store.fetchFull(row);
  editingProduct.value = product;
  hydratingForm.value = true;
  skuTouched.value = false;
  form.value = productFormFromDocument(product);
  // Products created before SKUs existed get one now, from the same name+id inputs a new product would use.
  if (!form.value.sku) form.value.sku = generateSku(product.name, product.product_id);
  draftLeadAction.value = { ...form.value.lead_capture };
  formError.value = "";
  uploadStatus.value = "";
  uploadStatusKind.value = "";
  wizardMode.value = false;   // editing shows every field at once; a wizard is the wrong shape for that
  showCreateModal.value = true;
  await nextTick();
  hydratingForm.value = false;
}

function closeCreateModal() {
  showCreateModal.value = false;
  wizardMode.value = false;
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
    brand: product.brand || "",
    mpn: product.mpn || "",
    gtin: product.gtin || "",
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
    image_dims: { ...(product.image_dims || {}) },
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

function applyLeadAction() {
  // The picker chooses WHICH action; the destination is asked once, on the step that follows (author,
  // 2026-09-16 -- it used to be asked in both places, which meant two phone controls to build and keep
  // agreeing). Re-opening the picker and confirming the same action therefore has to KEEP what was typed;
  // switching to a different one drops it, because a phone number is not a URL.
  const sameAction = form.value.lead_capture.action === draftLeadAction.value.action;
  const target = sameAction ? form.value.lead_capture.target : "";
  form.value.lead_capture = { ...draftLeadAction.value, target };
  showLeadPicker.value = false;
}

// Which actions need ONE destination typed here. A Social Page is deliberately absent: its links live on the
// page as cards, so asking for a profile URL here would be asking which of them is the real one
// (plans/LEAD_GEN_PAGES.md §8). Also the form's required-field check, so removing it from this map is what
// lets a Social Page save with nothing typed.
function leadTargetLabelFor(action) {
  if (action === "call_number") return "Phone number";
  if (action === "external_url") return "Destination URL";
  return "";
}

// Tip amounts, checked where the tenant can read the reason. The server enforces the same rules (it owns
// the range outright and overwrites it), so this is the message, not the guard.
function validateTipAmounts() {
  const price = form.value.prices[0];
  if (!price || price.pricing_model !== "customer_chooses") return "";
  const presets = (price.presets || []).map(Number).filter((amount) => amount > 0);
  if (presets.some((amount) => amount < TIP_MIN || amount > TIP_MAX)) {
    return `Tip amounts must be between ${formatMoney(TIP_RULES.min_amount, "usd")} and ${formatMoney(TIP_RULES.max_amount, "usd")}.`;
  }
  if (new Set(presets).size !== presets.length) return "Each tip amount must be different.";
  const cap = maxTipPresets(price.allow_custom !== false);
  if (presets.length > cap) {
    return `At most ${cap} tip amounts fit in the row${price.allow_custom !== false ? " alongside “enter your own”" : ""}.`;
  }
  return "";
}

function validateProductForm() {
  if (!form.value.name.trim()) return "Product name is required.";
  // Required wherever it is ASKED FOR, and nowhere else. The full form always asks. The wizard asks only on
  // the flow that has one -- a tip jar files itself under "tip" and a lead magnet is never sold -- and
  // demanding one on those pointed the tenant at a field that was not on their screen, which rejected every
  // product the wizard could produce (2026-09-13).
  const categoryAsked = !wizardMode.value || wizardIntent.value === "transaction";
  if (categoryAsked && !form.value.product_category) return "Choose a product category.";
  const tipError = validateTipAmounts();
  if (tipError) return tipError;
  if (form.value.product_intent === "lead_gen" && leadTargetLabelFor(form.value.lead_capture.action) && !form.value.lead_capture.target) {
    return `${form.value.lead_capture.label} requires a target.`;
  }
  if (form.value.product_intent === "transaction" && form.value.prices.some((price) => Number(price.quantity || 0) < 1)) return "Each price quantity must be at least 1.";
  // Caught here as well as server-side, so the tenant is told on the screen holding the field rather than by
  // a rejected save. A recurring price with no interval used to save happily and then charge once.
  if (form.value.prices.some((price) => price.pricing_model === "recurring" && !price.billing_interval)) {
    return "Choose a billing interval for your recurring price.";
  }
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

function canSyncProduct(product) {
  // Payment products push to Stripe; lead-gen (non-canonical) products never sync. Offer a manual sync whenever
  // the product isn't successfully synced yet — this covers grandfathered products stuck in "pending" (created
  // before auto-sync existed) as well as "failed" retries, so neither needs a dummy edit-and-save.
  if (product?.product_intent === "lead_gen" || product?.canonical === false) return false;
  return product?.sync?.status !== "success";
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
      const { url, dims, imageId } = await uploadProductImage(file);
      addUploadedImage(url, dims, imageId);
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
      const probe = await imageUrlLoads(url);
      if (probe.ok) return { url, dims: dimsFromStatus(body, probe), imageId };
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
  return toAssetCdnUrl(url);  // upload bucket host -> configured asset CDN (public_asset_base_url)
}

function imageUrlLoads(url, timeoutMs = 4000) {
  if (!url) return Promise.resolve({ ok: false });
  return new Promise((resolve) => {
    const image = new Image();
    let done = false;
    const finish = (ok) => {
      if (done) return;
      done = true;
      const dims = ok ? { width: image.naturalWidth, height: image.naturalHeight } : {};
      image.onload = null;
      image.onerror = null;
      resolve({ ok, ...dims });
    };
    image.onload = () => finish(true);
    image.onerror = () => finish(false);
    image.src = `${url}${url.includes("?") ? "&" : "?"}_probe=${Date.now()}`;
    setTimeout(() => finish(false), timeoutMs);
  });
}

function addUploadedImage(url, dims, imageId) {
  if (!url) return;
  // Keep the asset id against the URL so this image stays croppable after the modal closes.
  if (imageId) form.value.image_assets = { ...(form.value.image_assets || {}), [url]: imageId };
  form.value.uploaded_images = [...new Set([...form.value.uploaded_images, url])].slice(0, 8);
  form.value.images = [...new Set([...String(form.value.images || "").split(/\n+/).map((line) => line.trim()).filter(Boolean), url])].slice(0, 8).join("\n");
  recordImageDims(form.value.image_dims, url, dims);
}

// A product photo is an ASSET: it appears on the hero carousel, price cards, listicle slides AND in
// og:image and Product JSON-LD. Meta tags are URLs no stylesheet can reach, so the crop is baked into a
// derivative and the stored URL becomes the cropped one (plans/IMAGE_CROPPER.md).
const croppingUrl = ref("");
const cropBusy = ref(false);

function cropAssetId(url) {
  return (form.value.image_assets || {})[url] || (form.value.image_crops || {})[url]?.image_id || "";
}
function cropSourceUrl(url) {
  return (form.value.image_crops || {})[url]?.original_url || url;
}
function existingCrop(url) {
  return (form.value.image_crops || {})[url] || null;
}
function canCrop(url) {
  // Pasted URLs and images uploaded before cropping existed have no asset id, so there is nothing to
  // crop from -- the service crops the original it holds, not whatever a URL happens to point at.
  return Boolean(cropAssetId(url));
}

function replaceImageUrl(oldUrl, newUrl) {
  form.value.uploaded_images = form.value.uploaded_images.map((u) => (u === oldUrl ? newUrl : u));
  form.value.images = String(form.value.images || "")
    .split(/\n+/).map((line) => (line.trim() === oldUrl ? newUrl : line.trim())).filter(Boolean).join("\n");
}

async function applyProductCrop(rect) {
  const oldUrl = croppingUrl.value;
  const id = cropAssetId(oldUrl);
  const original = cropSourceUrl(oldUrl);
  cropBusy.value = true;
  uploadStatusKind.value = "";
  uploadStatus.value = "Applying crop...";
  try {
    const url = await cropImage(id, rect, cropBox(rect.ar));
    replaceImageUrl(oldUrl, url);
    const assets = { ...(form.value.image_assets || {}) };
    delete assets[oldUrl];
    assets[url] = id;
    form.value.image_assets = assets;
    const crops = { ...(form.value.image_crops || {}) };
    delete crops[oldUrl];
    crops[url] = { ...rect, image_id: id, original_url: original };
    form.value.image_crops = crops;
    uploadStatus.value = "Crop applied.";
    croppingUrl.value = "";
  } catch (error) {
    uploadStatusKind.value = "error";
    uploadStatus.value = error.message || "The crop could not be applied.";
  } finally {
    cropBusy.value = false;
  }
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
