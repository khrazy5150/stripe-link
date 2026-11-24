<template>
  <section class="page video-studio">
    <header class="page-header">
      <div>
        <h1>AI Video Generator</h1>
        <p>Create a clip from a prompt or a starting image.</p>
      </div>
    </header>

    <div v-if="catalogError" class="keys-status-banner error" role="alert">
      {{ catalogError }}
      <button class="secondary-action compact" type="button" @click="loadModels">Retry</button>
    </div>

    <div class="video-studio-grid">
      <form class="dashboard-card" @submit.prevent="requestQuote">
        <header class="dashboard-card-header"><h2>Video input</h2></header>
        <div class="dashboard-card-body">
          <p v-if="loading" role="status">Loading video models…</p>
          <fieldset class="studio-fields" :disabled="loading || !model || !!busy || tracking">
            <label class="offer-field">
              <span>Create from</span>
              <select v-model="inputMode" @change="selectDefaultModel">
                <option value="text">Text to video</option>
                <option value="image">Image to video</option>
              </select>
            </label>

            <template v-if="inputMode === 'image'">
              <label class="offer-field">
                <span>Image source</span>
                <select v-model="referenceSource">
                  <option value="file">Upload an image</option>
                  <option value="url">Use an image URL</option>
                </select>
              </label>
              <label v-if="referenceSource === 'file'" class="offer-field">
                <span>Starting image</span>
                <input type="file" accept="image/jpeg,image/png,image/webp" required @change="selectImage" />
                <small>JPEG, PNG, or WebP up to 4 MiB. Requesting an estimate sends the image to Higgsfield.</small>
              </label>
              <label v-else class="offer-field">
                <span>Starting image URL</span>
                <input v-model.trim="referenceUrl" type="url" placeholder="https://" required />
                <small>Use a direct HTTPS link to an image Higgsfield can access.</small>
              </label>
            </template>

            <label class="offer-field">
              <span>Video prompt <small v-if="model?.prompt_required === false">(optional)</small></span>
              <textarea v-model="prompt" :required="model?.prompt_required !== false" rows="6" maxlength="2000" placeholder="Describe the shot, movement, and lighting you want." />
            </label>
            <div class="studio-settings">
              <label class="offer-field">
                <span>Gallery title <small>(optional)</small></span>
                <input v-model.trim="title" type="text" maxlength="90" />
              </label>
              <label class="offer-field">
                <span>Gallery tags <small>(optional)</small></span>
                <input v-model="tagText" type="text" maxlength="480" placeholder="Separate tags with commas" />
              </label>
            </div>

            <h3>Video settings</h3>
            <label class="offer-field">
              <span>Model</span>
              <select v-model="modelId" @change="applyDefaults">
                <option v-for="entry in models" :key="entry.id" :value="entry.id">{{ entry.label }}</option>
              </select>
            </label>
            <div class="studio-settings">
              <label v-for="setting in visibleSettings" :key="setting.key" class="offer-field">
                <span>{{ setting.label }}</span>
                <select v-model="settings[setting.key]">
                  <option v-for="option in model[setting.choices]" :key="option" :value="option">{{ setting.format(option) }}</option>
                </select>
              </label>
            </div>

            <button class="primary-action studio-submit" type="submit">Get estimate</button>
          </fieldset>
        </div>
      </form>

      <div class="studio-results">
        <section class="dashboard-card" aria-labelledby="video-estimate-heading">
          <header class="dashboard-card-header"><h2 id="video-estimate-heading">Cost estimate</h2></header>
          <div class="dashboard-card-body">
            <template v-if="quote">
              <p class="studio-price">{{ formatPrice(quote.quoted_usd) }}</p>
              <p>Expires at {{ formatExpiry(quote.quote_expires_at) }}. Generating uses Junior Bay’s shared Higgsfield account.</p>
              <div class="studio-actions">
                <button class="primary-action" type="button" :disabled="!!busy || tracking" @click="approveQuote">Approve &amp; generate</button>
                <button class="secondary-action" type="button" :disabled="!!busy" @click="clearQuote">Dismiss</button>
              </div>
            </template>
            <p v-else>Request an estimate to see the cost before you generate.</p>
            <p v-if="busy" role="status">{{ busy }}</p>
            <p v-if="error" class="field-error studio-error" role="alert">{{ error }}</p>
          </div>
        </section>

        <section v-if="job" class="dashboard-card" aria-labelledby="video-result-heading">
          <header class="dashboard-card-header"><h2 id="video-result-heading">Video result</h2></header>
          <div class="dashboard-card-body">
            <p role="status">{{ statusMessage }}</p>
            <p v-if="job.error" class="field-error studio-error">{{ job.error }}</p>
            <p v-if="jobError" class="field-error studio-error" role="alert">{{ jobError }}</p>
            <video v-if="videoUrl" :src="videoUrl" controls playsinline preload="metadata" aria-label="Generated video" @error="playbackError" />
            <div class="studio-actions">
              <button v-if="job.video_available && !videoUrl" class="secondary-action" type="button" @click="loadVideo">Load video</button>
              <button v-if="job.video_available" class="secondary-action" type="button" :disabled="downloading" @click="downloadVideo">Download video</button>
              <button v-else-if="tracking || ['submitting', 'submission_unknown'].includes(job.state)" class="secondary-action" type="button" :disabled="checking" @click="refreshJob">Refresh status</button>
            </div>
          </div>
        </section>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { apiRequest, getTenantId, hostnameReleaseChannel } from "../api/client";

