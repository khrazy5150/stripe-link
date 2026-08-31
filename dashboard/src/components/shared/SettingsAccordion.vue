<template>
  <div class="acc-item" :class="{ open }">
    <button type="button" class="acc-head" :aria-expanded="open" @click="$emit('toggle')">
      <span class="acc-caret" aria-hidden="true">{{ open ? "▾" : "▸" }}</span>
      <span v-if="icon" class="acc-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path v-for="(d, i) in icon" :key="i" :d="d" />
        </svg>
      </span>
      <strong class="acc-label">{{ label }}</strong>
      <span v-if="hint" class="acc-hint">{{ hint }}</span>
    </button>
    <div v-if="open" class="acc-body"><slot /></div>
  </div>
</template>

<script setup>
// A disclosure row. Open state is OWNED BY THE PARENT so a group can enforce one-at-a-time: independent
// state was defensible in principle, but several tall panels open at once makes the modal a wall to
// scroll rather than a set of choices.
defineProps({
  label: { type: String, required: true },
  hint: { type: String, default: "" },
  open: { type: Boolean, default: false },
  // SVG path `d` strings, drawn in a filled circle. An array so multi-stroke glyphs work; the same
  // 24x24 stroke style the sidebar uses, so these do not read as a foreign icon set.
  icon: { type: Array, default: () => [] },
});
defineEmits(["toggle"]);
</script>

<style scoped>
.acc-item {
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  /* NO overflow:hidden. On a grid item that sets the automatic minimum size to ZERO, so a short viewport
     squeezes the open panel to a sliver instead of letting the modal body scroll — and because it also
     clips, the content simply disappears. Corners are rounded on the children instead. */
}

.acc-head {
  border-radius: calc(var(--radius-md) - 1px);
}

.acc-item.open .acc-head {
  border-radius: calc(var(--radius-md) - 1px) calc(var(--radius-md) - 1px) 0 0;
}

.acc-body {
  border-radius: 0 0 calc(var(--radius-md) - 1px) calc(var(--radius-md) - 1px);
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

/* The circled badge the Post-Checkout steps use for their step number — same shape, an icon instead of
   a numeral, because settings have no sequence to number. */
.acc-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.6rem;
  height: 2.6rem;
  flex: 0 0 auto;
  align-self: center;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
}

.acc-icon svg {
  width: 1.4rem;
  height: 1.4rem;
}

/* The open one fills in, so the active panel reads at a glance from the badge as well as the border. */
.acc-item.open .acc-icon {
  background: var(--accent);
  color: #fff;
}

.acc-hint {
  color: var(--text-muted);
  font-size: var(--text-hint);
  font-weight: var(--weight-normal);
}

.acc-body {
  display: grid;
  gap: 1rem;
  align-content: start;
  /* A little more below than above: the last control's helper text sits tight against the border
     otherwise, and a panel that ends flush reads as cut off even when it is not. */
  padding: 1.2rem 1.2rem 1.6rem;
  border-top: 1px solid var(--line);
}
</style>
