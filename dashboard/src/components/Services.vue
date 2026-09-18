<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Services</h1>
        <p>Configure services, fulfillers, availability, and appointments</p>
      </div>
    </header>

    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>Service Catalog</h2>
        <div class="button-row">
          <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load()">
            {{ store.loading ? "Loading..." : "Load Services" }}
          </button>
          <button class="primary-action" type="button" @click="openCreateModal">+ Create Service</button>
        </div>
      </header>

      <div class="product-filter-bar">
        <label>
          Search
          <input v-model.trim="store.filters.search" type="search" placeholder="Name, description, service ID..." @focus="store.ensureLoaded()" />
        </label>
        <label>
          Status
          <select v-model="store.filters.status" @focus="store.ensureLoaded()">
            <option value="all">All</option>
            <option value="active">Active</option>
            <option value="inactive">Archived</option>
          </select>
        </label>
        <div class="product-filter-actions">
          <button type="button" class="secondary-action" @click="resetFilters">Reset</button>
        </div>
      </div>

      <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
      <div v-else-if="store.statusMessage" class="keys-status-banner">{{ store.statusMessage }}</div>

      <div v-if="!store.filteredServices.length" class="product-empty-state">
        {{ store.loading ? "Loading services..." : store.loaded ? "No services found. Create a service to get started." : "Click Load Services to see services." }}
      </div>

      <div v-else class="product-card-list">
        <ListCard
          v-for="service in store.filteredServices"
          :key="service.service_id"
          :image="serviceImage(service)"
          :icon-color-key="service.service_id"
          :title="service.name || 'Untitled Service'"
          :description="service.description"
          :status-label="serviceIsActive(service) ? 'Active' : 'Archived'"
          :status-tone="serviceIsActive(service) ? 'active' : 'archived'"
          :archived="!serviceIsActive(service)"
        >
          <template #icon>
            <svg class="service-tools-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17 17.25 21A2.652 2.652 0 0 0 21 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 1 1-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 0 0 4.486-6.336l-3.276 3.277a3.004 3.004 0 0 1-2.25-2.25l3.276-3.276a4.5 4.5 0 0 0-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437 1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008Z" />
            </svg>
          </template>
          <template #subtitle>
            <strong>{{ formatServicePrice(service) }}</strong>
            <span class="product-card-compare">{{ serviceMetaText(service) }}</span>
          </template>
          <template #actions>
            <button type="button" class="secondary-action" @click="openEditModal(service)">Edit</button>
            <button type="button" class="secondary-action" @click="selectedService = service">Details</button>
            <button type="button" class="secondary-action" :disabled="store.saving" @click="toggleArchive(service)">
              {{ serviceIsActive(service) ? "Archive" : "Restore" }}
            </button>
            <button
              v-if="!serviceIsActive(service)"
              type="button"
              class="secondary-action danger-action"
              :disabled="store.saving"
              @click="promptDelete(service)"
            >
              Delete
            </button>
          </template>
        </ListCard>
      </div>
    </section>

    <FulfillersPanel />
    <TenantAvailabilityPanel />
    <AvailabilityExceptionsPanel />
    <CalendarPanel />
    <AppointmentsPanel />

    <div v-if="showServiceModal" class="modal-backdrop" @click.self="closeServiceModal">
      <section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="serviceModalTitle">
        <header class="modal-card-header">
          <h2 id="serviceModalTitle">{{ editingService ? "Edit Service" : "Create a service" }}</h2>
          <button type="button" class="modal-close" aria-label="Close service modal" @click="closeServiceModal">×</button>
        </header>

        <WizardSteps v-if="wizardMode" :steps="wizardLabels" :current="wizardStep" />

        <form class="coupon-form" @submit.prevent="onServiceFormSubmit">
          <div v-if="formError" class="keys-status-banner error">{{ formError }}</div>

          <section v-if="showsBlock('details')" class="offer-form-section">
            <header v-if="wizardMode" class="offer-section-header">
              <div>
                <h3>What do you offer?</h3>
                <p>Name it the way a customer would ask for it.</p>
              </div>
            </header>
            <div class="offer-two-column">
              <label class="offer-field">
                <span>Service Name <strong>*</strong></span>
                <input :value="form.name" type="text" placeholder="60-Minute Consultation" required
                       @input="applyTitleCaseInput((value) => { form.name = value; }, $event)" />
              </label>
              <!-- Where it happens is a real question, but not the FIRST one: it has a working default and a
                   tenant creating their first service is thinking about what they sell, not logistics. -->
              <label v-if="!wizardMode" class="offer-field">
                <span>Location Mode</span>
                <select v-model="form.location_mode">
                  <option v-for="mode in LOCATION_MODES" :key="mode" :value="mode">{{ locationLabel(mode) }}</option>
                </select>
              </label>
            </div>
            <!-- Asked as "does this need an appointment?" on the Scheduling step instead, where it belongs. -->
            <label v-if="!wizardMode" class="offer-field">
              <span>Fulfillment</span>
              <select v-model="form.fulfillment_mode">
                <option value="scheduled">Scheduled — customer books a time</option>
                <option value="no_booking">No booking — pay only (no appointment)</option>
              </select>
              <small v-if="form.fulfillment_mode === 'no_booking'" class="services-hint">
                Pay-only service with no appointment (e.g. an add-on or standalone charge). Taxed as a service; routes to a fulfiller for payout.
              </small>
            </label>
            <label class="offer-field">
              <span>Description</span>
              <textarea v-model.trim="form.description" rows="3" placeholder="What the customer gets"></textarea>
            </label>
          </section>

          <section v-if="showsBlock('pricing') || showsBlock('scheduling')" class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3 v-if="!wizardMode">Pricing &amp; Duration</h3>
                <h3 v-else-if="wizardStepKey === 'pricing'">What does it cost?</h3>
                <h3 v-else>How is it scheduled?</h3>
                <p v-if="!wizardMode">The price a customer pays and how long the service takes.</p>
                <p v-else-if="wizardStepKey === 'pricing'">What a customer pays to book it.</p>
                <p v-else>Most services take an appointment. You can change any of this later.</p>
              </div>
            </header>
            <PricingCard
              v-if="showsBlock('pricing')"
              :prices="form.prices"
              v-model:default-index="form.default_price_index"
              product-type="service"
              title="Pricing"
              subtitle="Net-guaranteed adds fees on top so you keep the full amount."
              :contexts="SERVICE_PRICE_CONTEXTS"
              :pricing-models="SERVICE_PRICING_MODELS"
            />
            <!-- The wizard asks the schema's `fulfillment_mode` as the question a tenant actually has. Both
                 answers are one click, and the default is the common one. -->
            <label v-if="showsBlock('scheduling') && wizardMode" class="checkbox-row offer-checkbox-inline">
              <input :checked="form.fulfillment_mode !== 'no_booking'" type="checkbox"
                     @change="form.fulfillment_mode = $event.target.checked ? 'scheduled' : 'no_booking'" />
              <span>Customers book an appointment for this</span>
            </label>
            <small v-if="showsBlock('scheduling') && wizardMode && form.fulfillment_mode === 'no_booking'"
                   class="services-hint">
              They will pay for it without picking a time — an add-on or a standalone charge.
            </small>
            <div v-if="showsBlock('scheduling') && form.fulfillment_mode !== 'no_booking'" class="offer-two-column">
              <label class="offer-field">
                <span>Duration (minutes) <strong>*</strong></span>
                <input v-model.number="form.duration_minutes" min="1" step="5" type="number" required />
              </label>
              <!-- Pay-then-book is the default and the safer one; a tenant who wants to invoice afterwards
                   is describing a business model they already know they have, and can say so in the editor. -->
              <label v-if="!wizardMode" class="offer-field">
                <span>Booking flow</span>
                <select v-model="form.booking_flow">
                  <option value="pay_then_book">Pay first, then book a time</option>
                  <option value="book_then_pay">Book first, pay later (invoice)</option>
                </select>
              </label>
            </div>
          </section>

          <!-- The operations console: staff, compensation, overrides, check-in windows. Hidden while creating,
               shown in full when editing. The defaults it would have asked for are already correct for the
               tenant who is doing the work themselves, which is who is creating their first service. -->
          <section v-if="showsAdvanced" class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3>Allowed Fulfillers</h3>
                <p>If you intend to fulfill the work yourself, leave this blank. Otherwise, you can assign which fulfillers can perform this service, with an optional per-service compensation override.</p>
              </div>
            </header>
            <!-- Assign an existing fulfiller (staff already created). -->
            <template v-if="assignableFulfillers.length">
              <div class="offer-three-column">
                <label class="offer-field">
                  <span>Fulfiller</span>
                  <select v-model="allowedForm.fulfiller_id">
                    <option value="">Select fulfiller</option>
                    <option v-for="f in assignableFulfillers" :key="f.fulfiller_id" :value="f.fulfiller_id">{{ fulfillerDisplayName(f) }}</option>
                  </select>
                </label>
                <label class="offer-field">
                  <span>Override Type</span>
                  <select v-model="allowedForm.override_type">
                    <option value="use_fulfiller_default">Use fulfiller default</option>
                    <option value="flat_fee">Flat Fee</option>
                    <option value="percent">Percent</option>
                  </select>
                </label>
                <label class="offer-field">
                  <span>Override Amount</span>
                  <input v-model.number="allowedForm.override_amount" type="number" min="0" step="0.01" :disabled="allowedForm.override_type === 'use_fulfiller_default'" />
                </label>
              </div>
              <label class="checkbox-row offer-checkbox-inline"><input v-model="allowedForm.tips_to_fulfiller" type="checkbox" /><span>Tips go to fulfiller</span></label>
              <div class="button-row services-form-actions">
                <button type="button" class="secondary-action" :disabled="!allowedForm.fulfiller_id" @click="addAllowedFulfiller">Assign fulfiller</button>
              </div>
            </template>
            <p v-else-if="!form.allowed_fulfillers.length" class="services-hint">No staff yet — add one below.</p>

            <!-- Create a brand-new fulfiller without leaving this modal. -->
            <div v-if="!showAddFulfiller" class="button-row services-form-actions">
              <button type="button" class="secondary-action" @click="openAddFulfiller">+ Add a fulfiller</button>
            </div>
            <div v-else class="quick-add-fulfiller">
              <div class="offer-two-column">
                <label class="offer-field"><span>First Name</span><input v-model.trim="newFulfiller.first_name" type="text" placeholder="Mary" /></label>
                <label class="offer-field"><span>Last Name</span><input v-model.trim="newFulfiller.last_name" type="text" placeholder="Therapist" /></label>
              </div>
              <div class="offer-three-column">
                <label class="offer-field"><span>Email <strong>*</strong></span><input v-model.trim="newFulfiller.email" type="email" placeholder="mary@example.com" /></label>
                <label class="offer-field">
                  <span>Compensation Type</span>
                  <select v-model="newFulfiller.compensation_type">
                    <option value="flat_fee">Flat Fee</option>
                    <option value="percent">Percent</option>
                    <option value="hourly">Hourly</option>
                  </select>
                </label>
                <label class="offer-field"><span>Compensation Amount</span><input v-model.number="newFulfiller.compensation_amount" type="number" min="0" step="0.01" /></label>
              </div>
              <p v-if="addFulfillerError" class="services-hint warning">{{ addFulfillerError }}</p>
              <div class="button-row services-form-actions">
                <button type="button" class="secondary-action" @click="showAddFulfiller = false">Cancel</button>
                <button type="button" class="primary-action" :disabled="fulfillers.saving" @click="createFulfiller">
                  {{ fulfillers.saving ? "Adding…" : "Add fulfiller" }}
                </button>
              </div>
            </div>

            <table v-if="form.allowed_fulfillers.length" class="dashboard-table services-table">
              <thead><tr><th>Fulfiller</th><th>Compensation</th><th>Tips</th><th>Enabled</th><th></th></tr></thead>
              <tbody>
                <tr v-for="(row, index) in form.allowed_fulfillers" :key="row.fulfiller_id">
                  <td>{{ fulfillerName(row.fulfiller_id) }}</td>
                  <td>{{ overrideLabel(row) }}</td>
                  <td><input v-model="row.tips_to_fulfiller" type="checkbox" /></td>
                  <td><input v-model="row.enabled" type="checkbox" /></td>
                  <td><button type="button" class="secondary-action compact danger" @click="form.allowed_fulfillers.splice(index, 1)">Remove</button></td>
                </tr>
              </tbody>
            </table>
          </section>

          <!-- Already unreachable while creating (a new service has no fulfillers), but said out loud so a
               future default cannot quietly put a compensation override in front of a first-time tenant. -->
          <template v-if="showsAdvanced && form.allowed_fulfillers.length">
            <section class="offer-form-section">
              <header class="offer-section-header">
                <div>
                  <h3>Assignment Override</h3>
                  <p>The default fulfiller and calendar for this service. Each fulfiller's own calendar takes priority; use these to override the default — e.g. when the usual fulfiller is unavailable.</p>
                </div>
              </header>
              <div class="offer-two-column">
                <label class="offer-field">
                  <span>Default Fulfiller</span>
                  <select v-model="form.default_fulfiller_id">
                    <option value="">Unassigned</option>
                    <option v-for="f in serviceFulfillerOptions" :key="f.fulfiller_id" :value="f.fulfiller_id">{{ fulfillerDisplayName(f) }}</option>
                  </select>
                </label>
                <label v-if="form.fulfillment_mode !== 'no_booking'" class="offer-field">
                  <span>Calendar</span>
                  <select v-model="form.calendar_connection_id">
                    <option value="">Default calendar</option>
                    <option v-for="c in calendar.connections" :key="c.connection_id" :value="c.connection_id" :disabled="!c.connected">
                      {{ c.display_name }}{{ c.connected ? "" : " (not connected)" }}
                    </option>
                  </select>
                </label>
              </div>
              <p v-if="delegateNeedsCalendar && form.fulfillment_mode !== 'no_booking'" class="services-hint warning">
                The default fulfiller has no calendar of their own — their bookings will use this service's calendar. Connect one on the Fulfillers tab to have bookings land on their own calendar automatically.
              </p>
            </section>

            <section v-if="form.default_fulfiller_id && form.fulfillment_mode !== 'no_booking'" class="offer-form-section">
              <header class="offer-section-header">
                <div>
                  <h3>Check-in &amp; Completion</h3>
                  <p>Optional on-site check-in and completion steps for the fulfiller.</p>
                </div>
              </header>
              <div class="offer-two-column">
                <label class="offer-field"><span>Check-In Label</span><input v-model.trim="form.booking_rules.check_in_label" type="text" placeholder="Ready on Site" /></label>
                <label class="offer-field"><span>Completion Label</span><input v-model.trim="form.booking_rules.completion_label" type="text" placeholder="Done" /></label>
              </div>
              <div class="offer-two-column">
                <label class="offer-field"><span>Check-In Window Start (min before)</span><input v-model.number="form.booking_rules.check_in_window_start_minutes" type="number" min="0" /></label>
                <label class="offer-field"><span>Check-In Window End (min before)</span><input v-model.number="form.booking_rules.check_in_window_end_minutes" type="number" min="0" /></label>
              </div>
              <div class="offer-two-column">
                <label class="checkbox-row offer-checkbox-inline"><input v-model="form.booking_rules.check_in_required" type="checkbox" /><span>Check-in required</span></label>
                <label class="checkbox-row offer-checkbox-inline"><input v-model="form.booking_rules.completion_required" type="checkbox" /><span>Completion required</span></label>
              </div>
            </section>
          </template>

          <section v-if="showsBlock('photo')" class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3 v-if="wizardMode">Add a photo</h3>
                <h3 v-else>Presentation</h3>
                <p>Optional hero image for the service.</p>
              </div>
            </header>
            <label class="offer-field">
              <span>Hero Image</span>
              <div class="builder-upload-stack">
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
                <button
                  v-if="form.hero_image_url"
                  type="button"
                  class="secondary-action compact"
                  @click="form.hero_image_url = ''; form.hero_image_crop = null"
                >Remove</button>
              </div>
              <small v-if="heroUploadError" class="builder-upload-error">{{ heroUploadError }}</small>
            </label>
            <label class="checkbox-row offer-checkbox-inline">
              <input v-model="form.active" type="checkbox" />
              <span>Active (available for booking)</span>
            </label>
          </section>

          <footer class="modal-footer">
            <button v-if="wizardMode && wizardStep > 1" class="secondary-action" type="button"
                    @click="previousWizardStep">Back</button>
            <button v-else class="secondary-action" type="button" @click="closeServiceModal">Cancel</button>
            <button v-if="wizardMode && !onLastWizardStep" class="primary-action" type="button"
                    @click="nextWizardStep">Next</button>
            <button v-else class="primary-action" type="submit" :disabled="store.saving">
              {{ store.saving ? "Saving..." : (wizardMode ? "Create service" : "Save Service") }}
            </button>
          </footer>
        </form>
      </section>
    </div>

    <div v-if="selectedService" class="modal-backdrop" @click.self="selectedService = null">
      <section class="modal-card product-details-modal" role="dialog" aria-modal="true" aria-labelledby="serviceDetailsTitle">
        <header class="modal-card-header">
          <h2 id="serviceDetailsTitle">Service Details</h2>
          <button type="button" class="modal-close" aria-label="Close service details" @click="selectedService = null">×</button>
        </header>
        <div class="product-details-body">
          <dl class="product-details-grid">
            <div><dt>Service ID</dt><dd>{{ selectedService.service_id }}</dd></div>
            <div><dt>Name</dt><dd>{{ selectedService.name }}</dd></div>
            <div><dt>Price</dt><dd>{{ formatServicePrice(selectedService) }}</dd></div>
            <div v-if="selectedService.fulfillment_mode !== 'no_booking'"><dt>Duration</dt><dd>{{ formatServiceDuration(selectedService) }}</dd></div>
            <div v-else><dt>Fulfillment</dt><dd>No booking</dd></div>
            <div><dt>Location</dt><dd>{{ locationLabel(selectedService.location_mode) }}</dd></div>
            <div><dt>Status</dt><dd>{{ serviceIsActive(selectedService) ? "Active" : "Archived" }}</dd></div>
          </dl>
          <details class="product-json-details">
            <summary>Raw JSON</summary>
            <pre>{{ JSON.stringify(selectedService, null, 2) }}</pre>
          </details>
        </div>
      </section>
    </div>

    <ConfirmDialog
      :open="!!pendingDeleteService"
      danger
      title="Delete service?"
      confirm-label="Delete"
      :busy="deletingService"
      @cancel="pendingDeleteService = null"
      @confirm="confirmDelete"
    >
      Permanently delete "{{ pendingDeleteService?.name || "this service" }}"? This cannot be undone.
    </ConfirmDialog>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import {
  LOCATION_MODES,
  defaultBookingRules,
  formatServiceDuration,
  formatServicePrice,
  serviceIsActive,
  useServicesStore,
  fetchFullService,
} from "../stores/services";
import { uploadImage } from "../api/uploads";
import { recordImageDims } from "../utils/imageDims";
import ImageUploadField from "./shared/ImageUploadField.vue";
import imageRatios from "../../../src/stripe_link/image_ratios.json";
import { fulfillerDisplayName, useFulfillersStore } from "../stores/fulfillers";
import { formatMoney } from "../stores/products";
import { useCalendarStore } from "../stores/calendar";
import { applyTitleCaseInput } from "../utils/titleCase.js";
import { defaultPriceForm, priceFormFromDocument } from "../utils/priceForm";
import PricingCard from "./shared/PricingCard.vue";
import WizardSteps from "./shared/WizardSteps.vue";
import ConfirmDialog from "./shared/ConfirmDialog.vue";
import ListCard from "./shared/ListCard.vue";
import FulfillersPanel from "./services/FulfillersPanel.vue";
import TenantAvailabilityPanel from "./services/TenantAvailabilityPanel.vue";
import AvailabilityExceptionsPanel from "./services/AvailabilityExceptionsPanel.vue";
import CalendarPanel from "./services/CalendarPanel.vue";
import AppointmentsPanel from "./services/AppointmentsPanel.vue";

