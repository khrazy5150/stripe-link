// Product-category helpers, mirroring src/stripe_link/domain/categories.py so the key a product stores here
// matches what the backend computes. See plans/PRODUCT_CATEGORY_AUTOCOMPLETE.md.
// Explicit .js: Vite resolves extensionless, raw node (which runs the parity tests) does not.
import { apiRequest } from "../api/client.js";

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

// How many suggestions to pull when caching a whole scope. The endpoint defaults to 20 — a typeahead
// page — and there are already 30 categories, so caching the default and filtering locally would be fast
// and silently WRONG. Filtering client-side is only correct over a complete set.
export const SCOPE_FETCH_LIMIT = 500;

// Autocomplete search: curated + promoted + the tenant's own, scoped to product type. Returns
// [{ key, label, source }]. Errors resolve to [] so the field degrades to a plain free-text input.
export async function searchCategories(query, productType, limit = 0) {
  try {
    const params = { q: query || "", product_type: productType || "" };
    if (limit) params.limit = String(limit);
    const body = await apiRequest("/product-categories", { params });
    return Array.isArray(body.categories) ? body.categories : [];
  } catch {
    return [];
  }
}

// Every suggestion for a product type, for the client-side cache. Empty query = the whole scoped set.
export function fetchCategoriesForScope(productType) {
  return searchCategories("", productType, SCOPE_FETCH_LIMIT);
}

// JS MIRROR of search_suggestions' matching (domain/categories.py): a normalized substring against the
// KEY or the normalized LABEL, so "supp" finds "Dietary Supplement". The server returns results already
// ordered (curated first, then alphabetical) and filtering preserves that order, so there is nothing to
// re-sort. Product-type scoping is applied server-side when the scope is fetched.
export function filterCategories(items, query) {
  const needle = normalizeCategory(query);
  if (!needle) return items;
  return (items || []).filter((item) => {
    const key = normalizeCategory(item?.key || "");
    const label = normalizeCategory(item?.label || "");
    return key.includes(needle) || label.includes(needle);
  });
}
