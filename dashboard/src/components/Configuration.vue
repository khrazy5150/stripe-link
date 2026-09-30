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
            <PhoneInput v-model="form.support.phone" />
          </label>
        </div>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>SMS Notification Phone</span>
            <PhoneInput v-model="form.support.sms_notification_phone" />
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
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Price Label</span>
            <input v-model.trim="form.page_defaults.upsell.price_label" type="text" placeholder="Yours for only" />
            <small>Shown above the price on the upsell page.</small>
          </label>
          <label class="offer-field">
            <span>Downsell Headline</span>
            <input v-model.trim="form.page_defaults.upsell.downsell_headline" type="text" placeholder="Wait — Here's a Smaller Option" />
          </label>
        </div>
        <label class="offer-field">
          <span>Downsell Note</span>
          <input v-model.trim="form.page_defaults.upsell.downsell_note" type="text" placeholder="This offer will not be shown again." />
          <small>A last-chance line above the button, shown when the downsell appears.</small>
        </label>
      </div>
    </section>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Thank You Page Defaults</h2></header>
      <div class="dashboard-card-body">
        <div class="ty-field-row">
          <label class="offer-field ty-emoji"><span>Emoji</span>
            <input v-model.trim="form.page_defaults.thank_you.headline_icon" type="text" maxlength="4" placeholder="🎉" /></label>
          <label class="offer-field"><span>Headline</span>
            <input v-model.trim="form.page_defaults.thank_you.headline" type="text" placeholder="Thank You for Your Purchase!" /></label>
        </div>
        <label class="offer-field"><span>Subtitle</span>
          <input v-model.trim="form.page_defaults.thank_you.subtitle" type="text" placeholder="Your Order Has Been Confirmed!" /></label>
        <label class="offer-field"><span>Message</span>
          <textarea v-model.trim="form.page_defaults.thank_you.message" rows="2" placeholder="Look for an email from us with further details on your order."></textarea></label>

        <label class="builder-toggle"><input v-model="form.page_defaults.thank_you.enable_celebration" type="checkbox" /><span>Show the celebration animation</span></label>

        <label class="builder-toggle"><input v-model="form.page_defaults.thank_you.enable_next_steps" type="checkbox" /><span>Show a “What’s Next?” section</span></label>
        <template v-if="form.page_defaults.thank_you.enable_next_steps">
          <label class="offer-field"><span>Section title</span>
            <input v-model.trim="form.page_defaults.thank_you.next_steps_title" type="text" placeholder="What's Next?" /></label>
          <div v-for="(card, i) in form.page_defaults.thank_you.next_steps" :key="i" class="ty-card-editor">
            <div class="ty-field-row">
              <label class="offer-field ty-emoji"><span>Icon</span><input v-model.trim="card.icon" type="text" maxlength="4" placeholder="📧" /></label>
              <label class="offer-field"><span>Card title</span><input v-model.trim="card.title" type="text" placeholder="Check Your Email" /></label>
              <button type="button" class="ty-card-remove" title="Remove card" @click="removeThankYouCard(i)">✕</button>
            </div>
            <label class="offer-field"><span>Card text</span><input v-model.trim="card.desc" type="text" placeholder="Confirmation and tracking details…" /></label>
          </div>
          <button v-if="form.page_defaults.thank_you.next_steps.length < 6" type="button" class="secondary-action compact" @click="addThankYouCard">+ Add card</button>
        </template>

        <label class="builder-toggle"><input v-model="form.page_defaults.thank_you.enable_footer" type="checkbox" /><span>Show a footer message</span></label>
        <template v-if="form.page_defaults.thank_you.enable_footer">
          <label class="offer-field"><span>Footer headline</span>
            <input v-model.trim="form.page_defaults.thank_you.footer_headline" type="text" placeholder="The Ball Is in Our Court" /></label>
          <label class="offer-field"><span>Footer message</span>
            <input v-model.trim="form.page_defaults.thank_you.footer_message" type="text" placeholder="Look for an email with tracking information." /></label>
        </template>

        <label class="builder-toggle"><input v-model="form.page_defaults.thank_you.show_home_button" type="checkbox" /><span>Show a “Back to Home” link</span></label>
        <label v-if="form.page_defaults.thank_you.show_home_button" class="offer-field"><span>Home link text</span>
          <input v-model.trim="form.page_defaults.thank_you.home_button_text" type="text" placeholder="Back to Home" /></label>

        <label class="builder-toggle"><input v-model="form.page_defaults.thank_you.enable_download" type="checkbox" /><span>Show a download button</span></label>
        <template v-if="form.page_defaults.thank_you.enable_download">
          <label class="offer-field"><span>Download URL</span>
            <input v-model.trim="form.page_defaults.thank_you.download_url" type="url" placeholder="https://…" /></label>
          <label class="offer-field"><span>Download button text</span>
            <input v-model.trim="form.page_defaults.thank_you.download_button_text" type="text" placeholder="Download Your Product" /></label>
        </template>
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
      <header class="dashboard-card-header"><h2>Refund Policy</h2></header>
      <div class="dashboard-card-body">
        <p class="field-note">
          What your storefront promises buyers, per kind of product. Until you set these, the platform's
          default applies and is labelled as such — it is not a policy you chose.
        </p>
        <div v-for="cls in refundClasses" :key="cls" class="refund-class">
          <div class="refund-class-head">
            <div>
              <h3>{{ refundOptions.class_labels?.[cls] || cls }}</h3>
              <p class="field-note">{{ refundOptions.class_hints?.[cls] }}</p>
            </div>
            <label class="builder-toggle">
              <input v-model="form.refund_policies[cls].enabled" type="checkbox" />
              <span>Set my own</span>
            </label>
          </div>

          <div v-if="form.refund_policies[cls].enabled" class="offer-three-column">
            <label class="offer-field">
              <span>Refund window</span>
              <select v-model="form.refund_policies[cls].refund_window">
                <option v-for="w in refundOptions.windows || []" :key="w.value" :value="w.value">{{ w.label }}</option>
              </select>
            </label>
            <label class="offer-field">
              <span>Condition required</span>
              <select v-model="form.refund_policies[cls].condition">
                <option v-for="c in refundOptions.conditions || []" :key="c.value" :value="c.value">{{ c.label }}</option>
              </select>
            </label>
            <label class="offer-field">
              <span>Return handling</span>
              <select v-model="form.refund_policies[cls].return_method">
                <option v-for="m in refundOptions.return_methods || []" :key="m.value" :value="m.value">{{ m.label }}</option>
              </select>
            </label>
          </div>

          <label v-if="form.refund_policies[cls].enabled && form.refund_policies[cls].refund_window === 'custom'" class="offer-field">
            <span>Your policy wording <em>(required for a custom window)</em></span>
            <textarea v-model="form.refund_policies[cls].full_policy" rows="3"
                      placeholder="Describe your refund terms in full. This is what buyers read."></textarea>
          </label>

          <label v-if="form.refund_policies[cls].enabled && form.refund_policies[cls].return_method === 'return_required'" class="offer-field">
            <span>Waive the return below this order value <em>(optional, in {{ (form.default_currency || 'usd').toUpperCase() }})</em></span>
            <input v-model="form.refund_policies[cls].keep_it_below" type="text" inputmode="decimal" placeholder="e.g. 20.00" />
            <small class="field-note">
              When return postage costs more than the item is worth, asking for it back loses money — and a
              buyer held waiting files a chargeback that costs more than the refund.
            </small>
          </label>

          <div class="refund-preview">
            <span class="refund-preview-badge">{{ refundPreview(cls).short_label }}</span>
            <p v-if="refundPreview(cls).full_policy">{{ refundPreview(cls).full_policy }}</p>
            <p v-else class="field-note">Write your wording above — a custom window has nothing to show without it.</p>
            <small class="field-note">{{ refundSourceNote(cls) }}</small>
          </div>
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

    <section v-if="isTestEnv" class="dashboard-card danger-zone">
      <header class="dashboard-card-header"><h2>Danger Zone</h2></header>
      <div class="dashboard-card-body">
        <p class="field-note">Permanently delete all of this workspace's <strong>test</strong> data from
          Stripe and the database. This cannot be undone. Available in the Test environment only.</p>
        <button class="danger-action" type="button" :disabled="deleting" @click="openDeleteModal">
          {{ deleting ? "Deleting…" : "Delete Test Data" }}
        </button>
        <p v-if="deleteSummary" class="field-note delete-summary">{{ deleteSummary }}</p>
      </div>
    </section>

    <footer class="config-save-bar">
      <button class="primary-action" type="button" :disabled="saving || loading" @click="save">
        {{ saving ? "Saving..." : "Save Configuration" }}
      </button>
    </footer>

    <div v-if="showDeleteModal" class="modal-backdrop" @click.self="showDeleteModal = false">
      <section class="modal-card delete-test-data-modal" role="dialog" aria-modal="true" aria-labelledby="deleteTestDataTitle">
        <header class="modal-card-header">
          <h2 id="deleteTestDataTitle" class="danger-title">Delete All Test Data</h2>
          <button type="button" class="modal-close" aria-label="Close" @click="showDeleteModal = false">×</button>
        </header>
        <div class="dashboard-card-body">
          <p class="danger-text"><strong>Warning: this action cannot be undone.</strong></p>
          <p><strong>Database</strong> — permanently deletes this workspace's:</p>
          <ul class="delete-scope">
            <li>Products, offers, coupons, landing pages</li>
            <li>Orders, checkout sessions, invoices, refunds, ledger entries</li>
            <li>Customers, leads, reviews, carts, notifications</li>
          </ul>
          <p><strong>Stripe (test mode)</strong> — best effort:</p>
          <ul class="delete-scope">
            <li>Customers &amp; coupons (deleted)</li>
            <li>Products without prices (deleted); with prices (archived)</li>
            <li>Prices (archived — Stripe cannot delete them)</li>
          </ul>
          <p class="field-note">Not touched: Stripe keys, your profile &amp; preferences, custom domains
            (Sites), and services/bookings.</p>
          <p v-if="deleteError" class="field-error">{{ deleteError }}</p>
        </div>
        <footer class="config-save-bar">
          <button class="secondary-action" type="button" :disabled="deleting" @click="showDeleteModal = false">Cancel</button>
          <button class="danger-action" type="button" :disabled="deleting" @click="confirmDelete">
            {{ deleting ? "Deleting…" : "Delete All Test Data" }}
          </button>
        </footer>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { apiRequest, getApiBase, getStripeMode, getTenantId } from "../api/client";