// Services support only these price contexts and one-time pricing (PRD Phase 1 scope).
const SERVICE_PRICE_CONTEXTS = [["standard", "Standard"], ["sale", "Sale"], ["flash_sale", "Flash sale"]];
const SERVICE_PRICING_MODELS = [["one_time", "One-time"]];

const store = useServicesStore();
const fulfillers = useFulfillersStore();
const calendar = useCalendarStore();

// List-card helpers (mirrors the Products long-card layout).
function serviceImage(service) {
  return service?.presentation?.hero_image_url || "";
}
function serviceMetaText(service) {
  const where = locationLabel(service.location_mode);
  if (service.fulfillment_mode === "no_booking") return `No booking · ${where}`;
  return `${formatServiceDuration(service)} · ${where}`;
}
async function toggleArchive(service) {
  await store.setActive(service, !serviceIsActive(service));
}
function promptDelete(service) {
  pendingDeleteService.value = service; // open the modal instantly; reference check runs on confirm
}
async function confirmDelete() {
  const service = pendingDeleteService.value;
  if (!service || deletingService.value) return;
  deletingService.value = true;
  try {
    const offers = await store.offersReferencing(service.service_id);
    if (offers.length) {
      store.error = store.message =
        `Can't delete "${service.name}" — it's used by ${offers.length} offer(s): ${offers.join(", ")}. Remove it from those offers first.`;
      return;
    }
    await store.deleteService(service);
  } finally {
    deletingService.value = false;
    pendingDeleteService.value = null;
  }
}
const showServiceModal = ref(false);
const editingService = ref(null);
const selectedService = ref(null);
const pendingDeleteService = ref(null);
const deletingService = ref(false);
const formError = ref("");
const form = ref(defaultServiceForm());