const base = "/ai/video";
const storageKey = `jb.video-job.${hostnameReleaseChannel()}.${getTenantId()}`;
const currency = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 6 });
const fields = [
  { key: "duration", label: "Duration", choices: "durations", format: (value) => `${value} seconds` },
  { key: "aspect_ratio", label: "Aspect ratio", choices: "aspect_ratios", format: (value) => value },
  { key: "resolution", label: "Quality", choices: "resolutions", format: (value) => value },
  { key: "bitrate_mode", label: "Bitrate", choices: "bitrates", format: (value) => value.charAt(0).toUpperCase() + value.slice(1) },
];
const states = {
  waiting: "Waiting for an available generation slot…",
  queued: "Queued for generation…",
  submitting: "Waiting for Higgsfield to confirm the request…",
  in_progress: "Generating video…",
  archiving: "Saving the video…",
  completed: "Your video is ready.",
  failed: "Generation failed.",
  rejected: "Generation was declined.",
  nsfw: "Generation was blocked by content moderation.",
  canceled: "Generation was canceled.",
  archive_failed: "The video could not be saved.",
  submission_unknown: "Higgsfield hasn’t confirmed whether generation started.",
};
const activeStates = new Set(["waiting", "queued", "in_progress", "archiving"]);

const catalog = ref({});
const catalogError = ref("");
const loading = ref(true);
const inputMode = ref("text");
const referenceSource = ref("file");
const referenceUrl = ref("");
const referenceFile = ref(null);
const prompt = ref("");
const title = ref("");
const tagText = ref("");
const modelId = ref("");
const settings = reactive({});
const quote = ref(null);
const job = ref(null);
const busy = ref("");
const error = ref("");
const jobError = ref("");
const videoUrl = ref("");
const checking = ref(false);
const downloading = ref(false);
let requestId = "";
let uploadedImage;
let pollTimer;
let disposed = false;

const models = computed(() => (inputMode.value === "image" ? catalog.value.image_models : catalog.value.models) || []);
const model = computed(() => models.value.find((entry) => entry.id === modelId.value));
const visibleSettings = computed(() => fields.filter((field) => model.value?.[field.choices]?.length));
const tracking = computed(() => activeStates.has(job.value?.state)
  || (["submitting", "submission_unknown"].includes(job.value?.state) && job.value.retry_after_seconds != null));
const statusMessage = computed(() => states[job.value?.state] || "Checking video status…");

function applyDefaults() {
  for (const field of fields) settings[field.key] = model.value?.defaults?.[field.key] ?? null;
}

function selectDefaultModel() {
  const preferred = inputMode.value === "image" ? catalog.value.default_image_model : catalog.value.default_model;
  modelId.value = models.value.find((entry) => entry.id === preferred)?.id || models.value[0]?.id || "";
  applyDefaults();
}

async function loadModels() {
  loading.value = true;
  catalogError.value = "";
  try {
    catalog.value = await apiRequest(`${base}/models`);
    selectDefaultModel();
  } catch (err) {
    catalogError.value = err.message;
  } finally {
    loading.value = false;
  }
}

function selectImage(event) {
  referenceFile.value = event.target.files?.[0] || null;
  uploadedImage = null;
}

function clearQuote() {
  quote.value = null;
  error.value = "";
  requestId = "";
}

watch([inputMode, referenceSource, referenceUrl, referenceFile, prompt, title, tagText, modelId, settings], clearQuote);

function readImage(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("The reference image could not be read."));
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.readAsDataURL(file);
  });
}

async function getReferenceImage() {
  if (referenceSource.value === "url") {
    if (!referenceUrl.value.startsWith("https://")) throw new Error("Enter an HTTPS image URL.");
    return referenceUrl.value;
  }
  const file = referenceFile.value;
  if (!file || file.size > 4 * 1024 * 1024) throw new Error("Choose an image up to 4 MiB.");
  if (!uploadedImage) {
    busy.value = "Uploading starting image…";
    uploadedImage = await apiRequest(`${base}/reference-image`, {
      method: "POST", body: { content_type: file.type, image_base64: await readImage(file) },
    });
  }
  return uploadedImage.image_url;
}

