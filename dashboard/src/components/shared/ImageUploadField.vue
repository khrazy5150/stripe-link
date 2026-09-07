<script setup>
/**
 * One image control: preview, upload button, and the ratio-locked cropper behind it.
 *
 * It owns its OWN file input. The builder's inputs were kept in a map keyed by `element.id`, along with the
 * uploading and error flags, which is correct only while no element has two images -- the second input
 * overwrites the first's ref, the spinner appears on both slots, and an error on one shows on both. Owning
 * the input here makes that collision structurally impossible rather than fixed once.
 *
 * Uploading is DELEGATED to the caller. The parent records image dimensions and refreshes the preview as
 * side effects of a successful upload, and those belong with the document, not in a presentation component.
 */
import { ref } from "vue";
import ImageCropper from "./ImageCropper.vue";

const props = defineProps({
  modelValue: { type: String, default: "" },
  crop: { type: Object, default: null },
  // width / height the consuming surface needs. The cropper locks to it, so the output is the right shape
  // by construction rather than by asking the tenant to eyeball it.
  ratio: { type: Number, default: 1 },
  label: { type: String, default: "Upload image" },
  alt: { type: String, default: "Image preview" },
  uploader: { type: Function, required: true },
});
const emit = defineEmits(["update:modelValue", "update:crop"]);

const input = ref(null);
const uploading = ref(false);
const error = ref("");
const cropping = ref(false);

function choose() {
  input.value?.click();
}

async function picked(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  error.value = "";
  uploading.value = true;
  try {
    const url = await props.uploader(file);
    emit("update:modelValue", url);
    // A fresh image invalidates any previous framing.
    emit("update:crop", null);
    cropping.value = true;
  } catch (err) {
    error.value = err?.message || "Image upload failed.";
  } finally {
    uploading.value = false;
  }
}

function applyCrop(rect) {
  emit("update:crop", rect);
  cropping.value = false;
}

// The stored rect describes which part of the source survives. Reproduce it in the preview by scaling the
// image so the crop fills the box and offsetting it -- object-position alone cannot express a zoom.
function previewStyle() {
  const c = props.crop;
  if (!c || !(c.w > 0) || !(c.h > 0)) return { width: "100%", height: "100%", objectFit: "cover" };
  return {
    position: "absolute",
    width: `${100 / c.w}%`,
    height: `${100 / c.h}%`,
    left: `${(-c.x / c.w) * 100}%`,
    top: `${(-c.y / c.h) * 100}%`,
    maxWidth: "none",
  };
}
</script>

<template>
  <div class="image-upload-field">
    <div v-if="modelValue" class="image-upload-preview" :style="{ aspectRatio: String(ratio) }">
      <img :src="modelValue" :alt="alt" :style="previewStyle()" />
    </div>

    <input ref="input" type="file" accept="image/*" hidden @change="picked" />

    <div class="image-upload-actions">
      <button type="button" class="secondary-action compact" :disabled="uploading" @click.prevent="choose">
        {{ uploading ? "Uploading..." : label }}
      </button>
      <button
        v-if="modelValue"
        type="button"
        class="secondary-action compact"
        :disabled="uploading"
        @click.prevent="cropping = true"
      >
        Crop
      </button>
    </div>

    <p v-if="error" class="field-error">{{ error }}</p>

    <ImageCropper
      v-if="cropping && modelValue"
      :src="modelValue"
      :ratio="ratio"
      :crop="crop"
      @apply="applyCrop"
      @cancel="cropping = false"
    />
  </div>
</template>

<style scoped>
.image-upload-field { display: flex; flex-direction: column; gap: 0.5rem; }
.image-upload-preview {
  position: relative; overflow: hidden;
  width: 120px; border-radius: 8px; background: #f1f5f9;
}
.image-upload-preview img { display: block; }
.image-upload-actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
</style>
