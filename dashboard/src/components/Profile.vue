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
        <!-- Business identity moved to the Site (plans/SITE_AS_BUSINESS_IDENTITY.md). This section is
             now two things wearing one heading: an ACCOUNT-LEVEL FALLBACK for the name and reply address,
             used by any site that has not set its own, and the OPERATIONAL fields (address, phone,
             timezone, cutoff) that shipping and delivery estimates genuinely read from the account. Said
             plainly here, because a tenant who edits a name on this screen expecting their storefront to
             change would otherwise be quietly disappointed. -->
        <p class="field-note">
          <strong>Each site has its own business identity</strong> — name, address, brands and reply
          address live on the site, in <em>Sites → Edit → Business</em>, so you can run more than one
          business from one account. <strong>Brands are managed there only.</strong> What is left here is
          the fallback for a site that has not named itself, plus the account-level details shipping and
          delivery estimates use. All optional.
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
        <!-- BUSINESS EMAIL RETIRED (plans/SITE_AS_BUSINESS_IDENTITY.md P4, 2026-11-04). A business's
             reply address belongs to the site that IS the business and is verified there, in
             Sites -> Edit -> Business. Leaving the field here would let a tenant verify an address that
             drives nothing — the worse half of a half-migration. Customer replies now reach the site's
             verified address, or your sign-in email if it has none. -->

        <p v-if="hasStripeSourcedFields" class="field-note">
          Some details were filled automatically from your Stripe account. Edit any field to override it.
        </p>

        <fieldset class="offer-field business-address">
          <span>Business Address</span>
          <small>For NAP consistency and local-SEO structured data. Manual entry; overridable by Google Business Profile once connected.</small>
          <!--
            The SAME component the Shipping screen uses, so one address looks and behaves like another
            wherever a tenant meets one. `contact` is off because a business address is a PLACE: the
            business's own name and phone are fields above this, and "residential" is a carrier's pricing
            question rather than something true of a business.
          -->
          <AddressFields :address="form.business.address" :contact="false" />
        </fieldset>
        <label class="offer-field">
          <span>Store Timezone</span>
          <select v-model="form.business.timezone">
            <option value="">
              Suggested from your address{{ timezoneSuggested ? ` — ${zoneLabel(timezoneSuggested)}` : "" }}
            </option>
            <option v-for="zone in timezoneChoices" :key="zone" :value="zone">{{ zoneLabel(zone) }}</option>
          </select>
          <small>
            Your working day — it decides when the shipping cutoff falls, so buyers get an honest delivery
            estimate. Suggested from your business address, but yours to change: you might live in one zone
            and ship from a warehouse in another.
          </small>
        </label>
        <label class="offer-field">
          <span>Orders after this ship the next business day</span>
          <select v-model.number="form.business.shipping_cutoff_hour">
            <option :value="null">3:00 PM (suggested)</option>
            <option v-for="hour in 24" :key="hour - 1" :value="hour - 1">{{ hourLabel(hour - 1) }}</option>
          </select>
          <small>
            A buffer, not a rule — most days you will ship same-day and quietly beat the estimate. It only
            changes the arrival date shown to buyers on your thank-you page.
          </small>
        </label>
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
import { normalizeCountry } from "../utils/countries";
import AddressFields from "./AddressFields.vue";
import { useProfileStore } from "../stores/profile";
import { hourLabel, timeZoneOptions, zoneLabel } from "../utils/timezones";


const session = getAuthSession() || {};
const userId = session.user_id || "";
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");
const rawDoc = ref({});
const profileStore = useProfileStore();
const email = ref(session.email || "");
const form = reactive({
  first_name: session.first_name || "", last_name: session.last_name || "", display_name: "",
  business: emptyBusiness(),
});

// The server's guess from the business address. Transient and NOT part of `form`: a suggestion the tenant
// has not looked at must never be saved as a value they appear to have chosen -- an empty stored timezone
// means "use the suggestion", which keeps following the address if they move.
const timezoneSuggested = ref("");
// The shared helpers rather than private copies: the Sites screen needs the same three for a Site's own
// working day, and a second copy is a second answer to "which zones exist".
const timezoneChoices = computed(() => timeZoneOptions(form.business.timezone));

const hasStripeSourcedFields = computed(() =>
  Object.values((rawDoc.value.business || {}).sources || {}).includes("stripe"),
);

// The form holds the shape AddressFields edits; the DOCUMENT keeps its PostalAddress shape, because that
// is what feeds LocalBusiness JSON-LD, the localized image alt text and the figcaption NAP
// (`_postal_address_ld` maps street/locality/region straight to schema.org). Translating at the two edges
// keeps one vocabulary on screen and the other in storage, rather than changing what search engines read.
function emptyPlace() {
  return { street1: "", street2: "", city: "", state: "", postal_code: "", country: "" };
}

function placeFromDocument(address = {}) {
  return {
    street1: address.street || "",
    street2: address.street2 || "",
    city: address.locality || "",
    state: address.region || "",
    postal_code: address.postal_code || "",
    country: normalizeCountry(address.country),
  };
}

function placeToDocument(place = {}) {
  return {
    street: place.street1 || "",
    street2: place.street2 || "",
    locality: place.city || "",
    region: place.state || "",
    postal_code: place.postal_code || "",
    country: place.country || "",
  };
}

function emptyBusiness() {
  // `null` cutoff and blank timezone both mean "use the suggestion" -- see cleanBusiness.
  return { name: "", phone: "", address: emptyPlace(), timezone: "",
           shipping_cutoff_hour: null };
}

// Build the stored business block, dropping blanks so an untouched section saves nothing. Preserves the
// provenance map (business.sources) and stamps a field 'manual' when the tenant changes it, so a later
// auto-seed (Stripe/GBP) knows the tenant owns it.
function cleanBusiness(business, original = {}) {
  const address = Object.fromEntries(
    Object.entries(placeToDocument(business.address)).filter(([, value]) => String(value || "").trim()),
  );
  const result = {};
  if (business.name) result.name = business.name;
  if (business.phone) result.phone = normalizeE164(business.phone);
  if (Object.keys(address).length) result.address = address;
  // Sent only when the tenant actually CHOSE one. Blank means "follow my address", which keeps working if
  // they move -- persisting the suggestion would freeze a guess into a decision they never made.
  if (business.timezone) result.timezone = business.timezone;
  // Null means "use the suggested 3pm" and must stay absent, for the same reason a blank timezone does:
  // a default nobody chose should not look like a decision.
  if (Number.isInteger(business.shipping_cutoff_hour)) {
    result.shipping_cutoff_hour = business.shipping_cutoff_hour;
  }

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
    phone: business.phone || "",
    address: placeFromDocument(address),
    timezone: business.timezone || "",
    shipping_cutoff_hour: Number.isInteger(business.shipping_cutoff_hour)
      ? business.shipping_cutoff_hour : null,
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
    // Derived server-side from the address, never stored. The inference lives in one place; a JS copy of
    // the state table would be a second answer to "where is this store" and the two would drift.
    timezoneSuggested.value = body.timezone_suggested || "";
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
    // The SHARED store caches this profile for six other screens -- the brand picker, landing-page
    // defaults, the Sites header, Shipping's "Copy from business address" -- and nothing invalidated it.
    // Without this, a tenant edits their business here and every one of those keeps the old values until
    // a full page reload. Failing to refresh must not fail the save, which has already succeeded.
    profileStore.load().catch(() => {});
    message.value = "Profile saved.";
  } catch (err) {
    error.value = err.message || "Failed to save profile.";
  } finally {
    saving.value = false;
  }
}

load();
</script>
