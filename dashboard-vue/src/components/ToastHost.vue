<template>
  <div class="toast-host" aria-live="polite" aria-atomic="false">
    <transition-group name="toast">
      <div
        v-for="toast in toasts.items"
        :key="toast.id"
        class="toast"
        :class="[`toast-${toast.severity}`, { 'toast-clickable': !!toast.route }]"
        role="status"
        @click="select(toast)"
      >
        <div class="toast-body">
          <p class="toast-title">
            <span v-if="toast.icon" class="toast-icon" aria-hidden="true">{{ toast.icon }}</span>{{ toast.title }}
          </p>
          <p v-if="toast.message" class="toast-message">{{ toast.message }}</p>
        </div>
        <button class="toast-close" type="button" aria-label="Dismiss" @click.stop="toasts.dismiss(toast.id)">×</button>
      </div>
    </transition-group>
  </div>
</template>

<script setup>
import { onBeforeUnmount, watch } from "vue";
import { useToastsStore } from "../stores/toasts";

const AUTO_DISMISS_MS = 6500;
const toasts = useToastsStore();
const emit = defineEmits(["select"]);
const timers = new Map();

// Auto-dismiss non-sticky toasts; sticky ones (e.g. a refund that needs a decision) wait for a click.
watch(
  () => toasts.items.slice(),
  (items) => {
    const ids = new Set(items.map((t) => t.id));
    for (const [id, timer] of timers) {
      if (!ids.has(id)) {
        clearTimeout(timer);
        timers.delete(id);
      }
    }
    for (const toast of items) {
      if (!toast.sticky && !timers.has(toast.id)) {
        timers.set(toast.id, window.setTimeout(() => {
          toasts.dismiss(toast.id);
          timers.delete(toast.id);
        }, AUTO_DISMISS_MS));
      }
    }
  },
  { immediate: true, deep: true },
);

onBeforeUnmount(() => {
  for (const timer of timers.values()) clearTimeout(timer);
  timers.clear();
});

function select(toast) {
  if (toast.route) emit("select", toast);
}
</script>

<style scoped>
.toast-host {
  position: fixed;
  top: 1.2rem;
  right: 1.2rem;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
  max-width: min(92vw, 380px);
  pointer-events: none;
}
.toast {
  pointer-events: auto;
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  padding: 0.9rem 1rem;
  border-radius: 12px;
  /* --surface/--border are theme tokens (defined in styles.css for both test/live) so the toast follows the theme.
     They were previously undefined, so in live(dark) mode the toast fell back to a white background under near-white
     --text — light-on-light and unreadable. */
  background: var(--surface, #fff);
  color: var(--text, #111);
  border: 1px solid var(--border, #e3e3e3);
  border-left: 4px solid var(--toast-accent, #6b7280);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.16);
}
.toast-clickable { cursor: pointer; }
.toast-clickable:hover { border-color: var(--toast-accent, #6b7280); }
.toast-success { --toast-accent: #16a34a; }
.toast-warning { --toast-accent: #d97706; }
.toast-error { --toast-accent: #dc2626; }
.toast-info { --toast-accent: #2563eb; }
.toast-body { flex: 1; min-width: 0; }
.toast-title {
  margin: 0;
  font-weight: 700;
  font-size: 0.95rem;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.toast-icon { font-size: 1.05rem; }
.toast-message {
  margin: 0.25rem 0 0;
  font-size: 0.85rem;
  color: var(--muted, #555);
  line-height: 1.35;
}
.toast-close {
  flex: none;
  border: 0;
  background: transparent;
  color: var(--muted, #888);
  font-size: 1.35rem;
  line-height: 1;
  cursor: pointer;
  padding: 0 0.15rem;
}
.toast-close:hover { color: var(--text, #111); }
.toast-enter-active, .toast-leave-active { transition: all 0.25s ease; }
.toast-enter-from { opacity: 0; transform: translateX(20px); }
.toast-leave-to { opacity: 0; transform: translateX(20px); }
</style>
