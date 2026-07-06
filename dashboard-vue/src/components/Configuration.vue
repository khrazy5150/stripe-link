<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Configuration</h1>
        <p>Tenant-wide defaults for checkout, landing pages, legal links, and analytics</p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="loading" @click="load">
          {{ loading ? "Loading..." : "Reload" }}
        </button>
        <button class="primary-action" type="button" :disabled="saving || loading" @click="save">
          {{ saving ? "Saving..." : "Save Configuration" }}
        </button>
      </div>
    </header>

    <div v-if="error" class="keys-status-banner error">{{ error }}</div>
    <div v-else-if="message" class="keys-status-banner">{{ message }}</div>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>General</h2></header>
      <div class="dashboard-card-body">
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Default Currency</span>
            <input v-model.trim="form.default_currency" type="text" maxlength="3" placeholder="usd" />
            <small>Three-letter ISO currency code (lowercase), e.g. usd.</small>
          </label>
        </div>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Support Contact</h2></header>
      <div class="dashboard-card-body">
        <p class="field-note">Shown to customers and used for tenant notifications.</p>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Support Email</span>
            <input v-model.trim="form.support.email" type="email" placeholder="support@yourbusiness.com" />
          </label>
          <label class="offer-field">
            <span>Support Phone</span>
            <input v-model.trim="form.support.phone" type="tel" placeholder="+1 555 555 0123" />
          </label>
        </div>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>SMS Notification Phone</span>
            <input v-model.trim="form.support.sms_notification_phone" type="tel" placeholder="+15555550123" />
            <small>E.164 number for tenant SMS/admin notifications.</small>
          </label>
        </div>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Checkout Defaults</h2></header>
      <div class="dashboard-card-body">
        <p class="field-note">Individual offers can override these settings.</p>
        <label class="checkbox-row">
          <input v-model="form.checkout.phone_number_collection_enabled" type="checkbox" />
          <span>Collect the customer's phone number at checkout</span>
        </label>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Default Success URL</span>
            <input v-model.trim="form.checkout.default_success_url" type="url" placeholder="https://yourbusiness.com/thank-you" />
          </label>
          <label class="offer-field">
            <span>Default Cancel URL</span>
            <input v-model.trim="form.checkout.default_cancel_url" type="url" placeholder="https://yourbusiness.com/checkout" />
          </label>
        </div>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Upsell Page Defaults</h2></header>
      <div class="dashboard-card-body">
        <p class="field-note">Auto-populate when creating landing pages. Individual pages can override them.</p>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Headline</span>
            <input v-model.trim="form.page_defaults.upsell.headline" type="text" placeholder="Wait! Before You Go..." />
          </label>
          <label class="offer-field">
            <span>Subheadline</span>
            <input v-model.trim="form.page_defaults.upsell.subheadline" type="text" placeholder="Exclusive One-Time Offer Just For You" />
          </label>
        </div>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Accept Button Text</span>
            <input v-model.trim="form.page_defaults.upsell.accept_button_text" type="text" :placeholder="acceptButtonPlaceholder" />
            <small>Use {{ priceToken }} to insert the product price.</small>
          </label>
          <label class="offer-field">
            <span>Decline Button Text</span>
            <input v-model.trim="form.page_defaults.upsell.decline_button_text" type="text" placeholder="No, Thank You! Let's Move On" />
          </label>
        </div>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Thank You Page Defaults</h2></header>
      <div class="dashboard-card-body">
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Headline</span>
            <input v-model.trim="form.page_defaults.thank_you.headline" type="text" placeholder="Thank You for Your Purchase!" />
          </label>
          <label class="offer-field">
            <span>Subtitle</span>
            <input v-model.trim="form.page_defaults.thank_you.subtitle" type="text" placeholder="Your Order Has Been Confirmed!" />
          </label>
        </div>
        <label class="offer-field">
          <span>Message</span>
          <textarea v-model.trim="form.page_defaults.thank_you.message" rows="3" placeholder="Look for an email from us with further details on your order."></textarea>
        </label>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Legal Links</h2></header>
      <div class="dashboard-card-body">
        <p class="field-note">Default legal page URLs linked from checkout and landing pages.</p>
        <div class="offer-three-column">
          <label class="offer-field">
            <span>Terms URL</span>
            <input v-model.trim="form.legal_defaults.terms_url" type="url" placeholder="https://yourbusiness.com/terms" />
          </label>
          <label class="offer-field">
            <span>Privacy URL</span>
            <input v-model.trim="form.legal_defaults.privacy_url" type="url" placeholder="https://yourbusiness.com/privacy" />
          </label>
          <label class="offer-field">
            <span>Refund URL</span>
            <input v-model.trim="form.legal_defaults.refund_url" type="url" placeholder="https://yourbusiness.com/refunds" />
          </label>
        </div>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Analytics Defaults</h2></header>
      <div class="dashboard-card-body">
        <p class="field-note">Applied to landing pages that don't set their own tracking IDs.</p>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Google Tag ID</span>
            <input v-model.trim="form.analytics_defaults.google_tag_id" type="text" placeholder="G-XXXXXXXXXX" />
          </label>
          <label class="offer-field">
            <span>Meta Pixel ID</span>
            <input v-model.trim="form.analytics_defaults.pixel_id" type="text" placeholder="000000000000000" />
          </label>
        </div>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>System</h2></header>
      <div class="dashboard-card-body">
        <p class="field-note">Read-only. Managed by the platform for the active environment.</p>
        <dl class="product-details-grid">
          <div><dt>Environment</dt><dd>{{ environmentLabel }}</dd></div>
          <div><dt>API Endpoint</dt><dd class="font-mono">{{ apiBase || "—" }}</dd></div>
        </dl>
      </div>
    </section>

    <footer class="config-save-bar">
      <button class="primary-action" type="button" :disabled="saving || loading" @click="save">
        {{ saving ? "Saving..." : "Save Configuration" }}
      </button>
    </footer>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { apiRequest, getApiBase, getApiEnvironment, getTenantId } from "../api/client";

