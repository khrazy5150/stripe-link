<script setup>
/**
 * Crop / zoom / reposition, locked to the aspect ratio the CALLER declares.
 *
 * The ratio lock is the whole point. A free-form crop box solves nothing: the hero still receives a square
 * photo from a tenant who cropped square. Because the frame is fixed and the image moves behind it, the
 * output is the requested shape by construction -- which is also what makes a Before/After pair align,
 * since both sides are cropped to one ratio rather than to two well-meant guesses.
 *
 * The value is a NORMALIZED rect ({x, y, w, h} as fractions of the source, 0..1), never pixels. The image
 * service emits thumb/small/medium/large/full and mints more on demand, so a pixel rect is correct against
 * exactly one rendition and silently wrong against every other. Fractions survive all of them, and survive
 * the source being reprocessed. See plans/IMAGE_CROPPER.md.
 */
import { computed, ref, watch } from "vue";

const props = defineProps({
  src: { type: String, required: true },
  // width / height. 1 = square, 16/9 = wide.
  ratio: { type: Number, default: 1 },
  // Reopen with the crop already applied, so a crop is an editable decision rather than a one-shot.
  crop: { type: Object, default: null },
  title: { type: String, default: "Crop, zoom, or move" },
});
const emit = defineEmits(["apply", "cancel"]);

const FRAME_WIDTH = 420;
const frameHeight = computed(() => Math.round(FRAME_WIDTH / (props.ratio || 1)));

const natural = ref({ width: 0, height: 0 });
const scale = ref(1);
const offset = ref({ x: 0, y: 0 }); // top-left of the scaled image, relative to the frame
const dragging = ref(false);
const loadFailed = ref(false);
let dragStart = null;

// Below this the image cannot cover the frame and gaps appear at the edges, so it is the floor for zoom.
const minScale = computed(() => {
  if (!natural.value.width || !natural.value.height) return 1;
  return Math.max(FRAME_WIDTH / natural.value.width, frameHeight.value / natural.value.height);
});
// Never enlarge past native resolution: upscaling produces a soft image the tenant cannot diagnose. An
// image smaller than the frame is the exception -- it has to be enlarged to cover at all.
const maxScale = computed(() => Math.max(1, minScale.value));

const canZoom = computed(() => maxScale.value - minScale.value > 0.001);

function clampOffset(next, atScale) {
  const w = natural.value.width * atScale;
  const h = natural.value.height * atScale;
  return {
    x: Math.min(0, Math.max(FRAME_WIDTH - w, next.x)),
    y: Math.min(0, Math.max(frameHeight.value - h, next.y)),
  };
}

function centreOn(atScale) {
  offset.value = clampOffset({
    x: (FRAME_WIDTH - natural.value.width * atScale) / 2,
    y: (frameHeight.value - natural.value.height * atScale) / 2,
  }, atScale);
}

function onImageLoad(event) {
  loadFailed.value = false;
  natural.value = { width: event.target.naturalWidth, height: event.target.naturalHeight };
  if (props.crop && props.crop.w > 0 && props.crop.h > 0) {
    // Reopening: recover the transform the stored rect describes.
    const restored = Math.max(minScale.value, FRAME_WIDTH / (props.crop.w * natural.value.width));
    scale.value = Math.min(maxScale.value, restored);
    offset.value = clampOffset({
      x: -props.crop.x * natural.value.width * scale.value,
      y: -props.crop.y * natural.value.height * scale.value,
    }, scale.value);
  } else {
    scale.value = minScale.value;
    centreOn(scale.value);
  }
}

watch(scale, (next, previous) => {
  if (!natural.value.width || next === previous) return;
  // Zoom about the frame's centre, so the subject the tenant framed stays framed.
  const cx = (FRAME_WIDTH / 2 - offset.value.x) / previous;
  const cy = (frameHeight.value / 2 - offset.value.y) / previous;
  offset.value = clampOffset({ x: FRAME_WIDTH / 2 - cx * next, y: frameHeight.value / 2 - cy * next }, next);
});

function startDrag(event) {
  if (!natural.value.width) return;
  dragging.value = true;
  dragStart = { x: event.clientX - offset.value.x, y: event.clientY - offset.value.y };
  event.currentTarget.setPointerCapture?.(event.pointerId);
}
function onDrag(event) {
  if (!dragging.value || !dragStart) return;
  offset.value = clampOffset({ x: event.clientX - dragStart.x, y: event.clientY - dragStart.y }, scale.value);
}
function endDrag(event) {
  dragging.value = false;
  dragStart = null;
  event.currentTarget.releasePointerCapture?.(event.pointerId);
}

// Keyboard panning, because a drag-only cropper is unusable without a pointer.
function nudge(dx, dy) {
  offset.value = clampOffset({ x: offset.value.x + dx, y: offset.value.y + dy }, scale.value);
}