// A CREATE wizard over the same form state and the same save. Editing keeps the full screen (author,
// 2026-09-18) -- the big form is a fine console for someone who already has a service and knows what a
// fulfiller is; it is a terrible front door for someone who wants to say "I cut hair, 45 minutes, £40".
//
// Deliberately NOT a second form model or a second save path. `savePage()` in LandingPages.vue was exactly
// that and quietly stopped being called, taking its behaviour with it. The wizard shows and hides parts of
// one form; there is nothing to drift.
const SERVICE_WIZARD_STEPS = ["details", "pricing", "scheduling", "photo"];
const SERVICE_WIZARD_LABELS = { details: "Details", pricing: "Price", scheduling: "Scheduling", photo: "Photo" };
const wizardMode = ref(false);
const wizardStep = ref(1);
const wizardStepKey = computed(() => SERVICE_WIZARD_STEPS[wizardStep.value - 1] || "details");
const wizardLabels = computed(() => SERVICE_WIZARD_STEPS.map((key) => SERVICE_WIZARD_LABELS[key]));
const onLastWizardStep = computed(() => wizardStep.value >= SERVICE_WIZARD_STEPS.length);
// Which block a section belongs to. In edit mode every block shows, as it always has.
function showsBlock(key) {
  return !wizardMode.value || wizardStepKey.value === key;
}
// The advanced console -- fulfillers, compensation, overrides, check-in windows. A solo tenant creating their
// first service should never meet the word "fulfiller"; they are one, and the defaults already say so.
const showsAdvanced = computed(() => !wizardMode.value);

