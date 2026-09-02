// The machinery every list screen repeats: load a slim index, filter it locally, fetch the full document
// only when something is opened for editing.
//
// Four screens (Products, Services, Offers, Landing Pages) had four implementations of the same shape.
// The FIELD LISTS differ legitimately — a service has no tags, an offer searches through to its items —
// but the surrounding behaviour does not, and that is where the next change lands inconsistently. This
// session has already produced eight instances of "two things that must agree, with nothing forcing them
// to"; virtualized rendering and pagination adoption are both still to come, and without one home each
// would be built four times.
//
// Deliberately plain functions, NOT a Vue component and NOT a store. Products and Services need Pinia
// store semantics (the Offers screen reads productStore), while Offers and Landing Pages hold local
// state; plain functions compose into both without forcing either to change shape.

import { apiRequest } from "../api/client.js";

/**
 * The slim list projection for a resource: GET /{resource}?view=index.
 *
 * Loading the WHOLE index is the point, not an optimisation: client-side filtering is only correct over a
 * complete set. Paginating this and filtering locally would leave search covering just the fetched pages
 * — the failure this codebase keeps producing. Pagination belongs to RENDERING (windowing the DOM) and,
 * past the response cliff, to a server-side search that replaces local filtering entirely.
 */
export async function loadIndex(resource, { key, params = {} } = {}) {
  const body = await apiRequest(`/${resource}`, { params: { view: "index", ...params } });
  const rows = body?.[key || resource];
  return Array.isArray(rows) ? rows : [];
}

/**
 * The full document behind an index row, for an editor.
 *
 * Falls back to the row on failure so a modal still opens rather than blocking on a network error — a
 * partly-populated form beats a dead button.
 */
export async function fetchFullDocument(resource, id, { key } = {}) {
  if (!id) return null;
  try {
    const body = await apiRequest(`/${resource}/${encodeURIComponent(id)}`);
    return body?.[key || resource.replace(/s$/, "")] || null;
  } catch {
    return null;
  }
}

/** Lowercased haystack for a row: the named fields, plus any extra text the caller derives. */
export function searchText(row, fields, extra = "") {
  const parts = [];
  for (const field of fields || []) {
    const value = typeof field === "function" ? field(row) : row?.[field];
    if (Array.isArray(value)) parts.push(...value);
    else if (value !== undefined && value !== null && value !== "") parts.push(value);
  }
  if (extra) parts.push(extra);
  return parts.join(" ").toLowerCase();
}

export function matchesSearch(row, fields, term, extra = "") {
  const needle = String(term || "").trim().toLowerCase();
  if (!needle) return true;
  return searchText(row, fields, extra).includes(needle);
}

/**
 * Status + search in one pass.
 *
 * `statusOf(row)` returns the row's lifecycle value; `status` is what the filter is set to. An empty or
 * "all" status filters nothing, so a caller with no status concept simply omits both.
 */
export function filterRows(
  rows,
  { term = "", fields = [], statusOf = null, status = "", extraText = null, where = null } = {},
) {
  const wanted = String(status || "").trim();
  return (rows || []).filter((row) => {
    if (wanted && wanted !== "all" && statusOf && statusOf(row) !== wanted) return false;
    // `where` is the screen's own extra predicate — a product TYPE, a Landing Page's owning Site. Those
    // are genuinely per-entity, so they stay a callback rather than becoming more options here.
    if (where && !where(row)) return false;
    return matchesSearch(row, fields, term, extraText ? extraText(row) : "");
  });
}

/** "3 of 12 services shown." — the count line every list screen writes by hand. */
export function shownMessage(shown, total, noun, { empty = "" } = {}) {
  if (!total) return empty || `No ${noun}s have been saved yet.`;
  return `${shown} of ${total} ${noun}${total === 1 ? "" : "s"} shown.`;
}
