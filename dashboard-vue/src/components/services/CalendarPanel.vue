<template>
  <section class="dashboard-card">
    <header class="dashboard-card-header">
      <div>
        <h2>Calendar Sync</h2>
        <p>Connect a Google Calendar so bookings appear on it and its busy times block open slots.</p>
      </div>
      <button class="secondary-action" type="button" :disabled="store.loading" @click="store.loadStatus()">
        {{ store.loading ? "Checking..." : "Refresh" }}
      </button>
    </header>

    <div class="dashboard-card-body">
      <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
      <div v-else-if="store.connected" class="keys-status-banner">
        Connected to <strong>{{ store.connection.account_email }}</strong>.
      </div>
      <div v-else class="keys-status-banner">No calendar connected.</div>

      <div class="button-row">
        <button
          v-if="!store.connected"
          class="primary-action"
          type="button"
          :disabled="store.connecting"
          @click="connect"
        >
          {{ store.connecting ? "Opening Google…" : "Connect Google Calendar" }}
        </button>
        <button v-else class="secondary-action" type="button" @click="disconnect">Disconnect</button>
      </div>

      <p v-if="waiting" class="calendar-waiting">Waiting for you to finish in the Google window…</p>
    </div>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useCalendarStore } from "../../stores/calendar";

const store = useCalendarStore();
const waiting = ref(false);
let pollTimer = null;
let pollTries = 0;

onMounted(() => {
  store.loadStatus();
  window.addEventListener("focus", onFocus);
});

onBeforeUnmount(() => {
  stopPolling();
  window.removeEventListener("focus", onFocus);
});

async function connect() {
  if (await store.connect()) startPolling();
}

async function disconnect() {
  try {
    await store.disconnect();
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
    await store.loadStatus();
    if (store.connected || pollTries >= 24) stopPolling();
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
  if (!store.connected) store.loadStatus();
}
</script>
