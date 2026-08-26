<template>
  <input ref="el" type="tel" autocomplete="tel" :placeholder="placeholder" />
</template>

<script setup>
// Reusable international phone field. Wraps intl-tel-input (country flag + dial-code picker,
// per-country auto-format/placeholder) and exposes a plain E.164 string via v-model, so it's a
// drop-in for the existing E.164 text inputs and plugs into utils/phone.js validation.
// Modernized migration of stripe-cart's format-phone.js (same library, no global DOM lookups).
// The heavy validation `utils` (libphonenumber, ~220 KB) is lazy-loaded as its own chunk on first use.
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from "vue";
import intlTelInput from "intl-tel-input";
import "intl-tel-input/styles";

const props = defineProps({
  modelValue: { type: String, default: "" },
  // Default country while the field is empty (e.g. an address's country); falls back to US.
  initialCountry: { type: String, default: "us" },
  placeholder: { type: String, default: "" },
});
const emit = defineEmits(["update:modelValue"]);

const el = ref(null);
let iti = null;
let syncing = false; // guard so a model->widget sync doesn't echo back out

const normCountry = (c) => String(c || "").trim().toLowerCase() || "us";

// E.164 for whatever is currently typed ("" when blank). getNumber() needs utils to format.
function currentE164() {
  if (!iti || !el.value) return "";
  return el.value.value.trim() ? (iti.getNumber() || "") : "";
}

function onInput() {
  if (syncing) return;
  emit("update:modelValue", currentE164());
}

function setFromModel(val) {
  syncing = true;
  iti.setNumber(val || "");
  nextTick(() => { syncing = false; });
}

onMounted(() => {
  iti = intlTelInput(el.value, {
    initialCountry: normCountry(props.initialCountry),
    separateDialCode: true,
    nationalMode: true,
    autoPlaceholder: "aggressive",
    placeholderNumberType: "MOBILE",
    loadUtils: () => import("intl-tel-input/utils"),
    // Attach the country dropdown to <body> so it escapes the card's overflow/stacking context
    // (otherwise it's clipped by the section below). The library positions it via getBoundingClientRect.
    dropdownParent: document.body,
  });
  el.value.addEventListener("input", onInput);
  el.value.addEventListener("countrychange", onInput);
  // Apply an existing value + reconcile the emitted E.164 once utils (formatting) have loaded.
  iti.promise
    .then(() => {
      if (props.modelValue) setFromModel(props.modelValue);
      const e164 = currentE164();
      if (e164 !== (props.modelValue || "")) emit("update:modelValue", e164);
    })
    .catch(() => { if (props.modelValue) setFromModel(props.modelValue); });
});

// Follow the default country when the parent changes it (e.g. the address country) — but only while
// the field is empty, so a typed number's own country isn't overridden.
watch(
  () => props.initialCountry,
  (c) => {
    if (!iti || !el.value) return;
    const iso = normCountry(c);
    if (!el.value.value.trim() && iti.getSelectedCountry()?.iso2 !== iso) {
      iti.setSelectedCountry(iso);
    }
  }
);

// Keep the widget in sync when the model changes elsewhere (e.g. loaded from the server),
// skipping when it already matches what's typed (our own emit) to avoid a feedback loop.
watch(
  () => props.modelValue,
  (val) => {
    if (!iti || (val || "") === currentE164()) return;
    setFromModel(val);
  }
);

onBeforeUnmount(() => {
  if (el.value) {
    el.value.removeEventListener("input", onInput);
    el.value.removeEventListener("countrychange", onInput);
  }
  if (iti) { iti.destroy(); iti = null; }
});
</script>

<!-- Not scoped: the .iti wrapper is injected outside this component's template by the library. -->
<style>
/* Pin to the app's base input font-size (styles.css `input {font-size:1.4rem}`) so the separate dial
   code lines up with the typed number. Some surrounding labels (e.g. .offer-field) set a smaller size
   that the dial code would otherwise inherit, throwing off the vertical alignment. */
/* Match the input's metrics (app base input = 1.4rem, line-height normal) on the whole widget so the
   separate dial code renders on the same baseline as the typed number. */
.iti { width: 100%; display: block; font-size: 1.4rem; line-height: normal; }
/* display:block removes the inline-block descender gap below the input — otherwise the .iti wrapper is
   taller than the input and the absolutely-positioned dial code centers lower than the typed number. */
.iti input[type="tel"] { width: 100%; display: block; }
/* Baseline calibration: the dial code is <div> text while the number is <input> text, and Chrome renders
   an input's text box ~1px higher than a div's. Nudge the flag + dial code up 1px so they sit on the
   number's baseline. (Metric-matching alone can't close this — it's inherent to div-vs-input rendering.) */
.iti__selected-country { position: relative; top: -3px; }
</style>
