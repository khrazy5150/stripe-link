<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Services</h1>
        <p>Manage bookable services in your catalog</p>
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
      <div v-else class="keys-status-banner">{{ store.message }}</div>

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
                <input v-model.trim="form.name" type="text" placeholder="60-Minute Consultation" required />
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
            <div class="offer-three-column">
              <label class="offer-field">
                <span>Price <strong>*</strong></span>
                <input v-model.number="form.price_amount" min="0" type="number" step="0.01" required />
              </label>
              <label class="offer-field">
                <span>Currency</span>
                <select v-model="form.currency">
                  <option value="usd">USD</option>
                </select>
              </label>
              <label class="offer-field">
                <span>Duration (minutes) <strong>*</strong></span>
                <input v-model.number="form.duration_minutes" min="1" step="5" type="number" required />
              </label>
            </div>
          </section>

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
import { ref } from "vue";
import {
  LOCATION_MODES,
  formatServiceDuration,
  formatServicePrice,
  serviceIsActive,
  useServicesStore,
} from "../stores/services";
import { uploadImage } from "../api/uploads";

const store = useServicesStore();
const showServiceModal = ref(false);
const editingService = ref(null);
const selectedService = ref(null);
const formError = ref("");
const form = ref(defaultServiceForm());
const heroFileInput = ref(null);
const heroUploading = ref(false);
const heroUploadError = ref("");

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
    price_amount: 0,
    currency: "usd",
    duration_minutes: 60,
    location_mode: "onsite",
    hero_image_url: "",
    active: true,
    created_at: null,
  };
}

function openCreateModal() {
  editingService.value = null;
  form.value = defaultServiceForm();
  formError.value = "";
  showServiceModal.value = true;
}

function openEditModal(service) {
  editingService.value = service;
  form.value = formFromService(service);
  formError.value = "";
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
  const price = service.price || {};
  return {
    ...defaultServiceForm(),
    service_id: service.service_id || "",
    name: service.name || "",
    description: service.description || "",
    price_amount: Number(price.unit_amount || 0) / 100,
    currency: price.currency || "usd",
    duration_minutes: Number(service.duration_minutes || 60),
    location_mode: service.location_mode || "onsite",
    hero_image_url: service.presentation?.hero_image_url || "",
    active: serviceIsActive(service),
    created_at: service.created_at || null,
  };
}

function locationLabel(mode) {
  return String(mode || "onsite").replace(/\b\w/g, (char) => char.toUpperCase());
}
</script>
