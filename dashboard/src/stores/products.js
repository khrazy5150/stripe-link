import { defineStore } from "pinia";
import { apiRequest, getStripeMode, getTenantId } from "../api/client";
import { fetchFullDocument, filterRows, loadIndex, searchText } from "../composables/indexedList.js";
import { buildPriceDocument, freeLeadPrice } from "./pricing";
import { imageDimsForUrls } from "../utils/imageDims";

function productLifecycleStatus(product) {
  return product?.status === "archived" || product?.active === false ? "archived" : "active";
}

// What a product is searchable by — the only product-specific part of the filtering. The category appears
// twice on purpose: once as the stored key ("dietary_supplement") and once humanised, so typing either
// "dietary supplement" or the key finds it.
export const PRODUCT_SEARCH_FIELDS = [
  "product_id",
  "stripe_product_id",
  "name",
  "description",
  "product_category",
  (product) => String(product?.product_category || "").replace(/_/g, " "),
  "product_type",
  "tags",
];

function productSearchText(product) {
  return searchText(product, PRODUCT_SEARCH_FIELDS);
}

function localId(prefix = "local") {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
  const cryptoApi = globalThis.crypto;
  const bytes = cryptoApi?.getRandomValues ? cryptoApi.getRandomValues(new Uint8Array(11)) : null;
  const suffix = Array.from({ length: 11 }, (_, index) => alphabet[(bytes ? bytes[index] : Math.floor(Math.random() * 62)) % alphabet.length]).join("");
  return `${prefix}_${suffix}`;
}

/**
 * A merchant SKU: 5 chars from each of the first two name words, then product_id's unique tail.
 * e.g. "Creatine Gummies" + local_fgt7iPiPiL3 -> CREAT-GUMMI-FGT7IPIPIL3
 *
 * The unique tail is not decoration. Product names collide in real catalogues (three different products
 * named "Creatine Gummies"), and a SKU that repeats tells Google two products are one. product_id is the
 * only component that is both unique and permanent.
 *
 * Generated ONCE, at creation, and stored. A SKU is an identifier: deriving it live from the name would
 * mean renaming a product silently re-identified it.
 */
export function generateSku(name, productId) {
  const words = String(name || "")
    // Fold accents first: without this "Créatine" splits at the é and yields "CR-ATINE".
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase()
    .split(/[^A-Z0-9]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word.slice(0, 5));
  const unique = String(productId || "").replace(/^local_/i, "").toUpperCase();
  return [...words, unique].filter(Boolean).join("-");
}

// A GTIN with a valid mod-10 check digit (plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-06). Blank counts as valid
// (the field is optional); a non-empty value must be a real UPC/EAN/ISBN/ITF-14/GTIN-8. An invalid GTIN
// makes Google reject the whole merchant listing, so we never store one.
export function isValidGtin(raw) {
  const value = String(raw || "").trim();
  if (!value) return true;
  const digits = value.replace(/\D/g, "");
  if (![8, 12, 13, 14].includes(digits.length)) return false;
  const body = digits.slice(0, -1).split("").map(Number);
  const check = Number(digits.slice(-1));
  let sum = 0;
  let weight = 3;
  for (let i = body.length - 1; i >= 0; i--) {
    sum += body[i] * weight;
    weight = weight === 3 ? 1 : 3;
  }
  return (10 - (sum % 10)) % 10 === check;
}

function cents(value) {
  return Math.max(0, Math.round(Number(value || 0) * 100));
}

export function normalizeTag(value) {
  return String(value || "").trim().toLowerCase().replace(/[_-]+/g, " ").replace(/\s+/g, " ");
}

function titleTagParts(name) {
  return normalizeTag(name).split(" ").filter((part) => part.length > 2);
}

function uniqueTags(tags) {
  return [...new Set(tags.map(normalizeTag).filter(Boolean))];
}


