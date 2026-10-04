<template>
  <div>
    <div v-if="contact" class="offer-two-column">
      <label class="offer-field">
        <span>Name <strong>*</strong></span>
        <input v-model.trim="address.name" type="text" placeholder="Warehouse / Contact name" />
      </label>
      <label class="offer-field">
        <span>Company</span>
        <input v-model.trim="address.company" type="text" placeholder="Optional" />
      </label>
    </div>
    <div class="offer-two-column">
      <label class="offer-field">
        <span>Street 1 <strong>*</strong></span>
        <input v-model.trim="address.street1" type="text" placeholder="123 Main St" />
      </label>
      <label class="offer-field">
        <span>Street 2</span>
        <input v-model.trim="address.street2" type="text" placeholder="Suite / Unit (optional)" />
      </label>
    </div>
    <div class="offer-three-column">
      <label class="offer-field">
        <span>City <strong>*</strong></span>
        <input v-model.trim="address.city" type="text" />
      </label>
      <label class="offer-field">
        <span>State / Province <strong>*</strong></span>
        <!-- A CODE where there is a list to pick from, free text everywhere else. Typed names break the
             timezone inference, NAP consistency and the carriers all at once — see utils/subdivisions. -->
        <select v-if="subdivisions" v-model="address.state">
          <option value="">Choose…</option>
          <!-- A stored value we do not recognise is kept and shown, never silently blanked. -->
          <option v-if="unlistedState" :value="unlistedState">{{ unlistedState }}</option>
          <option v-for="[code, name] in subdivisions" :key="code" :value="code">{{ code }} — {{ name }}</option>
        </select>
        <input v-else v-model.trim="address.state" type="text" placeholder="Region / Province" />
      </label>
      <label class="offer-field">
        <span>Postal Code <strong>*</strong></span>
        <input v-model.trim="address.postal_code" type="text" />
      </label>
    </div>
    <div :class="contact ? 'offer-three-column' : 'offer-two-column'">
      <label class="offer-field">
        <span>Country <strong>*</strong></span>
        <select v-model="address.country" class="country-select">
          <option value="">Country…</option>
          <option v-for="c in COUNTRIES" :key="c.code" :value="c.code">{{ c.name }} ({{ c.code }})</option>
        </select>
      </label>
      <label v-if="contact" class="offer-field">
        <span>Phone</span>
        <PhoneInput v-model="address.phone" :initial-country="address.country" />
      </label>
      <label v-if="contact" class="offer-field">
        <span>Email</span>
        <input v-model.trim="address.email" type="email" placeholder="Optional" />
      </label>
    </div>
    <label v-if="contact" class="checkbox-row offer-checkbox-inline">
      <input v-model="address.residential" type="checkbox" />
      <span>Residential address</span>
    </label>
  </div>
</template>

<script setup>
import { computed, watch } from "vue";

import PhoneInput from "./PhoneInput.vue";
// A named list beats a two-letter box: carriers want ISO-3166 alpha-2, and a tenant typing "UK" (not a
// code) or "us" produced an address the carrier rejected. Profile already used this list; sharing it here
// means both screens get the better control rather than the shipping form dragging Profile down to a
// free-text field.
import { COUNTRIES } from "../utils/countries";
import { normalizeSubdivision, subdivisionsFor } from "../utils/subdivisions";
// `address` is a reactive object owned by the parent; fields mutate it in place.
const props = defineProps({
  address: { type: Object, required: true },
  // A shipping address needs a contact and a delivery hint; a business address is just a PLACE. The
  // business's own name and phone already live on the Profile form above it, so repeating them inside the
  // address would be two fields for one fact -- and "Residential address" is a carrier's pricing question,
  // not something true of a business.
  contact: { type: Boolean, default: true },
});

const subdivisions = computed(() => subdivisionsFor(props.address.country));

// A value stored before this field was a list -- "Wyoming", or a region from a country with no list we
// kept. Offered as its own option so the select SHOWS it instead of appearing empty, which would read as
// "my address lost its state" and is how a tenant ends up re-typing an address that was already right.
const unlistedState = computed(() => {
  const current = String(props.address.state || "").trim();
  if (!current || !subdivisions.value) return "";
  return subdivisions.value.some(([code]) => code === current) ? "" : current;
});

// HEAL ON LOAD, and whenever the country changes. "Wyoming" becomes "WY" the moment the form can tell
// which country it belongs to, so the next save stores a code without the tenant doing anything -- and
// the timezone inference, the JSON-LD and the carrier all get the same string.
watch(() => [props.address.country, props.address.state], () => {
  const healed = normalizeSubdivision(props.address.state, props.address.country);
  if (healed !== props.address.state) props.address.state = healed;
}, { immediate: true });
</script>
