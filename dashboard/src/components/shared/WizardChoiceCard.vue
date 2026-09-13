<template>
  <!-- One choice in a wizard. Full-width and stacked, matching the landing-page wizard, with the SAME circled
       check the Offer item picker uses -- the three surfaces had three selected-states, and the one a tenant
       already recognises should win.
       Deliberately no icon: the product wizard shipped with tinted glyphs and they made a list of three
       sentences read as a toolbar. The title carries the meaning. -->
  <button
    type="button"
    class="wizard-choice-card"
    :class="{ selected }"
    :aria-pressed="selected"
    @click="$emit('select')"
  >
    <strong>{{ title }}</strong>
    <span v-if="description">{{ description }}</span>
    <slot />
    <span class="wizard-choice-check" aria-hidden="true">✓</span>
  </button>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: "" },
  selected: { type: Boolean, default: false },
});
defineEmits(["select"]);
</script>
