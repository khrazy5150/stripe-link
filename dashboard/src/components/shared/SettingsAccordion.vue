<template>
  <div class="acc-item" :class="{ open }">
    <button type="button" class="acc-head" :aria-expanded="open" @click="open = !open">
      <span class="acc-caret" aria-hidden="true">{{ open ? "▾" : "▸" }}</span>
      <strong class="acc-label">{{ label }}</strong>
      <span v-if="hint" class="acc-hint">{{ hint }}</span>
    </button>
    <div v-if="open" class="acc-body"><slot /></div>
  </div>
</template>

<script setup>
import { ref } from "vue";

// A disclosure row. Each one owns its open state — settings are independent, unlike the Post-Checkout
// steps, where opening one switches what the preview is showing and so only one may be open at a time.
defineProps({
  label: { type: String, required: true },
  hint: { type: String, default: "" },
});

const open = ref(false);
</script>

<style scoped>
.acc-item {
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  overflow: hidden;
}

/* Matches the Post-Checkout steps: the open one is outlined, so the eye finds it without hunting. */
.acc-item.open {
  border-color: var(--accent);
}

.acc-head {
  display: flex;
  align-items: baseline;
  gap: 0.8rem;
  width: 100%;
  padding: 1rem 1.2rem;
  background: var(--panel);
  border: 0;
  cursor: pointer;
  font: inherit;
  font-size: var(--text-label);
  line-height: var(--leading-label);
  text-align: left;
  color: var(--text);
}

.acc-caret {
  color: var(--text-muted);
  font-size: 1.1rem;
}

.acc-hint {
  color: var(--text-muted);
  font-size: var(--text-hint);
  font-weight: var(--weight-normal);
}

.acc-body {
  display: grid;
  gap: 1rem;
  padding: 1.2rem;
  border-top: 1px solid var(--line);
}
</style>