// All three or nothing. A half-measured item would be packed against a box chosen from an incomplete
// shape, and unlike the package dimensions there is no defensible default to fall back on -- 10x8x4 is a
// reasonable guess at a box and a meaningless guess at a product.
function itemDimensions(form, isShippable) {
  if (!isShippable) return null;
  const sides = [form.item_length_in, form.item_width_in, form.item_height_in].map((value) => Number(value));
  if (!sides.every((value) => Number.isFinite(value) && value > 0)) return null;
  const dimensions = { length_in: sides[0], width_in: sides[1], height_in: sides[2] };
  // The BARE weight, kept separate from fulfillment.weight_lb (what it weighs packed in its own box).
  // Summing the packed weight when several items share one carton billed the cardboard once per item.
  // Written only when given: absent means the packer falls back to the packed weight, which
  // over-estimates — the safe direction, since a carrier re-bills an under-weight parcel.
  const bare = Number(form.item_weight_lb);
  if (Number.isFinite(bare) && bare > 0) dimensions.weight_lb = bare;
  return dimensions;
}

export function defaultProductPrice(product) {
  const prices = Array.isArray(product?.prices) ? product.prices : [];
  return prices.find((price) => price.price_id === product.default_price_id)
    || prices.find((price) => price.active !== false)
    || prices[0]
    || null;
}

// What a price READS as in a list. A tip jar deliberately has NO unit_amount -- the buyer picks -- so
// formatMoney reported "No price", which is true of the field and false of the product: it offers several.
export function priceSummary(price) {
  if (!price) return "No price";
  if (price.pricing_model !== "customer_chooses") return formatMoney(price.unit_amount, price.currency);
  const parts = (price.presets || []).map((amount) => formatMoney(amount, price.currency));
  if (price.allow_custom !== false) parts.push(parts.length ? "or any amount" : "Any amount");
  return parts.length ? parts.join(" · ") : "No price";
}

export function formatMoney(cents, currency = "usd") {
  if (cents === undefined || cents === null || cents === "") return "No price";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: String(currency || "usd").toUpperCase(),
  }).format(Number(cents || 0) / 100);
}

// A Service wearing the shape the product list already knows how to draw. Same idea as Offers.vue's
// serviceSelectorCard(): adapt once, and every helper -- search fields, status, the type filter, the row
// template -- works unchanged instead of growing a parallel branch for services.
//
// `__service` is what the row is FOR: the list uses it to badge the row and to send Edit to the Services
// console rather than the product editor.
export function serviceListRow(service) {
  return {
    __service: true,
    product_id: service.service_id,
    service_id: service.service_id,
    name: service.name || "Untitled Service",
    description: service.description || "",
    product_type: "service",
    product_category: service.product_category || "",
    status: service.active === false ? "archived" : "active",
    // presentation.hero_image_url, which is where buildServiceDocument() PUTS it. `hero_image_url` is the
    // FORM's field name and exists on no stored service, so reading it gave every service the "no image"
    // placeholder -- the generic art is meant for services that genuinely have none. Offers.vue's adapter
    // had this right; mine was written from the form rather than from the document.
    images: service.presentation?.hero_image_url ? [service.presentation.hero_image_url] : [],
    prices: Array.isArray(service.prices) ? service.prices : [],
    default_price_id: service.default_price_id || "",
    created_at: service.created_at || null,
    updated_at: service.updated_at || null,
  };
}

// A Service shaped enough for the purchase-flow diagram: it wants a name and prices, nothing more. Kept
// beside serviceListRow rather than inlined at the call sites -- Offers.vue and LandingPages.vue both need
// it, and this codebase's recurring bug is two copies of one adaptation drifting apart.
export function serviceFlowCard(service) {
  return {
    product_id: service.service_id,
    service_id: service.service_id,
    name: service.name || "Untitled Service",
    product_type: "service",
    prices: Array.isArray(service.prices) ? service.prices : [],
    default_price_id: service.default_price_id || "",
  };
}

