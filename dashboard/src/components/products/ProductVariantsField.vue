<template>
  <div class="product-variants-group">
    <label class="switch-row variant-toggle">
      <input v-model="form.size_enabled" type="checkbox" @change="ensureSize" />
      <span><strong>Item Size</strong><small>Enable size variants, such as S, M, L, XL.</small></span>
    </label>
    <div v-if="form.size_enabled" class="variant-options">
      <div class="variant-row-list">
        <div v-for="(size, index) in form.sizes" :key="size.form_id" class="variant-item-row">
          <input v-model.trim="size.label" class="variant-label-input" :aria-label="`Size ${index + 1} label`" maxlength="10" placeholder="S" />
          <input v-model.trim="size.description" :aria-label="`Size ${index + 1} description`" placeholder="e.g., Waist: 30-32in, Hips: 37-39in" />
          <button type="button" class="variant-remove-button" :aria-label="`Remove size ${index + 1}`" @click="removeSize(index)">×</button>
        </div>
      </div>
      <button type="button" class="secondary-action" @click="addSize">+ New Size</button>
    </div>

    <label class="switch-row variant-toggle">
      <input v-model="form.color_enabled" type="checkbox" @change="ensureColor" />
      <span><strong>Item Color</strong><small>Enable color variants, such as Black, White, Navy.</small></span>
    </label>
    <div v-if="form.color_enabled" class="variant-options">
      <div class="variant-row-list">
        <div v-for="(color, index) in form.colors" :key="color.form_id" class="variant-item-row color-variant-row">
          <input v-model.trim="color.label" class="variant-label-input" :aria-label="`Color ${index + 1} label`" maxlength="20" placeholder="Black" />
          <input v-model="color.hex_color" class="variant-color-preview" type="color" :aria-label="`Color ${index + 1} swatch`" />
          <input v-model.trim="color.description" :aria-label="`Color ${index + 1} description`" placeholder="e.g., Jet black finish" />
          <button type="button" class="variant-remove-button" :aria-label="`Remove color ${index + 1}`" @click="removeColor(index)">×</button>
        </div>
      </div>
      <button type="button" class="secondary-action" @click="addColor">+ New Color</button>
    </div>

    <h3>Package Dimensions</h3>
    <div class="modal-dimensions-grid">
      <label>Length (inches)<input v-model.number="form.length_in" type="number" min="0" step="0.1" /></label>
      <label>Width (inches)<input v-model.number="form.width_in" type="number" min="0" step="0.1" /></label>
      <label>Height (inches)<input v-model.number="form.height_in" type="number" min="0" step="0.1" /></label>
      <label>Weight (pounds)<input v-model.number="form.weight_lb" type="number" min="0" step="0.1" /></label>
    </div>
  </div>
</template>

<script setup>
/**
 * Size and colour variants, and the box the thing ships in.
 *
 * Shown only for PHYSICAL products, which is the caller's decision rather than this component's: the wizard
 * puts it on the Details step and the edit form keeps it near the bottom, but both gate it on the same type.
 *
 * Turning a toggle on with no rows would show an empty list and read as broken, so each `ensure` seeds the
 * first row; removing the last row turns the toggle back off, so the two can never disagree.
 */
import { defaultColorVariant, defaultSizeVariant } from "../../utils/productVariants";

const props = defineProps({ form: { type: Object, required: true } });

function ensureSize() {
  if (props.form.size_enabled && !props.form.sizes.length) addSize();
}

function ensureColor() {
  if (props.form.color_enabled && !props.form.colors.length) addColor();
}

function addSize() {
  props.form.sizes.push(defaultSizeVariant());
}

function addColor() {
  props.form.colors.push(defaultColorVariant());
}

function removeSize(index) {
  props.form.sizes.splice(index, 1);
  if (!props.form.sizes.length) props.form.size_enabled = false;
}

function removeColor(index) {
  props.form.colors.splice(index, 1);
  if (!props.form.colors.length) props.form.color_enabled = false;
}
</script>
