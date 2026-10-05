<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="markShippedTitle">
      <header class="modal-card-header">
        <h2 id="markShippedTitle">Mark as shipped</h2>
        <button type="button" class="modal-close" aria-label="Close" @click="$emit('close')">×</button>
      </header>
      <div class="product-details-body">
        <p class="field-hint">
          Tells {{ buyerName }} their order is on its way, and records how it went out.
        </p>

        <label>
          Carrier
          <select v-model="form.carrier">
            <option value="">Not specified</option>
            <option v-for="option in carriers" :key="option.key" :value="option.key">{{ option.label }}</option>
          </select>
        </label>

        <label v-if="services.length">
          Service
          <select v-model="form.service">
            <option value="">Not specified</option>
            <option v-for="service in services" :key="service.key" :value="service.key">{{ service.label }}</option>
          </select>
        </label>

        <!-- The whole reason the number is optional. Said BEFORE they hunt for one that does not exist. -->
        <p v-if="selectedService && selectedService.tracking === false" class="keys-status-banner warning">
          {{ selectedService.label }} does not include tracking. Leave the number blank — the buyer will be
          told the parcel is on its way.
        </p>

        <label>
          Tracking number <span class="field-optional">optional</span>
          <input v-model.trim="form.tracking_number" type="text" placeholder="Leave blank if there is none" />
        </label>

        <!-- The tenant's OWN words, carried into the buyer's email. "We ran out of stock and restocked
             Tuesday" is a sentence only they can write, and it does more than any wording shipped here.
             Shown always, not only when late: a parcel going out early is worth a line too. -->
        <label>
          Note to the buyer <span class="field-optional">optional</span>
          <textarea v-model.trim="form.note" rows="2" maxlength="400"
                    placeholder="Anything they should know — a delay, a substitution, a thank you."></textarea>
          <small class="field-hint">
            Added to their shipping email, above the tracking details. They also get the arrival date,
            recalculated from today.
          </small>
        </label>

        <label v-if="form.carrier === 'other'">
          Tracking link
          <input v-model.trim="form.tracking_url" type="url" placeholder="https://..." />
          <small class="field-hint">We do not know this carrier's tracking page, so paste the link.</small>
        </label>

        <p v-if="localError || error" class="keys-status-banner error">{{ localError || error }}</p>

        <div class="button-row">
          <button type="button" class="primary-action" :disabled="saving" @click="submit">
            {{ saving ? "Sending…" : sendLabel }}
          </button>
          <button type="button" class="secondary-action" :disabled="saving" @click="$emit('close')">Cancel</button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";

// Presentation only: the parent owns the request, so `saving` and `error` arrive as props rather than
// being invented here. A component that fetches is a component that cannot be reused or reasoned about.
const props = defineProps({
  order: { type: Object, required: true },
  carriers: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
  error: { type: String, default: "" },
});
const emit = defineEmits(["close", "shipped"]);

const form = reactive({ carrier: "", service: "", tracking_number: "", tracking_url: "", note: "" });
const localError = ref("");

const buyerName = computed(() =>
  props.order?.customer?.name || props.order?.customer?.email || "the customer");

const services = computed(() =>
  (props.carriers.find((c) => c.key === form.carrier) || {}).services || []);

const selectedService = computed(() =>
  services.value.find((s) => s.key === form.service) || null);

// Changing carrier invalidates the service: "ground" means different things at UPS and FedEx.
watch(() => form.carrier, () => { form.service = ""; });

const sendLabel = computed(() =>
  form.tracking_number ? "Mark shipped & send tracking" : "Mark shipped & notify");

function submit() {
  localError.value = "";
  if (form.tracking_number && !form.carrier) {
    localError.value = "Choose a carrier so the tracking number becomes a link.";
    return;
  }
  emit("shipped", { ...form });
}
</script>