function nextWizardStep() {
  formError.value = "";
  if (wizardStepKey.value === "details" && !String(form.value.name || "").trim()) {
    formError.value = "Give the service a name.";
    return;
  }
  if (wizardStepKey.value === "scheduling" && form.value.fulfillment_mode !== "no_booking"
      && Number(form.value.duration_minutes || 0) < 1) {
    formError.value = "How long does it take? Enter at least 1 minute.";
    return;
  }
  wizardStep.value += 1;
}

function previousWizardStep() {
  formError.value = "";
  if (wizardStep.value > 1) wizardStep.value -= 1;
}
const allowedForm = ref(defaultAllowedForm());
const showAddFulfiller = ref(false);
const newFulfiller = ref(defaultNewFulfiller());
const addFulfillerError = ref("");
const heroFileInput = ref(null);
const heroUploading = ref(false);
const heroUploadError = ref("");

onMounted(() => {
  if (!fulfillers.loaded) fulfillers.load();
  if (!calendar.loaded) calendar.load();
});

// Warn when the service's default fulfiller has no calendar of their own — their bookings
// won't land on their own calendar (they fall back to the service/default calendar).
const delegateNeedsCalendar = computed(() => {
  const id = String(form.value.default_fulfiller_id || "").trim();
  if (!id) return false;
  const f = fulfillers.fulfillers.find((x) => x.fulfiller_id === id);
  return Boolean(f) && !String(f.calendar_connection_id || "").trim();
});

