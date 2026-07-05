<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Shipping</h1>
        <p>Carrier provider, addresses, and parcel defaults for label purchase and rates</p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="loading" @click="load">
          {{ loading ? "Loading..." : "Reload" }}
        </button>
        <button class="primary-action" type="button" :disabled="saving || loading" @click="save">
          {{ saving ? "Saving..." : "Save Shipping" }}
        </button>
      </div>
    </header>

    <div v-if="error" class="keys-status-banner error">{{ error }}</div>
    <div v-else-if="message" class="keys-status-banner">{{ message }}</div>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>General</h2></header>
      <label class="checkbox-row offer-checkbox-inline">
        <input v-model="form.enabled" type="checkbox" />
        <span>Enable shipping (rates and labels)</span>
      </label>
      <label class="checkbox-row offer-checkbox-inline">
        <input v-model="form.test_mode" type="checkbox" />
        <span>Test mode (use the provider's test environment)</span>
      </label>
      <label class="checkbox-row offer-checkbox-inline">
        <input v-model="form.auto_fulfill_after_label_purchase" type="checkbox" />
        <span>Auto-fulfill orders after a label is purchased</span>
      </label>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Provider</h2></header>
      <div class="offer-two-column">
        <label class="offer-field">
          <span>Provider <strong>*</strong></span>
          <select v-model="form.provider.name">
            <option value="">Select a provider…</option>
            <option value="shippo">Shippo</option>
            <option value="easypost">EasyPost</option>
            <option value="shipstation">ShipStation</option>
            <option value="easyship">Easyship</option>
            <option value="mock">Mock (testing)</option>
          </select>
        </label>
        <label class="offer-field">
          <span>Base URL</span>
          <input v-model.trim="form.provider.base_url" type="url" placeholder="Optional provider API base URL" />
        </label>
      </div>
      <div class="offer-two-column">
        <label class="offer-field">
          <span>API Key</span>
          <input v-model="form.provider.api_key" type="password" autocomplete="new-password" :placeholder="apiKeyPlaceholder" />
          <small>Your provider's API key. Stored encrypted and never shown again after saving.</small>
        </label>
        <label class="offer-field">
          <span>Connection Status</span>
          <input :value="statusLabel(rawDoc.provider?.connection_status || 'not_configured')" disabled />
          <small>{{ keyConfigured ? "A key is saved for this provider." : "No key saved yet." }}</small>
        </label>
      </div>
      <p v-if="providerChangedNeedsKey" class="keys-status-banner error">
        You changed providers — enter the new provider's API key. The previous key will not carry over.
      </p>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Ship-From Address</h2></header>
      <AddressFields :address="form.ship_from_address" />
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>Return Address</h2>
        <div class="button-row">
          <button class="secondary-action" type="button" @click="copyShipFromToReturn">Copy from ship-from</button>
        </div>
      </header>
      <AddressFields :address="form.return_address" />
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Default Parcel</h2></header>
      <div class="offer-three-column">
        <label class="offer-field">
          <span>Length <strong>*</strong></span>
          <input v-model.number="form.default_parcel.length" type="number" min="0" step="0.01" />
        </label>
        <label class="offer-field">
          <span>Width <strong>*</strong></span>
          <input v-model.number="form.default_parcel.width" type="number" min="0" step="0.01" />
        </label>
        <label class="offer-field">
          <span>Height <strong>*</strong></span>
          <input v-model.number="form.default_parcel.height" type="number" min="0" step="0.01" />
        </label>
      </div>
      <div class="offer-three-column">
        <label class="offer-field">
          <span>Weight <strong>*</strong></span>
          <input v-model.number="form.default_parcel.weight" type="number" min="0" step="0.01" />
        </label>
        <label class="offer-field">
          <span>Distance Unit</span>
          <select v-model="form.default_parcel.distance_unit">
            <option value="in">in</option>
            <option value="cm">cm</option>
          </select>
        </label>
        <label class="offer-field">
          <span>Mass Unit</span>
          <select v-model="form.default_parcel.mass_unit">
            <option value="oz">oz</option>
            <option value="lb">lb</option>
            <option value="g">g</option>
            <option value="kg">kg</option>
          </select>
        </label>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Rate & Label Options</h2></header>
      <p class="field-note">Optional.</p>
      <div class="offer-two-column">
        <label class="offer-field">
          <span>Default Service Level</span>
          <input v-model.trim="form.rate_options.default_service_level" type="text" placeholder="e.g. usps_priority" />
        </label>
        <label class="offer-field">
          <span>Allowed Carriers</span>
          <input v-model.trim="form.rate_options.allowed_carriers" type="text" placeholder="Comma-separated, e.g. usps, ups" />
        </label>
      </div>
      <div class="offer-two-column">
        <label class="offer-field">
          <span>Markup Amount (cents)</span>
          <input v-model.number="form.rate_options.markup_amount" type="number" min="0" step="1" />
        </label>
        <label class="offer-field">
          <span>Free Shipping Threshold (cents)</span>
          <input v-model.number="form.rate_options.free_shipping_threshold" type="number" min="0" step="1" />
        </label>
      </div>
      <div class="offer-two-column">
        <label class="offer-field">
          <span>Label Format</span>
          <select v-model="form.label_options.format">
            <option value="pdf">PDF</option>
            <option value="png">PNG</option>
            <option value="zpl">ZPL</option>
          </select>
        </label>
        <label class="offer-field">
          <span>Label Size</span>
          <select v-model="form.label_options.size">
            <option value="4x6">4x6</option>
            <option value="8.5x11">8.5x11</option>
          </select>
        </label>
      </div>
    </section>

    <footer class="config-save-bar">
      <button class="primary-action" type="button" :disabled="saving || loading" @click="save">
        {{ saving ? "Saving..." : "Save Shipping" }}
      </button>
    </footer>
  </section>
</template>

<script setup>
import { computed, reactive, ref } from "vue";
import { apiRequest, getTenantId } from "../api/client";
import { statusLabel } from "../utils/format";
import AddressFields from "./AddressFields.vue";

const loading = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");
const rawDoc = ref({});
const form = reactive(defaultForm());

// A saved key comes back redacted (api_key_ref === "********"), so a truthy value means configured.
const keyConfigured = computed(() => Boolean(rawDoc.value.provider?.api_key_ref));
const apiKeyPlaceholder = computed(() => (keyConfigured.value ? "Saved — enter a new key to replace" : "Enter your provider API key"));
const providerChangedNeedsKey = computed(() =>
  Boolean(
    form.provider.name &&
    rawDoc.value.provider?.name &&
    form.provider.name !== rawDoc.value.provider.name &&
    keyConfigured.value &&
    !String(form.provider.api_key || "").trim(),
  ),
);

function emptyAddress() {
  return { name: "", company: "", street1: "", street2: "", city: "", state: "", postal_code: "", country: "US", phone: "", email: "", residential: false };
}

function defaultForm() {
  return {
    enabled: false,
    test_mode: true,
    auto_fulfill_after_label_purchase: false,
    provider: { name: "", base_url: "", api_key: "" },
    ship_from_address: emptyAddress(),
    return_address: emptyAddress(),
    default_parcel: { length: "", width: "", height: "", weight: "", distance_unit: "in", mass_unit: "oz" },
    rate_options: { default_service_level: "", allowed_carriers: "", markup_amount: "", free_shipping_threshold: "" },
    label_options: { format: "pdf", size: "4x6" },
  };
}

function fillAddress(target, source) {
  const base = emptyAddress();
  Object.keys(base).forEach((key) => {
    target[key] = source?.[key] ?? base[key];
  });
}

function applyConfig(config) {
  rawDoc.value = config || {};
  const base = defaultForm();
  form.enabled = Boolean(config.enabled);
  form.test_mode = config.test_mode ?? true;
  form.auto_fulfill_after_label_purchase = Boolean(config.auto_fulfill_after_label_purchase);
  form.provider.name = config.provider?.name || "";
  form.provider.base_url = config.provider?.base_url || "";
  form.provider.api_key = ""; // never populate the actual key; it's redacted on read
  fillAddress(form.ship_from_address, config.ship_from_address);
  fillAddress(form.return_address, config.return_address);
  const parcel = config.default_parcel || {};
  form.default_parcel = {
    length: parcel.length ?? "",
    width: parcel.width ?? "",
    height: parcel.height ?? "",
    weight: parcel.weight ?? "",
    distance_unit: parcel.distance_unit || "in",
    mass_unit: parcel.mass_unit || "oz",
  };
  const rate = config.rate_options || {};
  form.rate_options = {
    default_service_level: rate.default_service_level || "",
    allowed_carriers: Array.isArray(rate.allowed_carriers) ? rate.allowed_carriers.join(", ") : "",
    markup_amount: rate.markup_amount ?? "",
    free_shipping_threshold: rate.free_shipping_threshold ?? "",
  };
  form.label_options = { format: config.label_options?.format || "pdf", size: config.label_options?.size || "4x6" };
  void base;
}

function copyShipFromToReturn() {
  fillAddress(form.return_address, form.ship_from_address);
}

function cleanAddress(address) {
  const result = {
    name: address.name.trim(),
    street1: address.street1.trim(),
    city: address.city.trim(),
    state: address.state.trim(),
    postal_code: address.postal_code.trim(),
    country: address.country.trim().toUpperCase(),
    residential: Boolean(address.residential),
  };
  ["company", "street2", "phone", "email"].forEach((key) => {
    const value = String(address[key] || "").trim();
    if (value) result[key] = value;
  });
  return result;
}

function validationErrors() {
  const errors = [];
  if (!form.provider.name) errors.push("Provider");
  [["Ship-from", form.ship_from_address], ["Return", form.return_address]].forEach(([label, addr]) => {
    ["name", "street1", "city", "state", "postal_code", "country"].forEach((field) => {
      if (!String(addr[field] || "").trim()) errors.push(`${label} ${field.replace(/_/g, " ")}`);
    });
    const country = String(addr.country || "").trim();
    if (country && country.length !== 2) errors.push(`${label} country must be a 2-letter code`);
  });
  ["length", "width", "height", "weight"].forEach((field) => {
    if (!(Number(form.default_parcel[field]) > 0)) errors.push(`Parcel ${field} must be greater than 0`);
  });
  return errors;
}

async function load() {
  loading.value = true;
  error.value = "";
  message.value = "";
  try {
    const body = await apiRequest("/shipping");
    applyConfig(body.shipping_config || {});
  } catch (err) {
    if (/not found/i.test(err.message)) {
      applyConfig({});
      message.value = "No shipping config saved yet. Complete the required fields and save.";
    } else {
      error.value = err.message || "Failed to load shipping config.";
    }
  } finally {
    loading.value = false;
  }
}

function buildPayload() {
  const doc = { ...rawDoc.value };
  doc.schema_version = "2026-05-29";
  doc.document_type = "shipping_config";
  doc.tenant_id = getTenantId();
  doc.enabled = form.enabled;
  doc.test_mode = form.test_mode;
  doc.auto_fulfill_after_label_purchase = form.auto_fulfill_after_label_purchase;

  // Provider: send a newly-typed key as plaintext (backend encrypts), the redacted
  // sentinel to keep an unchanged key, or nothing when no key is set. connection_status/
  // last_tested_at are managed by the backend, so don't carry the redacted copies back.
  const provider = { name: form.provider.name };
  if (form.provider.base_url) provider.base_url = form.provider.base_url;
  const enteredKey = String(form.provider.api_key || "").trim();
  if (enteredKey) {
    provider.api_key_ref = enteredKey;
  } else if (rawDoc.value.provider?.api_key_ref) {
    provider.api_key_ref = "********";
  }
  doc.provider = provider;

  doc.ship_from_address = cleanAddress(form.ship_from_address);
  doc.return_address = cleanAddress(form.return_address);
  doc.default_parcel = {
    length: Number(form.default_parcel.length),
    width: Number(form.default_parcel.width),
    height: Number(form.default_parcel.height),
    weight: Number(form.default_parcel.weight),
    distance_unit: form.default_parcel.distance_unit,
    mass_unit: form.default_parcel.mass_unit,
  };

  const rate = {};
  if (form.rate_options.default_service_level.trim()) rate.default_service_level = form.rate_options.default_service_level.trim();
  const carriers = form.rate_options.allowed_carriers.split(",").map((item) => item.trim()).filter(Boolean);
  if (carriers.length) rate.allowed_carriers = carriers;
  if (form.rate_options.markup_amount !== "" && form.rate_options.markup_amount != null) rate.markup_amount = Number(form.rate_options.markup_amount);
  if (form.rate_options.free_shipping_threshold !== "" && form.rate_options.free_shipping_threshold != null) rate.free_shipping_threshold = Number(form.rate_options.free_shipping_threshold);
  if (Object.keys(rate).length) doc.rate_options = rate;
  else delete doc.rate_options;

  doc.label_options = { format: form.label_options.format, size: form.label_options.size };
  doc.updated_at = Math.floor(Date.now() / 1000);
  return doc;
}

async function save() {
  error.value = "";
  message.value = "";
  const errors = validationErrors();
  if (errors.length) {
    error.value = `Please complete: ${errors.slice(0, 4).join(", ")}${errors.length > 4 ? ", …" : ""}.`;
    return;
  }
  saving.value = true;
  try {
    const body = await apiRequest("/shipping", { method: "PUT", body: buildPayload() });
    applyConfig(body.shipping_config || buildPayload());
    message.value = "Shipping config saved.";
  } catch (err) {
    error.value = err.message || "Failed to save shipping config.";
  } finally {
    saving.value = false;
  }
}

load();
</script>
