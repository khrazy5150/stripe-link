<template>
  <label class="product-unit-cost">
    What this costs you
    <span class="currency-input">
      <span class="currency-symbol" aria-hidden="true">$</span>
      <input
        v-model.trim="model"
        type="text"
        inputmode="decimal"
        placeholder="Leave blank if you don't know"
        aria-describedby="unit-cost-note"
      />
    </span>
    <span id="unit-cost-note" class="field-note">
      What you paid to acquire one unit — not what you sell it for. Used to work out your profit, and
      never shown to customers.
    </span>
    <!-- Blank and zero are different answers and the tenant has to be able to give either. A dropshipped
         item costs money; a digital download may genuinely cost nothing. Saying so explicitly is cheaper
         than a support question about why Profit is blank. -->
    <span v-if="blank" class="field-note">
      Without this, Reports can't show your profit. Enter <strong>0</strong> if this really costs you
      nothing.
    </span>
    <span v-else-if="invalid" class="field-warning">
      That doesn't look like an amount. Enter a number like 6.50, or leave it blank.
    </span>
    <span v-else-if="margin" class="field-note">{{ margin }}</span>
  </label>
</template>

<script setup>
/**
 * The per-unit ACQUISITION COST, in the tenant's own words.
 *
 * One component so the create wizard and the edit form ask the same question the same way. Held as a
 * STRING of dollars rather than a number of cents, because `""` and `"0"` have to stay different all the
 * way to the payload: absent means "nobody has costed this", zero means "this is genuinely free", and
 * collapsing the two is what makes a margin report overstate profit (plans/MONEY_ACROSS_SILOS.md P2).
 */
import { computed } from "vue";
import { formatMoney } from "../../stores/products";

const props = defineProps({
  modelValue: { type: String, default: "" },
  // The sale price in cents, when there is one, purely to show the tenant their margin as they type. It is
  // feedback, not arithmetic anyone relies on — the real figure is computed server-side from the ledger.
  unitAmount: { type: Number, default: 0 },
  currency: { type: String, default: "usd" },
});
const emit = defineEmits(["update:modelValue"]);

const model = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

const blank = computed(() => String(props.modelValue || "").trim() === "");
const parsed = computed(() => Number(String(props.modelValue || "").trim()));
const invalid = computed(() => !blank.value && (!Number.isFinite(parsed.value) || parsed.value < 0));

const margin = computed(() => {
  if (blank.value || invalid.value || !props.unitAmount) return "";
  const costCents = Math.round(parsed.value * 100);
  const gross = props.unitAmount - costCents;
  const pct = props.unitAmount > 0 ? Math.round((gross / props.unitAmount) * 100) : 0;
  // Named "before fees" deliberately. Stripe and the platform both take a cut, so a tenant told "60%
  // margin" here and shown a smaller profit in Reports would reasonably think one of them was lying.
  return `${formatMoney(gross, props.currency)} per unit before fees (${pct}%).`;
});
</script>

<style scoped>
.currency-input {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.currency-symbol {
  opacity: 0.7;
}
.currency-input input {
  flex: 1;
}
</style>
