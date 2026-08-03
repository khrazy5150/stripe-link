<template>
  <label class="offer-field store-address-field">
    <span>{{ label }}</span>
    <div class="subdomain-input">
      <input
        :value="modelValue"
        type="text"
        :placeholder="placeholder"
        autocapitalize="off"
        autocorrect="off"
        spellcheck="false"
        @input="onInput"
      />
      <span class="subdomain-suffix">.{{ hostingDomain }}</span>
    </div>
    <small :class="availabilityClass">{{ availabilityText }}</small>
    <div v-if="check.state.suggestions.length" class="subdomain-suggestions">
      <span class="field-note">Try:</span>
      <button v-for="s in check.state.suggestions" :key="s" type="button" class="subdomain-chip" @click="pick(s)">{{ s }}</button>
    </div>
  </label>
</template>

<script setup>
// Shared store-address (subdomain) field: suggests an address from the Site name (slugified), keeps it editable,
// and checks availability live via the debounced useSubdomainCheck. Used by every create/edit-Site form so the
// behaviour can't drift. See plans/SITE_OBJECT.md.
import { computed, onMounted, ref, watch } from "vue";
import { useSubdomainCheck } from "../composables/useSubdomainCheck";

const props = defineProps({
  modelValue: { type: String, default: "" },
  name: { type: String, default: "" },               // Site name to auto-fill / slugify from
  hostingDomain: { type: String, default: "jbay.uk" },
  siteId: { type: String, default: "" },             // set in edit mode to exclude the current Site from the check
  label: { type: String, default: "Store address" },
  placeholder: { type: String, default: "my-shop" },
  autofill: { type: Boolean, default: true },        // false in edit mode (an existing Site keeps its address)
  // Output halves of v-model:available / v-model:normalized (declared so they don't fall through as attributes).
  available: { type: Boolean, default: false },
  normalized: { type: String, default: "" },
});
const emit = defineEmits(["update:modelValue", "update:available", "update:normalized"]);

const check = useSubdomainCheck();
const edited = ref(false);

// Mirrors the backend normalize_subdomain (lowercase, non-alphanumeric -> single dash, trimmed); the backend
// re-normalizes on check/save, so this only needs to be close enough to suggest.
function slugify(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/-{2,}/g, "-").replace(/^-+|-+$/g, "").slice(0, 63);
}

function fillFrom(name) {
  const slug = slugify(name);
  emit("update:modelValue", slug);
  if (slug) check.check(slug, props.siteId);
  else check.clear();
}

// As the tenant types the Site name, suggest an address — until they edit it themselves. Clearing the name resets.
watch(() => props.name, (name) => {
  if (!props.autofill || edited.value) return;
  if (!name) { edited.value = false; emit("update:modelValue", ""); check.clear(); return; }
  fillFrom(name);
});

// Fill once on mount when the parent opens the form with a Site name already set (e.g. a pre-seeded wizard step).
onMounted(() => {
  if (props.autofill && props.name && !props.modelValue) fillFrom(props.name);
  else if (props.modelValue) check.check(props.modelValue, props.siteId);
});

function onInput(event) {
  const value = String(event.target.value || "").trim();
  edited.value = value !== "";  // typing takes over; clearing hands auto-fill back to the name
  emit("update:modelValue", value);
  check.check(value, props.siteId);
}

function pick(value) {
  edited.value = true;
  emit("update:modelValue", value);
  check.check(value, props.siteId);
}

// Surface availability + the canonical (normalized) value so the parent can gate + submit.
watch(() => check.state.available, (v) => emit("update:available", v));
watch(() => check.state.normalized, (v) => emit("update:normalized", v));

const availabilityText = computed(() => {
  const s = check.state;
  if (!s.input) return "";
  if (s.checking) return "Checking availability…";
  if (!s.checked) return "";
  return s.available ? `✓ ${s.hostname} is available` : `✗ ${s.reason}`;
});
const availabilityClass = computed(() => {
  const s = check.state;
  if (s.checking || !s.checked || !s.input) return "field-note";
  return s.available ? "subdomain-ok" : "subdomain-bad";
});
</script>

<style scoped>
.subdomain-input { display: flex; align-items: stretch; border: 1px solid var(--line-strong); border-radius: 8px; overflow: hidden; }
.subdomain-input input { flex: 1; min-width: 0; border: none; background: transparent; color: var(--text); padding: 0.6rem 0.75rem; font: inherit; outline: none; }
.subdomain-suffix { display: flex; align-items: center; padding: 0 0.75rem; background: var(--bg); color: var(--muted); font-family: ui-monospace, monospace; white-space: nowrap; }
.subdomain-suggestions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem; margin-top: 0.35rem; }
.subdomain-chip { border: 1px solid var(--line-strong); background: var(--bg); color: var(--text); border-radius: 999px; padding: 0.15rem 0.7rem; font-family: ui-monospace, monospace; font-size: 0.85em; cursor: pointer; }
.subdomain-ok { color: #22c55e; font-weight: 600; }
.subdomain-bad { color: #f87171; font-weight: 600; }
</style>
