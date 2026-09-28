<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Build a page with AI</h1>
        <p>Answer a few questions and we'll create the product, the offer and a draft page</p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="store.generating" @click="store.reset()">
          Start over
        </button>
      </div>
    </header>

    <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>

    <!-- ---------- done ---------- -->
    <section v-if="store.result" class="dashboard-card">
      <header class="dashboard-card-header"><h2>Your draft page is ready</h2></header>
      <div class="dashboard-card-body">
        <p>
          We created <strong>{{ store.result.product.name }}</strong> and a draft page.
          Nothing is live &mdash; review it and publish when you're happy.
        </p>
        <p class="field-note">
          {{ store.result.page.sections.length }} sections &middot;
          {{ store.result.generation.model }} &middot;
          {{ store.result.usage.used }} of {{ store.result.usage.allowance }} generations used
        </p>
        <!-- The honest part: what the page could NOT say, and which answer would change it. -->
        <template v-if="store.result.withheld.length">
          <h3>What we couldn't say</h3>
          <p class="field-note">
            We only write what you told us. Add these and regenerate to say more:
          </p>
          <ul>
            <li v-for="w in store.result.withheld" :key="w.claim_class" class="field-note">
              {{ w.prompt }}
            </li>
          </ul>
        </template>
        <div class="button-row">
          <button class="primary-action" type="button" @click="openPage">Open in the builder</button>
          <!-- Same brief, same product, new words. The brief took minutes; the words took seconds. -->
          <button class="secondary-action" type="button" :disabled="store.generating"
                  @click="store.regenerate()">
            {{ store.generating ? "Rewriting…" : "Regenerate the copy" }}
          </button>
          <button class="secondary-action" type="button" @click="store.editAnswers()">
            Change my answers
          </button>
          <button class="secondary-action" type="button" @click="store.reset()">Start fresh</button>
        </div>
        <p class="field-note">
          Regenerating rewrites the words on this page. Your product, price and offer stay as they
          are. It uses one generation.
        </p>
      </div>
    </section>

    <!-- ---------- the wizard ---------- -->
    <template v-else>
      <section class="dashboard-card">
        <header class="dashboard-card-header">
          <h2>{{ stepLabel }}</h2>
          <span class="field-note">Step {{ store.step + 1 }} of {{ store.steps.length }}</span>
        </header>
        <div class="dashboard-card-body">

          <!-- 1. identity: the kind question carries the fulfilment question with it -->
          <template v-if="key === 'identity'">
            <p class="field-note">What kind of thing is it? This decides what we ask next.</p>
            <div class="offer-two-column">
              <label v-for="k in KINDS" :key="k.key" class="offer-field">
                <span>
                  <input v-model="b.kind" type="radio" :value="k.key" />
                  {{ k.label }}
                </span>
                <small class="field-note">{{ k.hint }}</small>
              </label>
            </div>
            <label class="offer-field">
              <span>Name</span>
              <input v-model="b.name" type="text" placeholder="e.g. Poliaxis Creatine Gummies" />
            </label>
            <label class="offer-field">
              <span>What is it, in a sentence?</span>
              <textarea v-model="b.what_it_is" rows="2"
                        placeholder="Creatine monohydrate in a chewable gummy, sold monthly."></textarea>
            </label>
          </template>

          <!-- 2. price -->
          <template v-else-if="key === 'price'">
            <div class="offer-two-column">
              <label class="offer-field">
                <span>Price</span>
                <input v-model.number="b.price.unit_amount" type="number" min="0" step="0.01" placeholder="32.91" />
              </label>
              <label class="offer-field">
                <span>Currency</span>
                <input v-model="b.price.currency" type="text" maxlength="3" />
              </label>
            </div>
            <div class="offer-two-column">
              <label class="offer-field">
                <span>How is it charged?</span>
                <select v-model="b.price.pricing_model">
                  <option value="one_time">Once</option>
                  <option value="recurring">On a schedule</option>
                </select>
              </label>
              <label v-if="b.price.pricing_model === 'recurring'" class="offer-field">
                <span>Every</span>
                <select v-model="b.price.recurring_interval">
                  <option value="week">Week</option>
                  <option value="month">Month</option>
                  <option value="year">Year</option>
                </select>
              </label>
            </div>
          </template>

          <!-- 3. audience -->
          <template v-else-if="key === 'audience'">
            <label class="offer-field">
              <span>Who is it for?</span>
              <textarea v-model="b.audience" rows="2"
                        placeholder="Lifters in their 20s-40s who dislike swallowing powder."></textarea>
            </label>
            <p class="field-note">We write to this person. Be specific &mdash; "everyone" reads as no one.</p>
          </template>

          <!-- 4. facts: the substance of nearly every section -->
          <template v-else-if="key === 'facts'">
            <label class="offer-field">
              <span>What should people know? One per line.</span>
              <textarea v-model="b.facts" rows="6"
                        placeholder="5g creatine monohydrate per serving&#10;60 gummies per tub&#10;Third-party lab tested"></textarea>
            </label>
            <p class="field-note">
              These become the page. We can only state what you put here &mdash; more lines, richer page.
            </p>
          </template>

          <!-- 5a. physical -->
          <template v-else-if="key === 'shipping_use'">
            <label class="offer-field">
              <span>What do you tell buyers about shipping?</span>
              <input v-model="b.physical.shipping" type="text"
                     placeholder="e.g. Free in the US &middot; $5 flat &middot; Ships in 2 business days" />
            </label>
            <p class="field-note">
              Whatever you actually offer, in your words &mdash; free, flat rate, calculated at
              checkout. We'll only say what you put here. Leave it empty and the page won't mention
              shipping at all.
            </p>
            <label class="offer-field">
              <span>How is it used?</span>
              <textarea v-model="b.physical.usage" rows="2" placeholder="One scoop in your drink."></textarea>
            </label>
            <label class="offer-field">
              <span>Materials</span>
              <input v-model="b.physical.materials" type="text" />
            </label>

            <h3>Parcel size and weight</h3>
            <p class="field-note">
              Used to quote shipping and buy labels &mdash; not written on the page. Leave blank if you
              haven't measured yet; you can add them on the product later.
            </p>
            <div class="offer-two-column">
              <label class="offer-field">
                <span>Length (in)</span>
                <input v-model.number="b.physical.length_in" type="number" min="0" step="0.1" />
              </label>
              <label class="offer-field">
                <span>Width (in)</span>
                <input v-model.number="b.physical.width_in" type="number" min="0" step="0.1" />
              </label>
            </div>
            <div class="offer-two-column">
              <label class="offer-field">
                <span>Height (in)</span>
                <input v-model.number="b.physical.height_in" type="number" min="0" step="0.1" />
              </label>
              <label class="offer-field">
                <span>Weight (lb)</span>
                <input v-model.number="b.physical.weight_lb" type="number" min="0" step="0.01" />
              </label>
            </div>
          </template>

          <!-- 5b. digital: never asked about shipping -->
          <template v-else-if="key === 'delivery'">
            <label class="offer-field">
              <span>What do they receive?</span>
              <input v-model="b.digital.format" type="text" placeholder="PDF, 48 pages" />
            </label>
            <label class="offer-field">
              <span>Access or licence terms</span>
              <textarea v-model="b.digital.access" rows="2"
                        placeholder="Yours to keep. Free updates for a year."></textarea>
            </label>
            <p class="field-note">Delivery is instant download &mdash; we don't need to ask.</p>
          </template>

          <!-- 5c. service: the only kind block that can block -->
          <template v-else-if="key === 'session'">
            <div class="offer-two-column">
              <label class="offer-field">
                <span>How long does it take? (minutes)</span>
                <input v-model.number="b.service.duration_minutes" type="number" min="1" />
              </label>
              <label class="offer-field">
                <span>Where?</span>
                <select v-model="b.service.location_mode">
                  <option value="remote">Remote</option>
                  <option value="in_person">In person</option>
                </select>
              </label>
            </div>
            <label class="offer-field">
              <span>Who performs it?</span>
              <input v-model="b.service.performed_by" type="text" placeholder="Me" />
            </label>
            <label class="offer-field">
              <span>What happens in a session?</span>
              <textarea v-model="b.service.what_happens" rows="3"></textarea>
            </label>
          </template>

          <!-- 6. promises -->
          <template v-else-if="key === 'promises'">
            <p class="field-note">
              Only what you actually offer. We'll never invent a promise you didn't make.
            </p>
            <label class="offer-field">
              <span>Guarantee</span>
              <input v-model="b.guarantee" type="text" placeholder="30-day money-back guarantee" />
            </label>
            <label class="offer-field">
              <span>Cancellation or renewal terms</span>
              <input v-model="b.terms" type="text" placeholder="Cancel any time, no fee" />
            </label>
            <label class="offer-field">
              <span>Certifications you hold. One per line.</span>
              <textarea v-model="b.certifications" rows="2"></textarea>
            </label>
            <label class="offer-field">
              <span>Evidence for any results you claim</span>
              <textarea v-model="b.evidence" rows="2"
                        placeholder="Leave empty unless you can stand behind it."></textarea>
            </label>
            <p class="field-note">
              Evidence is the only thing that lets us describe results. Leave it empty and we won't.
            </p>
          </template>

          <!-- 7. voice -->
          <template v-else-if="key === 'voice'">
            <div class="offer-two-column">
              <label class="offer-field">
                <span>Tone</span>
                <select v-model="b.tone">
                  <option v-for="t in TONES" :key="t" :value="t">{{ t }}</option>
                </select>
              </label>
            </div>
            <ProductCategoryField v-model="b.category" :product-type="categoryScope" :required="false" />
            <p class="field-note">
              Category picks the colour palette, and files the product alongside your others.
            </p>
          </template>

          <!-- 8. exact -->
          <template v-else-if="key === 'exact'">
            <label class="offer-field">
              <span>Lines to include word for word</span>
              <textarea v-model="b.must_say" rows="3"></textarea>
            </label>
            <label class="offer-field">
              <span>Things never to say</span>
              <textarea v-model="b.must_not_say" rows="3"></textarea>
            </label>
          </template>

          <!-- 9. review -->
          <template v-else-if="key === 'review'">
            <p>We'll create a product, an offer and a <strong>draft</strong> page. Nothing goes live.</p>
            <ul>
              <li v-for="row in summary" :key="row.label" class="field-note">
                <strong>{{ row.label }}:</strong> {{ row.value }}
              </li>
            </ul>
            <!-- Shown BEFORE generating. A tenant who sees this understands a thin page; one who
                 doesn't thinks the AI is bad. -->
            <template v-if="store.withheld.length">
              <h3>What we won't be able to say</h3>
              <ul>
                <li v-for="w in store.withheld" :key="w.claimClass" class="field-note">{{ w.prompt }}</li>
              </ul>
              <p class="field-note">
                You can go back and add these, or generate now and fill them in later.
              </p>
            </template>
            <p v-else class="field-note">You've answered everything &mdash; we can write the full page.</p>
          </template>
        </div>
      </section>

      <div class="button-row">
        <button v-if="store.step > 0" class="secondary-action" type="button" @click="store.back()">Back</button>
        <button
          v-if="!store.onLastStep"
          class="primary-action"
          type="button"
          :disabled="!store.canAdvance"
          @click="store.next()"
        >
          {{ SKIPPABLE.has(key) ? "Skip" : "Next" }}
        </button>
        <button v-else class="primary-action" type="button" :disabled="store.generating" @click="generate">
          {{ store.generating ? "Writing your page…" : "Generate the page" }}
        </button>
      </div>
      <p v-if="store.generating" class="field-note">
        This takes a few seconds &mdash; we're writing and checking every line against what you told us.
      </p>
    </template>
  </section>
