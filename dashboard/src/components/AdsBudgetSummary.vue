<template>
  <section v-if="amountMicros > 0" class="ads-budget-summary" aria-label="Budget and spend estimate">
    <div>
      <span>Average daily budget</span>
      <strong>{{ formatUsd(amountMicros) }}</strong>
    </div>
    <label v-if="adjustable" class="offer-field">
      <span>Estimate period</span>
      <select :value="days" @change="$emit('update:days', Number($event.target.value))">
        <option v-for="option in ESTIMATE_DAYS" :key="option" :value="option">{{ option }} days</option>
      </select>
    </label>
    <div>
      <span>Estimated spend for {{ days }} days</span>
      <strong>{{ formatUsd(spendEstimate(amountMicros, days)) }}</strong>
    </div>
    <div class="ads-budget-notes">
      <p>Google can exceed {{ formatUsd(amountMicros) }} on an individual day. For most campaigns at this unchanged average, Google’s usual spending limits are {{ formatUsd(amountMicros * 2) }} per day and {{ formatUsd(amountMicros * 30.4) }} per full month.</p>
      <p>The estimate multiplies the average by the number of days. Actual spend can vary. Google may continue serving until it confirms the stop.</p>
      <a href="https://support.google.com/google-ads/answer/6385083" target="_blank" rel="noopener noreferrer">Google Ads budget rules</a>
    </div>
  </section>
</template>

<script setup>
import { ESTIMATE_DAYS, formatUsd, spendEstimate } from "../utils/adsPromo";

defineProps({
  amountMicros: { type: Number, required: true },
  days: { type: Number, required: true },
  adjustable: { type: Boolean, default: false },
});
defineEmits(["update:days"]);
</script>

<style scoped>
.ads-budget-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 15rem), 1fr));
  align-items: start;
  gap: 1.4rem;
  padding: 1.6rem;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
}
.ads-budget-summary strong { display: block; margin-top: .35rem; font-size: 1.8rem; }
.ads-budget-notes { grid-column: 1 / -1; color: var(--muted); }
.ads-budget-notes p { margin: 0 0 .65rem; }
</style>
