// Product-category helpers, mirroring src/stripe_link/domain/categories.py so the key a product stores here
// matches what the backend computes. See plans/PRODUCT_CATEGORY_AUTOCOMPLETE.md.
import { apiRequest } from "../api/client";

// Canonical key for a label: lowercased, accent-folded, non-alphanumerics -> single underscore.
// MUST match normalize_category() in Python, or a category picked here won't match one recorded there.
export function normalizeCategory(text) {
  return String(text || "")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

// Display label for a key when we don't have the server's label (e.g. a legacy product's stored key).
export function humanizeCategory(key) {
  return String(key || "")
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

// Autocomplete search: curated + promoted + the tenant's own, scoped to product type. Returns
// [{ key, label, source }]. Errors resolve to [] so the field degrades to a plain free-text input.
export async function searchCategories(query, productType) {
  try {
    const body = await apiRequest("/product-categories", {
      params: { q: query || "", product_type: productType || "" },
    });
    return Array.isArray(body.categories) ? body.categories : [];
  } catch {
    return [];
  }
}
