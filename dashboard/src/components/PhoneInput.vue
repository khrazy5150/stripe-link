<template>
  <input ref="el" type="tel" autocomplete="tel" :placeholder="placeholder" />
</template>

<script setup>
// Reusable international phone field. Wraps intl-tel-input (country flag + dial-code picker,
// per-country auto-formatting/placeholders) and exposes a plain E.164 string via v-model, so it's
// a drop-in for the existing E.164 text inputs and plugs straight into utils/phone.js validation.
// Modernized migration of stripe-cart's dist/**/format-phone.js (same library, no global DOM lookups).
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from "vue";
import intlTelInput from "intl-tel-input/intlTelInputWithUtils";
import "intl-tel-input/styles";

const props = defineProps({
  modelValue: { type: String, default: "" },
  initialCountry: { type: String, default: "us" },
  placeholder: { type: String, default: "" },
});
const emit = defineEmits(["update:modelValue"]);

const el = ref(null);
let iti = null;
let syncing = false; // guard so model->widget sync doesn't echo back out

// E.164 for whatever is currently typed ("" when the field is blank). getNumber() uses the bundled
// utils to build the international number from the selected country + national digits.
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
    initialCountry: props.initialCountry,
    separateDialCode: true,
    nationalMode: true,
    autoPlaceholder: "aggressive",
    placeholderNumberType: "MOBILE",
  });
  if (props.modelValue) setFromModel(props.modelValue);
  el.value.addEventListener("input", onInput);
  el.value.addEventListener("countrychange", onInput);
});

// Keep the widget in sync when the model is changed elsewhere (e.g. loaded from the server),
// but skip when the value already matches what's typed (our own emit) to avoid a feedback loop.
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
.iti { width: 100%; display: block; }
.iti input[type="tel"] { width: 100%; }
</style>
