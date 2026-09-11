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
    :title="disabledReason || title || fallbackTitle"
    @click="$emit('choose')"
  >
    <span class="selector-card-media">
      <img v-if="image" :src="image" :alt="title || 'Item image'" />
      <span v-else class="selector-card-initial" :style="initialStyle">{{ initial }}</span>
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

// An image-less card used to be a grey tile with one letter on it, so a grid of them was unreadable: the
// tenant had to remember which product started with which letter, and two products sharing an initial were
// indistinguishable. The colour is DERIVED from the name, so it is stable for a given product across
// sessions and screens -- recognisable without being meaningful. Hue only; saturation and lightness are
// fixed so every tile sits at the same weight and none of them shouts.
const initialStyle = computed(() => {
  const name = (props.title || props.fallbackTitle || "").trim();
  if (!name) return {};
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) % 360;
  return {
    background: `hsl(${hash} 62% 88%)`,
    color: `hsl(${hash} 55% 32%)`,
  };
});
</script>