const assignableFulfillers = computed(() => {
  const taken = new Set(form.value.allowed_fulfillers.map((row) => row.fulfiller_id));
  return fulfillers.fulfillers.filter((f) => !taken.has(f.fulfiller_id));
});

// The default fulfiller must be one of the service's allowed fulfillers.
const serviceFulfillerOptions = computed(() => {
  const ids = new Set(form.value.allowed_fulfillers.map((row) => row.fulfiller_id));
  return fulfillers.fulfillers.filter((f) => ids.has(f.fulfiller_id));
});

function defaultAllowedForm() {
  return { fulfiller_id: "", override_type: "use_fulfiller_default", override_amount: 0, tips_to_fulfiller: true };
}

function defaultNewFulfiller() {
  return { first_name: "", last_name: "", email: "", compensation_type: "flat_fee", compensation_amount: 0 };
}

function openAddFulfiller() {
  newFulfiller.value = defaultNewFulfiller();
  addFulfillerError.value = "";
  showAddFulfiller.value = true;
}

// Create a new staff member without leaving the modal, then assign them to this service.
async function createFulfiller() {
  addFulfillerError.value = "";
  if (!String(newFulfiller.value.email || "").trim()) {
    addFulfillerError.value = "Email is required.";
    return;
  }
  try {
    const created = await fulfillers.saveFulfiller({
      first_name: newFulfiller.value.first_name,
      last_name: newFulfiller.value.last_name,
      email: newFulfiller.value.email,
      compensation_type: newFulfiller.value.compensation_type,
      compensation_amount: newFulfiller.value.compensation_amount,
      tips_to_fulfiller: true,
    });
    if (created?.fulfiller_id && !form.value.allowed_fulfillers.some((r) => r.fulfiller_id === created.fulfiller_id)) {
      form.value.allowed_fulfillers.push({ fulfiller_id: created.fulfiller_id, enabled: true, tips_to_fulfiller: true, compensation_override: { type: "use_fulfiller_default" } });
    }
    showAddFulfiller.value = false;
    newFulfiller.value = defaultNewFulfiller();
  } catch {
    addFulfillerError.value = fulfillers.error || "Could not add the fulfiller.";
  }
}

