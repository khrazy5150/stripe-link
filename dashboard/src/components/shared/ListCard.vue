<template>
  <article class="product-card" :class="{ archived }">
    <div
      class="product-card-image"
      :class="{ placeholder: !image }"
      :style="image ? {} : idColorStyle(iconColorKey || title)"
    >
      <img v-if="image" :src="image" :alt="title || 'image'" />
      <!-- Fallback when there's no uploaded image: caller supplies the icon (SVG, initial, …). -->
      <slot v-else name="icon"><span>{{ (title || "?").charAt(0).toUpperCase() }}</span></slot>
    </div>

    <div class="product-card-body">
      <div class="product-card-heading">
        <h3>{{ title || "Untitled" }}</h3>
        <slot name="badge">
          <span v-if="statusLabel" class="product-status" :class="statusTone">{{ statusLabel }}</span>
        </slot>
      </div>
      <slot name="description"><p>{{ description || "No description provided." }}</p></slot>
      <div v-if="$slots.subtitle || subtitle" class="product-card-price">
        <slot name="subtitle"><strong>{{ subtitle }}</strong></slot>
      </div>
      <div class="product-card-actions">
        <slot name="actions" />
      </div>
      <slot name="footer" />
    </div>
  </article>
</template>

<script setup>
import { idColorStyle } from "../../utils/iconColor";

// Presentational long-card for entity lists (products, services, …). Image if provided, otherwise
// an id-tinted placeholder holding the #icon slot. Actions/subtitle/footer are caller-owned slots.
defineProps({
  image: { type: String, default: "" },
  iconColorKey: { type: String, default: "" }, // hashed to the placeholder tint (falls back to title)
  title: { type: String, default: "" },
  subtitle: { type: String, default: "" },
  description: { type: String, default: "" },
  statusLabel: { type: String, default: "" },
  statusTone: { type: String, default: "active" }, // maps to .product-status.{tone}
  archived: { type: Boolean, default: false },
});
</script>
