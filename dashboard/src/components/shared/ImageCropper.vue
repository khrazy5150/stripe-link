<script setup>
/**
 * Crop / zoom / reposition, in whatever shape the CONSUMING SURFACE allows.
 *
 * Some surfaces demand one ratio -- a circular avatar is not negotiable, and a Before/After pair only
 * aligns because both sides crop to one shape. Others (the page ribbon renders height:auto) never had a
 * shape at all, and forcing one silently discards the framing the tenant chose. So the surface declares
 * what it allows and this adapts: locked, a choice of presets, or the source's own ratio.
 *
 * The value is a NORMALIZED rect ({x, y, w, h} as fractions of the source, 0..1), never pixels. The image
 * service emits thumb/small/medium/large/full and mints more on demand, so a pixel rect is correct against
 * exactly one rendition and silently wrong against every other. Fractions survive all of them, and survive
 * the source being reprocessed. See plans/IMAGE_CROPPER.md.
 */
import { computed, ref, watch } from "vue";

const props = defineProps({
  src: { type: String, required: true },
  /**
   * What shape this crop may be, from image_ratios.json. Three forms, and the UI adapts to each:
   *   a NUMBER          -- locked; the layout demands one shape (a circular avatar is not negotiable)
   *   an ARRAY          -- the tenant picks; "original" means the source image's own ratio
   *   null / undefined  -- the surface accepts any shape, so the source's own ratio is offered
   * A surface that renders height:auto never had one shape, and forcing one silently discards framing
   * the tenant chose. See plans/IMAGE_CROPPER.md.
   */
  ratios: { type: [Number, Array, String], default: null },
  // Reopen with the crop already applied, so a crop is an editable decision rather than a one-shot.
  crop: { type: Object, default: null },
  title: { type: String, default: "Crop, zoom, or move" },
});
const emit = defineEmits(["apply", "cancel"]);

const FREEFORM = "original";

const natural = ref({ width: 0, height: 0 });
const scale = ref(1);
const offset = ref({ x: 0, y: 0 }); // top-left of the scaled image, relative to the frame
const dragging = ref(false);
const loadFailed = ref(false);
let dragStart = null;


// Fits a phone as well as a desktop; a fixed 420 overflowed narrow viewports.
const frameWidth = ref(Math.min(420, (typeof window !== "undefined" ? window.innerWidth : 420) - 96));

const options = computed(() => {
  const raw = props.ratios;
  if (raw === null || raw === undefined || raw === "") return [FREEFORM];
  const list = Array.isArray(raw) ? raw : [raw];
  const usable = list.filter((r) => r === FREEFORM || (typeof r === "number" && r > 0));
  return usable.length ? usable : [FREEFORM];
});
const locked = computed(() => options.value.length === 1);
const chosen = ref(null);

// "original" resolves only once the image has loaded and its own shape is known.
const activeRatio = computed(() => {
  const pick = chosen.value ?? options.value[0];
  if (pick === FREEFORM) {
    return natural.value.width && natural.value.height
      ? natural.value.width / natural.value.height
      : 1;
  }
  return pick;
});
const frameHeight = computed(() => Math.round(frameWidth.value / (activeRatio.value || 1)));

function ratioLabel(option) {
  if (option === FREEFORM) return "Original";
  const named = { 1: "1:1", 1.3333333333: "4:3", 1.7777777778: "16:9", 0.8: "4:5", 0.5625: "9:16" };
  const hit = Object.keys(named).find((k) => Math.abs(Number(k) - option) < 0.001);
  return hit ? named[hit] : `${Math.round(option * 100) / 100}`;
}

// Below this the image cannot cover the frame and gaps appear at the edges, so it is the floor for zoom.
const minScale = computed(() => {
  if (!natural.value.width || !natural.value.height) return 1;
  return Math.max(frameWidth.value / natural.value.width, frameHeight.value / natural.value.height);
});
// Never enlarge past native resolution: upscaling produces a soft image the tenant cannot diagnose. An
// image smaller than the frame is the exception -- it has to be enlarged to cover at all.
const maxScale = computed(() => Math.max(1, minScale.value));

const canZoom = computed(() => maxScale.value - minScale.value > 0.001);

