<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Profile</h1>
        <p>Your account name and details</p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="loading" @click="load">
          {{ loading ? "Loading..." : "Reload" }}
        </button>
        <button class="primary-action" type="button" :disabled="saving || loading || !userId" @click="save">
          {{ saving ? "Saving..." : "Save Profile" }}
        </button>
      </div>
    </header>

    <div v-if="error" class="keys-status-banner error">{{ error }}</div>
    <div v-else-if="message" class="keys-status-banner">{{ message }}</div>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Details</h2></header>
      <div class="dashboard-card-body">
        <div class="offer-two-column">
          <label class="offer-field">
            <span>First Name</span>
            <input v-model.trim="form.first_name" type="text" placeholder="Ada" />
          </label>
          <label class="offer-field">
            <span>Last Name</span>
            <input v-model.trim="form.last_name" type="text" placeholder="Lovelace" />
          </label>
        </div>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Display Name</span>
            <input v-model.trim="form.display_name" type="text" :placeholder="displayNamePlaceholder" />
            <small>Shown in the dashboard. Defaults to your name if left blank.</small>
          </label>
          <label class="offer-field">
            <span>Email</span>
            <input :value="email" type="email" disabled />
            <small>Your sign-in email is managed by the auth provider.</small>
          </label>
        </div>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Business</h2></header>
      <div class="dashboard-card-body">
        <p class="field-note">
          Your business identity. Used for the brand shown on landing pages and (soon) local-SEO signals.
          All optional. When you connect Google Business Profile later, it can keep these in sync.
        </p>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Business Name</span>
            <input v-model.trim="form.business.name" type="text" placeholder="Luxe Spa" />
            <small>Brand fallback when an offer doesn't pick a brand.</small>
          </label>
          <label class="offer-field">
            <span>Business Phone</span>
            <input v-model.trim="form.business.phone" type="tel" placeholder="+1 555 010 0100" />
          </label>
        </div>
        <div class="offer-field">
          <span>Brand Name(s)</span>
          <small>Optional. An offer can display one of these; otherwise it falls back to the business name, then the product name.</small>
          <div v-for="(brand, index) in form.business.brands" :key="index" class="brand-row">
            <input v-model.trim="form.business.brands[index]" type="text" placeholder="e.g. Luxe Wellness" />
            <button type="button" class="secondary-action compact" @click="removeBrand(index)">Remove</button>
          </div>
          <button type="button" class="secondary-action compact" @click="addBrand">+ Add brand</button>
        </div>
        <fieldset class="offer-field business-address">
          <span>Business Address</span>
          <small>For NAP consistency and local-SEO structured data. Manual entry; overridable by Google Business Profile once connected.</small>
          <input v-model.trim="form.business.address.street" type="text" placeholder="Street address" />
          <div class="offer-two-column">
            <input v-model.trim="form.business.address.locality" type="text" placeholder="City" />
            <input v-model.trim="form.business.address.region" type="text" placeholder="State / Region" />
          </div>
          <div class="offer-two-column">
            <input v-model.trim="form.business.address.postal_code" type="text" placeholder="Postal code" />
            <input v-model.trim="form.business.address.country" type="text" placeholder="Country (e.g. US)" />
          </div>
        </fieldset>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Account</h2></header>
      <div class="dashboard-card-body">
        <p class="field-note">Read-only. Managed by the platform.</p>
        <dl class="product-details-grid">
          <div><dt>Role</dt><dd>{{ statusLabel(rawDoc.role || "user") }}</dd></div>
          <div><dt>Status</dt><dd>{{ statusLabel(rawDoc.status || "active") }}</dd></div>
          <div><dt>Plan Tier</dt><dd>{{ rawDoc.subscription?.tier_id || "—" }}</dd></div>
          <div><dt>Account Status</dt><dd>{{ statusLabel(rawDoc.subscription?.account_status || "—") }}</dd></div>
          <div><dt>Billing Status</dt><dd>{{ statusLabel(rawDoc.subscription?.billing_status || "—") }}</dd></div>
          <div><dt>Email Verified</dt><dd>{{ rawDoc.auth?.email_verified ? "Yes" : "No" }}</dd></div>
          <div><dt>Last Login</dt><dd>{{ formatDate(rawDoc.auth?.last_login_at) }}</dd></div>
          <div><dt>Created</dt><dd>{{ formatDate(rawDoc.created_at) }}</dd></div>
        </dl>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, reactive, ref } from "vue";
