<template>
  <div class="modal-pricing-card">
    <header>
      <div>
        <h3>{{ title }}</h3>
        <p v-if="subtitle">{{ subtitle }}</p>
      </div>
    </header>

    <div v-for="(price, index) in prices" :key="price.form_id" class="product-price-row">
      <div class="price-row-heading">
        <strong>Price {{ index + 1 }}</strong>
        <div class="price-row-actions">
          <label class="default-price-check">
            <input type="checkbox" :checked="defaultIndex === index" @change="$emit('update:defaultIndex', index)" />
            Default price
          </label>
          <button
            v-if="allowMultiple"
            type="button"
            class="secondary-action danger-action"
            :disabled="prices.length === 1"
            @click="removePrice(index)"
          >
            Remove
          </button>
        </div>
      </div>

      <div class="price-top-row">
        <!-- A tip jar has no sales price: the buyer picks from the amounts below, and a number typed here
             was the field that used to decide what a "customer chooses" product actually sold for. -->
        <label v-if="price.pricing_model !== 'customer_chooses'">Sales price
          <input v-model.number="price.sales_price" type="number" min="0" step="0.01" />
        </label>
        <label v-if="price.pricing_model !== 'customer_chooses'">Regular price
          <input v-model.number="price.regular_price" type="number" min="0" step="0.01" />
        </label>
        <label>Currency
          <select v-model="price.currency">
            <option value="usd">USD</option>
          </select>
        </label>
        <label>Quantity
          <input v-model.number="price.quantity" type="number" min="1" step="1" />
        </label>
      </div>

      <div class="price-options-grid">
        <fieldset v-if="!isTipPrice(price) && pricingModels.length > 1">
          <legend>Pricing model</legend>
          <label v-for="[value, label] in pricingModels" :key="value">
            <input v-model="price.pricing_model" type="radio" :value="value" /> {{ label }}
          </label>
        </fieldset>
        <!-- A tip jar STATES its pricing model rather than offering to stop being one. It is what the
             "Receive tips" purpose produces, and the amounts below only mean anything under it — a radio
             that silently turned four presets into a dead list was the second route to a tip jar, without
             any of the guardrails the first one has. -->
        <fieldset v-else-if="isTipPrice(price)" class="price-model-stated">
          <legend>Pricing model</legend>
          <strong>Supporters choose the amount</strong>
          <small>Set by this product's purpose. To sell at a fixed price instead, create a product and choose
            “Sell something”.</small>
        </fieldset>
        <fieldset>
          <legend>Fee handling</legend>
          <label><input v-model="price.fee_handling" type="radio" value="standard" /> Standard fees deducted</label>
          <label><input v-model="price.fee_handling" type="radio" value="split" /> Split 50/50 — fees shared with your buyer</label>
          <label><input v-model="price.fee_handling" type="radio" value="net_guaranteed" /> Net-guaranteed fees added on top</label>
        </fieldset>
      </div>

      <!-- HOW OFTEN it charges. Shown only for a recurring price, and required: a subscription with no
           interval is a one-time charge wearing the word "recurring", which is exactly what this used to
           save (plans/TODO.md, 2026-09-15). -->
      <fieldset v-if="price.pricing_model === 'recurring'" class="price-recurring-field">
        <legend>Billing</legend>
        <div class="price-recurring-row">
          <label>Billing interval
            <select v-model="price.billing_interval">
              <option value="" disabled>Choose how often…</option>
              <option v-for="[value, label] in BILLING_INTERVALS" :key="value" :value="value">{{ label }}</option>
            </select>
          </label>
          <label>Every
            <span class="price-interval-count">
              <input v-model.number="price.interval_count" type="number" min="1"
                     :max="maxIntervalCount(price)" step="1" :disabled="!price.billing_interval" />
              <span>{{ intervalUnit(price) }}</span>
            </span>
          </label>
        </div>
        <small v-if="!price.billing_interval" class="price-recurring-warning">
          ⚠ Choose an interval. Without one this saves as a single charge, not a subscription.
        </small>

        <!-- A trial here may be FREE or PAID, and the paid one is not a watered-down free one (author,
             2026-09-15). A physical product has a real unit cost before shipping is counted, so giving one
             away for a trial period loses money on every sign-up; a paid trial covers that cost and keeps
             freeloaders out while still pricing the first period below the subscription. It is the only
             trial a physical subscription can afford to offer. -->
        <label class="switch-row">
          <input v-model="price.trial_enabled" type="checkbox" />
          <span><strong>Enable trial period</strong><small>Let buyers start before the first full charge.</small></span>
        </label>
        <div v-if="price.trial_enabled" class="price-trial-options">
          <label>Trial length
            <span class="price-interval-count">
              <input v-model.number="price.trial_days" type="number" min="1" max="730" step="1" />
              <span>day(s)</span>
            </span>
          </label>
          <label>Trial price
            <input v-model.number="price.trial_price" type="number" min="0" step="0.01" />
            <!-- Stripe's own trial is free by definition and Checkout always renders "X days free" with no
                 way to reword it, so a paid trial is charged as its own one-time line beside the
                 subscription. Said plainly here because the tenant will otherwise see that wording and
                 think the charge was lost. -->
            <span class="field-note">
              {{ Number(price.trial_price) > 0
                ? "Charged once, up front, as a separate line. Stripe still shows the trial as free."
                : "Free — leave at 0 for a standard free trial." }}
            </span>
          </label>
        </div>
      </fieldset>

      <label class="price-context-field">Price context
        <select v-model="price.context">
          <option v-for="[value, label] in contexts" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
      <small v-if="redundancyWarning(price, index)" class="price-context-warning">⚠ {{ redundancyWarning(price, index) }}</small>

      <!-- A tip jar's real pricing: the amounts it offers, each showing what the buyer pays and what the
           tenant keeps under the mode above. The old pair of inputs here (Minimum / Suggested amount) is
           gone -- the platform owns the range now, and "suggested" was the deprecated single-amount shape
           presets replaced. -->
      <TipAmountsField v-if="price.pricing_model === 'customer_chooses'" :price="price" :product-type="productType" />

      <!-- One amount, one preview. A tip jar's previews are per-amount, inside the field above. -->
      <div v-if="price.pricing_model !== 'customer_chooses'" class="price-preview">
        <span>Preview:</span>
        <strong>{{ previewFor(price).amount }}</strong>
        <span v-if="previewFor(price).compareAt" class="price-preview-compare">{{ previewFor(price).compareAt }}</span>
        <span v-if="previewFor(price).discount" class="price-preview-discount">Save {{ previewFor(price).discount }}%</span>
        <span v-if="previewFor(price).note" class="price-preview-note">{{ previewFor(price).note }}</span>
        <span v-if="previewFor(price).youKeep" class="price-preview-note">You keep {{ previewFor(price).youKeep }}</span>
      </div>
    </div>

    <footer v-if="allowMultiple" class="price-card-footer">
      <button type="button" class="secondary-action" @click="addPrice">+ Add another price</button>
    </footer>
  </div>
