<!--
  Generate a hero image, or reuse one you already made.

  WHY THIS EXISTS AT ALL: the hero inherits the offer's product photographs, which is reasonable and
  rarely striking. The price card already carries the product shot, so the hero is free to do a hero's
  job — convey a feeling — and that is precisely the image a tenant does not have.

  Nothing renderable is decided here. The quality options, the style presets, the credit count and the
  refusal sentence all come from /ai/config, so this file does not have to be edited when a tier
  changes. The quality list is one entry long today and a one-entry list renders no control.
-->
<template>
  <div class="aip-backdrop" @click.self="close">
    <div class="aip" role="dialog" aria-modal="true" aria-labelledby="aip-title">
      <header class="aip-head">
        <h2 id="aip-title">Generate an image</h2>
        <span v-if="store.credits" class="aip-credits" :title="creditsTitle">{{ store.remainingLabel }}</span>
        <button type="button" class="aip-x" aria-label="Close" @click="close">&times;</button>
      </header>

      <div class="aip-body">
        <p class="aip-hint">
          Describe a scene or a feeling, not the product — your product photos are already on the price card.
        </p>

        <div class="aip-compose">
          <input
            ref="promptInput"
            v-model="prompt"
            class="aip-prompt"
            type="text"
            maxlength="2000"
            placeholder="A golden retriever waiting by a sunlit front door"
            :disabled="store.generating"
            @keyup.enter="generate"
          >
          <select v-if="store.styles.length" v-model="style" class="aip-style" :disabled="store.generating">
            <option value="">No style</option>
            <option v-for="option in store.styles" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <!-- Rendered only when the server offers a choice. One option is not a choice. -->
          <select v-if="store.qualities.length > 1" v-model="quality" class="aip-style" :disabled="store.generating">
            <option v-for="option in store.qualities" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <select v-model.number="count" class="aip-count" :disabled="store.generating">
            <option :value="1">1</option>
            <option :value="2">2</option>
            <option :value="3">3</option>
            <option :value="4">4</option>
          </select>
          <button type="button" class="aip-go" :disabled="!canSubmit" @click="generate">
            {{ store.generating ? "Generating…" : "Generate" }}
          </button>
        </div>

        <!-- A limit reached is the system working, so it is worded and coloured as information.
             A fault is not. -->
        <p v-if="blockedReason" class="aip-note is-limit">{{ blockedReason }}</p>
        <p v-else-if="store.error" class="aip-note is-error">{{ store.error }}</p>
        <p v-if="store.libraryUnavailable" class="aip-note is-limit">
          Your previous images could not be loaded just now. You can still generate a new one.
        </p>

        <div v-if="store.generating" class="aip-waiting">
          <span class="aip-spinner" aria-hidden="true"></span>
          <span>This takes about {{ count > 1 ? "half a minute" : "fifteen seconds" }}.</span>
        </div>

        <h3 v-if="store.images.length" class="aip-sub">Your images</h3>
        <div v-if="store.images.length" class="aip-groups">
          <section v-for="entry in store.images" :key="entry.jobId" class="aip-group">
            <div class="aip-shots">
              <button
                v-for="image in entry.images"
                :key="image.id"
                type="button"
                class="aip-shot"
                :title="entry.prompt"
                @click="choose(image)"
              >
                <img :src="thumb(image)" :alt="entry.prompt" loading="lazy">
                <span class="aip-use">Use</span>
              </button>
            </div>
            <div class="aip-meta">
              <p class="aip-prompt-text" :title="entry.prompt">{{ entry.prompt }}</p>
              <div class="aip-actions">
                <button type="button" class="aip-mini" @click="reuse(entry)">Use this prompt</button>
                <button type="button" class="aip-mini is-danger" @click="remove(entry)">Delete</button>
                <span class="aip-when">{{ when(entry.createdAt) }}</span>
              </div>
            </div>
          </section>
        </div>
        <p v-else-if="store.loaded && !store.generating" class="aip-empty">
          Nothing yet. Describe an image above and press Generate.
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from "vue";

import { useAiImagesStore } from "../../stores/aiImages";

const emit = defineEmits(["close", "picked"]);

const store = useAiImagesStore();
const prompt = ref("");
const style = ref("lifestyle");
const quality = ref("");
const count = ref(2);
const promptInput = ref(null);

onMounted(async () => {
  await store.load();
  // Default to whatever the server says is the best this tenant may have, rather than a value typed
  // here that a tier change would make wrong.
  quality.value = store.qualities[store.qualities.length - 1]?.value || "";
  await nextTick();
  promptInput.value?.focus();
});

const blockedReason = computed(() => (store.credits && !store.credits.can_generate)
  ? store.credits.reason : "");
const canSubmit = computed(() => prompt.value.trim().length >= 3
  && !store.generating && store.canGenerate);
const creditsTitle = computed(() => {
  const credits = store.credits;
  if (!credits) return "";
  const noun = credits.period?.includes("trial") ? "in your trial" : "this month";
  return `${credits.used} of ${credits.allowance} AI images used ${noun}.`;
});

// The medium variant: a picker shows a dozen of these at a time, and the full-size hero is a click
// away on the page itself.
const thumb = (image) => image?.urls?.medium?.webp || image?.urls?.medium?.jpg
  || image?.urls?.full?.jpg || image?.urls?.original || "";
