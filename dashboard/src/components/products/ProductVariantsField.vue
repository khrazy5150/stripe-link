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

    <h3>Size &amp; Weight <span class="field-optional">{{ sizeBadge }}</span></h3>
    <p class="field-hint">
      The product itself, out of any packaging. Needed to buy shipping labels — with it we pick the
      cheapest box that fits the whole order, so two things bought together share one parcel instead of
      shipping separately. You can skip it and take parcels to the post office yourself.
    </p>
    <!-- WHAT LEAVING IT BLANK ACTUALLY COSTS, derived from the tenant's own zones rather than asserted
         (plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P0b). "You cannot charge shipping" is false for flat and
         free zones, and a warning that is wrong teaches tenants to ignore the ones that are right. Shown
         only while the fields are actually blank: a solved problem is not a notice. -->
    <p v-if="unmeasured && consequence.message"
       :class="consequence.severity === 'warning' ? 'keys-status-banner warning' : 'field-hint'">
      {{ consequence.message }}
    </p>
    <div class="modal-dimensions-grid">
      <label>Length (inches)<input v-model.number="form.item_length_in" type="number" min="0" step="0.1" placeholder="—" /></label>
      <label>Width (inches)<input v-model.number="form.item_width_in" type="number" min="0" step="0.1" placeholder="—" /></label>
      <label>Height (inches)<input v-model.number="form.item_height_in" type="number" min="0" step="0.1" placeholder="—" /></label>
      <label>Weight (pounds)<input v-model.number="form.item_weight_lb" type="number" min="0" step="0.1" placeholder="—" /></label>
    </div>
    <label class="switch-row variant-toggle">
      <input v-model="form.compressible" type="checkbox" />
      <span>
        <strong>This item squashes</strong>
        <small>A pouch, bag or soft goods — it can go in a padded mailer thicker than the mailer lies
          flat. Leave off for anything rigid: a jar forced into an envelope is refused at the counter.</small>
      </span>
    </label>

    <!-- The BOX is deliberately absent from the wizard. Which box an order actually needs is learned from
         real orders, not known the day a product is created, and asking at creation invites a guess that
         then hardens into the number the packer trusts (plans/SHIPPING_PROVIDERS.md). -->
    <template v-if="surface === 'edit'">
      <h3>Shipping Box <span class="field-optional">optional</span></h3>
      <p class="field-hint">
        Normally we work the box out from the sizes above and what else is in the order. Set this only when
        that would be wrong — something fragile needing extra padding, an awkward shape, or anything you
        ship in the manufacturer's packaging.
      </p>
      <!-- WHAT WE WORKED OUT, which the paragraph above has always promised and never shown. A tenant
           overriding an answer they cannot see is guessing; one who can see it is deciding. -->
      <p v-if="derivedParcel" class="field-hint derived-parcel">
        <strong>This ships in {{ derivedParcel }}.</strong>
      </p>
      <label class="switch-row variant-toggle">
        <input v-model="form.ships_alone" type="checkbox" />
        <span>
          <strong>Always ships in its own box</strong>
          <small>Never shares a parcel, even when bought with something else.</small>
        </span>
      </label>
      <!-- Revealed ONLY when it is ticked, because that is now the only case these four numbers are read
           in. They used to double as a silent fallback for unmeasured products, which charged buyers for
           a box nobody measured (P0a); with that path gone, showing them unticked collects four numbers
           that go nowhere. -->
      <template v-if="form.ships_alone">
        <div class="modal-dimensions-grid">
          <label>Length (inches)<input v-model.number="form.length_in" type="number" min="0" step="0.1" /></label>
          <label>Width (inches)<input v-model.number="form.width_in" type="number" min="0" step="0.1" /></label>
          <label>Height (inches)<input v-model.number="form.height_in" type="number" min="0" step="0.1" /></label>
          <label>Packed weight (pounds)<input v-model.number="form.weight_lb" type="number" min="0" step="0.1" /></label>
        </div>
        <p class="field-hint">Packed weight is the whole thing as it ships — box included.</p>
        <!-- A parcel cannot weigh less than what is inside it. Seen in real data: 1 lb packed on an item
             weighing 2.5 lb, which nothing rejected. -->
        <p v-if="packedWeightTooLight" class="keys-status-banner warning">
          Packed weight ({{ form.weight_lb }} lb) is less than the item itself ({{ form.item_weight_lb }} lb).
          The box cannot weigh less than what goes in it.
        </p>
      </template>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue";
