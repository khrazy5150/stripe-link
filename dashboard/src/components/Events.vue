<template>
  <section class="page events-page">
    <header class="page-header">
      <div>
        <h1>Events</h1>
        <p>Live sessions people can register for</p>
      </div>
      <button v-if="!editing" class="primary-action" type="button" @click="startNew">+ Create Event</button>
      <button v-else class="secondary-action" type="button" @click="editing = null">‹ Back to List</button>
    </header>

    <p v-if="store.error" class="field-error">{{ store.error }}</p>

    <section v-if="!editing" class="dashboard-card">
      <header class="dashboard-card-header"><h2>Your events</h2></header>
      <p v-if="store.loading" class="field-note">Loading…</p>
      <p v-else-if="!store.events.length" class="field-note">
        No events yet. An event is a live session — a webinar, a workshop — that visitors register for on a
        landing page.
      </p>
      <ul v-else class="event-list">
        <li v-for="item in store.events" :key="item.event_id" class="event-row">
          <div class="event-row-main">
            <strong>{{ item.title }}</strong>
            <span class="event-row-note">{{ occurrenceSummary(item) }}</span>
          </div>
          <button class="secondary-action compact" type="button" @click="startEdit(item)">Edit</button>
          <button class="danger-action compact" type="button" @click="remove(item)">Delete</button>
        </li>
      </ul>
    </section>

    <section v-else class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>{{ editing.event_id ? "Edit event" : "New event" }}</h2>
      </header>

      <label class="offer-field">
        <span>Title <small>(what the page announces)</small></span>
        <input v-model.trim="editing.title" type="text" placeholder="e.g. How to sell AI tools" />
      </label>

      <label class="offer-field">
        <span>Description <small>(optional)</small></span>
        <textarea v-model.trim="editing.description" rows="2"></textarea>
      </label>

      <!-- AUTO IS FIRST AND IS THE DEFAULT (author, 2026-11-15). The two modes need different fields --
           a recording has no provider and no join link -- so the rest of this block follows the choice. -->
      <div class="offer-two-column">
        <label class="offer-field">
          <span>How it runs</span>
          <select v-model="editing.delivery">
            <option value="auto">Automated — play a recording on schedule</option>
            <option value="live">Live — you host it somewhere else</option>
          </select>
        </label>
        <label class="offer-field">
          <span>How long <small>(minutes, optional)</small></span>
          <input v-model.number="editing.duration_minutes" type="number" min="1" />
        </label>
      </div>

      <label class="offer-field">
        <span>Latest someone can still join <small>(minutes after the start)</small></span>
        <input v-model.number="editing.late_join_minutes" type="number" min="0" placeholder="0 — anyone, any time" />
      </label>
      <p class="field-note">
        Leave at 0 and anyone can join at any point, part-way through. Set it if your session builds to
        something: walking in just before the close means seeing the ask without the argument, and that is
        a first impression you cannot repair. Only you know where your content turns, so there is no
        default.
      </p>

      <template v-if="editing.delivery !== 'live'">
        <label class="offer-field">
          <span>The recording</span>
          <input ref="videoInput" type="file" accept="video/mp4,video/webm" hidden @change="pickVideo" />
          <div class="element-subrow">
            <button class="secondary-action" type="button" :disabled="uploading" @click="videoInput?.click()">
              {{ uploading ? uploadLabel : (editing.video_url ? "Replace recording" : "Upload a recording") }}
            </button>
            <button v-if="editing.video_url && !uploading" class="danger-action compact" type="button"
                    @click="editing.video_url = ''">Remove</button>
          </div>
        </label>
        <p v-if="videoError" class="keys-status-banner error">{{ videoError }}</p>
        <video v-else-if="editing.video_url" class="event-recording-preview" :src="editing.video_url" controls preload="metadata"></video>
        <p class="field-note">
          MP4 plays everywhere; WebM will not play on older iPhones. The recording is not converted, so
          whatever you upload is what every attendee has to play. It starts at the scheduled time and
          follows the clock — someone arriving late joins part-way in, exactly as they would a live session.
        </p>
      </template>

      <template v-else>
        <label class="offer-field">
          <span>Where it runs</span>
          <select v-model="editing.provider">
            <option value="zoom">Zoom</option>
            <option value="webinarjam">WebinarJam</option>
            <option value="meet">Google Meet</option>
            <option value="teams">Microsoft Teams</option>
            <option value="other">Somewhere else</option>
          </select>
        </label>
        <label class="offer-field">
          <span>Join link <small>(optional for now)</small></span>
          <input v-model.trim="editing.join_url" type="url" placeholder="https://zoom.us/j/…" />
        </label>
        <p class="field-note">
          Registrants will be sent this link. You can add it later — the session can be scheduled before the
          meeting exists.
        </p>
      </template>

      <div class="composition-subhead">Sessions</div>
      <p class="field-note">
        One row per time you run it. Two rows is how you cover two time zones.
      </p>
      <div v-for="(row, index) in editing.occurrences" :key="row.occurrence_id" class="element-subrow">
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Starts</span>
            <input :value="toLocal(row.starts_at)" type="datetime-local"
                   @input="row.starts_at = fromLocal($event.target.value)" />
          </label>
          <label class="offer-field">
            <span>Time zone <small>(how it is announced)</small></span>
            <select v-model="row.timezone">
              <option v-for="zone in timeZoneOptions(row.timezone)" :key="zone" :value="zone">{{ zone }}</option>
            </select>
          </label>
        </div>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Seats <small>(0 = no limit)</small></span>
            <input v-model.number="row.capacity" type="number" min="0" />
          </label>
          <label class="offer-field">
            <span>Status</span>
            <select v-model="row.status">
              <option value="scheduled">Scheduled</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </label>
        </div>
        <p class="field-note">
          {{ row.registered_count || 0 }} registered{{ row.capacity ? ` of ${row.capacity}` : "" }}.
          <template v-if="!row.starts_at">Pick a date, or this session is not offered.</template>
        </p>
        <button class="danger-action compact" type="button" @click="editing.occurrences.splice(index, 1)">
          Remove session
        </button>
      </div>
      <button class="secondary-action compact" type="button" @click="addOccurrence">+ Add session</button>

      <footer class="builder-footer">
        <button class="secondary-action" type="button" @click="editing = null">Cancel</button>
        <button class="primary-action" type="button" :disabled="saving || !editing.title" @click="save">
          {{ saving ? "Saving…" : "Save Event" }}
        </button>
      </footer>
      <p v-if="saveError" class="field-error">{{ saveError }}</p>
    </section>
  </section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { uploadVideo } from "../api/uploads";