function clampOffset(next, atScale) {
  const w = natural.value.width * atScale;
  const h = natural.value.height * atScale;
  return {
    x: Math.min(0, Math.max(frameWidth.value - w, next.x)),
    y: Math.min(0, Math.max(frameHeight.value - h, next.y)),
  };
}

function centreOn(atScale) {
  offset.value = clampOffset({
    x: (frameWidth.value - natural.value.width * atScale) / 2,
    y: (frameHeight.value - natural.value.height * atScale) / 2,
  }, atScale);
}

function onImageLoad(event) {
  loadFailed.value = false;
  natural.value = { width: event.target.naturalWidth, height: event.target.naturalHeight };
  if (props.crop?.ar > 0) {
    const match = options.value.find(
      (o) => o !== FREEFORM && Math.abs(o - props.crop.ar) < 0.001,
    );
    chosen.value = match ?? (options.value.includes(FREEFORM) ? FREEFORM : options.value[0]);
  }
  if (props.crop && props.crop.w > 0 && props.crop.h > 0) {
    // Reopening: recover the transform the stored rect describes.
    const restored = Math.max(minScale.value, frameWidth.value / (props.crop.w * natural.value.width));
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
  const cx = (frameWidth.value / 2 - offset.value.x) / previous;
  const cy = (frameHeight.value / 2 - offset.value.y) / previous;
  offset.value = clampOffset({ x: frameWidth.value / 2 - cx * next, y: frameHeight.value / 2 - cy * next }, next);
});

watch(activeRatio, () => {
  if (!natural.value.width) return;
  // A new frame shape can leave the old scale too small to cover it, which would show bare background.
  scale.value = Math.max(minScale.value, Math.min(maxScale.value, scale.value));
  centreOn(scale.value);
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
    w: Math.min(frameWidth.value / w, 1),
    h: Math.min(frameHeight.value / h, 1),
  };
  // Round to the fifth decimal: enough precision for any real image, and it keeps the stored document and
  // the generated cache key stable instead of churning on floating-point noise.
  const round = (n) => Math.round(n * 1e5) / 1e5;
  emit("apply", {
    x: round(rect.x), y: round(rect.y), w: round(rect.w), h: round(rect.h),
    ar: Math.round(activeRatio.value * 1e5) / 1e5,
  });
}
</script>

<template>
  <div class="cropper-backdrop" role="dialog" aria-modal="true" :aria-label="title" @click.self="emit('cancel')">
    <div class="cropper-panel">
      <h3 class="cropper-title">{{ title }}</h3>

      <p v-if="loadFailed" class="field-error">That image could not be loaded.</p>

      <!-- Only when there is a decision to make. A locked surface showing a one-option picker invites the
           tenant to look for a choice that does not exist. -->
      <div v-if="!locked" class="cropper-ratios" role="group" aria-label="Shape">
        <button
          v-for="option in options"
          :key="String(option)"
          type="button"
          class="cropper-ratio"
          :class="{ 'is-active': (chosen ?? options[0]) === option }"
          :aria-pressed="(chosen ?? options[0]) === option"
          @click="chosen = option"
        >{{ ratioLabel(option) }}</button>
      </div>

      <div
        class="cropper-frame"
        :style="{ width: `${frameWidth}px`, height: `${frameHeight}px` }"
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
.cropper-ratios { display: flex; justify-content: center; gap: 0.4rem; flex-wrap: wrap; margin-bottom: 0.9rem; }
.cropper-ratio {
  border: 1px solid #e2e8f0; background: #fff; border-radius: 999px;
  padding: 0.25rem 0.7rem; font-size: 0.8rem; cursor: pointer; color: #475569;
}
.cropper-ratio.is-active { border-color: #4f46e5; color: #4f46e5; font-weight: 600; }
.cropper-zoom { display: flex; align-items: center; gap: 0.75rem; margin: 1rem auto 0; max-width: 420px; }
.cropper-zoom input[type="range"] { flex: 1; }
.cropper-zoom-step {
  border: 1px solid #e2e8f0; background: #fff; border-radius: 6px;
  width: 2rem; height: 2rem; font-size: 1.1rem; line-height: 1; cursor: pointer;
}
.cropper-hint { margin: 1rem 0 0; text-align: center; font-size: 0.85rem; color: #64748b; }
.cropper-actions { display: flex; justify-content: flex-end; gap: 0.75rem; margin-top: 1.25rem; }
</style>
