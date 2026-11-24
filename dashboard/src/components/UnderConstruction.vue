<template>
  <section class="construction-notice" aria-labelledby="construction-status">
    <div class="construction-wordmark">
      <img v-if="logoUrl" :src="logoUrl" alt="" />
      <span>Junior <strong>Bay</strong></span>
    </div>

    <div class="construction-card">
      <div class="construction-card-body">
        <p class="construction-eyebrow">{{ feature }}</p>
        <h1 id="construction-status">Under <em>Construction</em></h1>
        <p class="construction-description">{{ description }}</p>
      </div>
    </div>
  </section>
</template>

<script setup>
defineProps({
  logoUrl: { type: String, default: "" },
  feature: { type: String, required: true },
  description: { type: String, required: true },
});
</script>

<style scoped>
/* The public Sabbath closure uses this same centered blue card and orange accent. */
.construction-notice {
  --construction-orange: #ff8309;
  min-height: 100%;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: clamp(2.4rem, 5vw, 4.8rem);
  padding: clamp(2rem, 5vw, 4rem);
  color: #fff;
  background:
    radial-gradient(ellipse 80% 60% at 15% 10%, rgb(255 255 255 / 8%), transparent 60%),
    radial-gradient(ellipse 60% 50% at 85% 90%, rgb(0 0 0 / 28%), transparent 60%),
    #0b5294;
}

.construction-wordmark {
  display: flex;
  align-items: center;
  gap: 1.2rem;
  font: 700 3.4rem / 1 "Ubuntu Titling", sans-serif;
}

.construction-wordmark img {
  width: 4.4rem;
  height: 4.4rem;
  border-radius: 1rem;
}

.construction-wordmark strong {
  color: var(--construction-orange);
}

.construction-card {
  width: min(100%, 52rem);
  overflow: hidden;
  border: 1px solid rgb(255 255 255 / 12%);
  border-radius: 2.2rem;
  background: #104163;
  box-shadow: inset 0 2px rgb(255 255 255 / 7%), 0 4rem 8rem rgb(0 0 0 / 35%);
}

.construction-card::before {
  display: block;
  height: 3px;
  background: linear-gradient(90deg, var(--construction-orange), #ffb347 55%, transparent);
  content: "";
}

.construction-card-body {
  padding: clamp(2rem, 5vw, 4.4rem);
}

.construction-eyebrow {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  margin: 0 0 1.6rem;
  color: var(--construction-orange);
  font-size: 1.1rem;
  font-weight: 600;
  letter-spacing: 0.13em;
  text-transform: uppercase;
}

.construction-eyebrow::before {
  width: 0.6rem;
  height: 0.6rem;
  border-radius: 50%;
  background: currentColor;
  content: "";
}

.construction-card h1 {
  margin: 0 0 1.4rem;
  font-size: clamp(2.6rem, 5vw, 3.6rem);
  font-weight: 400;
  line-height: 1.14;
  letter-spacing: -0.06rem;
}

.construction-card em {
  color: var(--construction-orange);
  font-style: normal;
  font-weight: 700;
}

.construction-description {
  margin: 0;
  color: rgb(255 255 255 / 75%);
  font-size: 1.5rem;
  line-height: 1.65;
}
</style>