import { useRefundPolicyStore } from "../stores/refundPolicy";
import PhoneInput from "./PhoneInput.vue";

const loading = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");
// Full stored document, kept so unmanaged sections (custom_domains, developer_tools,
// system, etc.) survive a save -- this screen only owns a subset of TenantConfig.
const rawConfig = ref({});

// The platform's default "What's Next?" cards (mirror of upsell_pages.DEFAULT_THANK_YOU.next_steps). Declared
// BEFORE `form` because defaultForm() reads it — a const referenced before its line throws a TDZ error.
const CONFIG_THANK_YOU_CARDS = [
  { icon: "📧", title: "Check Your Email", desc: "Confirmation and tracking details are on the way to your inbox." },
  { icon: "📦", title: "Free Shipping", desc: "Your order will arrive within 5–7 business days." },
  { icon: "🚀", title: "Start Your Journey", desc: "Begin your routine as soon as it arrives." },
];
// Vocabulary and generated sentences come from the SERVER via one shared store, because the product form
// needs the same tables and the two must not disagree. Composing the sentence in JavaScript is precisely the
// bug this screen exists to fix (plans/REFUND_POLICY.md).
const refundStore = useRefundPolicyStore();
const refundOptions = computed(() => refundStore.options);
const refundResolved = computed(() => refundStore.resolved);
const refundClasses = computed(() => refundStore.classes);