const full = (image) => image?.urls?.full?.jpg || image?.urls?.original || thumb(image);

const when = (seconds) => (seconds
  ? new Date(seconds * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" })
  : "");

async function generate() {
  if (!canSubmit.value) return;
  await store.generate({ prompt: prompt.value.trim(), style: style.value, count: count.value });
}

function choose(image) {
  emit("picked", { url: full(image), id: image.id });
  close();
}

function reuse(entry) {
  prompt.value = entry.prompt;
  promptInput.value?.focus();
}

async function remove(entry) {
  // Takedown is irreversible and the images may be on a published page, so it is confirmed rather
  // than undoable — there is nothing to undo once a CDN has been purged.
  const count = entry.images.length;
  const message = `Delete ${count === 1 ? "this image" : `these ${count} images`}? `
    + "If they are on a published page they will stop loading.";
  if (!window.confirm(message)) return;
  await store.remove(entry.jobId);
}

function close() {
  emit("close");
}
</script>

<style scoped>
.aip-backdrop {
  position: fixed; inset: 0; z-index: 1200; background: rgba(13, 20, 32, .6);
  display: flex; align-items: center; justify-content: center; padding: 24px;
}
.aip {
  background: #fff; border-radius: 14px; width: min(860px, 100%); max-height: 88vh;
  display: flex; flex-direction: column; box-shadow: 0 20px 60px rgba(13, 20, 32, .3);
}
.aip-head {
  display: flex; align-items: center; gap: 12px; padding: 18px 22px;
  border-bottom: 1px solid #e6e9ef;
}
.aip-head h2 { margin: 0; font-size: 17px; font-weight: 600; flex: 1; }
.aip-credits {
  font-size: 12px; font-variant-numeric: tabular-nums; color: #0b5294;
  background: #e9f1fa; border-radius: 999px; padding: 3px 10px; white-space: nowrap;
}
.aip-x { border: none; background: none; font-size: 24px; line-height: 1; color: #6b7684; cursor: pointer; }
.aip-body { padding: 18px 22px 24px; overflow-y: auto; }
.aip-hint { margin: 0 0 12px; color: #6b7684; font-size: 13px; }
.aip-compose { display: flex; flex-wrap: wrap; gap: 8px; }
.aip-prompt {
  flex: 1 1 260px; min-width: 0; padding: 10px 12px; border: 1px solid #d7dce4;
  border-radius: 9px; font-size: 14px;
}
.aip-prompt:focus, .aip-style:focus, .aip-count:focus { outline: 2px solid #0b5294; outline-offset: 1px; }
.aip-style, .aip-count { padding: 10px; border: 1px solid #d7dce4; border-radius: 9px; background: #fff; }
.aip-count { width: 64px; }
.aip-go {
  padding: 10px 18px; border: none; border-radius: 9px; background: #0b5294; color: #fff;
  font-weight: 600; cursor: pointer;
}
.aip-go:disabled { opacity: .45; cursor: not-allowed; }
.aip-note { margin: 12px 0 0; font-size: 13px; padding: 9px 12px; border-radius: 9px; }
.aip-note.is-limit { background: #fdf3e7; color: #8a5316; }
.aip-note.is-error { background: #fdecec; color: #a3272b; }
.aip-waiting { display: flex; align-items: center; gap: 10px; margin-top: 14px; color: #6b7684; font-size: 13px; }
.aip-spinner {
  width: 16px; height: 16px; border-radius: 50%; border: 2px solid #e6e9ef;
  border-top-color: #0b5294; animation: aip-spin 1s linear infinite;
}
@keyframes aip-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .aip-spinner { animation-duration: 3s; } }
.aip-sub { font-size: 13px; font-weight: 600; color: #6b7684; margin: 22px 0 10px; }
.aip-groups { display: flex; flex-direction: column; gap: 18px; }
.aip-group { border: 1px solid #e6e9ef; border-radius: 12px; overflow: hidden; }
.aip-shots { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 2px; background: #e6e9ef; }
.aip-shot { position: relative; border: none; padding: 0; cursor: pointer; background: #f4f6f8; aspect-ratio: 3 / 2; }
.aip-shot img { width: 100%; height: 100%; object-fit: cover; display: block; }
.aip-use {
  position: absolute; inset: auto 0 0 0; background: rgba(11, 82, 148, .9); color: #fff;
  font-size: 12px; padding: 5px; opacity: 0; transition: opacity .15s;
}
.aip-shot:hover .aip-use, .aip-shot:focus-visible .aip-use { opacity: 1; }
.aip-meta { padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; }
.aip-prompt-text {
  margin: 0; font-size: 12.5px; color: #3c4756; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.aip-actions { display: flex; align-items: center; gap: 8px; }
.aip-mini {
  border: 1px solid #d7dce4; background: none; border-radius: 999px; padding: 3px 10px;
  font-size: 12px; color: #6b7684; cursor: pointer;
}
.aip-mini:hover { border-color: #0b5294; color: #0b5294; }
.aip-mini.is-danger:hover { border-color: #a3272b; color: #a3272b; }
.aip-when { margin-left: auto; font-size: 12px; color: #9aa4b2; }
.aip-empty { color: #9aa4b2; text-align: center; padding: 30px 0; font-size: 13px; }
</style>
