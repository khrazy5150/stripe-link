<template>
  <section class="page video-gallery">
    <header class="page-header">
      <div>
        <h1>Video Gallery</h1>
        <p>Watch and download the videos you generated.</p>
      </div>
      <button class="secondary-action compact" type="button" @click="navigateTo('aiVideo')">Create video</button>
    </header>

    <label class="offer-field gallery-search">
      <span>Search videos</span>
      <input v-model.trim="search" type="search" maxlength="160" placeholder="Title, tags, model, or prompt" />
    </label>

    <div v-if="videos.length" class="gallery-grid">
      <article v-for="video in videos" :key="video.id" class="dashboard-card gallery-card">
        <button
          :ref="observeThumbnail"
          class="gallery-preview"
          type="button"
          :data-video-id="video.id"
          :aria-label="`Watch ${video.title}`"
          @click="watchVideo(video)"
        >
          <video
            v-if="thumbnails[video.id]"
            :src="thumbnails[video.id]"
            preload="metadata"
            muted
            playsinline
            aria-hidden="true"
            @error="delete thumbnails[video.id]"
          />
          <span class="gallery-play" aria-hidden="true">▶</span>
        </button>
        <div class="gallery-card-body">
          <h2>{{ video.title }}</h2>
          <time :datetime="new Date(video.created_at).toISOString()">{{ formatDate(video.created_at) }}</time>
          <ul v-if="video.tags.length" class="gallery-tags" aria-label="Tags">
            <li v-for="tag in video.tags" :key="tag">{{ tag }}</li>
          </ul>
          <button
            class="secondary-action compact"
            type="button"
            :disabled="!!downloading"
            :aria-label="`Download ${video.title}`"
            @click="download(video)"
          >
            {{ downloading === video.id ? "Preparing…" : "Download" }}
          </button>
        </div>
      </article>
    </div>

    <p v-if="loading || waitingForSearch" class="gallery-status" role="status">Loading videos…</p>
    <p v-else-if="!hasMore && !videos.length && !error" class="gallery-status">
      {{ search ? "No videos match your search." : "Your completed videos will appear here." }}
    </p>
    <div v-if="error" class="keys-status-banner error" role="alert">
      {{ error }}
      <button class="secondary-action compact" type="button" @click="loadMore">Retry</button>
    </div>
    <p v-if="downloadError && !active" class="field-error" role="alert">{{ downloadError }}</p>
    <div v-if="hasMore && !loading && !waitingForSearch && !error" ref="sentinel" class="gallery-status">
      <button class="secondary-action compact" type="button" @click="loadMore">Load more</button>
    </div>

    <dialog ref="player" class="gallery-player" aria-labelledby="gallery-player-title" @close="closePlayer">
      <div v-if="active">
        <header class="gallery-player-header">
          <h2 id="gallery-player-title">{{ active.title }}</h2>
          <button class="secondary-action compact" type="button" autofocus @click="player.close()">Close</button>
        </header>
        <video
          v-if="playbackUrl"
          :src="playbackUrl"
          controls
          playsinline
          preload="metadata"
          :aria-label="active.title"
          @error="playbackFailed"
        />
        <p v-else-if="!playbackError" role="status">Loading video…</p>
        <p v-if="playbackError" class="field-error" role="alert">{{ playbackError }}</p>
        <p v-if="downloadError" class="field-error" role="alert">{{ downloadError }}</p>
        <div class="gallery-player-actions">
          <button v-if="playbackError" class="secondary-action compact" type="button" @click="loadPlayback">Reload video</button>
          <button class="secondary-action compact" type="button" :disabled="!!downloading" @click="download(active)">
            {{ downloading === active.id ? "Preparing…" : "Download video" }}
          </button>
        </div>
      </div>
    </dialog>
  </section>
</template>

