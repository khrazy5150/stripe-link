<template>
  <div class="weekly-hours">
    <div v-for="row in rows" :key="row.day" class="weekly-hours-row">
      <span class="weekly-hours-day">{{ dayLabel(row.day) }}</span>
      <label class="switch">
        <input type="checkbox" v-model="row.enabled" @change="emitChange" />
        <span class="switch-track" aria-hidden="true"></span>
      </label>
      <input type="time" v-model="row.start_time" :disabled="!row.enabled" @change="emitChange" />
      <input type="time" v-model="row.end_time" :disabled="!row.enabled" @change="emitChange" />
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from "vue";
import { dayLabel, normalizeWeeklyHours } from "../../utils/weeklyHours";

const props = defineProps({ modelValue: { type: Array, default: () => [] } });
const emit = defineEmits(["update:modelValue"]);

const rows = ref(normalizeWeeklyHours(props.modelValue));

watch(
  () => props.modelValue,
  (value) => {
    rows.value = normalizeWeeklyHours(value);
  },
);

function emitChange() {
  emit("update:modelValue", rows.value.map((row) => ({ ...row })));
}
</script>