export const useProductsStore = defineStore("products", {
  state: () => ({
    products: [],
    services: [],
    loading: false,
    loaded: false,
    savingStatus: false,
    error: "",
    message: "Click Load Products to see products.",
    filters: {
      search: "",
      productType: "",
      status: "active",
    },
  }),

  getters: {
    filteredProducts(state) {
      // Status + type + search through the shared machinery (composables/indexedList.js). Only the FIELD
      // LIST and the type predicate are product-specific.
      //
      // SERVICES ARE IN THIS LIST. A tenant creates one on the Products screen (the wizard's "Service" type),
      // so it has to be findable there afterwards -- otherwise the fix to creation just moves the
      // discontinuity to the day after. The list's own "Service" type filter has existed all along and
      // matched nothing, because no product is ever stored with product_type "service".
      //
      // Adapted, not merged raw: `serviceListRow` gives each one the product shape every helper already
      // expects, the same trick Offers.vue uses to put both in one selector.
      const rows = [...state.products, ...(state.services || []).map(serviceListRow)];
      return filterRows(rows, {
        term: state.filters.search,
        fields: PRODUCT_SEARCH_FIELDS,
        statusOf: productLifecycleStatus,
        status: state.filters.status,
        where: state.filters.productType
          ? (row) => row.product_type === state.filters.productType
          : null,
      });
    },

    shownCount() {
      return this.filteredProducts.length;
    },
  },

  actions: {
    // Services shown alongside products in the list. Held here rather than reached for through the services
    // store so `filteredProducts` stays a pure getter over state.
    setServices(services) {
      this.services = Array.isArray(services) ? services : [];
    },

    reset() {
      this.products = [];
      this.services = [];
      this.loading = false;
      this.loaded = false;
      this.savingStatus = false;
      this.error = "";
      this.message = "Click Load Products to see products.";
      this.resetFilters();
    },

    resetFilters() {
      this.filters.search = "";
      this.filters.productType = "";
      this.filters.status = "active";
      if (!this.loaded) this.message = "Click Load Products to see products.";
    },

    // Load on first interaction so filtering "just works" — a tenant shouldn't have to click Load Products
    // before the search box does anything. Guarded so it fires once and never races a manual load.
    ensureLoaded() {
      if (!this.loaded && !this.loading) this.load();
    },

    /** The full document for one product. The list holds index rows, which omit what only an editor
     *  needs (refund policy, variants, identifiers, per-price fee breakdowns). Falls back to the row on
     *  failure so the modal still opens rather than blocking on a network error. */
    async fetchFull(product) {
      const productId = product?.product_id;
      if (!productId) return product;
      return (await fetchFullDocument("products", productId, { key: "product" })) || product;
    },

    async load() {
      this.loading = true;
      this.error = "";
      try {
        // The slim list projection: ~34% of a full document. Products are the payload that reaches the
        // 6MB response ceiling FIRST — bigger documents than offers, and usually more of them — and BOTH
        // the Products screen and the Offers screen load the whole catalogue. Editing fetches the one
        // full document it needs (fetchFull below). plans/OFFER_ITEM_VISIBILITY.md §7.
        this.products = await loadIndex("products");
        this.loaded = true;
        this.message = this.products.length
          ? `${this.filteredProducts.length} of ${this.products.length} product${this.products.length === 1 ? "" : "s"} shown.`
          : "No products have been saved for this client yet.";
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
      } finally {
        this.loading = false;
      }
    },

    async setStatus(product, status) {
      this.savingStatus = true;
      this.error = "";
      const updatedAt = Math.floor(Date.now() / 1000);
      try {
        const body = await apiRequest(`/products/${encodeURIComponent(product.product_id)}/status`, {
          method: "PATCH",
          body: {
            tenant_id: product.tenant_id,
            status,
            updated_at: updatedAt,
          },
        });
        this.upsertProduct(body.product || { ...product, status, updated_at: updatedAt });
        this.message = `${product.name || "Product"} ${status === "archived" ? "archived" : "restored"}.`;
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
      } finally {
        this.savingStatus = false;
      }
    },

    async createProduct(form) {
      this.savingStatus = true;
      this.error = "";
      try {
        const product = await buildProductDocument(form);
        const body = await apiRequest("/products", {
          method: "POST",
          body: product,
        });
        const saved = body.product || product;
        this.upsertProduct(saved);
        this.loaded = true;
        this.message = `${product.name} was saved to the products database.`;
        // Payment-enabled products push to Stripe automatically. On a price edit this creates a
        // new Stripe price and archives the old one behind the scenes (Stripe prices are immutable).
        if (saved.canonical) {
          await this._autoSyncToStripe(saved);
        }
        return saved;
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
        throw error;
      } finally {
        this.savingStatus = false;
      }
    },

    async _autoSyncToStripe(product) {
      try {
        const body = await apiRequest(`/products/${encodeURIComponent(product.product_id)}/sync`, { method: "POST" });
        if (body.product) this.upsertProduct(body.product);
        this.message = `${product.name || "Product"} saved and synced to Stripe.`;
      } catch (error) {
        // The local save already succeeded; surface the sync error without failing the save.
        this.message = `${product.name || "Product"} saved, but Stripe sync failed: ${error.message}`;
      }
    },

    async syncToStripe(product) {
      this.error = "";
      try {
        const body = await apiRequest(`/products/${encodeURIComponent(product.product_id)}/sync`, { method: "POST" });
        if (body.product) this.upsertProduct(body.product);
        this.message = `${product.name || "Product"} synced to Stripe.`;
        return body;
      } catch (error) {
        this.error = error.message;
        this.message = `Stripe sync failed: ${error.message}`;
        await this.load();  // pull the persisted failed status
        throw error;
      }
    },

    async checkDrift(product) {
      this.error = "";
      try {
        const body = await apiRequest(`/products/${encodeURIComponent(product.product_id)}/sync`, {
          method: "POST",
          params: { check: "true" },
        });
        if (body.product) this.upsertProduct(body.product);
        const differences = body.drift?.differences || [];
        this.message = body.drift?.in_sync
          ? `${product.name || "Product"} is in sync with Stripe.`
          : `${differences.length} difference(s) vs Stripe.`;
        return body;
      } catch (error) {
        this.error = error.message;
        this.message = error.message;
        throw error;
      }
    },

    async uploadDigitalAsset(productId, file) {
      this.error = "";
      const contentType = file.type || "application/octet-stream";
      const presign = await apiRequest("/downloads/upload-url", {
        method: "POST",
        body: { product_id: productId, filename: file.name, content_type: contentType, size_bytes: file.size },
      });
      const put = await fetch(presign.upload_url, {
        method: "PUT",
        headers: { "Content-Type": contentType },
        body: file,
      });
      if (!put.ok) throw new Error(`Upload failed with ${put.status}`);
      return presign.digital_asset;
    },

    upsertProduct(product) {
      const index = this.products.findIndex((item) => item.product_id === product.product_id);
      if (index >= 0) {
        this.products.splice(index, 1, product);
      } else {
        this.products.push(product);
      }
    },
  },
});

