<template>
  <div class="service-wizard">
    <WizardSteps :steps="stepLabels" :current="displayStep" />

    <div v-if="error" class="keys-status-banner error">{{ error }}</div>

    <form class="coupon-form" @submit.prevent="onSubmit">
      <!-- 1. What you offer -->
      <section v-if="stepKey === 'identity'" class="offer-form-section">
        <header class="offer-section-header">
          <div>
            <h3>What do you offer?</h3>
            <p>Name it the way a customer would ask for it.</p>
          </div>
        </header>
        <label class="offer-field">
          <span>Name <strong>*</strong></span>
          <input :value="form.name" type="text" placeholder="60-Minute Consultation"
                 @input="applyTitleCaseInput((value) => { form.name = value; }, $event)" />
        </label>
        <label class="offer-field">
          <span>Description</span>
          <textarea v-model.trim="form.description" rows="3" placeholder="What the customer gets"></textarea>
        </label>
      </section>

      <!-- 2. Details -->
      <section v-else-if="stepKey === 'details'" class="offer-form-section">
        <header class="offer-section-header">
          <div>
            <h3>A few details</h3>
            <p>How you'd file it, and where the work happens.</p>
          </div>
        </header>
        <ProductCategoryField v-model="form.product_category" product-type="service" />
        <label class="offer-field">
          <span>Where does it happen?</span>
          <select v-model="form.location_mode">
            <option v-for="mode in LOCATION_MODES" :key="mode" :value="mode">{{ locationLabel(mode) }}</option>
          </select>
        </label>
      </section>

      <!-- 3. THE BRANCH -->
      <section v-else-if="stepKey === 'booking'" class="offer-form-section">
        <header class="offer-section-header">
          <div>
            <h3>Do customers book an appointment?</h3>
            <p>This decides most of what's left — answer it and the rest follows.</p>
          </div>
        </header>
        <div class="wizard-choice-list">
          <WizardChoiceCard
            title="Yes — they pick a time"
            description="A calendar slot is reserved. Haircuts, consultations, home visits."
            :selected="form.fulfillment_mode === 'scheduled'"
            @select="form.fulfillment_mode = 'scheduled'"
          />
          <WizardChoiceCard
            title="No — they just pay"
            description="No time is reserved. An add-on, a retainer, a standalone charge."
            :selected="form.fulfillment_mode === 'no_booking'"
            @select="form.fulfillment_mode = 'no_booking'"
          />
        </div>
      </section>

      <!-- 4. Price -->
      <section v-else-if="stepKey === 'price'" class="offer-form-section">
        <header class="offer-section-header">
          <div>
            <h3>What does it cost?</h3>
            <p>What a customer pays for it.</p>
          </div>
        </header>
        <PricingCard
          :prices="form.prices"
          v-model:default-index="form.default_price_index"
          product-type="service"
          title="Pricing"
          subtitle="Net-guaranteed adds fees on top so you keep the full amount."
          :contexts="SERVICE_PRICE_CONTEXTS"
          :pricing-models="SERVICE_PRICING_MODELS"
        />
      </section>

      <!-- 5. Duration -->
      <section v-else-if="stepKey === 'duration'" class="offer-form-section">
        <header class="offer-section-header">
          <div>
            <h3>How long does it take?</h3>
            <p>This sizes the slot on your calendar.</p>
          </div>
        </header>
        <label class="offer-field">
          <span>Duration (minutes) <strong>*</strong></span>
          <input v-model.number="form.duration_minutes" min="1" step="5" type="number" />
        </label>
      </section>

      <!-- 6. Payment timing -->
      <section v-else-if="stepKey === 'payment'" class="offer-form-section">
        <header class="offer-section-header">
          <div>
            <h3>When do they pay?</h3>
            <p>Most businesses take payment up front. You can change this later.</p>
          </div>
        </header>
        <div class="wizard-choice-list">
          <WizardChoiceCard
            title="Pay first, then book"
            description="The slot is held once payment clears."
            :selected="form.booking_flow === 'pay_then_book'"
            @select="form.booking_flow = 'pay_then_book'"
          />
          <WizardChoiceCard
            title="Book first, pay later"
            description="You invoice afterwards. Suits work that's quoted or variable."
            :selected="form.booking_flow === 'book_then_pay'"
            @select="form.booking_flow = 'book_then_pay'"
          />
        </div>
      </section>

      <!-- 7. Who performs it -->
      <section v-else-if="stepKey === 'who'" class="offer-form-section">
        <header class="offer-section-header">
          <div>
            <h3>Who will do the work?</h3>
            <p>If it's just you, there's nothing to set up.</p>
          </div>
        </header>
        <div class="wizard-choice-list">
          <WizardChoiceCard
            title="I do"
            description="Bookings use your own hours and calendar."
            :selected="!hasStaff"
            @select="hasStaff = false"
          />
          <WizardChoiceCard
            title="My team does"
            description="Add the people who perform it and how they're paid."
            :selected="hasStaff"
            @select="hasStaff = true"
          />
        </div>
        <div v-if="hasStaff" class="wizard-embed">
          <FulfillersPanel embedded />
        </div>
      </section>

      <!-- 8. Availability (tenant-scoped) -->
      <section v-else-if="stepKey === 'availability'" class="offer-form-section">
        <header class="offer-section-header">
          <div>
            <h3>When are you available?</h3>
            <p>Your business hours, and how far ahead people can book. This is set once and used by every service.</p>
          </div>
        </header>
        <div class="wizard-embed"><TenantAvailabilityPanel embedded /></div>
      </section>

      <!-- 9. Exceptions (tenant-scoped) -->
      <section v-else-if="stepKey === 'exceptions'" class="offer-form-section">
        <header class="offer-section-header">
          <div>
            <h3>Any exceptions?</h3>
            <p>Holidays, one-off closures, or extra hours. Skip this — you can add them any time.</p>
          </div>
        </header>
        <div class="wizard-embed"><AvailabilityExceptionsPanel embedded /></div>
      </section>

      <!-- 10. Tips -->
      <section v-else-if="stepKey === 'tips'" class="offer-form-section">
        <header class="offer-section-header">
          <div>
            <h3>Who gets the tips?</h3>
            <p>If a customer adds a tip when they book.</p>
          </div>
        </header>
        <div class="wizard-choice-list">
          <WizardChoiceCard
            title="The person who did the work"
            description="The tip goes to whoever fulfilled the booking."
            :selected="form.tips_to_fulfiller"
            @select="form.tips_to_fulfiller = true"
          />
          <WizardChoiceCard
            title="The business"
            description="Tips stay with the business."
            :selected="!form.tips_to_fulfiller"
            @select="form.tips_to_fulfiller = false"
          />
        </div>
      </section>

      <!-- 11. Calendar (tenant-scoped) -->
      <section v-else-if="stepKey === 'calendar'" class="offer-form-section">
        <header class="offer-section-header">
          <div>
            <h3>Calendar</h3>
            <p>Connect a calendar so bookings appear on it and busy times block new ones.</p>
          </div>
        </header>
        <div class="wizard-embed"><CalendarPanel embedded /></div>
      </section>

      <!-- 12. Photo -->
      <section v-else-if="stepKey === 'photo'" class="offer-form-section">
        <header class="offer-section-header">
          <div>
            <h3>Add a photo</h3>
            <p>Optional. It's the image customers see when this is on a page.</p>
          </div>
        </header>
        <!-- Wired exactly as the service editor wires it. My first pass invented the API: no `uploader`
             (which the component REQUIRES, so nothing could upload), an `@uploaded` event it does not emit,
             and `asset.service` for a ratio key that is called `asset.service_hero`. -->
        <ImageUploadField
          v-model="form.hero_image_url"
          :crop="form.hero_image_crop"
          :ratios="imageRatios.asset.service_hero"
          :uploader="uploadServiceHero"
          bake
          label="Upload hero image"
          alt="Hero image preview"
          @update:crop="(rect) => (form.hero_image_crop = rect)"
        />
      </section>

      <!-- 13. Review -->
      <section v-else-if="stepKey === 'review'" class="offer-form-section">
        <header class="offer-section-header">
          <div>
            <h3>Ready?</h3>
            <p>Anything here can be changed later. Click a line to go back to it.</p>
          </div>
        </header>
        <ul class="wizard-review">
          <li v-for="row in reviewRows" :key="row.step">
            <button type="button" class="wizard-review-line" @click="goToStep(row.step)">
              <span class="wizard-review-label">{{ row.label }}</span>
              <span class="wizard-review-value">{{ row.value }}</span>
            </button>
          </li>
        </ul>
        <label class="checkbox-row offer-checkbox-inline">
          <input v-model="form.active" type="checkbox" />
          <span>Available for booking straight away</span>
        </label>
      </section>

      <footer class="modal-footer">
        <button v-if="step > 1" class="secondary-action" type="button" @click="back">Back</button>
        <button v-else class="secondary-action" type="button" @click="emit('cancel')">Cancel</button>
        <button v-if="skippable" class="secondary-action" type="button" @click="next">Skip</button>
        <button class="primary-action" type="submit" :disabled="store.saving">
          {{ store.saving ? "Saving..." : (onLastStep ? "Create service" : "Next") }}
        </button>
      </footer>
    </form>
  </div>
