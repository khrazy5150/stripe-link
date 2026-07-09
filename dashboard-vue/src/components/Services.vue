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
          <input v-model.trim="store.filters.search" type="search" placeholder="Name, description, service ID..." />
        </label>
        <label>
          Status
          <select v-model="store.filters.status">
            <option value="all">All</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
        <div class="product-filter-actions">
          <button type="button" class="primary-action" @click="store.applyFilters">Apply</button>
          <button type="button" class="secondary-action" @click="resetFilters">Reset</button>
        </div>
      </div>

      <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
      <div v-else-if="store.message" class="keys-status-banner">{{ store.message }}</div>

      <div v-if="!store.filteredServices.length" class="product-empty-state">
        {{ store.loaded ? "No services found. Create a service to get started." : "Click Load Services to see services." }}
      </div>

      <div v-else class="coupon-card-grid">
        <article v-for="service in store.filteredServices" :key="service.service_id" class="coupon-card">
          <header>
            <div>
              <h3>{{ service.name }}</h3>
              <p class="font-mono">{{ service.service_id }}</p>
            </div>
            <span class="product-status" :class="serviceIsActive(service) ? 'active' : 'inactive'">
              {{ serviceIsActive(service) ? "Active" : "Inactive" }}
            </span>
          </header>
          <strong class="coupon-discount">{{ formatServicePrice(service) }}</strong>
          <dl class="coupon-detail-list">
            <div><dt>Duration</dt><dd>{{ formatServiceDuration(service) }}</dd></div>
            <div><dt>Location</dt><dd>{{ locationLabel(service.location_mode) }}</dd></div>
          </dl>
          <div class="product-card-actions">
            <button type="button" class="secondary-action" @click="openEditModal(service)">Edit</button>
            <button type="button" class="secondary-action" @click="selectedService = service">Details</button>
          </div>
        </article>
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
          <h2 id="serviceModalTitle">{{ editingService ? "Edit Service" : "Create Service" }}</h2>
          <button type="button" class="modal-close" aria-label="Close service modal" @click="closeServiceModal">×</button>
        </header>

        <form class="coupon-form" @submit.prevent="saveService">
          <div v-if="formError" class="keys-status-banner error">{{ formError }}</div>

          <section class="offer-form-section">
            <div class="offer-two-column">
              <label class="offer-field">
                <span>Service Name <strong>*</strong></span>
                <input :value="form.name" type="text" placeholder="60-Minute Consultation" required
                       @input="applyTitleCaseInput((value) => { form.name = value; }, $event)" />
              </label>
              <label class="offer-field">
                <span>Location Mode</span>
                <select v-model="form.location_mode">
                  <option v-for="mode in LOCATION_MODES" :key="mode" :value="mode">{{ locationLabel(mode) }}</option>
                </select>
              </label>
            </div>
            <label class="offer-field">
              <span>Description</span>
              <textarea v-model.trim="form.description" rows="3" placeholder="What the customer gets"></textarea>
            </label>
          </section>

          <section class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3>Pricing &amp; Duration</h3>
                <p>The price a customer pays and how long the service takes.</p>
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
            <div class="offer-two-column">
              <label class="offer-field">
                <span>Duration (minutes) <strong>*</strong></span>
                <input v-model.number="form.duration_minutes" min="1" step="5" type="number" required />
              </label>
              <label class="offer-field">
                <span>Booking flow</span>
                <select v-model="form.booking_flow">
                  <option value="pay_then_book">Pay first, then book a time</option>
                  <option value="book_then_pay">Book first, pay later (invoice)</option>
                </select>
              </label>
            </div>
          </section>

          <section class="offer-form-section">
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

          <template v-if="form.allowed_fulfillers.length">
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
                <label class="offer-field">
                  <span>Calendar</span>
                  <select v-model="form.calendar_connection_id">
                    <option value="">Default calendar</option>
                    <option v-for="c in calendar.connections" :key="c.connection_id" :value="c.connection_id" :disabled="!c.connected">
                      {{ c.display_name }}{{ c.connected ? "" : " (not connected)" }}
                    </option>
                  </select>
                </label>
              </div>
              <p v-if="delegateNeedsCalendar" class="services-hint warning">
                The default fulfiller has no calendar of their own — their bookings will use this service's calendar. Connect one on the Fulfillers tab to have bookings land on their own calendar automatically.
              </p>
            </section>

            <section v-if="form.default_fulfiller_id" class="offer-form-section">
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

          <section class="offer-form-section">
            <header class="offer-section-header">
              <div>
                <h3>Presentation</h3>
                <p>Optional hero image for the service.</p>
              </div>
            </header>
            <label class="offer-field">
              <span>Hero Image</span>
              <div class="builder-upload-stack">
                <input ref="heroFileInput" type="file" accept="image/*" hidden @change="handleHeroPicked" />
                <button
                  class="secondary-action compact"
                  type="button"
                  :disabled="heroUploading"
                  @click="heroFileInput?.click()"
                >
                  {{ heroUploading ? "Uploading..." : form.hero_image_url ? "Replace image" : "Upload hero image" }}
                </button>
                <div v-if="form.hero_image_url" class="service-hero-preview">
                  <img :src="form.hero_image_url" alt="Hero image preview" />
                  <button type="button" class="secondary-action compact" @click="form.hero_image_url = ''">Remove</button>
                </div>
              </div>
              <small v-if="heroUploadError" class="builder-upload-error">{{ heroUploadError }}</small>
            </label>
            <label class="checkbox-row offer-checkbox-inline">
              <input v-model="form.active" type="checkbox" />
              <span>Active (available for booking)</span>
            </label>
          </section>

          <footer class="modal-footer">
            <button class="secondary-action" type="button" @click="closeServiceModal">Cancel</button>
            <button class="primary-action" type="submit" :disabled="store.saving">
              {{ store.saving ? "Saving..." : "Save Service" }}
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
            <div><dt>Duration</dt><dd>{{ formatServiceDuration(selectedService) }}</dd></div>
            <div><dt>Location</dt><dd>{{ locationLabel(selectedService.location_mode) }}</dd></div>
            <div><dt>Status</dt><dd>{{ serviceIsActive(selectedService) ? "Active" : "Inactive" }}</dd></div>
          </dl>
          <details class="product-json-details">
            <summary>Raw JSON</summary>
            <pre>{{ JSON.stringify(selectedService, null, 2) }}</pre>
          </details>
        </div>
      </section>
    </div>
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
} from "../stores/services";
import { uploadImage } from "../api/uploads";
import { fulfillerDisplayName, useFulfillersStore } from "../stores/fulfillers";
import { formatMoney } from "../stores/products";
import { useCalendarStore } from "../stores/calendar";
import { applyTitleCaseInput } from "../utils/titleCase.js";
import { defaultPriceForm, priceFormFromDocument } from "../utils/priceForm";
import PricingCard from "./shared/PricingCard.vue";
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
const showServiceModal = ref(false);
const editingService = ref(null);
const selectedService = ref(null);
const formError = ref("");
const form = ref(defaultServiceForm());
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
    form.value.hero_image_url = await uploadImage(file, { basePrefix: "services" });
  } catch (error) {
    heroUploadError.value = error.message || "Hero image upload failed.";
  } finally {
    heroUploading.value = false;
  }
}

function defaultServiceForm() {
  return {
    service_id: "",
    name: "",
    description: "",
    prices: [defaultPriceForm()],
    default_price_index: 0,
    booking_flow: "pay_then_book",
    duration_minutes: 60,
    location_mode: "onsite",
    hero_image_url: "",
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
  formError.value = "";
  resetFulfillerForms();
  showServiceModal.value = true;
}

function openEditModal(service) {
  editingService.value = service;
  form.value = formFromService(service);
  formError.value = "";
  resetFulfillerForms();
  showServiceModal.value = true;
}

function closeServiceModal() {
  showServiceModal.value = false;
  editingService.value = null;
}

async function saveService() {
  formError.value = "";
  if (!String(form.value.name || "").trim()) {
    formError.value = "Service name is required.";
    return;
  }
  if (Number(form.value.duration_minutes || 0) < 1) {
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
  store.applyFilters();
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
    booking_flow: ["book_then_pay", "pay_then_book"].includes(service.booking_flow) ? service.booking_flow : "pay_then_book",
    duration_minutes: Number(service.duration_minutes || 60),
    location_mode: service.location_mode || "onsite",
    hero_image_url: service.presentation?.hero_image_url || "",
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