const loading = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");
// Full stored document, kept so unmanaged sections (custom_domains, developer_tools,
// system, etc.) survive a save -- this screen only owns a subset of TenantConfig.
const rawConfig = ref({});

const form = reactive(defaultForm());

const apiBase = computed(() => getApiBase());
const environmentLabel = computed(() => (getApiEnvironment() === "live" ? "Production (live)" : "Test (dev)"));
const priceToken = "{{ upsell_price }}";
const acceptButtonPlaceholder = `Yes, I'll Take This Deal for ${priceToken}`;

// Schema defaults. The backend validator requires page_defaults.upsell/thank_you to be
// complete when present, so partial entry is completed with these rather than rejected.
const UPSELL_DEFAULTS = {
  headline: "Wait! Before You Go...",
  subheadline: "Exclusive One-Time Offer Just For You",
  accept_button_text: acceptButtonPlaceholder,
  decline_button_text: "No, Thank You! Let's Move On",
};
const THANK_YOU_DEFAULTS = {
  headline: "Thank You for Your Purchase!",
  subtitle: "Your Order Has Been Confirmed!",
  message: "Look for an email from us with further details on your order.",
};

function defaultForm() {
  return {
    default_currency: "usd",
    support: { email: "", phone: "", sms_notification_phone: "" },
    checkout: { phone_number_collection_enabled: false, default_success_url: "", default_cancel_url: "" },
    page_defaults: {
      upsell: { headline: "", subheadline: "", accept_button_text: "", decline_button_text: "" },
      thank_you: { headline: "", subtitle: "", message: "" },
    },
    legal_defaults: { terms_url: "", privacy_url: "", refund_url: "" },
    analytics_defaults: { google_tag_id: "", pixel_id: "" },
  };
}