</template>

<script setup>
/*
 * Creating a service without being handed a console.
 *
 * The screen this replaces at create-time asks ~22 questions for a document whose validator requires three,
 * and the five panels beside it (fulfillers, availability, exceptions, calendar, appointments) are stacked
 * with no order. The author's instruction was not to ask LESS -- "if we simply say: here you go, create your
 * service in this huge screen, our software loses value" -- but to break the same material into pieces that
 * arrive one question at a time.
 *
 * So this EMBEDS those panels rather than reimplementing them (`embedded` prop), and the steps are
 * conditional on the answers rather than on the schema. Step 3 does most of the work: a service nobody books
 * needs no duration, no availability, no calendar and no exceptions, and the wizard collapses accordingly.
 *
 * Tenant-scoped vs service-scoped matters here. Availability, exceptions, staff and calendar belong to the
 * BUSINESS, not to this service -- so once they are set, later services show them as a confirmed line
 * instead of asking again. A wizard that re-asks your opening hours for every haircut is worse than the
 * console it replaced.
 */
import { computed, onMounted, ref } from "vue";
import WizardSteps from "../shared/WizardSteps.vue";
import WizardChoiceCard from "../shared/WizardChoiceCard.vue";
import PricingCard from "../shared/PricingCard.vue";
import ImageUploadField from "../shared/ImageUploadField.vue";
import ProductCategoryField from "../products/ProductCategoryField.vue";
import FulfillersPanel from "./FulfillersPanel.vue";
import TenantAvailabilityPanel from "./TenantAvailabilityPanel.vue";
import AvailabilityExceptionsPanel from "./AvailabilityExceptionsPanel.vue";
import CalendarPanel from "./CalendarPanel.vue";
import imageRatios from "../../../../src/stripe_link/image_ratios.json";
import { applyTitleCaseInput } from "../../utils/titleCase.js";
import { recordImageDims } from "../../utils/imageDims";
import { uploadImage } from "../../api/uploads";
import {
  LOCATION_MODES, SERVICE_PRICE_CONTEXTS, SERVICE_PRICING_MODELS,
  defaultServiceForm, locationLabel, useServicesStore,
} from "../../stores/services";
import { useFulfillersStore } from "../../stores/fulfillers";
import { useTenantAvailabilityStore } from "../../stores/tenantAvailability";

