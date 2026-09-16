<template>
  <div class="product-identifiers-group">
    <!-- Product identifiers (plans/ON_PAGE_SEO_REQUIREMENTS.md SEO-06). Optional; brand is the manufacturer,
         not the store name. Google matches products by GTIN, or by Brand + MPN. Only physical goods appear in
         shopping results, so these are hidden for digital/service products. -->
    <fieldset v-if="form.product_type === 'physical'" class="product-identifiers">
      <legend>Product identifiers</legend>
      <p class="field-note">
        Optional, but strongly recommended. Search engines match your products to shopping results using
        either a GTIN, or a Brand and MPN together. Used and refurbished items often have no GTIN — Brand
        plus MPN works just as well.
      </p>
      <div class="modal-inline-grid">
        <label>
          Product Brand
          <input v-model.trim="form.brand" type="text" placeholder="Apple" maxlength="70" />
          <span class="field-note">The manufacturer of this product — not your store name.</span>
        </label>
        <label>
          MPN
          <input v-model.trim="form.mpn" type="text" placeholder="MPXQ2LL/A" maxlength="70" />
          <span class="field-note">Manufacturer Part Number, usually printed on the product or its box.</span>
        </label>
      </div>
      <label>
        GTIN
        <input v-model.trim="form.gtin" type="text" placeholder="012345678905" @input="gtinTouched = true" />
        <span class="field-note">UPC, EAN, or ISBN barcode number. Leave blank if this item has none.</span>
        <span v-if="gtinWarning" class="field-warning">{{ gtinWarning }}</span>
      </label>
    </fieldset>

    <details class="sku-disclosure" :open="skuOpen">
      <summary>Advanced · Stock keeping unit (SKU)</summary>
      <label>
        SKU
        <input v-model.trim="form.sku" type="text" placeholder="Generated automatically" @input="emit('sku-edited')" />
        <span class="field-note">Generated from the product name and its ID, and kept stable after that. Edit it only if you have your own stock keeping unit.</span>
      </label>
    </details>
  </div>
</template>

<script setup>
/**
 * Everything that IDENTIFIES a product rather than describes or prices it: brand, MPN, GTIN, SKU.
 *
 * One component so the create wizard's Identifiers step and the full edit form show the same fields with the
 * same rules — most importantly that identifiers only appear for physical goods, since they exist to match a
 * listing in shopping results and nothing else has one.
 *
 * The GTIN warning lives here because it is about this input; the SKU's "has the tenant typed their own"
 * flag does NOT, because the parent's auto-SKU watcher is the thing that has to respect it.
 */
import { computed, ref } from "vue";
import { isValidGtin } from "../../stores/products";

const props = defineProps({
  form: { type: Object, required: true },
  // Open by default in the wizard, where this step exists to ask for exactly these fields; collapsed in the
  // edit form, where it is one section among a dozen.
  skuOpen: { type: Boolean, default: false },
});
const emit = defineEmits(["sku-edited"]);

const gtinTouched = ref(false);

// Non-blocking (SEO-06): the product still saves, and an invalid GTIN is simply dropped. A hard error here
// would block a save over a field that is optional in the first place.
const gtinWarning = computed(() =>
  gtinTouched.value && props.form.gtin && !isValidGtin(props.form.gtin)
    ? "This doesn't look like a valid barcode number — it won't be saved. Check the digits, or leave it blank."
    : "",
);
</script>