import { useEventsStore } from "../stores/events";
import { useProfileStore } from "../stores/profile";
import { timeZoneOptions } from "../utils/timezones";

const store = useEventsStore();
const profileStore = useProfileStore();
const editing = ref(null);
const saving = ref(false);
const saveError = ref("");
const videoInput = ref(null);
const videoError = ref("");
const uploading = ref(false);
const uploadLabel = ref("Uploading…");

onMounted(() => store.ensureLoaded());

function localId(prefix) {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
  const cryptoApi = globalThis.crypto;
  const bytes = cryptoApi?.getRandomValues ? cryptoApi.getRandomValues(new Uint8Array(11)) : null;
  const suffix = Array.from({ length: 11 }, (_, i) =>
    alphabet[(bytes ? bytes[i] : Math.floor(Math.random() * 62)) % alphabet.length]).join("");
  return `${prefix}_${suffix}`;
}

function browserTimeZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

// The store's own zone is the right first guess; each session can override it, because a business in
// Denver can run one sitting announced in EST and another in AEST.
function defaultZone() {
  return profileStore.business?.timezone || browserTimeZone();
}

function toLocal(secs) {
  if (!secs) return "";
  const d = new Date(secs * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fromLocal(value) {
  if (!value) return 0;
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? 0 : Math.floor(ms / 1000);
}

function emptyOccurrence() {
  return { occurrence_id: localId("occ"), starts_at: 0, timezone: defaultZone(), capacity: 0,
           registered_count: 0, status: "scheduled" };
}

function startNew() {
  saveError.value = "";
  editing.value = {
    schema_version: "1.0.0", document_type: "event", event_id: localId("ev"),
    title: "", description: "", delivery: "auto", provider: "zoom", join_url: "", video_url: "",
    duration_minutes: 60, late_join_minutes: 0,
    occurrences: [emptyOccurrence()],
  };
}

function startEdit(item) {
  saveError.value = "";
  videoError.value = "";
  // A deep-ish copy so Cancel really cancels: editing the stored object would leave the list showing
  // changes that were never saved.
  // `delivery` is defaulted HERE as well as on the server, and to the same value, so an event saved
  // before the field existed opens on Automated rather than on an empty select.
  editing.value = {
    delivery: "auto", video_url: "", late_join_minutes: 0,
    ...item,
    occurrences: (item.occurrences || []).map((row) => ({ ...row })),
  };
}

// The recording. uploadVideo owns the format gate and the size ceiling -- the ceiling is a parameter on
// the image-processing stack, never a number copied into this repo (docs/EXTERNAL_SERVICES.md).
async function pickVideo(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  videoError.value = "";
  uploading.value = true;
  uploadLabel.value = "Uploading…";
  try {
    editing.value.video_url = await uploadVideo(file, {
      basePrefix: "events",
      onProgress: ({ phase, percent }) => {
        uploadLabel.value = phase === "processing" ? "Processing…" : `Uploading ${Math.round(percent || 0)}%`;
      },
    });
  } catch (err) {
    videoError.value = err?.message || "That video could not be uploaded.";
  } finally {
    uploading.value = false;
  }
}

function addOccurrence() {
  editing.value.occurrences.push(emptyOccurrence());
}

function occurrenceSummary(item) {
  const rows = (item.occurrences || []).filter((row) => row.starts_at);
  if (!rows.length) return "no sessions scheduled";
  const next = [...rows].sort((a, b) => a.starts_at - b.starts_at)[0];
  const when = new Date(next.starts_at * 1000).toLocaleString(undefined, {
    weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
  return rows.length === 1 ? when : `${when} + ${rows.length - 1} more`;
}

async function save() {
  saving.value = true;
  saveError.value = "";
  try {
    // Sessions with no date are dropped rather than refused: a half-filled row is a tenant who added one
    // and changed their mind, and failing the save over it would lose everything else they typed.
    const document = {
      ...editing.value,
      duration_minutes: Number(editing.value.duration_minutes) || undefined,
      delivery: editing.value.delivery === "live" ? "live" : "auto",
      // 0 is a real value here ("anyone, any time"), so it must survive rather than become undefined the
      // way an optional number normally would.
      late_join_minutes: Math.max(0, Number(editing.value.late_join_minutes) || 0),
      // The OTHER mode's fields are dropped on save rather than carried along invisibly. An auto event
      // holding a stale join_url would have the page offer a room nobody is in, and the renderer prefers
      // the recording -- so the link would sit in the document being wrong and never being seen.
      join_url: editing.value.delivery === "live" ? (editing.value.join_url || undefined) : undefined,
      provider: editing.value.delivery === "live" ? (editing.value.provider || undefined) : undefined,
      video_url: editing.value.delivery === "live" ? undefined : (editing.value.video_url || undefined),
      occurrences: editing.value.occurrences
        .filter((row) => row.starts_at)
        .map((row) => ({ ...row, capacity: Number(row.capacity) || 0,
                         registered_count: Number(row.registered_count) || 0 })),
    };
    await store.save(document);
    editing.value = null;
  } catch (error) {
    saveError.value = error.message || "Could not save the event.";
  } finally {
    saving.value = false;
  }
}

async function remove(item) {
  const registered = (item.occurrences || []).reduce((n, row) => n + (Number(row.registered_count) || 0), 0);
  const warning = registered
    ? `"${item.title}" has ${registered} registration${registered === 1 ? "" : "s"}. Delete it anyway?`
    : `Delete "${item.title}"?`;
  if (!globalThis.confirm(warning)) return;
  try {
    await store.remove(item.event_id);
  } catch (error) {
    store.error = error.message || "Could not delete the event.";
  }
}
</script>
