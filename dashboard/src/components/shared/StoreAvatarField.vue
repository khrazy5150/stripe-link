<!--
  The store avatar: upload, crop to a circle, save.

  ONE implementation, used by Preferences and by the last step of onboarding. Preferences had its own
  bare file input and the advice "A square image works best; it is shown as a circle" — which is the
  software asking the tenant to do the cropping in their head, and then silently centre-cropping
  whatever they gave it. The cropper existed the whole time and says so in its own docstring: "a
  circular avatar is not negotiable". It was simply never wired to this surface.

  BAKED, not CSS-cropped. The avatar reaches places no stylesheet can follow — the page ribbon, and
  eventually `og:image` — so the crop has to be in the file, not in a rule.
-->
<template>
  <div class="store-avatar-field">
    <ImageUploadField
      :model-value="modelValue"
      :ratios="1"
      :uploader="uploader"
      :label="modelValue ? 'Replace photo' : 'Upload a photo'"
      alt="Store avatar preview"
      bake
      :bake-width="512"
      @update:model-value="(url) => emit('update:modelValue', url)"
    />
    <button
      v-if="modelValue"
      type="button"
      class="secondary-action compact"
      :disabled="busy"
      @click="emit('update:modelValue', '')"
    >
      Remove
    </button>
    <small v-if="error" class="builder-upload-error">{{ error }}</small>
  </div>
</template>

<script setup>
import ImageUploadField from "./ImageUploadField.vue";

defineProps({
  modelValue: { type: String, default: "" },
  // Injected rather than imported, so onboarding and Preferences can differ later without this caring.
  uploader: { type: Function, required: true },
  busy: { type: Boolean, default: false },
  error: { type: String, default: "" },
});

const emit = defineEmits(["update:modelValue"]);
</script>

<style scoped>
.store-avatar-field {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  align-items: flex-start;
}
</style>