</template>

<script setup>
import { BILLING_INTERVALS, MAX_INTERVAL_COUNT, defaultPriceForm, pricePreviewFor } from "../../utils/priceForm";
import TipAmountsField from "./TipAmountsField.vue";

const props = defineProps({
  prices: { type: Array, required: true },
  defaultIndex: { type: Number, default: 0 },
  productType: { type: String, default: "physical" },
  title: { type: String, default: "Pricing" },
  subtitle: { type: String, default: "" },
  allowMultiple: { type: Boolean, default: true },
  contexts: {
    type: Array,
    default: () => [["standard", "Standard"], ["sale", "Sale"], ["flash_sale", "Flash sale"], ["upsell", "Upsell"], ["downsell", "Downsell"], ["order_bump", "Order bump"]],
  },
  // What a tenant may CHOOSE here. "Customer chooses" is deliberately absent (author, 2026-09-15): a tip jar
  // is what the "Receive tips" purpose produces, and offering the same outcome as a radio on a product being
  // sold gave two routes to one thing — the second one skipping the fee-mode question the tip wizard asks
  // first, precisely because it changes what every amount below it means. Prices that ARE customer_chooses
  // still render in full; they just say so instead of asking.
  pricingModels: {
    type: Array,
    default: () => [["one_time", "One-time"], ["recurring", "Recurring"]],
  },
});
const emit = defineEmits(["update:defaultIndex"]);

function isTipPrice(price) {
  return price.pricing_model === "customer_chooses";
}

function maxIntervalCount(price) {
  return MAX_INTERVAL_COUNT[price.billing_interval] || 1;
}

// "every 2 month(s)". The unit follows the interval so the sentence stays readable at every setting.
function intervalUnit(price) {
  const entry = BILLING_INTERVALS.find(([value]) => value === price.billing_interval);
  return entry ? `${entry[2]}(s)` : "";
}

function previewFor(price) {
  return pricePreviewFor(price, props.productType);
}

// Only the FIRST price in a non-standard context is used per product. Standard may have many (quantity tiers);
// Sale/Flash pair to those tiers so they're one-PER-QUANTITY; funnel contexts are one per product. Flag the
// redundant (ignored) extras — the earlier duplicate wins.
function redundancyWarning(price, index) {
  const context = price.context || "standard";
  if (context === "standard") return "";
  const perQuantity = context === "sale" || context === "flash_sale";
  const quantity = Number(price.quantity || 1);
  const earlierDuplicate = props.prices.slice(0, index).some((other) =>
    (other.context || "standard") === context && (!perQuantity || Number(other.quantity || 1) === quantity),
  );
  if (!earlierDuplicate) return "";
  const label = (props.contexts.find(([value]) => value === context) || [context, context])[1];
  return perQuantity
    ? `Only the first ${label} price for quantity ${quantity} is used — this one is ignored.`
    : `Only the first ${label} price is used — this one is ignored. Put additional ${label.toLowerCase()}s on separate products.`;
}

function addPrice() {
  props.prices.push(defaultPriceForm());
}

function removePrice(index) {
  if (props.prices.length === 1) return;
  props.prices.splice(index, 1);
  if (props.defaultIndex >= props.prices.length) emit("update:defaultIndex", 0);
}
</script>
