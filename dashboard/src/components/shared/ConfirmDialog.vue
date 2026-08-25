<template>
  <div v-if="open" class="modal-backdrop" @click.self="onCancel">
    <section class="modal-card confirm-card" role="dialog" aria-modal="true" :aria-labelledby="titleId">
      <header class="confirm-icon" :class="danger ? 'danger' : 'primary'">{{ glyph }}</header>
      <h2 :id="titleId">{{ title }}</h2>
      <p><slot>{{ message }}</slot></p>
      <div class="confirm-actions">
        <button type="button" class="secondary-action" :disabled="busy" @click="onCancel">{{ cancelLabel }}</button>
        <button type="button" class="primary-action" :disabled="busy" @click="$emit('confirm')">{{ confirmLabel }}</button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed } from "vue";

// Reusable confirm dialog matching the app's confirm-card styling (styles.css). Presentational:
// the parent owns the target and the async action, and toggles `open`.
//
//   <ConfirmDialog :open="!!pending" danger title="Delete?" confirm-label="Delete"
//                  :busy="store.saving" @cancel="pending = null" @confirm="doIt">
//     Permanently delete "{{ pending?.name }}"? This cannot be undone.
//   </ConfirmDialog>
const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: "Are you sure?" },
  message: { type: String, default: "" },
  confirmLabel: { type: String, default: "Confirm" },
  cancelLabel: { type: String, default: "Cancel" },
  danger: { type: Boolean, default: false }, // destructive: red icon + × glyph
  icon: { type: String, default: "" }, // override the default glyph
  busy: { type: Boolean, default: false }, // disable buttons while an async action runs
});
const emit = defineEmits(["confirm", "cancel", "update:open"]);

const titleId = `confirm-title-${Math.random().toString(36).slice(2)}`;
const glyph = computed(() => props.icon || (props.danger ? "×" : "↺"));

function onCancel() {
  emit("cancel");
  emit("update:open", false);
}
</script>
