<template>
  <section class="dashboard-card">
    <header class="dashboard-card-header">
      <div>
        <h2>Availability Exceptions</h2>
        <p>Block time off (vacations, holidays) for everyone or a specific fulfiller.</p>
      </div>
    </header>

    <div class="dashboard-card-body">
      <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>

      <form class="offer-form-section" @submit.prevent="save">
        <div class="offer-two-column">
          <label class="offer-field"><span>Exception Start</span><input v-model="form.starts_at" type="datetime-local" /></label>
          <label class="offer-field"><span>Exception End</span><input v-model="form.ends_at" type="datetime-local" /></label>
        </div>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Type</span>
            <select v-model="form.type">
              <option value="block">Block</option>
              <option value="open">Open</option>
            </select>
          </label>
          <label class="offer-field"><span>Reason</span><input v-model.trim="form.reason" type="text" placeholder="Vacation" /></label>
        </div>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Fulfiller Scope</span>
            <select v-model="form.fulfiller_scope">
              <option value="all">All fulfillers</option>
              <option value="specific">Specific fulfiller</option>
            </select>
          </label>
          <label v-if="form.fulfiller_scope === 'specific'" class="offer-field">
            <span>Fulfiller</span>
            <select v-model="form.fulfiller_id">
              <option value="">Select fulfiller</option>
              <option v-for="f in fulfillers.fulfillers" :key="f.fulfiller_id" :value="f.fulfiller_id">
                {{ fulfillerDisplayName(f) }}
              </option>
            </select>
          </label>
        </div>
        <p class="services-hint">Choose a specific fulfiller to block only that person, or leave as "All" to block everyone.</p>

        <div class="button-row services-form-actions">
          <button class="primary-action" type="submit" :disabled="store.saving">
            {{ store.saving ? "Adding..." : "Add Exception" }}
          </button>
        </div>
      </form>

      <table v-if="store.exceptions.length" class="dashboard-table services-table">
        <thead><tr><th>Start</th><th>End</th><th>Fulfiller</th><th>Type</th><th>Reason</th><th>Actions</th></tr></thead>
        <tbody>
          <tr v-for="exception in store.exceptions" :key="exception.exception_id">
            <td>{{ formatDateTime(exception.starts_at) }}</td>
            <td>{{ formatDateTime(exception.ends_at) }}</td>
            <td>{{ scopeLabel(exception) }}</td>
            <td>{{ exception.type }}</td>
            <td>{{ exception.reason || "—" }}</td>
            <td class="services-row-actions">
              <button type="button" class="secondary-action compact danger" @click="remove(exception)">Delete</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="store.loaded" class="product-empty-state">No availability exceptions yet.</p>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { useAvailabilityExceptionsStore } from "../../stores/availabilityExceptions";
import { fulfillerDisplayName, useFulfillersStore } from "../../stores/fulfillers";

const store = useAvailabilityExceptionsStore();
const fulfillers = useFulfillersStore();
const form = ref(defaultForm());

onMounted(() => {
  if (!store.loaded) store.load();
  if (!fulfillers.loaded) fulfillers.load();
});

function defaultForm() {
  return { starts_at: "", ends_at: "", type: "block", reason: "", fulfiller_scope: "all", fulfiller_id: "" };
}

function scopeLabel(exception) {
  if (exception.fulfiller_scope !== "specific") return "All";
  const match = fulfillers.fulfillers.find((f) => f.fulfiller_id === exception.fulfiller_id);
  return match ? fulfillerDisplayName(match) : "Specific";
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

async function save() {
  if (!form.value.starts_at || !form.value.ends_at) {
    store.error = "Start and end are required.";
    return;
  }
  try {
    await store.saveException(form.value);
    form.value = defaultForm();
  } catch {
    /* error surfaced by store */
  }
}

async function remove(exception) {
  if (!window.confirm("Delete this availability exception?")) return;
  try {
    await store.removeException(exception.exception_id);
  } catch {
    /* error surfaced by store */
  }
}
</script>