const imageStyle = computed(() => ({
  width: `${natural.value.width * scale.value}px`,
  height: `${natural.value.height * scale.value}px`,
  transform: `translate(${offset.value.x}px, ${offset.value.y}px)`,
}));

function apply() {
  if (!natural.value.width) return;
  const w = natural.value.width * scale.value;
  const h = natural.value.height * scale.value;
  // The frame shows the region starting at -offset; convert back to fractions of the source.
  const rect = {
    x: Math.min(Math.max(-offset.value.x / w, 0), 1),
    y: Math.min(Math.max(-offset.value.y / h, 0), 1),
    w: Math.min(FRAME_WIDTH / w, 1),
    h: Math.min(frameHeight.value / h, 1),
  };
  // Round to the fifth decimal: enough precision for any real image, and it keeps the stored document and
  // the generated cache key stable instead of churning on floating-point noise.
  const round = (n) => Math.round(n * 1e5) / 1e5;
  emit("apply", { x: round(rect.x), y: round(rect.y), w: round(rect.w), h: round(rect.h) });
}
</script>

<template>
  <div class="cropper-backdrop" role="dialog" aria-modal="true" :aria-label="title" @click.self="emit('cancel')">
    <div class="cropper-panel">
      <h3 class="cropper-title">{{ title }}</h3>

      <p v-if="loadFailed" class="field-error">That image could not be loaded.</p>

      <div
        class="cropper-frame"
        :style="{ width: `${FRAME_WIDTH}px`, height: `${frameHeight}px` }"
        tabindex="0"
        role="application"
        aria-label="Drag to reposition. Arrow keys nudge."
        @pointerdown.prevent="startDrag"
        @pointermove="onDrag"
        @pointerup="endDrag"
        @pointercancel="endDrag"
        @keydown.left.prevent="nudge(12, 0)"
        @keydown.right.prevent="nudge(-12, 0)"
        @keydown.up.prevent="nudge(0, 12)"
        @keydown.down.prevent="nudge(0, -12)"
      >
        <img
          :src="src"
          alt=""
          draggable="false"
          :style="imageStyle"
          class="cropper-image"
          @load="onImageLoad"
          @error="loadFailed = true"
        />
      </div>

      <div v-if="canZoom" class="cropper-zoom">
        <button type="button" class="cropper-zoom-step" aria-label="Zoom out"
                @click="scale = Math.max(minScale, scale - (maxScale - minScale) / 10)">−</button>
        <input v-model.number="scale" type="range" :min="minScale" :max="maxScale"
               :step="(maxScale - minScale) / 100" aria-label="Zoom" />
        <button type="button" class="cropper-zoom-step" aria-label="Zoom in"
                @click="scale = Math.min(maxScale, scale + (maxScale - minScale) / 10)">+</button>
      </div>
      <p v-else class="cropper-hint">This image is only large enough for one framing.</p>

      <div class="cropper-actions">
        <button type="button" class="secondary-action" @click="emit('cancel')">Cancel</button>
        <button type="button" class="primary-action" :disabled="!natural.width" @click="apply">Use this photo</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cropper-backdrop {
  position: fixed; inset: 0; z-index: 1200;
  display: flex; align-items: center; justify-content: center;
  background: rgba(15, 23, 42, 0.55); padding: 1rem;
}
.cropper-panel {
  background: #fff; border-radius: 14px; padding: 1.5rem;
  box-shadow: 0 20px 50px rgba(15, 23, 42, 0.25);
  max-width: 100%; max-height: 100%; overflow: auto;
}
.cropper-title { margin: 0 0 1rem; text-align: center; font-size: 1.05rem; }
.cropper-frame {
  position: relative; overflow: hidden; margin: 0 auto;
  max-width: 100%; background: #0f172a; border-radius: 8px;
  cursor: grab; touch-action: none; user-select: none;
}
.cropper-frame:active { cursor: grabbing; }
.cropper-frame:focus-visible { outline: 2px solid #4f46e5; outline-offset: 2px; }
.cropper-image { position: absolute; top: 0; left: 0; max-width: none; transform-origin: 0 0; }
.cropper-zoom { display: flex; align-items: center; gap: 0.75rem; margin: 1rem auto 0; max-width: 420px; }
.cropper-zoom input[type="range"] { flex: 1; }
.cropper-zoom-step {
  border: 1px solid #e2e8f0; background: #fff; border-radius: 6px;
  width: 2rem; height: 2rem; font-size: 1.1rem; line-height: 1; cursor: pointer;
}
.cropper-hint { margin: 1rem 0 0; text-align: center; font-size: 0.85rem; color: #64748b; }
.cropper-actions { display: flex; justify-content: flex-end; gap: 0.75rem; margin-top: 1.25rem; }
</style>