function applyConfig(config) {
  const base = defaultForm();
  const support = config.support || {};
  const checkout = config.checkout || {};
  const pageDefaults = config.page_defaults || {};
  const upsell = pageDefaults.upsell || {};
  const thankYou = pageDefaults.thank_you || {};
  const legal = config.legal_defaults || {};
  const analytics = config.analytics_defaults || {};

  form.default_currency = config.default_currency || base.default_currency;
  form.support = { email: support.email || "", phone: support.phone || "", sms_notification_phone: support.sms_notification_phone || "" };
  form.checkout = {
    phone_number_collection_enabled: Boolean((checkout.phone_number_collection || {}).enabled),
    default_success_url: checkout.default_success_url || "",
    default_cancel_url: checkout.default_cancel_url || "",
  };
  form.page_defaults = {
    upsell: {
      headline: upsell.headline || "",
      subheadline: upsell.subheadline || "",
      accept_button_text: upsell.accept_button_text || "",
      decline_button_text: upsell.decline_button_text || "",
    },
    thank_you: {
      headline: thankYou.headline || "",
      subtitle: thankYou.subtitle || "",
      message: thankYou.message || "",
    },
  };
  form.legal_defaults = { terms_url: legal.terms_url || "", privacy_url: legal.privacy_url || "", refund_url: legal.refund_url || "" };
  form.analytics_defaults = { google_tag_id: analytics.google_tag_id || "", pixel_id: analytics.pixel_id || "" };
}

async function load() {
  loading.value = true;
  error.value = "";
  message.value = "";
  try {
    const body = await apiRequest("/config");
    rawConfig.value = body.config || {};
    applyConfig(rawConfig.value);
  } catch (err) {
    if (/not found/i.test(err.message)) {
      rawConfig.value = {};
      applyConfig({});
      message.value = "No configuration saved yet. Fill in the fields and save.";
    } else {
      error.value = err.message || "Failed to load configuration.";
    }
  } finally {
    loading.value = false;
  }
}

function prunedStrings(object) {
  return Object.fromEntries(Object.entries(object).filter(([, value]) => String(value || "").trim() !== ""));
}

function setOrDelete(target, key, value) {
  if (value && Object.keys(value).length) {
    target[key] = value;
  } else {
    delete target[key];
  }
}

// Returns a complete section (every field filled from entry or default) if the tenant
// entered anything, otherwise null so the whole section is omitted. Mirrors the backend's
// all-or-nothing requirement for page_defaults.upsell / thank_you.
function completeOrNull(formSection, defaults) {
  const anyEntered = Object.values(formSection).some((value) => String(value || "").trim() !== "");
  if (!anyEntered) return null;
  return Object.fromEntries(
    Object.keys(defaults).map((field) => [field, String(formSection[field] || "").trim() || defaults[field]]),
  );
}

function buildPayload() {
  // Start from the stored document so custom_domains and any other unmanaged
  // sections are preserved, then overlay only the fields this screen owns.
  const doc = { ...rawConfig.value };
  doc.schema_version = "2026-05-29";
  doc.document_type = "tenant_config";
  doc.tenant_id = getTenantId();
  doc.default_currency = (form.default_currency || "usd").toLowerCase();
  doc.updated_at = Math.floor(Date.now() / 1000);

  setOrDelete(doc, "support", prunedStrings(form.support));

  const checkout = {
    phone_number_collection: {
      enabled: Boolean(form.checkout.phone_number_collection_enabled),
      label: form.checkout.phone_number_collection_enabled ? "Enabled" : "Disabled",
    },
    ...prunedStrings({ default_success_url: form.checkout.default_success_url, default_cancel_url: form.checkout.default_cancel_url }),
  };
  doc.checkout = checkout;

  const pageDefaults = {};
  setOrDelete(pageDefaults, "upsell", completeOrNull(form.page_defaults.upsell, UPSELL_DEFAULTS));
  setOrDelete(pageDefaults, "thank_you", completeOrNull(form.page_defaults.thank_you, THANK_YOU_DEFAULTS));
  setOrDelete(doc, "page_defaults", pageDefaults);

  setOrDelete(doc, "legal_defaults", prunedStrings(form.legal_defaults));
  setOrDelete(doc, "analytics_defaults", prunedStrings(form.analytics_defaults));

  return doc;
}

async function save() {
  saving.value = true;
  error.value = "";
  message.value = "";
  try {
    const currency = (form.default_currency || "usd").toLowerCase();
    if (!/^[a-z]{3}$/.test(currency)) {
      error.value = "Default currency must be a three-letter code, e.g. usd.";
      return;
    }
    const payload = buildPayload();
    const body = await apiRequest("/config", { method: "PUT", body: payload });
    rawConfig.value = body.config || payload;
    applyConfig(rawConfig.value);
    message.value = "Configuration saved.";
  } catch (err) {
    error.value = err.message || "Failed to save configuration.";
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>