const props = defineProps({
  // Values already collected by whatever opened this -- the product wizard asks for a name and a category
  // before it knows the type is "service", and asking twice would be the discontinuity this exists to remove.
  seed: { type: Object, default: () => ({}) },
});
const emit = defineEmits(["created", "cancel"]);

const store = useServicesStore();
const fulfillers = useFulfillersStore();
const tenantAvailability = useTenantAvailabilityStore();

const form = ref({ ...defaultServiceForm(), tips_to_fulfiller: true, product_category: "", ...props.seed });
const step = ref(1);
const error = ref("");
const hasStaff = ref(false);

onMounted(() => {
  if (!fulfillers.loaded) fulfillers.load();
  if (!tenantAvailability.loaded) tenantAvailability.load?.();
});

const booked = computed(() => form.value.fulfillment_mode !== "no_booking");
// Tenant-scoped setup only has to happen ONCE. A second service skips straight past it.
const availabilityAlreadySet = computed(() => !!tenantAvailability.availability);
const hasFulfillers = computed(() => (fulfillers.fulfillers || []).length > 0);

const STEP_LABELS = {
  identity: "Service", details: "Details", booking: "Booking", price: "Price", duration: "Duration",
  payment: "Payment", who: "Who", availability: "Hours", exceptions: "Exceptions", tips: "Tips",
  calendar: "Calendar", photo: "Photo", review: "Review",
};
// The steps THIS tenant will see, derived once. The rail, the labels and the bounds all read this single
// list -- LandingPages.vue's rail is the scar that says what happens when three calculations each decide
// for themselves how long a conditional wizard is.
const steps = computed(() => {
  const out = ["identity", "details", "booking", "price"];
  if (booked.value) out.push("duration", "payment");
  out.push("who");
  if (booked.value && !availabilityAlreadySet.value) out.push("availability");
  if (booked.value && !availabilityAlreadySet.value) out.push("exceptions");
  if (hasStaff.value || hasFulfillers.value) out.push("tips");
  if (booked.value) out.push("calendar");
  out.push("photo", "review");
  return out;
});
const stepLabels = computed(() => steps.value.map((key) => STEP_LABELS[key]));
const stepKey = computed(() => steps.value[step.value - 1] || "identity");
const displayStep = computed(() => Math.min(step.value, steps.value.length));
const onLastStep = computed(() => step.value >= steps.value.length);
// Steps whose defaults are already right. Stated as a button, so "leave it" is one click and not a guess.
const skippable = computed(() => ["exceptions", "photo"].includes(stepKey.value) && !onLastStep.value);

