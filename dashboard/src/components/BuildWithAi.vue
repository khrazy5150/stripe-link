<template>
  <section class="wizard-panel">
    <p class="wizard-lede">{{ lede }}</p>

    <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>

    <!-- ---------- done ---------- -->
    <template v-if="store.result">
      <p>
        Your draft page is ready. Nothing is live &mdash; review it and publish when you're happy.
      </p>
      <p class="field-note">
        {{ store.result.page.sections.length }} sections &middot;
        {{ store.result.usage.used }} of {{ store.result.usage.allowance }} generations used
      </p>
      <!-- The honest part: what the page could NOT say, and which answer would change it. A tenant who
           understands a thin page is a different person from one who thinks the AI is bad. -->
      <template v-if="store.result.withheld?.length">
        <p class="field-heading">What we couldn't say</p>
        <p class="field-note">We only write what you've told us. Add these and regenerate to say more:</p>
        <ul>
          <li v-for="item in store.result.withheld" :key="item.claim_class" class="field-note">
            {{ item.prompt }}
          </li>
        </ul>
      </template>
      <div class="button-row">
        <button class="primary-action" type="button" @click="$emit('open', store.result.page)">
          Open in the builder
        </button>
        <button class="secondary-action" type="button" @click="$emit('done')">Done</button>
      </div>
    </template>

    <!-- ---------- the one step ---------- -->
    <template v-else>
      <label>
        Who is it for? <span class="required">*</span>
        <input
          v-model.trim="answers.audience"
          type="text"
          maxlength="500"
          autocomplete="off"
          placeholder="e.g. Lifters who hate mixing powder"
        />
        <span class="field-note">
          Who the page talks to. Every benefit is written for somebody &mdash; without this the copy
          addresses nobody in particular.
        </span>
      </label>

      <label>
        Facts about it <span class="required">*</span>
        <textarea
          v-model="factsText"
          rows="4"
          placeholder="One per line — 5g creatine per serving&#10;30 gummies per tub&#10;Made in Australia&#10;No artificial sweeteners"
        ></textarea>
        <span class="field-note">
          Plain, checkable statements &mdash; what's in it, how much, what it's made of, what's included.
          Not features or benefits: we write those <em>from</em> these. Any number that appears on the page
          has to appear here first, so list the specifics.
        </span>
      </label>

      <!-- Optional, and collapsed, and each one labelled with what it BUYS. "Add your guarantee and we can
           write about your guarantee" is a different sentence from "fill in 12 fields". -->
      <button class="secondary-action" type="button" @click="showMore = !showMore">
        {{ showMore ? "Fewer options" : "Add more (optional)" }}
      </button>

      <template v-if="showMore">
        <label>
          Evidence you can stand behind
          <textarea v-model.trim="answers.evidence" rows="2" maxlength="1000"
                    placeholder="e.g. Third-party lab assay, batch 2026-03"></textarea>
          <span class="field-note">The only thing that lets us describe results. Without it we won't claim any.</span>
        </label>

        <label>
          Certifications
          <textarea v-model="certificationsText" rows="2"
                    placeholder="One per line — Informed Sport"></textarea>
          <span class="field-note">Unlocks trust badges and compliance wording.</span>
        </label>

        <label>
          Tone
          <select v-model="answers.tone">
            <option value="">Match the category (default)</option>
            <option v-for="tone in TONES" :key="tone" :value="tone">{{ toneLabel(tone) }}</option>
          </select>
          <span class="field-note">How it should sound. Left alone, we follow the category.</span>
        </label>

        <!-- Trust badges, as CHOICES. They used to be defaulted on for everyone -- "Ships from USA" and
             "Satisfaction Guarantee" on a tenant who may do neither. A badge is a claim, so it gets asked
             (author, 2026-09-30). -->
        <label class="builder-toggle">
          <input v-model="answers.ships_from_us" type="checkbox" />
          <span>Does this ship from the United States?</span>
        </label>
        <span class="field-note">Adds a "Ships from USA" badge. Left unticked, no origin is claimed.</span>

        <template v-if="hasRefundPolicy">
          <label class="builder-toggle">
            <input v-model="answers.money_back_badge" type="checkbox" />
            <span>Show a money-back badge?</span>
          </label>
          <span class="field-note">
            Uses your own refund policy &mdash; we never invent a window you haven't committed to.
          </span>
        </template>
        <p v-else class="field-note">
          A money-back badge needs a refund policy on this product. Add one and it becomes an option here.
        </p>

        <label>
          Must say
          <textarea v-model="mustSayText" rows="2" placeholder="One per line"></textarea>
          <span class="field-note">Wording that has to appear, exactly as you write it.</span>
        </label>

        <label>
          Must not say
          <textarea v-model="mustNotSayText" rows="2" placeholder="One per line"></textarea>
          <span class="field-note">Wording to keep off the page entirely.</span>
        </label>
      </template>

      <p v-if="store.generating" class="field-note">{{ store.progress || "Working…" }}</p>

      <div class="button-row">
        <button class="primary-action" type="button" :disabled="!canGenerate || store.generating"
                @click="generate">
          {{ store.generating ? "Building…" : "Build with AI" }}
        </button>
        <button class="secondary-action" type="button" :disabled="store.generating" @click="$emit('cancel')">
          Not now
        </button>
      </div>
      <p class="field-note">
        We'll create a draft page for <strong>{{ product?.name }}</strong> using its name, description,
        price and your refund policy. Nothing goes live until you publish it.
      </p>
    </template>
  </section>