async function requestQuote() {
  if (busy.value || tracking.value || !model.value) return;
  error.value = "";
  quote.value = null;
  try {
    busy.value = "Getting estimate…";
    const imageUrl = inputMode.value === "image" ? await getReferenceImage() : "";
    if (disposed) return;
    requestId ||= crypto.randomUUID();
    const body = {
      request_id: requestId,
      model: modelId.value,
      title: title.value,
      tags: tagText.value.split(",").map((tag) => tag.trim()).filter(Boolean),
      ...Object.fromEntries(visibleSettings.value.map(({ key }) => [key, settings[key]])),
    };
    if (prompt.value.trim()) body.prompt = prompt.value.trim();
    if (imageUrl) body.image_url = imageUrl;
    busy.value = "Getting estimate…";
    quote.value = await apiRequest(`${base}/quote`, { method: "POST", body });
    requestId = "";
  } catch (err) {
    error.value = err.message;
  } finally {
    busy.value = "";
  }
}

function formatPrice(value) { return currency.format(Number(value)); }
function formatExpiry(value) { return new Date(Number(value) * 1000).toLocaleTimeString(); }

async function approveQuote() {
  if (!quote.value || busy.value || tracking.value) return;
  const { id, quoted_usd: quotedUsd, quote_expires_at: expires } = quote.value;
  if (Number(expires) * 1000 <= Date.now()) {
    clearQuote();
    error.value = "This estimate expired. Request a new estimate.";
    return;
  }
  busy.value = "Submitting video…";
  error.value = "";
  try {
    const approved = await apiRequest(`${base}/jobs/${id}/approve`, {
      method: "POST", body: { approved_usd: quotedUsd },
    });
    localStorage.setItem(storageKey, id);
    if (disposed) return;
    job.value = approved;
    videoUrl.value = "";
    jobError.value = "";
    clearQuote();
    if (approved.video_available) await loadVideo();
    schedulePoll();
  } catch (err) {
    error.value = err.message;
  } finally {
    busy.value = "";
  }
}

function schedulePoll(seconds = Math.max(2, job.value?.retry_after_seconds ?? 5)) {
  clearTimeout(pollTimer);
  if (!disposed && tracking.value) pollTimer = setTimeout(refreshJob, seconds * 1000);
}

async function refreshJob() {
  if (checking.value || !job.value || disposed) return;
  const { id } = job.value;
  checking.value = true;
  clearTimeout(pollTimer);
  try {
    const current = await apiRequest(`${base}/jobs/${id}`);
    if (disposed || job.value?.id !== id) return;
    job.value = current;
    jobError.value = "";
    if (job.value.state === "quoted") {
      forgetJob(id);
      job.value = null;
    } else if (job.value.video_available && !videoUrl.value) {
      await loadVideo();
    }
    schedulePoll();
  } catch (err) {
    if (disposed || job.value?.id !== id) return;
    if (err.status === 404) {
      forgetJob(id);
      job.value = null;
      error.value = err.message;
    } else {
      jobError.value = err.message;
      schedulePoll(10);
    }
  } finally {
    checking.value = false;
  }
}

function forgetJob(id) {
  if (localStorage.getItem(storageKey) === id) localStorage.removeItem(storageKey);
}

async function loadVideo() {
  const { id } = job.value;
  try {
    const result = await apiRequest(`${base}/jobs/${id}/video-link`);
    if (disposed || job.value?.id !== id) return;
    videoUrl.value = result.url;
    jobError.value = "";
  } catch (err) {
    if (job.value?.id === id) jobError.value = err.message;
  }
}

function playbackError() {
  videoUrl.value = "";
  jobError.value = "The playback link is unavailable. Load the video to renew it.";
}

async function downloadVideo() {
  downloading.value = true;
  try {
    const { url } = await apiRequest(`${base}/jobs/${job.value.id}/video-link`, { params: { download: true } });
    if (!disposed) window.location.assign(url);
  } catch (err) {
    jobError.value = err.message;
  } finally {
    downloading.value = false;
  }
}

onMounted(() => {
  loadModels();
  const saved = localStorage.getItem(storageKey);
  if (saved) {
    job.value = { id: saved, state: "waiting" };
    refreshJob();
  }
});
onBeforeUnmount(() => {
  disposed = true;
  clearTimeout(pollTimer);
});
</script>

<style scoped>
.video-studio-grid {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(26rem, 2fr);
  gap: 2rem;
  align-items: start;
}
.studio-fields,
.studio-results {
  display: grid;
  gap: 1.6rem;
  min-width: 0;
}
.studio-fields {
  border: 0;
  padding: 0;
  margin: 0;
}
.studio-fields h3,
.studio-results p {
  margin: 0;
}
.studio-fields textarea {
  resize: vertical;
}
.studio-settings {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1.2rem;
}
.studio-submit {
  justify-self: start;
}
.studio-price {
  color: var(--text);
  font-size: 3.2rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.studio-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.8rem;
}
.studio-results video {
  width: 100%;
  max-height: 55vh;
  border-radius: var(--radius-md, 10px);
  background: #111;
}
@media (max-width: 900px) {
  .video-studio-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
