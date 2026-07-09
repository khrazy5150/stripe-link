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
        <label>Sales price
          <input v-model.number="price.sales_price" type="number" min="0" step="0.01" />
        </label>
        <label>Regular price
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
        <fieldset v-if="pricingModels.length > 1">
          <legend>Pricing model</legend>
          <label v-for="[value, label] in pricingModels" :key="value">
            <input v-model="price.pricing_model" type="radio" :value="value" /> {{ label }}
          </label>
        </fieldset>
        <fieldset>
          <legend>Fee handling</legend>
          <label><input v-model="price.fee_handling" type="radio" value="standard" /> Standard fees deducted</label>
          <label><input v-model="price.fee_handling" type="radio" value="net_guaranteed" /> Net-guaranteed fees added on top</label>
        </fieldset>
      </div>

      <label class="price-context-field">Price context
        <select v-model="price.context">
          <option v-for="[value, label] in contexts" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>

      <div v-if="price.pricing_model === 'customer_chooses'" class="modal-inline-grid">
        <label>Minimum amount
          <input v-model.number="price.min_amount" type="number" min="0" step="0.01" />
        </label>
        <label>Suggested amount
          <input v-model.number="price.suggested_amount" type="number" min="0" step="0.01" />
        </label>
      </div>

      <div class="price-preview">
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
import { defaultPriceForm, pricePreviewFor } from "../../utils/priceForm";

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
  pricingModels: {
    type: Array,
    default: () => [["one_time", "One-time"], ["recurring", "Recurring"], ["customer_chooses", "Customer chooses"]],
  },
});
const emit = defineEmits(["update:defaultIndex"]);

function previewFor(price) {
  return pricePreviewFor(price, props.productType);
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