</template>

<script setup>
/**
 * Build with AI, as a FORK off the product wizard rather than a second wizard.
 *
 * The first version asked nine questions and, measured against this very screen, had already been told
 * almost all of them — kind, name, description, category, price. So this asks only what nothing else can
 * supply. Everything about the PRODUCT is read server-side, and the refund and shipping policies come from
 * the tenant's own settings rather than being retyped (plans/AI_PAGE_BRIEF.md v2 §4).
 *
 * The answers are saved onto `Product.ai_context`, so regenerating — or building a second page for the same
 * product — starts from them instead of asking again.
 */
import { computed, ref, watch } from "vue";
import { useAiPageStore } from "../stores/aiPage";

const props = defineProps({
  product: { type: Object, default: null },
  mode: { type: String, default: "test" },
});
defineEmits(["open", "done", "cancel"]);

const store = useAiPageStore();
const TONES = ["direct", "warm", "playful", "technical", "premium"];

const showMore = ref(false);
const answers = ref({ audience: "", evidence: "", tone: "", ships_from_us: false, money_back_badge: false });
const factsText = ref("");
const certificationsText = ref("");
const mustSayText = ref("");
const mustNotSayText = ref("");

// Prefill from whatever the product already carries, so the second page for a product is not a retype.
watch(
  () => props.product,
  (product) => {
    const context = product?.ai_context || {};
    answers.value = {
      audience: context.audience || "",
      evidence: context.evidence || "",
      tone: context.tone || "",
      ships_from_us: Boolean(context.ships_from_us),
      money_back_badge: Boolean(context.money_back_badge),
    };
    factsText.value = (context.facts || []).join("\n");
    certificationsText.value = (context.certifications || []).join("\n");
    mustSayText.value = (context.must_say || []).join("\n");
    mustNotSayText.value = (context.must_not_say || []).join("\n");
    store.result = null;
    store.error = "";
  },
  { immediate: true },
);

function lines(value) {
  return String(value || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

const lede = computed(() =>
  props.product?.name
    ? `Two questions, and we'll write a draft page for ${props.product.name}.`
    : "Two questions, and we'll write a draft page.",
);

// A money-back badge is only offerable when there is a policy to label it from. Offering it otherwise would
// have the tenant assert a guarantee they never wrote, which is the defaulting this replaced.
const hasRefundPolicy = computed(() => {
  const policy = props.product?.refund_policy;
  return Boolean(policy && (policy.full_policy || policy.short_label));
});

const canGenerate = computed(
  () => Boolean(answers.value.audience.trim()) && lines(factsText.value).length > 0,
);

function toneLabel(tone) {
  return tone.charAt(0).toUpperCase() + tone.slice(1);
}

function generate() {
  // Only non-empty values are sent. A blank field means "unchanged", never "erase what I said last time" —
  // the server applies the same rule, and the two have to agree or a page gets generated from different
  // facts than the ones that get kept.
  const context = {};
  if (answers.value.audience.trim()) context.audience = answers.value.audience.trim();
  if (answers.value.evidence.trim()) context.evidence = answers.value.evidence.trim();
  if (answers.value.tone) context.tone = answers.value.tone;
  const facts = lines(factsText.value);
  if (facts.length) context.facts = facts;
  const certifications = lines(certificationsText.value);
  if (certifications.length) context.certifications = certifications;
  const mustSay = lines(mustSayText.value);
  if (mustSay.length) context.must_say = mustSay;
  const mustNotSay = lines(mustNotSayText.value);
  if (mustNotSay.length) context.must_not_say = mustNotSay;
  // Booleans are sent whatever their value: unlike the text fields, FALSE is a real answer here ("no, it
  // does not ship from the US") and dropping it would make unticking a box impossible.
  context.ships_from_us = Boolean(answers.value.ships_from_us);
  context.money_back_badge = Boolean(hasRefundPolicy.value && answers.value.money_back_badge);
  return store.generateForProduct(props.product?.product_id, context, props.mode);
}
</script>
