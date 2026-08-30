<template>
  <div class="media-list-field">
    <p v-if="hint" class="media-list-hint">{{ hint }}</p>

    <div class="media-list-card">
      <ul v-if="items.length" class="media-list">
        <li
          v-for="(url, index) in items"
          :key="`${url}-${index}`"
          class="media-list-item"
          draggable="true"
          @dragstart="dragFrom = index"
          @dragover.prevent
          @drop="dropOn(index)"
        >
          <span class="media-drag" title="Drag to reorder" aria-hidden="true">⠿</span>
          <span class="media-thumb" :class="{ 'is-video': isVideo(url) }">
            <img v-if="!isVideo(url)" :src="url" alt="" loading="lazy" />
            <span v-else aria-hidden="true">▶</span>
          </span>
          <span class="media-meta">
            <span class="media-kind">{{ isVideo(url) ? "VIDEO" : "IMAGE" }}</span>
            <span class="media-name" :title="url">{{ shortName(url) }}</span>
          </span>
          <button type="button" class="media-remove" :aria-label="`Remove ${shortName(url)}`" @click="removeAt(index)">×</button>
        </li>
      </ul>
      <p v-else class="media-list-empty">{{ emptyText }}</p>

      <div class="media-actions">
        <input ref="imageInput" type="file" accept="image/*" hidden @change="pickImage" />
        <button type="button" class="secondary-action compact" :disabled="busy" @click="imageInput?.click()">
          {{ busy === "image" ? "Uploading…" : "⬆ Upload Image" }}
        </button>

        <input v-if="allowVideoUpload" ref="videoInput" type="file" accept="video/mp4,video/webm,video/quicktime" hidden @change="pickVideo" />
        <button v-if="allowVideoUpload" type="button" class="secondary-action compact" :disabled="busy" @click="videoInput?.click()">
          {{ busy === "video" ? "Uploading…" : "⬆ Upload Video" }}
        </button>

        <button v-if="allowVideoUrl" type="button" class="secondary-action compact" :disabled="busy" @click="openUrlEntry">
          ▶ Video URL
        </button>
      </div>

      <div v-if="urlEntryOpen" class="media-url-entry">
        <input
          ref="urlInput"
          v-model.trim="urlDraft"
          type="url"
          placeholder="https://…/clip.mp4"
          @keyup.enter="commitUrl"
          @keyup.esc="closeUrlEntry"
        />
        <button type="button" class="primary-action compact" @click="commitUrl">Add</button>
        <button type="button" class="secondary-action compact" @click="closeUrlEntry">Cancel</button>
      </div>

      <small v-if="error" class="builder-upload-error">{{ error }}</small>
    </div>

    <div v-if="suggestions.length" class="media-suggestions">
      <button
        v-for="image in suggestions"
        :key="image"
        type="button"
        class="builder-media-thumb"
        :class="{ selected: items.includes(image) }"
        :title="items.includes(image) ? 'Remove from list' : 'Add to list'"
        @click="toggle(image)"
      >
        <img :src="image" alt="" loading="lazy" />
      </button>
    </div>
  </div>
</template>

<script setup>
// Reusable ordered media list (images + videos) for builder fields — the stripe-cart "HERO MEDIA" pattern.
// Deliberately presentational: it owns NO upload transport and NO business rules. The parent passes an
// `upload` function and receives a plain string[] of URLs, so the stored shape (and therefore the renderer
// and Page schema) is unchanged — a hero_media section still stores `images: [url, ...]`.
//
// Media KIND is derived from the URL extension, never stored — mirroring the server's is_video_url()
// in runtime/html.py. Keep VIDEO_EXTENSIONS below in sync with that list.
import { computed, nextTick, ref } from "vue";

const VIDEO_EXTENSIONS = [".mp4", ".webm", ".mov", ".m4v", ".ogv"];

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  hint: { type: String, default: "" },
  emptyText: { type: String, default: "No media yet — upload an image or add a video." },
  // Quick-pick thumbnails (e.g. the offer's product images) the tenant can toggle in/out of the list.
  suggestions: { type: Array, default: () => [] },
  // async (file) => url. Required for the Upload Image action.
  upload: { type: Function, default: null },
  // async (file) => url. Video FILE upload needs a backend that stripe-link doesn't have yet
  // (stripe-cart used a presigned S3 POST + transcode); off until it does, so the UI never
  // offers a capability that would fail. Video URLs work today — the renderer handles them.
  uploadVideo: { type: Function, default: null },
  allowVideoUrl: { type: Boolean, default: true },
  allowVideoUpload: { type: Boolean, default: false },
});
const emit = defineEmits(["update:modelValue"]);

