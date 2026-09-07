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
import { computed, ref } from "vue";
import ImageCropper from "./ImageCropper.vue";

const props = defineProps({
  modelValue: { type: String, default: "" },
  crop: { type: Object, default: null },
  // What shape this surface allows: a number locks it, an array offers choices, null accepts any shape.
  // Passed straight through from image_ratios.json -- see ImageCropper for the three modes.
  ratios: { type: [Number, Array, String], default: null },
  label: { type: String, default: "Upload image" },
  alt: { type: String, default: "Image preview" },
  uploader: { type: Function, required: true },
  // Some surfaces let a tenant paste a URL instead of uploading. Kept because removing it would be a
  // silent regression for anyone hosting their images elsewhere.
  allowUrl: { type: Boolean, default: false },
  urlPlaceholder: { type: String, default: "or paste an image URL" },
});
const emit = defineEmits(["update:modelValue", "update:crop"]);

// The thumbnail shows the shape the crop was actually made at; before any crop, the surface's first
// allowed shape is the honest preview.
const previewRatio = computed(() => {
  if (props.crop?.ar > 0) return props.crop.ar;
  const first = Array.isArray(props.ratios) ? props.ratios[0] : props.ratios;
  return typeof first === "number" && first > 0 ? first : 1;
});

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

// A pasted URL is a different image, so any crop framed against the old one no longer means anything.
function onUrlTyped(event) {
  const next = event.target.value.trim();
  if (next === props.modelValue) return;
  emit("update:modelValue", next);
  emit("update:crop", null);
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
    <div v-if="modelValue" class="image-upload-preview" :style="{ aspectRatio: String(previewRatio) }">
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

    <input
      v-if="allowUrl"
      :value="modelValue"
      type="url"
      :placeholder="urlPlaceholder"
      @input="onUrlTyped"
    />

    <p v-if="error" class="field-error">{{ error }}</p>

    <ImageCropper
      v-if="cropping && modelValue"
      :src="modelValue"
      :ratios="ratios"
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