import { apiRequest, getAuthSession, getTenantId } from "../api/client";
import { formatEpochDate, statusLabel } from "../utils/format";

const session = getAuthSession() || {};
const userId = session.user_id || "";
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");
const rawDoc = ref({});
const email = ref(session.email || "");
const form = reactive({
  first_name: session.first_name || "", last_name: session.last_name || "", display_name: "",
  business: emptyBusiness(),
});

function emptyBusiness() {
  return { name: "", phone: "", brands: [], address: { street: "", locality: "", region: "", postal_code: "", country: "" } };
}

function addBrand() {
  form.business.brands.push("");
}

function removeBrand(index) {
  form.business.brands.splice(index, 1);
}

// Build the stored business block, dropping blanks so an untouched section saves nothing.
function cleanBusiness(business) {
  const brands = (business.brands || []).map((brand) => String(brand || "").trim()).filter(Boolean);
  const address = Object.fromEntries(
    Object.entries(business.address || {}).filter(([, value]) => String(value || "").trim()),
  );
  const result = {};
  if (business.name) result.name = business.name;
  if (business.phone) result.phone = business.phone;
  if (brands.length) result.brands = brands;
  if (Object.keys(address).length) result.address = address;
  return Object.keys(result).length ? result : null;
}

const formatDate = formatEpochDate;
const displayNamePlaceholder = computed(() => `${form.first_name} ${form.last_name}`.trim() || "Your name");

function applyProfile(profile) {
  rawDoc.value = profile || {};
  email.value = profile.email || session.email || "";
  form.first_name = profile.first_name ?? session.first_name ?? "";
  form.last_name = profile.last_name ?? session.last_name ?? "";
  form.display_name = profile.display_name || "";
  const business = profile.business || {};
  const address = business.address || {};
  form.business = {
    name: business.name || "",
    phone: business.phone || "",
    brands: Array.isArray(business.brands) ? [...business.brands] : [],
    address: {
      street: address.street || "", locality: address.locality || "", region: address.region || "",
      postal_code: address.postal_code || "", country: address.country || "",
    },
  };
}

async function load() {
  if (!userId) {
    error.value = "Could not determine your user account. Sign out and back in.";
    return;
  }
  loading.value = true;
  error.value = "";
  message.value = "";
  try {
    const body = await apiRequest("/profile", { params: { user_id: userId } });
    applyProfile(body.profile || {});
  } catch (err) {
    if (/not found/i.test(err.message)) {
      applyProfile({});
      message.value = "No profile saved yet. Fill in your details and save.";
    } else {
      error.value = err.message || "Failed to load profile.";
    }
  } finally {
    loading.value = false;
  }
}

async function save() {
  if (!userId) {
    error.value = "Could not determine your user account. Sign out and back in.";
    return;
  }
  saving.value = true;
  error.value = "";
  message.value = "";
  try {
    const doc = { ...rawDoc.value };
    doc.schema_version = "2026-05-29";
    doc.document_type = "user_profile";
    doc.tenant_id = getTenantId();
    doc.user_id = userId;
    doc.email = email.value || rawDoc.value.email || session.email || "";
    doc.first_name = form.first_name;
    doc.last_name = form.last_name;
    doc.display_name = form.display_name || `${form.first_name} ${form.last_name}`.trim() || doc.email;
    const business = cleanBusiness(form.business);
    if (business) doc.business = business;
    else delete doc.business;
    doc.updated_at = Math.floor(Date.now() / 1000);
    const body = await apiRequest("/profile", { method: "PUT", body: doc });
    applyProfile(body.profile || doc);
    message.value = "Profile saved.";
  } catch (err) {
    error.value = err.message || "Failed to save profile.";
  } finally {
    saving.value = false;
  }
}

load();
</script>