const imageInput = ref(null);
const videoInput = ref(null);
const urlInput = ref(null);
const busy = ref("");
const error = ref("");
const dragFrom = ref(null);
const urlEntryOpen = ref(false);
const urlDraft = ref("");

const items = computed(() => (Array.isArray(props.modelValue) ? props.modelValue : []));

function isVideo(url) {
  const clean = String(url || "").split("?")[0].toLowerCase();
  return VIDEO_EXTENSIONS.some((ext) => clean.endsWith(ext));
}

function shortName(url) {
  const clean = String(url || "").split("?")[0];
  const tail = clean.slice(clean.lastIndexOf("/") + 1) || clean;
  return tail.length > 42 ? `${tail.slice(0, 39)}…` : tail;
}

function commit(next) {
  emit("update:modelValue", next);
}

function append(url) {
  const value = String(url || "").trim();
  if (!value || items.value.includes(value)) return;
  commit([...items.value, value]);
}

function removeAt(index) {
  commit(items.value.filter((_, i) => i !== index));
}

function toggle(url) {
  if (items.value.includes(url)) commit(items.value.filter((item) => item !== url));
  else append(url);
}

function dropOn(index) {
  const from = dragFrom.value;
  dragFrom.value = null;
  if (from === null || from === index) return;
  const next = [...items.value];
  next.splice(index, 0, next.splice(from, 1)[0]);
  commit(next);
}

async function runUpload(file, kind, uploader) {
  if (!file || !uploader) return;
  error.value = "";
  busy.value = kind;
  try {
    append(await uploader(file));
  } catch (err) {
    error.value = err?.message || `${kind === "video" ? "Video" : "Image"} upload failed.`;
  } finally {
    busy.value = "";
  }
}

async function pickImage(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  await runUpload(file, "image", props.upload);
}

async function pickVideo(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  await runUpload(file, "video", props.uploadVideo || props.upload);
}

async function openUrlEntry() {
  urlEntryOpen.value = true;
  await nextTick();
  urlInput.value?.focus();
}

function closeUrlEntry() {
  urlEntryOpen.value = false;
  urlDraft.value = "";
}

function commitUrl() {
  if (urlDraft.value) append(urlDraft.value);
  closeUrlEntry();
}
</script>

<style scoped>
.media-list-hint { margin: 0 0 0.8rem; color: var(--muted); font-size: var(--text-hint); }
.media-list-card { border: 1px solid var(--line); border-radius: var(--radius-md); padding: 1rem; display: grid; gap: 1rem; }
.media-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.6rem; }
.media-list-item {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 1rem;
  padding: 0.6rem;
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  background: var(--panel);
  cursor: grab;
}
.media-drag { color: var(--text-muted); cursor: grab; }
.media-thumb { width: 4rem; height: 4rem; border-radius: var(--radius-md); overflow: hidden; border: 1px solid var(--line); display: grid; place-items: center; background: #f3f4f6; }
.media-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.media-thumb.is-video { background: #111827; color: #fff; font-size: 1.4rem; }
.media-meta { display: grid; min-width: 0; }
.media-kind { font-size: var(--text-micro); font-weight: var(--weight-bold); letter-spacing: 0.06em; color: var(--accent); }
.media-name { font-size: var(--text-hint); color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.media-remove { border: 0; background: transparent; color: var(--text-muted); font-size: 1.8rem; line-height: 1; cursor: pointer; padding: 0 0.4rem; }
.media-remove:hover { color: #dc2626; }
.media-list-empty { margin: 0; color: var(--text-muted); font-size: var(--text-hint); }
.media-actions { display: flex; flex-wrap: wrap; gap: 0.8rem; }
.media-url-entry { display: flex; gap: 0.8rem; align-items: center; }
.media-url-entry input { flex: 1; min-width: 0; }
.media-suggestions { display: flex; flex-wrap: wrap; gap: 0.8rem; margin-top: 1rem; }
</style>
