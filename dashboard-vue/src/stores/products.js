import { defineStore } from "pinia";
import { apiRequest, getApiEnvironment, getTenantId } from "../api/client";
import { buildPriceDocument, freeLeadPrice } from "./pricing";

function productLifecycleStatus(product) {
  return product?.status === "archived" || product?.active === false ? "archived" : "active";
}

function productSearchText(product) {
  return [
    product.product_id,
    product.stripe_product_id,
    product.name,
    product.description,
    product.product_category,
    String(product.product_category || "").replace(/_/g, " "),
    product.product_type,
    ...(Array.isArray(product.tags) ? product.tags : []),
  ].filter(Boolean).join(" ").toLowerCase();
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

function cents(value) {
  return Math.max(0, Math.round(Number(value || 0) * 100));
}

function normalizeTag(value) {
  return String(value || "").trim().toLowerCase().replace(/[_-]+/g, " ").replace(/\s+/g, " ");
}

function titleTagParts(name) {
  return normalizeTag(name).split(" ").filter((part) => part.length > 2);
}

function uniqueTags(tags) {
  return [...new Set(tags.map(normalizeTag).filter(Boolean))];
}


export function defaultProductPrice(product) {
  const prices = Array.isArray(product?.prices) ? product.prices : [];
  return prices.find((price) => price.price_id === product.default_price_id)
    || prices.find((price) => price.active !== false)
    || prices[0]
    || null;
}

export function formatMoney(cents, currency = "usd") {
  if (cents === undefined || cents === null || cents === "") return "No price";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: String(currency || "usd").toUpperCase(),
  }).format(Number(cents || 0) / 100);
}

export const useProductsStore = defineStore("products", {
  state: () => ({
    products: [],
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
      const search = state.filters.search.trim().toLowerCase();
      return state.products.filter((product) => {
        const status = productLifecycleStatus(product);
        if (state.filters.status === "active" && status !== "active") return false;
        if (state.filters.status === "archived" && status !== "archived") return false;
        if (state.filters.productType && product.product_type !== state.filters.productType) return false;
        if (search && !productSearchText(product).includes(search)) return false;
        return true;
      });
    },

    shownCount() {
      return this.filteredProducts.length;
    },
  },

  actions: {
    reset() {
      this.products = [];
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

    async load() {
      this.loading = true;
      this.error = "";
      try {
        const body = await apiRequest("/products");
        this.products = Array.isArray(body.products) ? body.products : [];
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
  const isPhysical = productType === "physical";
  const product = {
    schema_version: "2026-05-29",
    document_type: "product",
    tenant_id: getTenantId(),
    product_id: productId,
    stripe_product_id: form.stripe_product_id || null,
    stripe_mode: form.stripe_mode || getApiEnvironment(),
    canonical: !isLeadGen && form.canonical === "true",
    status: form.status === "archived" ? "archived" : "active",
    name: String(form.name || "").trim(),
    description: String(form.description || "").trim(),
    images: isLeadGen ? [] : images,
    product_intent: isLeadGen ? "lead_gen" : "transaction",
    product_type: productType,
    product_category: form.product_category,
    // Structured data only (schema.org sku / itemCondition). sku is omitted when blank so the renderer
    // falls back to product_id; condition is always stated, never inferred.
    ...(form.sku ? { sku: form.sku } : {}),
    condition: form.condition || "new",
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

function leadCaptureShape(action = {}) {
  const base = {
    action: action.action || "capture_email",
    title: action.title || action.label || "Capture email",
    description: action.description || "Collect lead information.",
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
  } else if (base.action === "open_form") {
    base.target = { type: "form", form_id: action.target || "" };
  } else if (base.action === "social_redirect") {
    base.target = { type: "social", value: action.target || "", platform: action.platform || "other", open: "new_tab" };
  }
  return base;
}
