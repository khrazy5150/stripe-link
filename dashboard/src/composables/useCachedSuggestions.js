// Fetch once per scope, filter locally, refresh when the field reopens.
//
// The product category autocomplete called the API on every focus AND every 180ms typing pause — each
// one a Lambda invoke plus a full DynamoDB scan of contributed categories. plans/PRODUCT_CATEGORY_
// AUTOCOMPLETE.md asked for this ("the client MAY fetch it once and filter locally"), the word "may"
// enforced nothing, and it was never built.
//
// Three rules make it correct rather than merely fast:
//
//  1. The cache is keyed by SCOPE. For categories that is product_type: switching type must not show the
//     previous type's list.
//  2. Refresh happens on OPEN, never on keystroke. Opening the field is the only moment staleness is
//     observable — a category the tenant typed a minute ago has to reappear — and it costs one request per
//     field-open instead of one per pause in typing.
//  3. Cached results render IMMEDIATELY while that refresh is in flight (stale-while-revalidate), so the
//     menu never blanks. A response for a scope the user has since left is discarded.
//
// The caller must fetch the WHOLE scoped set, not a typeahead page. Filtering locally over a truncated
// list is fast and silently wrong — the failure this codebase keeps finding.

import { ref } from "vue";

export function useCachedSuggestions({ fetchAll, filter, scope }) {
  const suggestions = ref([]);
  const loading = ref(false);

  let cacheKey = null;
  let cached = [];
  let query = "";
  let requestId = 0;

  const currentScope = () => String((scope ? scope() : "") ?? "");

  function apply() {
    suggestions.value = filter(cached, query);
  }

  /** Filter what is already held. No network — this is what runs on every keystroke. */
  function search(nextQuery) {
    query = String(nextQuery ?? "");
    apply();
  }

  /** Call on focus. Shows the cache at once, then refreshes it. */
  async function open() {
    const key = currentScope();
    if (key !== cacheKey) {
      // A different scope's list is not "stale", it is wrong — drop it rather than show it.
      cacheKey = key;
      cached = [];
    }
    apply();

    const id = ++requestId;
    loading.value = true;
    try {
      const items = await fetchAll(key);
      // Ignore a response the user has moved on from: a later open, or a scope change.
      if (id !== requestId || key !== cacheKey) return;
      cached = Array.isArray(items) ? items : [];
      apply();
    } finally {
      if (id === requestId) loading.value = false;
    }
  }

  /** Drop the cache — for when something is known to have changed the underlying set. */
  function invalidate() {
    cacheKey = null;
    cached = [];
  }

  return { suggestions, loading, open, search, invalidate };
}
