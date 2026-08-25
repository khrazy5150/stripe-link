<template>
  <div v-if="open" class="modal-backdrop" @click.self="onCancel">
    <section class="modal-card confirm-card" role="dialog" aria-modal="true" :aria-labelledby="titleId">
      <h2 :id="titleId">{{ title }}</h2>
      <p v-if="message">{{ message }}</p>
      <textarea
        v-if="multiline"
        ref="inputEl"
        v-model="value"
        class="modal-input"
        :rows="rows"
        :placeholder="placeholder"
        @keydown.esc="onCancel"
      ></textarea>
      <input
        v-else
        ref="inputEl"
        v-model="value"
        type="text"
        class="modal-input"
        :placeholder="placeholder"
        @keyup.enter="onConfirm"
        @keydown.esc="onCancel"
      />
      <div class="confirm-actions">
        <button type="button" class="secondary-action" :disabled="busy" @click="onCancel">{{ cancelLabel }}</button>
        <button type="button" class="primary-action" :disabled="busy || (required && !value.trim())" @click="onConfirm">{{ confirmLabel }}</button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { nextTick, ref, watch } from "vue";

// Reusable text-capture modal: covers a plain text input, a multiline "reason" capture, and a
// generic prompt — one primitive, configured by props (styled, theme-aware, replaces window.prompt).
//
//   <PromptDialog :open="!!renaming" title="Rename" :initial-value="renaming?.name" required
//                 confirm-label="Save" @cancel="renaming = null" @confirm="save" />
//   <PromptDialog :open="rejecting" title="Reject" multiline confirm-label="Reject"
//                 @cancel="rejecting = false" @confirm="reject" />  // value passed to @confirm
const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: "" },
  message: { type: String, default: "" },
  placeholder: { type: String, default: "" },
  initialValue: { type: String, default: "" },
  confirmLabel: { type: String, default: "Save" },
  cancelLabel: { type: String, default: "Cancel" },
  multiline: { type: Boolean, default: false }, // textarea (reasons/notes) vs single-line input
  rows: { type: Number, default: 3 },
  required: { type: Boolean, default: false }, // disable confirm until non-empty
  busy: { type: Boolean, default: false },
});
const emit = defineEmits(["confirm", "cancel", "update:open"]);

const titleId = `prompt-title-${Math.random().toString(36).slice(2)}`;
const value = ref(props.initialValue);
const inputEl = ref(null);

watch(
  () => props.open,
  (open) => {
    if (open) {
      value.value = props.initialValue;
      nextTick(() => inputEl.value?.focus());
    }
  },
);

function onConfirm() {
  if (props.required && !value.value.trim()) return;
  emit("confirm", value.value);
}
function onCancel() {
  emit("cancel");
  emit("update:open", false);
}
</script>
