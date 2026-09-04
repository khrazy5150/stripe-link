<!--
  One card for every "pick a thing from a visual grid" surface.

  There were two: the Offers item selector and the Page Ribbon's page picker. The second was written by
  copying the first's CSS classes, and immediately diverged — its images cropped where the original's did
  not, and its title was clipped out of a card whose row heights were sized for a price line it never had.
  That is the duplication pattern this codebase keeps paying for, so the card is a component now.

  Presentational only: it renders, it emits nothing but a click. Selection state, disabled rules and what a
  card MEANS stay with the screen that owns them.
-->
<template>
  <button
    type="button"
    class="selector-card"
    :class="{ selected, disabled, 'has-overlay': overlay }"
    :disabled="disabled"
    :title="disabledReason || undefined"
    @click="$emit('choose')"
  >
    <span class="selector-card-media">
      <img v-if="image" :src="image" :alt="title || 'Item image'" />
      <span v-else class="selector-card-initial">{{ initial }}</span>
      <span class="selector-card-check" aria-hidden="true">✓</span>
    </span>

    <span v-if="badge" class="selector-card-badge" :class="badgeClass">{{ badge }}</span>

    <span class="selector-card-body">
      <span class="selector-card-title">{{ title || fallbackTitle }}</span>
      <!-- The trailing line differs per screen — a price, a slug — so the owner supplies it. -->
      <slot />
    </span>
  </button>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  image: { type: String, default: "" },
  title: { type: String, default: "" },
  fallbackTitle: { type: String, default: "Untitled" },
  badge: { type: String, default: "" },
  badgeClass: { type: String, default: "" },
  selected: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  disabledReason: { type: String, default: "" },
  // `overlay` lays the title over the image instead of beneath it — for grids where the picture is the
  // point and the name is the disambiguator (two pages can promote the same product and look identical).
  overlay: { type: Boolean, default: false },
});

defineEmits(["choose"]);

const initial = computed(() => (props.title || props.fallbackTitle || "?").trim().charAt(0).toUpperCase());
</script>
