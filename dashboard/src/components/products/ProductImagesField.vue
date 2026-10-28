<template>
  <section class="product-images-field">
    <h3 v-if="heading">{{ heading }}</h3>
    <div class="info-toast">Image Limit: Maximum of {{ maxImages }} images allowed per product.</div>
    <input ref="fileInput" type="file" accept="image/*" multiple hidden @change="onPicked" />
    <div
      class="upload-dropzone product-upload-dropzone"
      :class="{ dragging: dragActive }"
      role="button"
      tabindex="0"
      @click="fileInput?.click()"
      @keydown.enter.prevent="fileInput?.click()"
      @keydown.space.prevent="fileInput?.click()"
      @dragover.prevent="dragActive = true"
      @dragleave.prevent="dragActive = false"
      @drop.prevent="onDropped"
    >
      <strong>Click to upload or drag and drop</strong>
      <small>PNG, JPG, WEBP up to 10MB</small>
    </div>
    <!-- Previews AND a crop button, not a count. The first cut of the wizard's image step printed "3 images
         added" and nothing else, so the tenant could neither see what they had uploaded nor frame it — and
         the crop is what decides the shape the page renders (plans/IMAGE_CROPPER.md). -->
    <!-- WHICH image Stripe shows, said where the tenant can act on it. A checkout line sends only the
         price id, so Stripe renders the image on the synced Stripe Product and uses the FIRST one -- the
         hero and the price card never reach it. Without this, the only way to find that out is to buy
         something and look. -->
    <p v-if="uploaded.length > 1" class="field-note">
      Upload as many as you like, then pick the marquee one — press <strong>Make first</strong> (or drag).
      The first image is the one Stripe shows on the checkout page.
    </p>
    <div v-if="uploaded.length" class="product-image-previews">
      <figure
        v-for="(url, index) in uploaded"
        :key="url"
        class="product-image-preview"
        :class="{ 'is-first': index === 0 }"
        draggable="true"
        @dragstart="dragFrom = index"
        @dragover.prevent
        @drop="dropOn(index)"
      >
        <img :src="url" alt="Uploaded product image" />
        <span v-if="index === 0" class="product-image-badge">Shown at checkout</span>
        <figcaption>{{ shortName(url) }}</figcaption>
        <!-- One click, because "which one is the marquee" is a CHOICE, not an ordering task. Dragging
             works too, but picking the cover out of a dozen phone photos should not require aiming. -->
        <button
          v-if="index !== 0"
          type="button"
          class="secondary-action compact"
          @click.prevent="makeFirst(index)"
        >Make first</button>
        <button
          v-if="canCrop(url)"
          type="button"
          class="secondary-action compact"
          :disabled="cropBusy"
          @click.prevent="emit('crop', url)"
        >Crop</button>
      </figure>
    </div>
    <div v-if="status" class="upload-status" :class="statusKind">{{ status }}</div>
    <!-- NOT trimmed on input. The old field carried `v-model.trim`, which ate the newline the moment it was
         typed and fought anyone entering a list. The store splits this on newlines and trims each line at
         save time, so the stored result is identical either way. -->
    <label>Paste image URLs, one per line
      <textarea :value="urls" rows="3" placeholder="https://example.com/image1.jpg"
                @input="emit('update:urls', $event.target.value)"></textarea>
    </label>
  </section>
</template>

<script setup>
/**
 * The product's pictures: a dropzone, what has been uploaded, and a box for URLs the tenant already hosts.
 *
 * PRESENTATION ONLY. Uploading talks to a presigned endpoint, counts remaining slots and records image
 * dimensions — business logic that stays in the parent, which is why files leave here as a plain `files`
 * event and progress comes back in as `status`. Cropping is the same: this knows a crop button belongs on a
 * preview, not how to crop.
 */
import { ref } from "vue";

const props = defineProps({
  uploaded: { type: Array, required: true },
  urls: { type: String, default: "" },
  status: { type: String, default: "" },
  statusKind: { type: String, default: "" },
  cropBusy: { type: Boolean, default: false },
  canCrop: { type: Function, default: () => false },
  shortName: { type: Function, default: (url) => url },
  maxImages: { type: Number, default: 8 },
  heading: { type: String, default: "" },
});
const emit = defineEmits(["files", "crop", "update:urls", "update:uploaded"]);

const fileInput = ref(null);
const dragActive = ref(false);
const dragFrom = ref(null);

// Reordering is the whole point of saying which image Stripe uses: a label naming a slot the tenant
// cannot change would just tell them their image is wrong and leave them there.
function makeFirst(index) {
  if (index <= 0) return;
  const next = [...props.uploaded];
  const [moved] = next.splice(index, 1);
  next.unshift(moved);
  emit("update:uploaded", next);
}

function dropOn(index) {
  const from = dragFrom.value;
  dragFrom.value = null;
  if (from === null || from === index) return;
  const next = [...props.uploaded];
  const [moved] = next.splice(from, 1);
  next.splice(index, 0, moved);
  emit("update:uploaded", next);
}

function onPicked(event) {
  emit("files", Array.from(event.target.files || []));
  event.target.value = "";   // so picking the same file twice still fires a change
}

function onDropped(event) {
  dragActive.value = false;
  emit("files", Array.from(event.dataTransfer?.files || []));
}
</script>