/**
 * Size and colour variants, and how the thing ships.
 *
 * Shown only for PHYSICAL products, which is the caller's decision rather than this component's: the wizard
 * puts it on the Details step and the edit form keeps it near the bottom, but both gate it on the same type.
 *
 * **The two surfaces differ by WHEN the knowledge exists**, not by how much room there is. The item's own
 * size and weight are measurable the moment the product is in front of you, so the wizard asks. Which BOX
 * an order needs is learned from real orders, so it lives in the edit form — asking at creation invites a
 * guess that then hardens into the number the packer trusts. The old form had this exactly inverted: it
 * asked the discovered question up front and made the measurable one optional, which is why 0 of 4
 * production products had item dimensions and the packer's multi-item path had never run.
 *
 * Turning a toggle on with no rows would show an empty list and read as broken, so each `ensure` seeds the
 * first row; removing the last row turns the toggle back off, so the two can never disagree.
 */
import { apiRequest } from "../../api/client";
import { defaultColorVariant, defaultSizeVariant } from "../../utils/productVariants";

const props = defineProps({
  form: { type: Object, required: true },
  surface: { type: String, default: "edit" },
  // `{severity, message}` from GET /shipping -- the server decides what is true for these zones, because
  // the rule lives beside the zones it reads, not in a component.
  consequence: { type: Object, default: () => ({}) },
});

/** Blank means ANY of the four is missing: a parcel needs all three sides and a weight to be rated. */
const unmeasured = computed(() => ["item_length_in", "item_width_in", "item_height_in", "item_weight_lb"]
  .some((field) => !(Number(props.form[field]) > 0)));

// WHICH BOX this product ships in, answered by the packer rather than guessed at here. Debounced,
// because the fields fire per keystroke and the answer only changes when a measurement does.
const derivedParcel = ref("");
let packTimer = null;

async function refreshDerivedParcel() {
  if (unmeasured.value) {
    derivedParcel.value = "";
    return;
  }
  try {
    const body = await apiRequest("/shipping/pack-preview", {
      method: "POST",
      body: JSON.stringify({ items: [{
        length: props.form.item_length_in, width: props.form.item_width_in,
        height: props.form.item_height_in, weight: props.form.item_weight_lb,
        compressible: !!props.form.compressible,
      }] }),
    });
    const parcel = (body?.parcels || [])[0];
    // No box named means the catalog held nothing it fits, so it would post on its own. Say that rather
    // than naming a box the tenant does not have.
    derivedParcel.value = parcel
      ? (parcel.box_name
          ? `your ${parcel.box_name}, ${parcel.weight} lb`
          : `its own parcel, ${parcel.length}x${parcel.width}x${parcel.height} in, ${parcel.weight} lb`)
      : "";
  } catch {
    // Silence. A derived figure this form could not verify is worse than no figure.
    derivedParcel.value = "";
  }
}

watch(
  () => [props.form.item_length_in, props.form.item_width_in, props.form.item_height_in,
         props.form.item_weight_lb, props.form.compressible],
  () => {
    clearTimeout(packTimer);
    packTimer = setTimeout(refreshDerivedParcel, 400);
  },
  { immediate: true },
);

/** A parcel cannot weigh less than its contents. Only meaningful once both numbers exist. */
const packedWeightTooLight = computed(() => {
  const packed = Number(props.form.weight_lb);
  const item = Number(props.form.item_weight_lb);
  return packed > 0 && item > 0 && packed < item;
});

/** Optional to SAVE, required to QUOTE -- and which applies depends on the tenant's zones. */
const sizeBadge = computed(() => (props.consequence.severity === "warning" ? "needed to charge shipping"
                                                                          : "optional"));

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
