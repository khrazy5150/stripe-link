<template>
  <!-- The amounts a tip jar offers. ONE component, used by the create wizard and by the full price editor,
       because a tenant who sets presets in the wizard and then edits the product must meet the same field --
       and because presets were previously only settable at creation. -->
  <div class="tip-amounts">
    <ul class="tip-amount-rows">
      <li v-for="(amount, index) in price.presets" :key="index">
        <label class="tip-amount-input">
          <span aria-hidden="true">{{ currencySymbol }}</span>
          <input
            v-model.number="price.presets[index]"
            type="number"
            :min="TIP_MIN"
            :max="TIP_MAX"
            step="1"
            :aria-label="`Tip amount ${index + 1}`"
          />
        </label>
        <!-- The whole point of this field: "Sales price" says nothing about who pays the fees, so the two
             numbers that actually matter are spelled out per amount, and they move when the mode does. -->
        <span class="tip-amount-preview">
          Customer pays <strong>{{ previewFor(amount).pays }}</strong> ·
          you keep <strong>{{ previewFor(amount).keeps }}</strong>
        </span>
        <button type="button" class="link-danger" :aria-label="`Remove amount ${index + 1}`"
                @click="price.presets.splice(index, 1)">Remove</button>
      </li>
    </ul>
    <div class="button-row">
      <button v-if="price.presets.length < presetCap" class="secondary-action compact" type="button"
              @click="addPreset()">+ Amount</button>
      <!-- So nobody has to invent a ladder. Frequency-aware on purpose: the same number means different
           things — $50 is an ordinary one-off tip and a steep monthly commitment. -->
      <!-- Primary, not secondary: it is the shortcut past the decision most tenants stall on, and a white
           button undersells it (author, 2026-09-14). -->
      <button class="primary-action compact" type="button" @click="useRecommended()">
        Use recommended amounts
      </button>
    </div>
    <span class="field-note">
      You enter what you want to keep. Up to {{ presetCap }} amounts — the buttons sit in one row, and
      “enter your own” takes one of the places. Recommended: {{ recommendedSummary }}.
    </span>

    <label class="modal-checkbox">
      <input v-model="price.allow_custom" type="checkbox" />
      Let them enter their own amount
    </label>
    <!-- The range is Junior Bay's, not the tenant's: a floor Stripe will actually charge, and a ceiling that
         keeps a mistyped amount from becoming a dispute. Shown, not editable — the server overwrites
         whatever a price document claims. -->
    <p class="field-note">
      The buyer may pay {{ formatMoney(TIP_RULES.min_amount, price.currency) }} to
      {{ formatMoney(TIP_RULES.max_amount, price.currency) }}. Junior Bay sets that range.
    </p>

    <label class="modal-checkbox">
      <input v-model="price.allow_recurring" type="checkbox" />
      Let them make it a recurring donation
    </label>
    <template v-if="price.allow_recurring">
      <label>
        How often
        <select v-model="price.recurring_interval">
          <option v-for="option in TIP_INTERVALS" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
        <span class="field-note">
          The page offers {{ intervalLabel }} first — defaulting a donation form to repeating rather than
          merely offering it raises repeating gifts sharply, and the default is the lever, not the only
          option.
        </span>
      </label>
      <!-- Off = a membership: repeating unlocks something, and a one-off payment for it would buy nothing.
           On (the default) = both, with the repeating option pre-selected. -->
      <label class="modal-checkbox">
        <input v-model="price.allow_one_time" type="checkbox" />
        Also accept one-time tips
      </label>
      <p v-if="!price.allow_one_time" class="field-note">
        This jar takes {{ intervalLabel.toLowerCase() }} support only. Someone who will not commit to a
        repeating tip has no way to give — worth it when {{ intervalLabel.toLowerCase() }} unlocks something,
        and costly when it does not.
      </p>
    </template>
  </div>
</template>

<script setup>
import { computed, watch } from "vue";
import { TIP_INTERVALS, TIP_MAX, TIP_MIN, TIP_RULES, maxTipPresets, recommendedTipPresets } from "../../config/tips";
import { amountPreviewFor } from "../../utils/priceForm";
import { formatMoney } from "../../stores/products";

const props = defineProps({
  // The price FORM row (dollars in inputs), mutated in place — the same contract PricingCard already uses.
  price: { type: Object, required: true },
  productType: { type: String, default: "digital" },
});

const currencySymbol = computed(() => formatMoney(0, props.price.currency).replace(/[\d.,\s]/g, "") || "$");

// How many preset buttons fit, from the rules file the server validates against.
const presetCap = computed(() => maxTipPresets(props.price.allow_custom !== false));

const intervalLabel = computed(() =>
  (TIP_INTERVALS.find((option) => option.value === props.price.recurring_interval) || TIP_INTERVALS[0]).label);

// The ladder this jar would get: lower when it repeats, one shorter when "enter your own" takes a place.
const recommended = computed(() => recommendedTipPresets(
  Boolean(props.price.allow_recurring), props.price.allow_custom !== false, props.price.currency));
const recommendedSummary = computed(() =>
  recommended.value.map((amount) => formatMoney(amount * 100, props.price.currency)).join(" · "));

function useRecommended() {
  props.price.presets = [...recommended.value];
}

function previewFor(amount) {
  return amountPreviewFor(amount, props.price, props.productType);
}

// A new button gets an amount nobody is using yet: pushing a constant produced a duplicate row the moment
// the tenant already had that amount, and duplicates are refused on save.
function addPreset() {
  const taken = new Set((props.price.presets || []).map(Number));
  const ladder = [5, 10, 25, 50, 100, 250, 500];
  const next = ladder.find((amount) => !taken.has(amount) && amount <= TIP_MAX);
  props.price.presets.push(next ?? Math.min(TIP_MAX, Math.max(...taken, 0) + 5));
}

// Offering a custom amount costs one of the five places, so turning it on with a full row has to give one
// back. Trimming the LAST one keeps the small amounts, which are the ones most people tap.
watch(() => props.price.allow_custom, () => {
  if (props.price.presets.length > presetCap.value) {
    props.price.presets = props.price.presets.slice(0, presetCap.value);
  }
});
</script>
