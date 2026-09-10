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
            <PhoneInput v-model="form.business.phone" />
            <small v-if="businessPhoneError" class="field-error">{{ businessPhoneError }}</small>
            <small v-else>International format, e.g. +12065551234 — same standard as your account phone.</small>
          </label>
        </div>
        <div class="offer-field">
          <span>Business Email</span>
          <div class="business-email-row">
            <input v-model.trim="form.business.email" type="email" placeholder="hello@yourbusiness.com" :disabled="emailVerify.step === 'code'" />
            <span v-if="businessEmailVerified" class="business-email-badge verified">Verified</span>
            <button
              v-else-if="emailVerify.step !== 'code'"
              class="secondary-action compact"
              type="button"
              :disabled="!form.business.email || emailVerify.busy"
              @click="startEmailVerification"
            >{{ emailVerify.busy ? "Checking..." : "Verify" }}</button>
          </div>

          <!-- The code step replaces the field rather than sitting beside it: there is one thing to do here
               and splitting attention between an address box and a code box is how people paste the wrong one. -->
          <div v-if="emailVerify.step === 'code'" class="business-email-code">
            <label class="offer-field">
              <span>Enter the 6-digit code we emailed to {{ emailVerify.pending }}</span>
              <input v-model.trim="emailVerify.code" type="text" inputmode="numeric" maxlength="6" placeholder="123456" />
            </label>
            <div class="business-email-actions">
              <button class="secondary-action compact" type="button" @click="cancelEmailVerification">Cancel</button>
              <button class="primary-action compact" type="button" :disabled="emailVerify.code.length !== 6 || emailVerify.busy" @click="confirmEmailVerification">
                {{ emailVerify.busy ? "Checking..." : "Confirm" }}
              </button>
            </div>
            <small class="field-note">The code expires in 5 minutes.</small>
          </div>

          <small v-if="emailVerify.error" class="field-error">{{ emailVerify.error }}</small>
          <small v-else-if="emailVerify.catchAll" class="field-note">
            That domain accepts mail to any address, so we could not confirm this specific mailbox — the code will.
          </small>
          <small v-else-if="businessEmailVerified">Replies to emails you send go here. Verified {{ formatDate(form.business.email_verified_at) }}.</small>
          <small v-else>Verify this address to send emails from your landing pages. It is also the public contact in your structured data.</small>
        </div>
        <p v-if="hasStripeSourcedFields" class="field-note">
          Some details were filled automatically from your Stripe account. Edit any field to override it.
        </p>
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
            <select v-model="form.business.address.country" class="country-select">
              <option value="">Country…</option>
              <option v-for="c in countries" :key="c.code" :value="c.code">{{ c.name }} ({{ c.code }})</option>
            </select>
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
import { normalizeE164, phoneError } from "../utils/phone";
import PhoneInput from "./PhoneInput.vue";
import { COUNTRIES, normalizeCountry } from "../utils/countries";

const countries = COUNTRIES;

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

// Verification state. Deliberately NOT part of `form`: it is a transient workflow, not a profile field,
// and mixing it in would send it to the save endpoint.
const emailVerify = reactive({ step: "idle", code: "", pending: "", busy: false, error: "", catchAll: false });

// Verified means verified for the address CURRENTLY typed. Editing the field to something else must drop
// the badge immediately, or a tenant sees "Verified" next to an address that is nothing of the sort.
const businessEmailVerified = computed(() =>
  Boolean(rawDoc.value.business?.email_verified)
  && (form.business.email || "").trim().toLowerCase() === (rawDoc.value.business?.email || "").toLowerCase(),
);

async function startEmailVerification() {
  emailVerify.busy = true;
  emailVerify.error = "";
  emailVerify.catchAll = false;
  try {
    const body = await apiRequest("/profile/business-email/start", {
      method: "POST",
      body: { tenant_id: getTenantId(), user_id: userId, email: form.business.email },
    });
    emailVerify.pending = form.business.email;
    emailVerify.catchAll = Boolean(body.catch_all);
    emailVerify.step = "code";
    emailVerify.code = "";
  } catch (err) {
    emailVerify.error = err.message || "We could not send the code. Please try again.";
  } finally {
    emailVerify.busy = false;
  }
}

async function confirmEmailVerification() {
  emailVerify.busy = true;
  emailVerify.error = "";
  try {
    const body = await apiRequest("/profile/business-email/confirm", {
      method: "POST",
      body: { tenant_id: getTenantId(), user_id: userId, code: emailVerify.code },
    });
    // The server is the source of truth for what is verified, so take its answer rather than assuming.
    rawDoc.value = { ...rawDoc.value, business: { ...(rawDoc.value.business || {}), email: body.email, email_verified: true } };
    form.business.email = body.email;
    emailVerify.step = "idle";
    emailVerify.code = "";
  } catch (err) {
    emailVerify.error = err.message || "That code is not right.";
  } finally {
    emailVerify.busy = false;
  }
}

function cancelEmailVerification() {
  emailVerify.step = "idle";
  emailVerify.code = "";
  emailVerify.error = "";
}

const hasStripeSourcedFields = computed(() =>
  Object.values((rawDoc.value.business || {}).sources || {}).includes("stripe"),
);

function emptyBusiness() {
  return { name: "", email: "", phone: "", brands: [], address: { street: "", locality: "", region: "", postal_code: "", country: "" } };
}

function addBrand() {
  form.business.brands.push("");
}

function removeBrand(index) {
  form.business.brands.splice(index, 1);
}

// Build the stored business block, dropping blanks so an untouched section saves nothing. Preserves the
// provenance map (business.sources) and stamps a field 'manual' when the tenant changes it, so a later
// auto-seed (Stripe/GBP) knows the tenant owns it.
function cleanBusiness(business, original = {}) {
  const brands = (business.brands || []).map((brand) => String(brand || "").trim()).filter(Boolean);
  const address = Object.fromEntries(
    Object.entries(business.address || {}).filter(([, value]) => String(value || "").trim()),
  );
  const result = {};
  if (business.name) result.name = business.name;
  if (business.email) result.email = business.email;
  if (business.phone) result.phone = normalizeE164(business.phone);
  if (brands.length) result.brands = brands;
  if (Object.keys(address).length) result.address = address;

  const sources = { ...(original.sources || {}) };
  for (const key of ["name", "email", "phone"]) {
    if ((result[key] || "") !== (original[key] || "")) sources[key] = result[key] ? "manual" : undefined;
    if (!result[key]) delete sources[key];
  }
  if (JSON.stringify(result.address || null) !== JSON.stringify(original.address || null)) {
    if (result.address) sources.address = "manual";
    else delete sources.address;
  }
  const cleanedSources = Object.fromEntries(Object.entries(sources).filter(([, v]) => v));
  if (Object.keys(cleanedSources).length) result.sources = cleanedSources;
  return Object.keys(result).length ? result : null;
}

const formatDate = formatEpochDate;
const displayNamePlaceholder = computed(() => `${form.first_name} ${form.last_name}`.trim() || "Your name");
const businessPhoneError = computed(() => phoneError(form.business.phone));

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
    email: business.email || "",
    phone: business.phone || "",
    brands: Array.isArray(business.brands) ? [...business.brands] : [],
    address: {
      street: address.street || "", locality: address.locality || "", region: address.region || "",
      postal_code: address.postal_code || "", country: normalizeCountry(address.country),
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
  if (businessPhoneError.value) {
    error.value = businessPhoneError.value;
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
    const business = cleanBusiness(form.business, rawDoc.value.business || {});
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