function goToStep(key) {
  const index = steps.value.indexOf(key);
  if (index >= 0) step.value = index + 1;
}

function validateStep() {
  if (stepKey.value === "identity" && !String(form.value.name || "").trim()) {
    return "Give the service a name.";
  }
  if (stepKey.value === "duration" && Number(form.value.duration_minutes || 0) < 1) {
    return "Enter how long it takes, in minutes.";
  }
  return "";
}

function next() {
  error.value = validateStep();
  if (error.value) return;
  if (!onLastStep.value) step.value += 1;
}

function back() {
  error.value = "";
  if (step.value > 1) step.value -= 1;
}

// One submit path: Enter advances rather than saving a half-built service, and only the last step creates.
function onSubmit() {
  if (!onLastStep.value) {
    next();
    return;
  }
  save();
}

async function uploadServiceHero(file) {
  const result = await uploadImage(file, { basePrefix: "services" });
  recordImageDims(form.value.image_dims, result.url, result.dims);
  return result;
}

const reviewRows = computed(() => {
  const rows = [
    { step: "identity", label: "Service", value: form.value.name || "—" },
    { step: "details", label: "Where", value: locationLabel(form.value.location_mode) },
    { step: "booking", label: "Booking", value: booked.value ? "Customers pick a time" : "No appointment" },
    { step: "price", label: "Price", value: priceSummary.value },
  ];
  if (booked.value) {
    rows.push({ step: "duration", label: "Takes", value: `${form.value.duration_minutes} minutes` });
    rows.push({
      step: "payment", label: "Payment",
      value: form.value.booking_flow === "book_then_pay" ? "Book first, pay later" : "Pay first, then book",
    });
  }
  rows.push({ step: "who", label: "Performed by", value: hasStaff.value ? "My team" : "Me" });
  return rows.filter((row) => steps.value.includes(row.step));
});

const priceSummary = computed(() => {
  const price = (form.value.prices || [])[form.value.default_price_index || 0];
  const amount = Number(price?.unit_amount_major ?? price?.unit_amount ?? 0);
  if (!amount) return "Not set";
  return `${String(price?.currency || "usd").toUpperCase()} ${amount}`;
});

async function save() {
  error.value = "";
  const problem = validateStep();
  if (problem) { error.value = problem; return; }
  if (!String(form.value.name || "").trim()) { error.value = "Give the service a name."; step.value = 1; return; }
  try {
    const saved = await store.saveService(form.value, null);
    emit("created", saved);
  } catch (err) {
    error.value = err.message || "The service could not be created.";
  }
}
</script>

<style scoped>
/* The panels bring their own card when they stand alone on the Services screen; inside a step the wizard
   supplies the heading, so `embedded` strips their chrome and this only has to give back the spacing. */
.wizard-embed { margin-top: 1.2rem; }
.wizard-review { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.wizard-review-line {
  width: 100%; display: flex; justify-content: space-between; gap: 1rem; align-items: baseline;
  background: transparent; border: 0; border-bottom: 1px solid var(--border, #e5e7eb);
  padding: 0.7rem 0.2rem; cursor: pointer; text-align: left; font: inherit;
}
.wizard-review-line:hover { background: var(--surface-hover, rgba(0, 0, 0, 0.03)); }
.wizard-review-label { color: var(--text-muted, #6b7280); }
.wizard-review-value { font-weight: 700; }
</style>
