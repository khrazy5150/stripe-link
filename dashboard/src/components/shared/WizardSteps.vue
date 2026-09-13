<template>
  <!-- The numbered step rail. ONE component, because three wizards had three ideas of what progress looks
       like: numbered pills here, three dots in the landing-page wizard, and "Step 2 of 3" in its header.
       A tenant meeting two of them in one session is meeting two products. -->
  <ol class="wizard-steps" :aria-label="label">
    <li
      v-for="(step, index) in steps"
      :key="step"
      :class="{ 'is-current': current === index + 1, 'is-done': current > index + 1 }"
      :aria-current="current === index + 1 ? 'step' : undefined"
    >
      <span class="wizard-steps-num" aria-hidden="true">{{ current > index + 1 ? "✓" : index + 1 }}</span>
      {{ step }}
    </li>
  </ol>
</template>

<script setup>
defineProps({
  steps: { type: Array, required: true },
  // 1-based: it is what the wizard's own counter uses, and off-by-one here is invisible until someone ships.
  current: { type: Number, required: true },
  label: { type: String, default: "Progress" },
});
</script>