function fulfillerName(id) {
  const match = fulfillers.fulfillers.find((f) => f.fulfiller_id === id);
  return match ? fulfillerDisplayName(match) : id;
}

function overrideLabel(row) {
  const type = row.compensation_override?.type || "use_fulfiller_default";
  if (type === "use_fulfiller_default") return "Fulfiller default";
  const amount = Number(row.compensation_override?.amount || 0);
  return type === "percent" ? `${amount}%` : formatMoney(Math.round(amount * 100), "usd");
}

function addAllowedFulfiller() {
  if (!allowedForm.value.fulfiller_id) return;
  const entry = {
    fulfiller_id: allowedForm.value.fulfiller_id,
    enabled: true,
    tips_to_fulfiller: allowedForm.value.tips_to_fulfiller !== false,
  };
  if (allowedForm.value.override_type !== "use_fulfiller_default") {
    entry.compensation_override = { type: allowedForm.value.override_type, amount: Math.max(0, Number(allowedForm.value.override_amount || 0)) };
  } else {
    entry.compensation_override = { type: "use_fulfiller_default" };
  }
  form.value.allowed_fulfillers.push(entry);
  allowedForm.value = defaultAllowedForm();
}

async function handleHeroPicked(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  heroUploadError.value = "";
  heroUploading.value = true;
  try {
    const { url, dims } = await uploadImage(file, { basePrefix: "services" });
    form.value.hero_image_url = url;
    recordImageDims(form.value.image_dims, url, dims);
  } catch (error) {
    heroUploadError.value = error.message || "Hero image upload failed.";
  } finally {
    heroUploading.value = false;
  }
}

