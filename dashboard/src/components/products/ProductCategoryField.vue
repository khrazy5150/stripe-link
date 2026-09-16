<template>
  <!-- Autocomplete over the shared, growing taxonomy (plans/PRODUCT_CATEGORY_AUTOCOMPLETE.md).
       Suggestions are scoped to the product type; typing something new is allowed and becomes the tenant's
       category immediately (only shared with others once enough tenants use it). -->
  <label class="category-autocomplete">
    Product Category <span v-if="required" class="required">*</span>
    <input
      v-model="query"
      type="text"
      placeholder="Search or type a category"
      autocomplete="off"
      @focus="onFocus"
      @input="onInput"
      @blur="onBlur"
      @keydown.enter.prevent="commitFreeText"
    />
    <ul v-if="menuOpen && suggestions.length" class="category-menu">
      <li
        v-for="suggestion in suggestions"
        :key="suggestion.key"
        :class="{ 'is-selected': suggestion.key === modelValue }"
        @mousedown.prevent="pick(suggestion)"
      >
        <span>{{ suggestion.label }}</span>
        <span v-if="suggestion.source === 'yours'" class="category-tag">your category</span>
      </li>
    </ul>
    <span class="field-note">Pick a suggestion or type your own. New categories become suggestions for others once several sellers use them.</span>
  </label>
</template>

<script setup>
/**
 * The category picker, as one field both the wizard and the full edit form can render.
 *
 * It owns the query string and the menu, because those are presentation: the only thing the parent cares
 * about is the normalized KEY, which is what `modelValue` carries. Extracted 2026-09-15 when the create
 * wizard grew a Details step — the alternative was a second copy of the autocomplete, and two copies of a
 * field that talks to a shared taxonomy is how the two quietly stop agreeing about what a category is.
 */
import { ref, watch } from "vue";
import { fetchCategoriesForScope, filterCategories, humanizeCategory, normalizeCategory } from "../../utils/categories";
import { useCachedSuggestions } from "../../composables/useCachedSuggestions";

const props = defineProps({
  modelValue: { type: String, default: "" },
  productType: { type: String, default: "physical" },
  required: { type: Boolean, default: true },
});
const emit = defineEmits(["update:modelValue"]);

// The label the tenant sees and types; `modelValue` is the key that gets stored.
const query = ref("");
const menuOpen = ref(false);

// Fetch once per product_type and filter locally, instead of calling the API on every focus AND every
// 180ms typing pause — each of which was a Lambda invoke plus a full scan of contributed categories.
// plans/CACHED_SUGGESTION_FIELD.md. The whole scoped set is fetched (the endpoint's default of 20 would
// truncate 30 categories, making local filtering fast and wrong).
const { suggestions, open: openSuggestions, search } = useCachedSuggestions({
  fetchAll: (productType) => fetchCategoriesForScope(productType),
  filter: filterCategories,
  scope: () => props.productType,
});

// Show the stored key's label whenever the parent changes it from outside — opening the modal on an existing
// product, or an intent that files the product for them. The proper server label arrives when the menu first
// opens; humanize is a fine placeholder ("dietary_supplement" -> "Dietary Supplement").
watch(() => props.modelValue, (key) => {
  if (normalizeCategory(query.value) !== key) query.value = key ? humanizeCategory(key) : "";
}, { immediate: true });

function onFocus() {
  menuOpen.value = true;
  // Refreshes on OPEN: the only moment staleness is observable, since a category the tenant typed a moment
  // ago must reappear. Cached results render immediately while that refresh is in flight.
  openSuggestions();
  search(query.value);
}

function onInput() {
  menuOpen.value = true;
  search(query.value);  // local; no request to debounce
}

function pick(suggestion) {
  query.value = suggestion.label;
  menuOpen.value = false;
  emit("update:modelValue", suggestion.key);
}

// Typed text with no pick becomes the tenant's own category: store the normalized key so it dedups with
// existing entries (and matches what the server records). An exact-label match to a suggestion picks it.
function commitFreeText() {
  const typed = query.value.trim();
  menuOpen.value = false;
  if (!typed) {
    emit("update:modelValue", "");
    return;
  }
  const exact = suggestions.value.find((item) => item.label.toLowerCase() === typed.toLowerCase());
  if (exact) {
    pick(exact);
    return;
  }
  emit("update:modelValue", normalizeCategory(typed));
}

function onBlur() {
  // Delay so a mousedown on a suggestion (which fires before blur) can win.
  setTimeout(() => { if (menuOpen.value || query.value) commitFreeText(); }, 150);
}
</script>
