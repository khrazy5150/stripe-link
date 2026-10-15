<template>
  <section class="digital-asset-field">
    <div class="field-heading"><span>Download File</span></div>
    <div v-if="form.digital_asset && form.digital_asset.filename" class="digital-asset-current">
      <span class="font-mono">📎 {{ form.digital_asset.filename }}</span>
      <button type="button" class="secondary-action" @click="form.digital_asset = null">Remove</button>
    </div>
    <label v-else class="digital-asset-picker">
      <input type="file" :disabled="uploading" @change="onFileChange" />
      <span>{{ uploading ? "Uploading…" : "Choose a file to deliver after purchase" }}</span>
    </label>
    <span class="field-note">Buyers receive a secure, purchase-verified download link in their receipt email.</span>
  </section>
</template>

<script setup>
/**
 * The file a digital product delivers after purchase.
 *
 * One component so the create WIZARD and the edit form offer it in the same breath. They did not: the file
 * could only be attached by saving the product and then reopening it, which is a step nobody is told about
 * and the reason a just-created download product delivers nothing (reported 2026-10-14).
 *
 * The upload happens IMMEDIATELY, before the product is saved -- that is why `ensureProductId` exists. The
 * object is written under the product's id, so the id has to be settled first; `buildProductDocument` then
 * keeps whatever id the form is carrying, and the two halves meet.
 */
import { ref } from "vue";
import { ensureProductId, useProductsStore } from "../../stores/products";

const props = defineProps({
  form: { type: Object, required: true },
});
// `uploading` is the parent's business too: a wizard step advanced mid-upload, or a save fired mid-upload,
// discards the file the tenant just chose without saying so.
const emit = defineEmits(["error", "update:uploading"]);

const store = useProductsStore();
const uploading = ref(false);

async function onFileChange(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  setUploading(true);
  emit("error", "");
  try {
    props.form.digital_asset = await store.uploadDigitalAsset(ensureProductId(props.form), file);
  } catch (error) {
    emit("error", `Upload failed: ${error.message}`);
  } finally {
    setUploading(false);
    event.target.value = "";
  }
}

function setUploading(value) {
  uploading.value = value;
  emit("update:uploading", value);
}
</script>