</template>

<script setup>
import { computed, inject } from "vue";
import { KINDS, SKIPPABLE, STEP_LABELS, TONES, useAiPageStore } from "../stores/aiPage";
import ProductCategoryField from "./products/ProductCategoryField.vue";

const store = useAiPageStore();
const navigateTo = inject("navigateTo", null);

const b = computed(() => store.brief);
const key = computed(() => store.stepKey);
const stepLabel = computed(() => STEP_LABELS[key.value] || "");
// Category suggestions are scoped by product type, and a service brief never reaches this wizard's
// generate step -- but the field still needs a scope while the tenant is on it.
const categoryScope = computed(() => (store.brief.kind === "digital" ? "digital" : "physical"));

const summary = computed(() => {
  const brief = store.brief;
  const rows = [
    { label: "Name", value: brief.name || "—" },
    { label: "Price", value: brief.price.unit_amount
        ? `${brief.price.unit_amount} ${brief.price.currency.toUpperCase()}`
          + (brief.price.pricing_model === "recurring" ? ` every ${brief.price.recurring_interval}` : "")
        : "—" },
    { label: "For", value: brief.audience || "—" },
    { label: "Facts", value: `${String(brief.facts || "").split("\n").filter((s) => s.trim()).length} lines` },
  ];
  return rows;
});

async function generate() {
  await store.generate();
}

function openPage() {
  // Straight into the builder on the page we just made: the tenant reviews and publishes there.
  if (navigateTo && store.result) navigateTo("landingPages", { edit: store.result.page.page_id });
}
</script>
