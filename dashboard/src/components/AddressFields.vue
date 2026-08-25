<template>
  <div>
    <div class="offer-two-column">
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
        <input v-model.trim="address.state" type="text" placeholder="CA" />
      </label>
      <label class="offer-field">
        <span>Postal Code <strong>*</strong></span>
        <input v-model.trim="address.postal_code" type="text" />
      </label>
    </div>
    <div class="offer-three-column">
      <label class="offer-field">
        <span>Country <strong>*</strong></span>
        <input v-model.trim="address.country" type="text" maxlength="2" placeholder="US" />
        <small>Two-letter code.</small>
      </label>
      <label class="offer-field">
        <span>Phone</span>
        <input v-model.trim="address.phone" type="tel" placeholder="Optional" />
      </label>
      <label class="offer-field">
        <span>Email</span>
        <input v-model.trim="address.email" type="email" placeholder="Optional" />
      </label>
    </div>
    <label class="checkbox-row offer-checkbox-inline">
      <input v-model="address.residential" type="checkbox" />
      <span>Residential address</span>
    </label>
  </div>
</template>

<script setup>
// `address` is a reactive object owned by the parent; fields mutate it in place.
defineProps({
  address: { type: Object, required: true },
});
</script>