// Returns the whole upload result, not just the URL: baking a crop needs the asset id so a re-crop reads
// the ORIGINAL rather than compounding the previous crop.
async function uploadServiceHero(file) {
  const result = await uploadImage(file, { basePrefix: "services" });
  recordImageDims(form.value.image_dims, result.url, result.dims);
  return result;
}

function defaultServiceForm() {
  return {
    service_id: "",
    name: "",
    description: "",
    prices: [defaultPriceForm()],
    default_price_index: 0,
    fulfillment_mode: "scheduled",
    booking_flow: "pay_then_book",
    duration_minutes: 60,
    location_mode: "onsite",
    hero_image_url: "",
    image_dims: {},
    active: true,
    default_fulfiller_id: "",
    calendar_connection_id: "",
    booking_rules: defaultBookingRules(),
    allowed_fulfillers: [],
    created_at: null,
  };
}

function resetFulfillerForms() {
  allowedForm.value = defaultAllowedForm();
  newFulfiller.value = defaultNewFulfiller();
  showAddFulfiller.value = false;
  addFulfillerError.value = "";
}

function openCreateModal() {
  editingService.value = null;
  form.value = defaultServiceForm();
  wizardMode.value = true;
  wizardStep.value = 1;
  formError.value = "";
  resetFulfillerForms();
  showServiceModal.value = true;
}

