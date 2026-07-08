<template>
  <section class="dashboard-card">
    <header class="dashboard-card-header">
      <div>
        <h2>Calendar Sync</h2>
        <p>Connect one or more Google Calendars. The default calendar receives bookings and its busy
          times block open slots; you can add others to delegate services to different calendars.</p>
      </div>
      <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load()">
        {{ store.loading ? "Checking..." : "Refresh" }}
      </button>
    </header>

    <div class="dashboard-card-body">
      <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>

      <div v-if="!store.connections.length" class="keys-status-banner">
        {{ store.loaded ? "No calendars connected yet." : "Loading…" }}
      </div>

      <ul v-else class="calendar-connection-list">
        <li v-for="conn in store.connections" :key="conn.connection_id" class="calendar-connection">
          <div class="calendar-connection-main">
            <strong>{{ conn.display_name }}</strong>
            <span v-if="conn.is_default" class="product-status default">Default</span>
            <span class="product-status" :class="conn.connected ? 'connected' : 'error'">
              {{ conn.connected ? "Connected" : (conn.status || "not connected") }}
            </span>
            <p class="calendar-connection-email">{{ conn.account_email }}</p>
          </div>
          <div class="calendar-connection-actions">
            <button v-if="!conn.is_default && conn.connected" type="button" class="secondary-action compact" @click="setDefault(conn)">Make default</button>
            <button type="button" class="secondary-action compact" @click="rename(conn)">Rename</button>
            <button type="button" class="secondary-action compact" @click="askDisconnect(conn)">Disconnect</button>
          </div>
        </li>
      </ul>

      <div class="button-row">
        <button class="primary-action" type="button" :disabled="store.connecting" @click="connect">
          {{ store.connecting ? "Opening Google…" : store.connections.length ? "Connect another calendar" : "Connect Google Calendar" }}
        </button>
      </div>

      <p v-if="waiting" class="calendar-waiting">Waiting for you to finish in the Google window…</p>
    </div>

    <div v-if="renaming" class="modal-backdrop" @click.self="renaming = null">
      <section class="modal-card confirm-card" role="dialog" aria-modal="true" aria-labelledby="renameCalendarTitle">
        <h2 id="renameCalendarTitle">Rename calendar</h2>
        <p>Give this calendar a label your team will recognize.</p>
        <input
          ref="renameInput"
          v-model.trim="renameLabel"
          type="text"
          class="modal-input"
          placeholder="e.g. Downtown Salon"
          @keyup.enter="saveRename"
        />
        <div class="confirm-actions">
          <button type="button" class="secondary-action" @click="renaming = null">Cancel</button>
          <button type="button" class="primary-action" :disabled="!renameLabel" @click="saveRename">Save</button>
        </div>
      </section>
    </div>

    <div v-if="disconnecting" class="modal-backdrop" @click.self="disconnecting = null">
      <section class="modal-card confirm-card" role="dialog" aria-modal="true" aria-labelledby="disconnectCalendarTitle">
        <header class="confirm-icon danger">×</header>
        <h2 id="disconnectCalendarTitle">Disconnect calendar?</h2>
        <p>Disconnect "{{ disconnecting.display_name }}"? Bookings will stop syncing to it.</p>
        <div class="confirm-actions">
          <button type="button" class="secondary-action" @click="disconnecting = null">Cancel</button>
          <button type="button" class="primary-action" @click="disconnect">Disconnect</button>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useCalendarStore } from "../../stores/calendar";

const store = useCalendarStore();
const waiting = ref(false);
const renaming = ref(null);
const renameLabel = ref("");
const renameInput = ref(null);
const disconnecting = ref(null);
let pollTimer = null;
let pollTries = 0;
let baselineCount = 0;

onMounted(() => {
  store.load();
  window.addEventListener("focus", onFocus);
});

onBeforeUnmount(() => {
  stopPolling();
  window.removeEventListener("focus", onFocus);
});

async function connect() {
  baselineCount = store.connections.length;
  if (await store.connect()) startPolling();
}

async function setDefault(conn) {
  try {
    await store.setDefault(conn.connection_id);
  } catch {
    /* error surfaced by store */
  }
}

function rename(conn) {
  renaming.value = conn;
  renameLabel.value = conn.display_name || conn.account_email || "";
  nextTick(() => renameInput.value?.focus());
}

async function saveRename() {
  const conn = renaming.value;
  const label = renameLabel.value.trim();
  if (!conn || !label) {
    renaming.value = null;
    return;
  }
  if (label !== conn.display_name) {
    try {
      await store.rename(conn.connection_id, label);
    } catch {
      /* error surfaced by store */
    }
  }
  renaming.value = null;
}

function askDisconnect(conn) {
  disconnecting.value = conn;
}

async function disconnect() {
  const conn = disconnecting.value;
  disconnecting.value = null;
  if (!conn) return;
  try {
    await store.disconnect(conn.connection_id);
  } catch {
    /* error surfaced by store */
  }
}

function startPolling() {
  stopPolling();
  waiting.value = true;
  pollTries = 0;
  pollTimer = setInterval(async () => {
    pollTries += 1;
    await store.load();
    if (store.connections.length > baselineCount || pollTries >= 24) stopPolling();
  }, 2500);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  waiting.value = false;
}

function onFocus() {
  if (waiting.value) store.load();
}
</script>