export async function buildProductDocument(form) {
  const now = Math.floor(Date.now() / 1000);
  const productId = form.product_id || localId("local");
  const productType = form.product_type || "physical";
  const priceForms = Array.isArray(form.prices) && form.prices.length ? form.prices : [defaultPriceForm()];
  const prices = await Promise.all(priceForms.map((priceForm) => buildPriceDocument(priceForm, productType, now)));
  const defaultPrice = prices[Math.min(Math.max(Number(form.default_price_index || 0), 0), prices.length - 1)] || prices[0];
  const tags = uniqueTags([
    form.name,
    ...titleTagParts(form.name),
    form.product_category === "other" ? "" : form.product_category,
    ...form.tags,
  ]);
  const pastedImages = String(form.images || "").split(/\n+/).map((line) => line.trim()).filter(Boolean);
  const images = [...new Set([...(form.uploaded_images || []), ...pastedImages])].slice(0, 8);
  const isLeadGen = form.product_intent === "lead_gen";
  // Intrinsic dimensions of the images this product keeps (base-keyed), so the renderer reserves
  // layout space and hints crawlers. Only images actually referenced are carried.
  const imageDims = isLeadGen ? {} : imageDimsForUrls(form.image_dims, images);
  const isPhysical = productType === "physical";
  const product = {
    schema_version: "2026-05-29",
    document_type: "product",
    tenant_id: getTenantId(),
    product_id: productId,
    stripe_product_id: form.stripe_product_id || null,
    stripe_mode: form.stripe_mode || getStripeMode(),
    // Payment gateway (Stripe sync) is derived from intent, not a separate toggle: a payment product is
    // canonical, a lead-capture product is not. "Enable Payment Gateway" was jargon and is gone from the UI.
    canonical: !isLeadGen,
    status: form.status === "archived" ? "archived" : "active",
    name: String(form.name || "").trim(),
    description: String(form.description || "").trim(),
    // A lead magnet keeps its images. They were stripped because it is "never sold" -- but the picture is
    // what the squeeze page shows ABOVE the form, and emptying the array left the hero_media section with
    // nothing to render, so every lead page was text on white (author, 2026-09-15).
    images,
    ...(Object.keys(imageDims).length ? { image_dims: imageDims } : {}),
    product_intent: isLeadGen ? "lead_gen" : "transaction",
    product_type: productType,
    product_category: form.product_category,
    // SKU is generated deterministically at save time (name + id) so it is ALWAYS present and stable —
    // never dropped because the form field was momentarily blank. A tenant's own SKU wins when set.
    sku: String(form.sku || "").trim() || generateSku(form.name, productId),
    condition: form.condition || "new",
    // Merchant-listing identifiers (SEO-06) — physical goods only (they're what appears in shopping results).
    // Omit blanks; drop an invalid GTIN rather than block the save (the form warns the tenant) — an invalid
    // GTIN would fail backend validation and reject the listing.
    ...(isPhysical && String(form.brand || "").trim() ? { brand: String(form.brand).trim() } : {}),
    ...(isPhysical && String(form.mpn || "").trim() ? { mpn: String(form.mpn).trim() } : {}),
    ...(isPhysical && String(form.gtin || "").trim() && isValidGtin(form.gtin) ? { gtin: String(form.gtin).trim() } : {}),
    refund_policy: refundPolicy(productType, form),
    variants: {
      size_enabled: isPhysical && !isLeadGen && Boolean(form.size_enabled),
      color_enabled: isPhysical && !isLeadGen && Boolean(form.color_enabled),
      sizes: isPhysical && !isLeadGen && form.size_enabled ? sizeVariants(form.sizes) : [],
      colors: isPhysical && !isLeadGen && form.color_enabled ? colorVariants(form.colors) : [],
    },
    prices: isLeadGen ? [freeLeadPrice(defaultPrice?.price_id || localId("price"), now)] : prices,
    default_price_id: isLeadGen ? (defaultPrice?.price_id || prices[0]?.price_id || localId("price")) : defaultPrice.price_id,
    fulfillment: {
      requires_shipping: isPhysical && !isLeadGen,
      ship_from: null,
      weight_lb: isPhysical && !isLeadGen ? Number(form.weight_lb || 1) : null,
      dimensions: {
        length_in: isPhysical && !isLeadGen ? Number(form.length_in || 10) : null,
        width_in: isPhysical && !isLeadGen ? Number(form.width_in || 8) : null,
        height_in: isPhysical && !isLeadGen ? Number(form.height_in || 4) : null,
      },
      // The product's OWN size, distinct from the box above. Written only when the tenant actually
      // entered all three: a partial item size packs into a box chosen from nonsense, and there is no
      // sensible default for "how big is this thing" the way there is for "what box do you use".
      item_dimensions: itemDimensions(form, isPhysical && !isLeadGen),
      // A pouch squashes into a padded mailer; a jar of the same size does not. And a declared box is an
      // EXCEPTION the tenant opts into, not something inferred from the box fields being filled in.
      compressible: isPhysical && !isLeadGen ? Boolean(form.compressible) : false,
      ships_alone: isPhysical && !isLeadGen ? Boolean(form.ships_alone) : false,
    },
    sync: {
      status: "pending",
      last_synced_at: null,
      error: null,
    },
    created_at: form.created_at || now,
    updated_at: now,
    tags,
  };
  if (isLeadGen) product.lead_capture = leadCaptureShape(form.lead_capture);
  if (!isLeadGen && form.digital_asset && form.digital_asset.bucket_key) {
    product.digital_asset = form.digital_asset;
  }
  return product;
}