async function openEditModal(row) {
  // The list holds index ROWS; the editor needs the whole document (booking_rules, image_dims and the
  // per-price fields the projection drops). One fetch, for the one service being opened.
  const service = await fetchFullService(row);
  editingService.value = service;
  form.value = formFromService(service);
  wizardMode.value = false;     // editing gets the whole console, as it always has
  formError.value = "";
  resetFulfillerForms();
  showServiceModal.value = true;
}

function closeServiceModal() {
  showServiceModal.value = false;
  editingService.value = null;
  wizardMode.value = false;
  wizardStep.value = 1;
}

// One submit handler so the Enter key cannot skip the remaining steps: in the wizard it advances, and only
// the final step actually saves.
function onServiceFormSubmit() {
  if (wizardMode.value && !onLastWizardStep.value) {
    nextWizardStep();
    return;
  }
  saveService();
}

async function saveService() {
  formError.value = "";
  if (!String(form.value.name || "").trim()) {
    formError.value = "Service name is required.";
    return;
  }
  if (form.value.fulfillment_mode !== "no_booking" && Number(form.value.duration_minutes || 0) < 1) {
    formError.value = "Duration must be at least 1 minute.";
    return;
  }
  try {
    await store.saveService(form.value, editingService.value);
    closeServiceModal();
  } catch (error) {
    formError.value = error.message;
  }
}

function resetFilters() {
  store.filters.search = "";
  store.filters.status = "all";
}

function formFromService(service) {
  // Load prices via the shared adapter: prices[] if present, else synthesize from the legacy price.
  const priceDocs = Array.isArray(service.prices) && service.prices.length
    ? service.prices
    : [{ price_id: `svcprice_${service.service_id}`, currency: (service.price || {}).currency || "usd", unit_amount: (service.price || {}).unit_amount || 0 }];
  const prices = priceDocs.map((price) => priceFormFromDocument(price));
  const defaultIndex = Math.max(0, prices.findIndex((p) => p.price_id === service.default_price_id));
  return {
    ...defaultServiceForm(),
    service_id: service.service_id || "",
    name: service.name || "",
    description: service.description || "",
    prices,
    default_price_index: defaultIndex >= 0 ? defaultIndex : 0,
    fulfillment_mode: service.fulfillment_mode === "no_booking" ? "no_booking" : "scheduled",
    booking_flow: ["book_then_pay", "pay_then_book"].includes(service.booking_flow) ? service.booking_flow : "pay_then_book",
    duration_minutes: Number(service.duration_minutes || 60),
    location_mode: service.location_mode || "onsite",
    hero_image_url: service.presentation?.hero_image_url || "",
    image_dims: { ...(service.image_dims || {}) },
    active: serviceIsActive(service),
    default_fulfiller_id: service.default_fulfiller_id || "",
    calendar_connection_id: service.calendar_connection_id || "",
    booking_rules: { ...defaultBookingRules(), ...(service.booking_rules || {}) },
    allowed_fulfillers: Array.isArray(service.allowed_fulfillers)
      ? service.allowed_fulfillers.map((row) => ({ ...row }))
      : [],
    created_at: service.created_at || null,
  };
}

function locationLabel(mode) {
  return String(mode || "onsite").replace(/\b\w/g, (char) => char.toUpperCase());
}
</script>