<script setup>
import { inject, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { apiRequest } from "../api/client";

const navigateTo = inject("navigateTo");
const date = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const search = ref("");
const videos = ref([]);
const cursor = ref("");
const hasMore = ref(true);
const loading = ref(false);
const waitingForSearch = ref(false);
const error = ref("");
const sentinel = ref(null);
const thumbnails = reactive({});
const active = ref(null);
const player = ref(null);
const playbackUrl = ref("");
const playbackError = ref("");
const downloadError = ref("");
const downloading = ref("");
let observer;
let searchTimer;
let sequence = 0;
let playerSequence = 0;
let unmounted = false;
const thumbnailRequests = new Set();

function formatDate(timestamp) {
  return date.format(new Date(timestamp));
}

async function loadMore() {
  if (loading.value || waitingForSearch.value || !hasMore.value || unmounted) return;
  const version = sequence;
  loading.value = true;
  error.value = "";
  try {
    const result = await apiRequest("/ai/video/gallery", { params: { cursor: cursor.value, q: search.value } });
    if (sequence !== version) return;
    videos.value.push(...result.videos);
    cursor.value = result.next_cursor || "";
    hasMore.value = Boolean(cursor.value);
  } catch (err) {
    if (sequence === version) error.value = err.message;
  } finally {
    if (sequence === version) loading.value = false;
  }
}

watch(search, () => {
  sequence += 1;
  clearTimeout(searchTimer);
  videos.value = [];
  cursor.value = "";
  hasMore.value = true;
  error.value = "";
  loading.value = false;
  waitingForSearch.value = true;
  searchTimer = setTimeout(() => {
    waitingForSearch.value = false;
    loadMore();
  }, 250);
});

function videoLink(id, download = false) {
  return apiRequest(`/ai/video/jobs/${id}/video-link`, { params: download ? { download: true } : {} });
}

async function loadThumbnail(id) {
  if (thumbnails[id] || thumbnailRequests.has(id)) return;
  thumbnailRequests.add(id);
  try {
    const { url } = await videoLink(id);
    if (!unmounted) thumbnails[id] = `${url}#t=0.1`;
  } catch {
    // The card falls back to its play control. Opening it requests a fresh link.
  } finally {
    thumbnailRequests.delete(id);
  }
}

function observeThumbnail(element) {
  if (element && !thumbnails[element.dataset.videoId]) observer?.observe(element);
}

watch(sentinel, (next, previous) => {
  if (previous) observer?.unobserve(previous);
  if (next) observer?.observe(next);
});

async function watchVideo(video) {
  active.value = video;
  playbackUrl.value = "";
  playbackError.value = "";
  downloadError.value = "";
  await nextTick();
  if (unmounted || player.value.open) return;
  player.value.showModal();
  loadPlayback();
}

async function loadPlayback() {
  const { id } = active.value;
  const version = ++playerSequence;
  playbackError.value = "";
  try {
    const { url } = await videoLink(id);
    if (playerSequence === version) playbackUrl.value = url;
  } catch (err) {
    if (playerSequence === version) playbackError.value = err.message;
  }
}

function playbackFailed() {
  playbackUrl.value = "";
  playbackError.value = "Playback is unavailable. Reload the video to get a fresh link.";
}

function closePlayer() {
  playerSequence += 1;
  active.value = null;
  playbackUrl.value = "";
  playbackError.value = "";
}

async function download(video) {
  if (downloading.value) return;
  downloading.value = video.id;
  downloadError.value = "";
  try {
    const { url } = await videoLink(video.id, true);
    if (!unmounted) window.location.assign(url);
  } catch (err) {
    if (!unmounted) downloadError.value = err.message;
  } finally {
    downloading.value = "";
  }
}

onMounted(() => {
  if ("IntersectionObserver" in window) {
    observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        if (entry.target === sentinel.value) {
          loadMore();
        } else if (entry.target.dataset.videoId) {
          observer.unobserve(entry.target);
          loadThumbnail(entry.target.dataset.videoId);
        }
      }
    }, { rootMargin: "200px 0px" });
  }
  loadMore();
});

onBeforeUnmount(() => {
  unmounted = true;
  sequence += 1;
  playerSequence += 1;
  observer?.disconnect();
  clearTimeout(searchTimer);
});
</script>

<style scoped>
.video-gallery {
  container-type: inline-size;
}
.gallery-search {
  width: min(100%, 42rem);
}
.gallery-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: clamp(0.8rem, 2vw, 1.8rem);
}
.gallery-card {
  display: flex;
  flex-direction: column;
}
.gallery-preview {
  position: relative;
  display: grid;
  place-items: center;
  width: 100%;
  padding: 0;
  border: 0;
  aspect-ratio: 16 / 9;
  background: #182331;
  color: #fff;
  cursor: pointer;
}
.gallery-preview video {
  width: 100%;
  height: 100%;
  object-fit: contain;
  position: absolute;
  inset: 0;
}
.gallery-play {
  z-index: 1;
  display: grid;
  place-items: center;
  width: 3.4rem;
  height: 3.4rem;
  border-radius: 50%;
  background: rgb(12 18 27 / 80%);
  font-size: 1.3rem;
}
.gallery-card-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.7rem;
  padding: clamp(0.8rem, 2vw, 1.5rem);
  min-width: 0;
}
.gallery-card h2 {
  margin: 0;
  font-size: 1.45rem;
  overflow-wrap: anywhere;
}
.gallery-card time {
  color: var(--muted);
  font-size: 1.2rem;
}
.gallery-card-body > button {
  margin-top: auto;
}
.gallery-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin: 0;
  padding: 0 0 0.4rem;
  list-style: none;
}
.gallery-tags li {
  border-radius: 0.6rem;
  padding: 0.15rem 0.5rem;
  background: var(--bg);
  color: var(--muted);
  font-size: 1.1rem;
  overflow-wrap: anywhere;
}
.gallery-status {
  margin: 0;
  color: var(--muted);
  text-align: center;
}
.gallery-player {
  width: min(72rem, calc(100vw - 2.4rem));
  max-height: calc(100dvh - 2.4rem);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 1.6rem;
  color: var(--text);
  background: var(--panel);
}
.gallery-player::backdrop {
  background: rgb(12 18 27 / 70%);
}
.gallery-player-header,
.gallery-player-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}
.gallery-player-header h2 {
  margin: 0;
  overflow-wrap: anywhere;
}
.gallery-player video {
  width: 100%;
  max-height: 65dvh;
  background: #111;
}
.gallery-player-actions {
  justify-content: flex-end;
  margin: 1rem 0 0;
}
@container (min-width: 54rem) {
  .gallery-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@container (min-width: 94rem) {
  .gallery-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}
@container (min-width: 118rem) {
  .gallery-grid { grid-template-columns: repeat(5, minmax(0, 1fr)); }
}
@media (max-width: 600px) {
  .video-gallery { padding: 1.4rem; gap: 1.6rem; }
  .video-gallery .page-header { flex-wrap: wrap; }
}
</style>