function blankRefundPolicy() {
  return { enabled: false, refund_window: "", condition: "", return_method: "", full_policy: "", keep_it_below: "" };
}

function refundPreview(cls) {
  const entry = form.refund_policies[cls];
  if (!entry.enabled) {
    const effective = refundStore.effective(cls);
    return { short_label: effective.short_label || "", full_policy: effective.full_policy || "" };
  }
  return refundStore.preview(cls, entry);
}

function refundSourceNote(cls) {
  if (form.refund_policies[cls].enabled) return "Your default. Products can still override it individually.";
  return refundStore.sourceNote(cls);
}

const form = reactive(defaultForm());

const apiBase = computed(() => getApiBase());
const environmentLabel = computed(() => (getStripeMode() === "live" ? "Live mode" : "Test mode"));
// Danger Zone (Test-only) — delete all of this tenant's test data.
const isTestEnv = computed(() => getStripeMode() !== "live");
const showDeleteModal = ref(false);
const deleting = ref(false);
const deleteError = ref("");
const deleteSummary = ref("");

function openDeleteModal() {
  deleteError.value = "";
  showDeleteModal.value = true;
}

async function confirmDelete() {
  deleting.value = true;
  deleteError.value = "";
  try {
    const res = await apiRequest("/admin/delete-test-data", { method: "POST" });
    const deleted = res.deleted || {};
    const total = Object.values(deleted).reduce((sum, n) => sum + (Number(n) || 0), 0);
    const stripe = res.stripe || {};
    const parts = [];
    if (stripe.customers_deleted != null) parts.push(`${stripe.customers_deleted} customers`);
    if (stripe.products_deleted != null || stripe.products_archived != null) {
      parts.push(`${(stripe.products_deleted || 0) + (stripe.products_archived || 0)} products`);
    }
    if (stripe.coupons_deleted != null) parts.push(`${stripe.coupons_deleted} coupons`);
    deleteSummary.value = `Deleted ${total} database records${parts.length ? `; Stripe: ${parts.join(", ")}` : ""}.`;
    showDeleteModal.value = false;
  } catch (err) {
    deleteError.value = err.message || "Failed to delete test data.";
  } finally {
    deleting.value = false;
  }
}
const priceToken = "{{ upsell_price }}";
const acceptButtonPlaceholder = `Yes, I'll Take This Deal for ${priceToken}`;