function sizeVariants(values) {
  return uniqueVariants((values || [])
    .map((value) => {
      if (typeof value === "string") return { label: value.trim(), description: "" };
      return {
        label: String(value?.label || "").trim(),
        description: String(value?.description || "").trim(),
      };
    })
    .filter((variant) => variant.label || variant.description));
}

function colorVariants(values) {
  return uniqueVariants((values || [])
    .map((value) => {
      if (typeof value === "string") return { label: value.trim(), hex_color: "#000000", description: "" };
      return {
        label: String(value?.label || "").trim(),
        hex_color: String(value?.hex_color || "#000000").trim() || "#000000",
        description: String(value?.description || "").trim(),
      };
    })
    .filter((variant) => variant.label || variant.description));
}

function uniqueVariants(variants) {
  const seen = new Set();
  return variants.filter((variant) => {
    const key = JSON.stringify(variant);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function defaultPriceForm() {
  return {
    sales_price: 0,
    regular_price: 0,
    currency: "usd",
    quantity: 1,
    pricing_model: "one_time",
    fee_handling: "standard",
    context: "standard",
    min_amount: 0,
    suggested_amount: 0,
  };
}

function refundPolicy(productType, form) {
  if (form.refund_source !== "product_override") {
    return {
      source: form.refund_source || "user_preference_default",
      refund_window: productType === "digital" ? "non_refundable" : "30_days",
      condition: productType === "digital" ? "any" : "unused",
      return_method: productType === "digital" ? "digital_revoke_access" : "no_return_customer_keeps",
      short_label: productType === "digital" ? "Non-refundable" : "30-day money-back",
      full_policy: productType === "digital"
        ? "All sales are final and as such, no item can be returned, replaced, or refunded in full or in part."
        : "Refunds are available within 30 days of delivery in unused condition.\n\nThis item does not need to be returned. The customer may keep the item and dispose of it in a responsible way. The seller may still grant a refund.",
    };
  }
  return {
    source: "product_override",
    refund_window: form.refund_window || "30_days",
    condition: form.refund_condition || "unused",
    return_method: form.refund_return_method || "no_return_customer_keeps",
    short_label: form.refund_short_label || "30-day money-back",
    full_policy: form.refund_full_policy || "Refunds are available within 30 days of delivery in unused condition.",
  };
}

// What the FORM says to a visitor, per action. Deliberately separate from the picker's label and
// description (leadActions[] in Products.vue), which are written for the TENANT choosing an action: "Capture
// email / Collect the visitor's email address." describes what the software does TO the visitor, and putting
// it on their screen is how a lead page came to introduce itself by explaining its own plumbing
// (author, 2026-09-15). The schema requires both fields, so these are prompts rather than nothing.
const LEAD_FORM_COPY = {
  capture_email: { title: "Where should we send it?", description: "Enter your email and we'll send it straight over." },
  capture_phone: { title: "Where can we reach you?", description: "Enter your number and we'll be in touch." },
  capture_email_phone: { title: "How should we reach you?", description: "Leave your details and we'll follow up." },
  call_number: { title: "Talk to us", description: "Give us a call and we'll take it from there." },
  external_url: { title: "Keep going", description: "Follow the link to continue." },
  social_redirect: { title: "Find us there", description: "Follow the link to continue." },
};

function leadCaptureShape(action = {}) {
  const key = action.action || "capture_email";
  const copy = LEAD_FORM_COPY[key] || LEAD_FORM_COPY.capture_email;
  const base = {
    action: key,
    // Derived from the action KEY, never carried over from the picked action object. The picker hands us its
    // own `label` and `description` -- tenant-facing vocabulary -- and reading either here is precisely the
    // leak. There is no tenant-editable field for these today; when one exists it can feed in deliberately.
    title: copy.title,
    description: copy.description,
  };
  if (base.action === "capture_email") {
    base.fields = [{ name: "email", type: "email", required: true }];
  } else if (base.action === "capture_phone") {
    base.fields = [{ name: "phone", type: "tel", required: true }];
  } else if (base.action === "capture_email_phone") {
    base.fields = [
      { name: "email", type: "email", required: true },
      { name: "phone", type: "tel", required: true },
    ];
  } else if (base.action === "call_number") {
    base.target = { type: "phone", value: action.target || "" };
  } else if (base.action === "external_url") {
    base.target = { type: "url", value: action.target || "", open: "new_tab" };
  } else if (base.action === "social_redirect" && action.target) {
    // Only when one was actually typed. A Social Page normally has none -- writing an empty target would
    // store a destination the page does not have, and `value` is required whenever the object exists.
    base.target = { type: "social", value: action.target, platform: action.platform || "other", open: "new_tab" };
  }
  return base;
}
