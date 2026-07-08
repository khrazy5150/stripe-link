<template>
  <section class="dashboard-card">
    <header class="dashboard-card-header">
      <div>
        <h2>Tenant Availability</h2>
        <p>Default bookable hours, slot interval, and buffers.</p>
      </div>
    </header>

    <div class="dashboard-card-body">
      <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
      <div v-else-if="store.message" class="keys-status-banner">{{ store.message }}</div>

      <form class="offer-form-section" @submit.prevent="save">
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Timezone</span>
            <select v-model="form.timezone">
              <option v-for="tz in timezones" :key="tz" :value="tz">{{ tz }}</option>
            </select>
          </label>
          <label class="offer-field"><span>Slot Interval (minutes)</span><input v-model.number="form.slot_interval_minutes" type="number" min="1" step="5" /></label>
        </div>
        <div class="offer-three-column">
          <label class="offer-field"><span>Lead Time (minutes)</span><input v-model.number="form.lead_time_minutes" type="number" min="0" step="5" /></label>
          <label class="offer-field"><span>Buffer Before (minutes)</span><input v-model.number="form.buffer_before_minutes" type="number" min="0" step="5" /></label>
          <label class="offer-field"><span>Buffer After (minutes)</span><input v-model.number="form.buffer_after_minutes" type="number" min="0" step="5" /></label>
        </div>

        <WeeklyHours v-model="form.weekly_hours" />

        <div class="button-row services-form-actions">
          <button class="primary-action" type="submit" :disabled="store.saving">
            {{ store.saving ? "Saving..." : "Save Defaults" }}
          </button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import WeeklyHours from "./WeeklyHours.vue";
import { defaultWeeklyHours } from "../../utils/weeklyHours";
import { timeZoneOptions } from "../../utils/timezones";
import { useTenantAvailabilityStore } from "../../stores/tenantAvailability";

const store = useTenantAvailabilityStore();
const form = ref(defaultForm());
const timezones = computed(() => timeZoneOptions(form.value.timezone));

onMounted(async () => {
  if (!store.loaded) await store.load();
  hydrate();
});

watch(() => store.availability, hydrate);

function defaultForm() {
  return {
    timezone: "America/Denver",
    slot_interval_minutes: 30,
    lead_time_minutes: 60,
    buffer_before_minutes: 0,
    buffer_after_minutes: 0,
    weekly_hours: defaultWeeklyHours(),
  };
}

function hydrate() {
  const a = store.availability;
  if (!a) return;
  form.value = {
    timezone: a.timezone || "America/Denver",
    slot_interval_minutes: Number(a.slot_interval_minutes || 30),
    lead_time_minutes: Number(a.lead_time_minutes || 60),
    buffer_before_minutes: Number(a.buffer_before_minutes || 0),
    buffer_after_minutes: Number(a.buffer_after_minutes || 0),
    weekly_hours: a.weekly_hours?.length ? a.weekly_hours : defaultWeeklyHours(),
  };
}

async function save() {
  try {
    await store.saveDefaults(form.value);
  } catch {
    /* error surfaced by store */
  }
}
</script>
