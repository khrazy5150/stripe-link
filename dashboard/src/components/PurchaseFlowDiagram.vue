<template>
  <div class="funnel-diagram">
    <div class="funnel-node funnel-offer">
      <span class="funnel-node-kind">Offer</span>
      <strong>{{ offerName || "Untitled offer" }}</strong>
    </div>

    <template v-for="stage in stages" :key="stage.key">
      <div class="funnel-connector" aria-hidden="true"></div>
      <div class="funnel-stage">
        <div class="funnel-stage-head">
          <span class="funnel-stage-label">{{ stage.label }}</span>
          <span class="funnel-stage-hint">{{ stage.hint }}</span>
        </div>
        <div class="funnel-cards">
          <article v-for="item in stage.items" :key="item.key" class="funnel-card">
            <span class="intent-badge" :class="'intent-' + item.intent" :title="INTENT_META[item.intent].desc">{{ INTENT_META[item.intent].label }}</span>
            <strong class="funnel-card-name">{{ item.product.name || "Untitled Product" }}</strong>
            <div class="funnel-pricing">
              <span v-for="chip in (item.chips || [item.amount])" :key="chip" class="price-chip">{{ chip }}</span>
            </div>
            <span v-if="item.synced === false" class="field-error">Not synced to Stripe — needs a synced price.</span>
            <small v-if="item.extra" class="funnel-extra-warning">⚠ {{ item.extra }} {{ INTENT_META[item.intent].desc }} prices on this product — only the first ({{ item.amount }}) is used. Put additional upsells on separate products.</small>
            <div v-if="item.downsell" class="funnel-downsell">
              <span class="intent-badge intent-recovery" :title="INTENT_META.recovery.desc">{{ INTENT_META.recovery.label }}</span>
              <span>if declined — {{ item.downsell.amount }}</span>
              <span v-if="item.downsell.synced === false" class="field-error">Not synced.</span>
              <small v-if="item.downsell.extra" class="funnel-extra-warning">⚠ {{ item.downsell.extra }} downsell prices — only the first is used.</small>
            </div>
          </article>
        </div>
      </div>
    </template>

    <div class="funnel-connector" aria-hidden="true"></div>
    <div class="funnel-node funnel-thankyou">
      <span class="funnel-node-kind">Always</span>
      <strong>Thank-you page</strong>
    </div>
  </div>
</template>

<script setup>
// A read-only visual of an offer's purchase flow (offer -> landing -> checkout bump -> upsells -> thank-you).
// Presentational only: each parent computes the `stages` from its own data (Offers.vue from the live form; the
// Landing builder from the saved offer). CSS is global (styles.css .funnel-*). plans/SALES_FUNNELS.md.
defineProps({
  offerName: { type: String, default: "" },
  stages: { type: Array, default: () => [] },
});

const INTENT_META = {
  primary: { label: "Primary", desc: "main purchase" },
  cross_sell: { label: "Cross-sell", desc: "order bump" },
  upgrade: { label: "Upgrade", desc: "upsell" },
  recovery: { label: "Recovery", desc: "downsell" },
};
</script>