// Schema defaults. The backend validator requires page_defaults.upsell/thank_you to be
// complete when present, so partial entry is completed with these rather than rejected.
const UPSELL_DEFAULTS = {
  headline: "Wait! Before You Go...",
  subheadline: "Exclusive One-Time Offer Just For You",
  accept_button_text: acceptButtonPlaceholder,
  decline_button_text: "No, Thank You! Let's Move On",
  price_label: "Yours for only",
  downsell_headline: "Wait — Here's a Smaller Option",
  downsell_note: "This offer will not be shown again.",
};
function addThankYouCard() {
  form.page_defaults.thank_you.next_steps.push({ icon: "", title: "", desc: "" });
}
function removeThankYouCard(index) {
  form.page_defaults.thank_you.next_steps.splice(index, 1);
}

function defaultForm() {
  return {
    default_currency: "usd",
    support: { email: "", phone: "", sms_notification_phone: "" },
    checkout: { phone_number_collection_enabled: false, default_success_url: "", default_cancel_url: "" },
    page_defaults: {
      upsell: {
        headline: "", subheadline: "", accept_button_text: "", decline_button_text: "",
        price_label: "", downsell_headline: "", downsell_note: "",
      },
      thank_you: {
        headline: "", headline_icon: "", subtitle: "", message: "",
        enable_celebration: true, enable_next_steps: true, next_steps_title: "",
        next_steps: CONFIG_THANK_YOU_CARDS.map((card) => ({ ...card })),
        enable_footer: false, footer_headline: "", footer_message: "",
        show_home_button: false, home_button_text: "",
        enable_download: false, download_button_text: "", download_url: "",
      },
    },
    legal_defaults: { terms_url: "", privacy_url: "", refund_url: "" },
    // One block per product class. `enabled` is the tenant's own default vs the platform fallback -- the
    // distinction the old code erased by stamping `user_preference_default` on a hardcoded literal.
    refund_policies: {
      physical: blankRefundPolicy(),
      digital: blankRefundPolicy(),
      subscription: blankRefundPolicy(),
    },
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
      price_label: upsell.price_label || "",
      downsell_headline: upsell.downsell_headline || "",
      downsell_note: upsell.downsell_note || "",
    },
    thank_you: {
      headline: thankYou.headline || "",
      headline_icon: thankYou.headline_icon || "",
      subtitle: thankYou.subtitle || "",
      message: thankYou.message || "",
      enable_celebration: thankYou.enable_celebration !== false,
      enable_next_steps: thankYou.enable_next_steps !== false,
      next_steps_title: thankYou.next_steps_title || "",
      next_steps: Array.isArray(thankYou.next_steps) && thankYou.next_steps.length
        ? thankYou.next_steps.map((c) => ({ icon: c.icon || "", title: c.title || "", desc: c.desc || "" }))
        : CONFIG_THANK_YOU_CARDS.map((card) => ({ ...card })),
      enable_footer: thankYou.enable_footer === true,
      footer_headline: thankYou.footer_headline || "",
      footer_message: thankYou.footer_message || "",
      show_home_button: thankYou.show_home_button === true,
      home_button_text: thankYou.home_button_text || "",
      enable_download: thankYou.enable_download === true,
      download_button_text: thankYou.download_button_text || "",
      download_url: thankYou.download_url || "",
    },
  };
  form.legal_defaults = { terms_url: legal.terms_url || "", privacy_url: legal.privacy_url || "", refund_url: legal.refund_url || "" };
  form.analytics_defaults = { google_tag_id: analytics.google_tag_id || "", pixel_id: analytics.pixel_id || "" };

  const storedPolicies = legal.refund_policies || {};
  refundClasses.value.forEach((cls) => {
    const stored = storedPolicies[cls];
    const fallback = refundResolved.value[cls] || {};
    // An absent class is the platform fallback, and the pickers are seeded from it so switching the toggle
    // on starts from what the storefront already says rather than from blanks.
    form.refund_policies[cls] = {
      enabled: Boolean(stored),
      refund_window: (stored || fallback).refund_window || "",
      condition: (stored || fallback).condition || "",
      return_method: (stored || fallback).return_method || "",
      full_policy: stored ? stored.full_policy || "" : "",
      keep_it_below: stored && stored.keep_it_below ? (stored.keep_it_below / 100).toFixed(2) : "",
    };
  });
}

