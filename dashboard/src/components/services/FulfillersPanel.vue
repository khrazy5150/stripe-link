<template>
  <section class="dashboard-card">
    <header class="dashboard-card-header">
      <div>
        <h2>Fulfillers</h2>
        <p>Staff or delegates who fulfill appointments and receive compensation.</p>
      </div>
      <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load()">
        {{ store.loading ? "Loading..." : "Refresh" }}
      </button>
    </header>

    <div class="dashboard-card-body">
      <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>

      <form class="offer-form-section" @submit.prevent="save">
        <div class="offer-two-column">
          <label class="offer-field"><span>First Name</span><input v-model.trim="form.first_name" type="text" placeholder="Mary" /></label>
          <label class="offer-field"><span>Last Name</span><input v-model.trim="form.last_name" type="text" placeholder="Therapist" /></label>
        </div>
        <div class="offer-two-column">
          <label class="offer-field"><span>Email <strong>*</strong></span><input v-model.trim="form.email" type="email" placeholder="mary@example.com" required /></label>
          <label class="offer-field"><span>Phone</span><input v-model.trim="form.phone" type="tel" placeholder="+15551234567" /></label>
        </div>
        <div class="offer-two-column">
          <label class="offer-field"><span>Display Name</span><input v-model.trim="form.display_name" type="text" placeholder="Mary Therapist" /></label>
          <label class="offer-field">
            <span>Status</span>
            <select v-model="form.status">
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="invited">Invited</option>
            </select>
          </label>
        </div>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Compensation Type</span>
            <select v-model="form.compensation_type">
              <option value="flat_fee">Flat Fee</option>
              <option value="percent">Percent</option>
              <option value="hourly">Hourly</option>
            </select>
          </label>
          <label class="offer-field"><span>Compensation Amount</span><input v-model.number="form.compensation_amount" type="number" min="0" step="0.01" /></label>
        </div>
        <label class="checkbox-row offer-checkbox-inline">
          <input v-model="form.tips_to_fulfiller" type="checkbox" />
          <span>Tips go to fulfiller</span>
        </label>

        <label class="offer-field">
          <span>Own calendar (for delegated bookings)</span>
          <select v-model="form.calendar_connection_id">
            <option value="">None — use the service / default calendar</option>
            <option v-for="c in calendar.connections" :key="c.connection_id" :value="c.connection_id" :disabled="!c.connected">
              {{ c.display_name }}{{ c.connected ? "" : " (not connected)" }}
            </option>
          </select>
        </label>
        <p v-if="form.calendar_connection_id && !calendarConnected(form.calendar_connection_id)" class="services-hint warning">
          This calendar is not connected — delegated bookings will fall back to the service/default calendar until it is reconnected.
        </p>

        <div class="services-subheading">Personal availability</div>
        <p class="services-hint">These weekly hours override tenant defaults when this fulfiller is assigned.</p>
        <WeeklyHours v-model="form.weekly_hours" />

        <div class="button-row services-form-actions">
          <button v-if="editing" type="button" class="secondary-action" @click="resetForm">Cancel</button>
          <button class="primary-action" type="submit" :disabled="store.saving">
            {{ store.saving ? "Saving..." : editing ? "Save Fulfiller" : "Add Fulfiller" }}
          </button>
        </div>
      </form>

      <table v-if="store.fulfillers.length" class="dashboard-table services-table">
        <thead><tr><th>Name</th><th>Email</th><th>Compensation</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>
          <tr v-for="fulfiller in store.fulfillers" :key="fulfiller.fulfiller_id">
            <td>{{ fulfillerDisplayName(fulfiller) }}</td>
            <td>{{ fulfiller.email }}</td>
            <td>{{ formatCompensation(fulfiller) }}</td>
            <td><span class="product-status" :class="fulfiller.status">{{ fulfiller.status }}</span></td>
            <td class="services-row-actions">
              <button type="button" class="secondary-action compact" @click="edit(fulfiller)">Edit</button>
              <button type="button" class="secondary-action compact danger" @click="pendingDelete = fulfiller">Delete</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="store.loaded" class="product-empty-state">No fulfillers yet. Add staff who deliver appointments.</p>
    </div>

    <ConfirmDialog
      :open="!!pendingDelete"
      danger
      title="Delete fulfiller?"
      confirm-label="Delete"
      @cancel="pendingDelete = null"
      @confirm="confirmRemove"
    >
      Delete fulfiller "{{ pendingDelete ? fulfillerDisplayName(pendingDelete) : "" }}"?
    </ConfirmDialog>
  </section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import WeeklyHours from "./WeeklyHours.vue";
import ConfirmDialog from "../shared/ConfirmDialog.vue";
import { defaultWeeklyHours } from "../../utils/weeklyHours";
import { fulfillerDisplayName, formatCompensation, useFulfillersStore } from "../../stores/fulfillers";
import { useCalendarStore } from "../../stores/calendar";

const store = useFulfillersStore();
const calendar = useCalendarStore();
const editing = ref(null);
const form = ref(defaultForm());
const pendingDelete = ref(null);

onMounted(() => {
  if (!store.loaded) store.load();
  if (!calendar.loaded) calendar.load();
});

function calendarConnected(connectionId) {
  return calendar.connections.some((c) => c.connection_id === connectionId && c.connected);
}

function defaultForm() {
  return {
    fulfiller_id: "",
    first_name: "",
    last_name: "",
    email: "",
    phone: "",
    display_name: "",
    status: "active",
    compensation_type: "flat_fee",
    compensation_amount: 0,
    tips_to_fulfiller: true,
    calendar_connection_id: "",
    weekly_hours: defaultWeeklyHours(),
    created_at: null,
  };
}

function resetForm() {
  editing.value = null;
  form.value = defaultForm();
}

function edit(fulfiller) {
  editing.value = fulfiller;
  form.value = {
    ...defaultForm(),
    fulfiller_id: fulfiller.fulfiller_id || "",
    first_name: fulfiller.first_name || "",
    last_name: fulfiller.last_name || "",
    email: fulfiller.email || "",
    phone: fulfiller.phone || "",
    display_name: fulfiller.display_name || "",
    status: fulfiller.status || "active",
    compensation_type: fulfiller.compensation?.type || "flat_fee",
    compensation_amount: Number(fulfiller.compensation?.amount || 0),
    tips_to_fulfiller: fulfiller.compensation?.tips_to_fulfiller !== false,
    calendar_connection_id: fulfiller.calendar_connection_id || "",
    weekly_hours: fulfiller.availability?.weekly_hours?.length ? fulfiller.availability.weekly_hours : defaultWeeklyHours(),
    created_at: fulfiller.created_at || null,
  };
}

async function save() {
  try {
    await store.saveFulfiller(form.value, editing.value);
    resetForm();
  } catch {
    /* error surfaced by store */
  }
}

async function confirmRemove() {
  const fulfiller = pendingDelete.value;
  if (!fulfiller) return;
  try {
    await store.removeFulfiller(fulfiller.fulfiller_id);
    if (editing.value?.fulfiller_id === fulfiller.fulfiller_id) resetForm();
  } catch {
    /* error surfaced by store */
  }
  pendingDelete.value = null;
}
</script>
