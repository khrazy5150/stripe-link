<template>
  <section class="dashboard-card">
    <header class="dashboard-card-header">
      <div>
        <h2>Appointments</h2>
        <p>Booked appointments and their lifecycle.</p>
      </div>
      <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load()">
        {{ store.loading ? "Loading..." : "Refresh" }}
      </button>
    </header>

    <div class="dashboard-card-body">
      <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>

      <div class="appt-layout">
        <div class="appt-calendar">
          <div class="appt-calendar-head">
            <div class="button-row">
              <button type="button" class="secondary-action compact" @click="shift(-1)">Prev</button>
              <strong class="appt-period">{{ periodLabel }}</strong>
              <button type="button" class="secondary-action compact" @click="shift(1)">Next</button>
            </div>
            <div class="button-row">
              <button type="button" class="secondary-action compact" :class="{ active: viewMode === 'month' }" @click="viewMode = 'month'">Month</button>
              <button type="button" class="secondary-action compact" :class="{ active: viewMode === 'week' }" @click="viewMode = 'week'">Week</button>
              <button type="button" class="secondary-action compact" :class="{ active: isViewingToday }" @click="goToday">Today</button>
            </div>
          </div>

          <div class="appt-weekdays">
            <span v-for="w in weekdayLabels" :key="w">{{ w }}</span>
          </div>
          <div class="appt-grid">
            <button
              v-for="cell in cells"
              :key="cell.key"
              type="button"
              class="appt-cell"
              :class="{ muted: !cell.inPeriod, today: cell.key === todayKey, selected: cell.key === selectedDay }"
              @click="selectedDay = cell.key"
            >
              <span class="appt-cell-day">{{ cell.day }}</span>
              <span v-if="countByDay[cell.key]" class="appt-count">{{ countByDay[cell.key] }}</span>
            </button>
          </div>
        </div>

        <div class="appt-selected">
          <div class="services-subheading">{{ selectedDayLabel }}</div>
          <p v-if="!selectedDayAppointments.length" class="product-empty-state">No appointments this day.</p>
          <ul v-else class="appt-day-list">
            <li v-for="a in selectedDayAppointments" :key="a.appointment_id">
              <strong>{{ formatTime(a.starts_at) }}</strong> · {{ a.service_name || a.service_id }}
              <span class="product-status" :class="a.status">{{ statusLabel(a.status) }}</span>
            </li>
          </ul>
        </div>
      </div>

      <table v-if="store.appointments.length" class="dashboard-table services-table">
        <thead><tr><th>Service</th><th>Start</th><th>Customer</th><th>Fulfiller</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>
          <tr v-for="a in sortedAppointments" :key="a.appointment_id">
            <td>{{ a.service_name || a.service_id }}</td>
            <td>{{ formatDateTime(a.starts_at) }}</td>
            <td>{{ a.customer?.name || a.customer?.email || "—" }}</td>
            <td>{{ fulfillerName(a.assigned_fulfiller_id) }}</td>
            <td><span class="product-status" :class="a.status">{{ statusLabel(a.status) }}</span></td>
            <td class="services-row-actions">
              <button
                v-for="action in availableActions(a.status)"
                :key="action"
                type="button"
                class="secondary-action compact"
                :disabled="store.acting === `${a.appointment_id}:${action}`"
                @click="run(a, action)"
              >
                {{ actionLabel(action) }}
              </button>
              <select
                v-if="fulfillers.fulfillers.length && !isTerminal(a.status)"
                class="appt-assign"
                :value="a.assigned_fulfiller_id || ''"
                @change="assign(a, $event.target.value)"
              >
                <option value="">Assign…</option>
                <option v-for="f in fulfillers.fulfillers" :key="f.fulfiller_id" :value="f.fulfiller_id">
                  {{ fulfillerDisplayName(f) }}
                </option>
              </select>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="store.loaded" class="product-empty-state">No appointments yet.</p>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { actionLabel, availableActions, useAppointmentsStore } from "../../stores/appointments";
import { fulfillerDisplayName, useFulfillersStore } from "../../stores/fulfillers";

const store = useAppointmentsStore();
const fulfillers = useFulfillersStore();

const viewMode = ref("month");
const cursor = ref(new Date());
const selectedDay = ref(dateKey(new Date()));
const todayKey = dateKey(new Date());
const weekdayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

onMounted(() => {
  if (!store.loaded) store.load();
  if (!fulfillers.loaded) fulfillers.load();
});

function dateKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
function startOfWeek(date) {
  const d = new Date(date);
  d.setDate(d.getDate() - d.getDay());
  d.setHours(0, 0, 0, 0);
  return d;
}
function isTerminal(status) {
  return ["completed", "canceled", "no_show"].includes(status);
}

const cells = computed(() => {
  const out = [];
  if (viewMode.value === "week") {
    const start = startOfWeek(cursor.value);
    for (let i = 0; i < 7; i += 1) {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      out.push({ key: dateKey(d), day: d.getDate(), inPeriod: true });
    }
    return out;
  }
  const first = new Date(cursor.value.getFullYear(), cursor.value.getMonth(), 1);
  const gridStart = startOfWeek(first);
  for (let i = 0; i < 42; i += 1) {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    out.push({ key: dateKey(d), day: d.getDate(), inPeriod: d.getMonth() === cursor.value.getMonth() });
  }
  return out;
});

const isViewingToday = computed(() => selectedDay.value === todayKey && cells.value.some((c) => c.key === todayKey));

const countByDay = computed(() => {
  const map = {};
  for (const a of store.appointments) {
    if (!a.starts_at) continue;
    const key = dateKey(new Date(a.starts_at));
    map[key] = (map[key] || 0) + 1;
  }
  return map;
});

const selectedDayAppointments = computed(() =>
  store.appointments
    .filter((a) => a.starts_at && dateKey(new Date(a.starts_at)) === selectedDay.value)
    .sort((x, y) => String(x.starts_at).localeCompare(String(y.starts_at))),
);

const sortedAppointments = computed(() =>
  [...store.appointments].sort((x, y) => String(y.starts_at || "").localeCompare(String(x.starts_at || ""))),
);

const periodLabel = computed(() => {
  if (viewMode.value === "week") {
    const start = startOfWeek(cursor.value);
    return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(start);
  }
  return new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric" }).format(cursor.value);
});

const selectedDayLabel = computed(() => {
  const parts = selectedDay.value.split("-").map(Number);
  const d = new Date(parts[0], parts[1] - 1, parts[2]);
  return new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric" }).format(d);
});

function shift(direction) {
  const d = new Date(cursor.value);
  if (viewMode.value === "week") d.setDate(d.getDate() + direction * 7);
  else d.setMonth(d.getMonth() + direction);
  cursor.value = d;
}
function goToday() {
  cursor.value = new Date();
  selectedDay.value = dateKey(new Date());
}
function fulfillerName(id) {
  if (!id) return "—";
  const match = fulfillers.fulfillers.find((f) => f.fulfiller_id === id);
  return match ? fulfillerDisplayName(match) : id;
}
function statusLabel(status) {
  return String(status || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
function formatTime(value) {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : new Intl.DateTimeFormat("en-US", { timeStyle: "short" }).format(d);
}
function formatDateTime(value) {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(d);
}
async function run(appointment, action) {
  try {
    await store.act(appointment.appointment_id, action);
  } catch {
    /* error surfaced by store */
  }
}
async function assign(appointment, fulfillerId) {
  if (!fulfillerId) return;
  try {
    await store.act(appointment.appointment_id, "assign", { assigned_fulfiller_id: fulfillerId });
  } catch {
    /* error surfaced by store */
  }
}
</script>