async function load() {
  loading.value = true;
  error.value = "";
  message.value = "";
  try {
    const [body] = await Promise.all([
      apiRequest("/config"),
      refundStore.load({ force: true }),
    ]);
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
// Thank-you defaults: persist only non-blank text, deviating toggles, and edited cards (null when untouched),
// mirroring how a landing page stores its own thank-you override.
function thankYouDefaultsPayload() {
  const ty = form.page_defaults.thank_you;
  const out = {};
  ["headline", "headline_icon", "subtitle", "message", "next_steps_title",
   "footer_headline", "footer_message", "home_button_text", "download_button_text", "download_url"]
    .forEach((k) => { const v = String(ty[k] || "").trim(); if (v) out[k] = v; });
  if (ty.enable_celebration === false) out.enable_celebration = false;
  if (ty.enable_next_steps === false) out.enable_next_steps = false;
  if (ty.enable_footer === true) out.enable_footer = true;
  if (ty.show_home_button === true) out.show_home_button = true;
  if (ty.enable_download === true) out.enable_download = true;
  const cards = (ty.next_steps || [])
    .map((c) => ({ icon: (c.icon || "").trim(), title: (c.title || "").trim(), desc: (c.desc || "").trim() }))
    .filter((c) => c.title || c.desc);
  if (JSON.stringify(cards) !== JSON.stringify(CONFIG_THANK_YOU_CARDS)) out.next_steps = cards;
  return Object.keys(out).length ? out : null;
}

function completeOrNull(formSection, defaults) {
  const anyEntered = Object.values(formSection).some((value) => String(value || "").trim() !== "");
  if (!anyEntered) return null;
  return Object.fromEntries(
    Object.keys(defaults).map((field) => [field, String(formSection[field] || "").trim() || defaults[field]]),
  );
}

// Only the classes the tenant switched on, and only the three structured choices plus their own wording.
// `short_label` and `full_policy` are generated SERVER-SIDE (handlers/config._generate_refund_copy), so this
// deliberately does not send them unless the tenant typed their own.
function refundPoliciesPayload() {
  const out = {};
  refundClasses.value.forEach((cls) => {
    const entry = form.refund_policies[cls];
    if (!entry || !entry.enabled) return;
    const policy = {
      refund_window: entry.refund_window,
      condition: entry.condition,
      return_method: entry.return_method,
    };
    const wording = String(entry.full_policy || "").trim();
    if (wording) policy.full_policy = wording;
    const threshold = Math.round(Number(entry.keep_it_below) * 100);
    if (entry.return_method === "return_required" && Number.isFinite(threshold) && threshold > 0) {
      policy.keep_it_below = threshold;
    }
    out[cls] = policy;
  });
  return out;
}

function refundPolicyProblem() {
  for (const cls of refundClasses.value) {
    const entry = form.refund_policies[cls];
    if (!entry || !entry.enabled) continue;
    const label = refundOptions.value.class_labels?.[cls] || cls;
    if (!entry.refund_window || !entry.condition || !entry.return_method) {
      return `${label}: choose a refund window, a condition and how returns are handled.`;
    }
    if (entry.refund_window === "custom" && !String(entry.full_policy || "").trim()) {
      // A custom policy IS its prose. Saving without it publishes a summary line opening onto nothing.
      return `${label}: a custom refund window needs your own wording, or buyers see an empty policy.`;
    }
  }
  return "";
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
  setOrDelete(pageDefaults, "thank_you", thankYouDefaultsPayload());
  setOrDelete(doc, "page_defaults", pageDefaults);

  const legal = prunedStrings({
    terms_url: form.legal_defaults.terms_url,
    privacy_url: form.legal_defaults.privacy_url,
    refund_url: form.legal_defaults.refund_url,
  });
  setOrDelete(legal, "refund_policies", refundPoliciesPayload());
  setOrDelete(doc, "legal_defaults", legal);
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
    // The server refuses these too -- this is only so the tenant reads what is wrong rather than a 400.
    const refundProblem = refundPolicyProblem();
    if (refundProblem) {
      error.value = refundProblem;
      return;
    }
    const payload = buildPayload();
    const body = await apiRequest("/config", { method: "PUT", body: payload });
    // The resolved defaults just changed, so the "platform's default" notes and previews are now stale.
    await refundStore.load({ force: true });
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

<style scoped>
.danger-zone {
  border: 1px solid rgba(239, 68, 68, 0.35);
}
.danger-action {
  border: 0;
  border-radius: 8px;
  background: #dc2626;
  color: #fff;
  font-weight: 700;
  padding: 0.9rem 1.6rem;
  cursor: pointer;
}
.danger-action:hover { background: #b91c1c; }
.danger-action:disabled { opacity: 0.6; cursor: default; }
.danger-title { color: #dc2626; }
.danger-text { color: #b91c1c; }
.delete-scope {
  margin: 0.4rem 0 1rem 1.2rem;
  padding: 0;
  color: var(--text-muted);
  line-height: 1.6;
}
.delete-summary { color: #16a34a; margin-top: 0.8rem; }
.delete-test-data-modal { width: min(100%, 52rem); }

.refund-class {
  border-top: 1px solid var(--border, rgba(148, 163, 184, 0.25));
  padding-top: 1rem;
  margin-top: 1rem;
  display: grid;
  gap: 0.75rem;
}
.refund-class:first-of-type { border-top: 0; margin-top: 0; padding-top: 0; }
.refund-class-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  flex-wrap: wrap;
}
.refund-class-head h3 { margin: 0 0 0.2rem; font-size: 1rem; }
.refund-class-head .field-note { margin: 0; max-width: 46ch; }
/* The preview is the point of the screen: a tenant must be able to read the sentence their storefront
   publishes before they publish it. Deliberately quiet -- it is a statement, not a control. */
.refund-preview {
  border-left: 3px solid var(--accent, #6366f1);
  background: var(--surface-muted, rgba(148, 163, 184, 0.08));
  border-radius: 0 8px 8px 0;
  padding: 0.7rem 0.9rem;
  display: grid;
  gap: 0.35rem;
}
.refund-preview p { margin: 0; line-height: 1.55; }
.refund-preview-badge {
  justify-self: start;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  color: var(--text-muted);
}
.refund-preview .field-note { margin: 0; }
</style>
