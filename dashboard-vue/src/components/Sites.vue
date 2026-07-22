<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Sites</h1>
        <p>Your public website — the domain, identity, and SEO that every landing page inherits.</p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="store.loading" @click="reload">
          {{ store.loading ? "Loading..." : "Reload" }}
        </button>
      </div>
    </header>

    <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
    <div v-else-if="store.message" class="keys-status-banner">{{ store.message }}</div>

    <div v-if="store.loaded && !store.sites.length" class="dashboard-card">
      <div class="dashboard-card-body">
        <h2>Create your Site</h2>
        <p class="field-note">
          Your Site is your public website — it owns your hostname and business identity, and every page lives
          under it. We'll seed the business identity from your Profile → Business details and attach any landing
          pages you've already built. It starts on a free <strong>{{ hostingDomainHint }}</strong> address and
          stays private to search engines until you connect your own custom domain.
        </p>
        <label class="offer-field">
          <span>Choose your store address</span>
          <div class="subdomain-input">
            <input
              v-model.trim="createSubdomain"
              type="text"
              placeholder="axel-mart"
              autocapitalize="off"
              autocorrect="off"
              spellcheck="false"
              @input="createCheck.check(createSubdomain)"
            />
            <span class="subdomain-suffix">.{{ hostingDomainHint }}</span>
          </div>
          <small :class="availabilityClass(createCheck.state)">{{ availabilityText(createCheck.state) }}</small>
          <div v-if="createCheck.state.suggestions.length" class="subdomain-suggestions">
            <span class="field-note">Try:</span>
            <button v-for="s in createCheck.state.suggestions" :key="s" type="button" class="subdomain-chip" @click="pickCreate(s)">{{ s }}</button>
          </div>
          <small class="field-note">This address is permanent and unique to you — pick it deliberately. You can add a custom domain later.</small>
        </label>
        <p class="field-note">
          {{ pages.length ? `We'll attach your ${pages.length} existing landing page${pages.length === 1 ? '' : 's'}.` : "You don't have any landing pages yet — that's fine. Create your Site first, then add pages to it." }}
        </p>
        <div class="button-row">
          <button class="primary-action" type="button" :disabled="!canCreate" @click="createDefault">
            {{ store.saving ? "Creating..." : "Create my Site" }}
          </button>
        </div>
      </div>
    </div>

    <div v-for="site in store.sites" :key="site.site_id" class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>{{ site.name }}</h2>
        <div class="button-row">
          <span class="product-status" :class="indexClass(site)">{{ indexLabel(site) }}</span>
          <button class="secondary-action" type="button" @click="openEdit(site)">Edit</button>
        </div>
      </header>
      <div class="dashboard-card-body">
        <dl class="product-details-grid">
          <div><dt>Canonical hostname</dt><dd class="font-mono">{{ canonicalHost(site) }}</dd></div>
          <div><dt>Platform host</dt><dd class="font-mono">{{ site.hosting?.platform_hostname }}</dd></div>
          <div><dt>Custom domain</dt><dd>{{ site.hosting?.custom_domain || "Not connected" }}</dd></div>
          <div><dt>Organization</dt><dd>{{ site.organization?.name || "—" }}</dd></div>
          <div><dt>Pages</dt><dd>{{ Object.keys(site.pages || {}).length }}</dd></div>
          <div><dt>Status</dt><dd>{{ site.status }}</dd></div>
        </dl>
        <p class="field-note">{{ indexReason(site) }}</p>
      </div>
    </div>

    <div v-if="editing" class="modal-backdrop" @click.self="editing = null">
      <section class="modal-card" role="dialog" aria-modal="true">
        <header class="modal-card-header">
          <h2>Edit Site</h2>
          <button type="button" class="modal-close" aria-label="Close" @click="editing = null">×</button>
        </header>
        <div class="product-create-body">
          <div v-if="formError" class="keys-status-banner error">{{ formError }}</div>
          <label class="offer-field">
            <span>Site Name</span>
            <input v-model.trim="form.name" type="text" placeholder="My Store" />
          </label>
          <label class="offer-field">
            <span>Free address (subdomain)</span>
            <div class="subdomain-input">
              <input
                v-model.trim="form.subdomain"
                type="text"
                placeholder="axel-mart"
                autocapitalize="off"
                autocorrect="off"
                spellcheck="false"
                @input="editCheck.check(form.subdomain, editing.site_id)"
              />
              <span class="subdomain-suffix">.{{ hostingDomainHint }}</span>
            </div>
            <small :class="availabilityClass(editCheck.state)">{{ availabilityText(editCheck.state) }}</small>
            <div v-if="editCheck.state.suggestions.length" class="subdomain-suggestions">
              <span class="field-note">Try:</span>
              <button v-for="s in editCheck.state.suggestions" :key="s" type="button" class="subdomain-chip" @click="pickEdit(s)">{{ s }}</button>
            </div>
            <small class="field-note">Changing this claims a new address; your old one stays reserved to you, so existing links keep working. Not indexed by search engines.</small>
          </label>

          <fieldset class="product-identifiers">
            <legend>Business identity (Organization)</legend>
            <p class="field-note">The single source of truth for your business's structured data — every page's Organization, seller, and local-business markup derives from here.</p>
            <div class="offer-two-column">
              <label class="offer-field"><span>Business name</span><input v-model.trim="form.org.name" type="text" placeholder="Axel Mart" /></label>
              <label class="offer-field"><span>Legal name</span><input v-model.trim="form.org.legal_name" type="text" placeholder="Axel Mart LLC" /></label>
            </div>
            <label class="offer-field">
              <span>Business type</span>
              <select v-model="form.org.entity_type">
                <option v-for="t in entityTypes" :key="t" :value="t">{{ t }}</option>
              </select>
            </label>
            <label class="offer-field"><span>Description</span><textarea v-model.trim="form.org.description" rows="2" /></label>
            <div class="offer-two-column">
              <label class="offer-field">
                <span>Phone</span>
                <input v-model.trim="form.org.telephone" type="tel" placeholder="+1 555 010 0100"
                       @blur="form.org.telephone = normalizeE164(form.org.telephone)" />
                <small v-if="orgPhoneError" class="field-error">{{ orgPhoneError }}</small>
              </label>
              <label class="offer-field"><span>Email</span><input v-model.trim="form.org.email" type="email" /></label>
            </div>
            <div class="offer-two-column">
              <label class="offer-field"><span>City</span><input v-model.trim="form.org.address.locality" type="text" /></label>
              <label class="offer-field"><span>Region</span><input v-model.trim="form.org.address.region" type="text" /></label>
            </div>
          </fieldset>

          <fieldset class="product-identifiers">
            <legend>Search engine verification</legend>
            <p class="field-note">Verify your Site in Google/Bing Search Console so you can submit sitemaps. Paste the token from each provider's "HTML tag" verification method (just the content value).</p>
            <label class="offer-field"><span>Google verification token</span><input v-model.trim="form.seo.google_site_verification" type="text" placeholder="google-site-verification content…" /></label>
            <label class="offer-field"><span>Bing verification token</span><input v-model.trim="form.seo.bing_site_verification" type="text" placeholder="msvalidate.01 content…" /></label>
          </fieldset>

          <fieldset v-if="customDomainsEnabled" class="product-identifiers">
            <legend>Custom domain</legend>
            <p class="field-note">Connect your own domain to serve this Site's homepage and become eligible for search indexing. On the free {{ hostingDomainHint }} address a Site is never indexed.</p>
            <div v-if="domainError" class="keys-status-banner error">{{ domainError }}</div>

            <template v-if="!editing.hosting?.custom_domain">
              <label class="offer-field">
                <span>Your domain</span>
                <input v-model.trim="domainForm.domain" type="text" placeholder="shop.yourbrand.com" autocapitalize="off" spellcheck="false" />
              </label>
              <label v-if="!siteHasHomepage" class="offer-field">
                <span>Which page should the domain show?</span>
                <select v-model="domainForm.homepage">
                  <option value="">Choose a homepage…</option>
                  <option v-for="p in pages" :key="p.page_id" :value="p.page_id">
                    {{ p.name || p.page_id }}{{ p.status === 'published' ? '' : ' — draft, publish to go live' }}
                  </option>
                </select>
                <small v-if="!pages.length" class="field-note">This Site has no landing pages yet. Create and publish a landing page first, then connect your domain.</small>
                <small v-else class="field-note">The homepage must be published for the domain to serve it.</small>
              </label>
              <div class="button-row">
                <button type="button" class="primary-action" :disabled="domainBusy || !domainForm.domain || (!siteHasHomepage && !domainForm.homepage)" @click="connectDomain">
                  {{ domainBusy ? "Connecting…" : "Connect domain" }}
                </button>
              </div>
            </template>

            <template v-else>
              <dl class="product-details-grid">
                <div><dt>Domain</dt><dd class="font-mono">{{ editing.hosting.custom_domain }}</dd></div>
                <div><dt>Status</dt><dd>{{ domainStatusLabel }}</dd></div>
              </dl>
              <div v-if="!editing.hosting.verification?.verified" class="domain-dns">
                <div class="dns-provider-row">
                  <label for="dns-provider">Add these at your DNS provider:</label>
                  <select id="dns-provider" v-model="dnsProvider">
                    <option v-for="p in dnsProviders" :key="p.id" :value="p.id">{{ p.label }}</option>
                  </select>
                </div>
                <p v-if="apexHint" class="field-note apex-hint">{{ apexHint }}</p>
                <div class="dns-accordion">
                  <div v-for="(rec, i) in displayRecords" :key="i" class="dns-step" :class="{ open: openStep === i }">
                    <button type="button" class="dns-step-header" @click="openStep = openStep === i ? -1 : i">
                      <span class="dns-badge" :class="rec.badgeClass">{{ rec.badgeIcon }}</span>
                      <span class="dns-step-title">{{ rec.stepLabel }}</span>
                      <span class="dns-step-status" :class="rec.badgeClass">{{ rec.statusText }}</span>
                      <span class="dns-chevron">{{ openStep === i ? '▾' : '▸' }}</span>
                    </button>
                    <div class="dns-step-body">
                      <p v-if="providerTip" class="field-note">{{ providerTip }}</p>
                      <div class="dns-field"><span class="dns-field-label">Type</span><code>{{ rec.type }}</code></div>
                      <div class="dns-field">
                        <span class="dns-field-label">Name</span><code>{{ rec.displayName }}</code>
                        <button type="button" class="copy-btn" @click="copy(rec.displayName)">{{ copied === rec.displayName ? 'Copied!' : 'Copy' }}</button>
                      </div>
                      <div class="dns-field">
                        <span class="dns-field-label">Value</span><code class="dns-value">{{ rec.value }}</code>
                        <button type="button" class="copy-btn" @click="copy(rec.value)">{{ copied === rec.value ? 'Copied!' : 'Copy' }}</button>
                      </div>
                      <p v-if="rec.note" class="field-note">{{ rec.note }}</p>
                    </div>
                  </div>
                </div>
              </div>
              <div class="button-row">
                <button v-if="!editing.hosting.verification?.verified" type="button" class="primary-action" :disabled="domainBusy" @click="checkDomain">
                  {{ domainBusy ? "Checking…" : "Verify domain" }}
                </button>
                <button type="button" class="secondary-action" :disabled="domainBusy" @click="disconnectDomain">Disconnect</button>
              </div>
            </template>
          </fieldset>

          <div class="offer-field">
            <span>Homepage</span>
            <div class="homepage-picker">
              <select v-model="homepagePick">
                <option value="">Choose a page…</option>
                <option v-for="p in pages" :key="p.page_id" :value="p.page_id">{{ p.name || p.page_id }}</option>
              </select>
              <button type="button" class="secondary-action" :disabled="!homepagePick || homepageBusy" @click="setAsHomepage">
                {{ homepageBusy ? "Setting…" : "Set as homepage" }}
              </button>
            </div>
            <small>The page served at your domain root (/). Your current homepage moves to its own slug so it stays live.</small>
            <p v-if="homepageError" class="field-error">{{ homepageError }}</p>
          </div>

          <div class="offer-field">
            <span>Attach a page</span>
            <div class="homepage-picker">
              <select v-model="attachForm.pageId">
                <option value="">Choose a page…</option>
                <option v-for="p in pages" :key="p.page_id" :value="p.page_id">{{ p.name || p.page_id }}</option>
              </select>
              <input v-model.trim="attachForm.slug" type="text" placeholder="/slug" class="attach-slug" />
              <button type="button" class="secondary-action" :disabled="!attachForm.pageId || !attachForm.slug || attachBusy" @click="attachPage">
                {{ attachBusy ? "Attaching…" : "Attach" }}
              </button>
            </div>
            <small>Places a page at a slug so it serves on your domain. A category page is detected automatically; other pages attach as landing pages (which is what lets category pages find them).</small>
            <p v-if="attachError" class="field-error">{{ attachError }}</p>
          </div>

          <div class="offer-field">
            <span>Pages in this Site</span>
            <ul class="category-menu">
              <li v-for="(entry, slug) in editing.pages" :key="slug">
                <span class="font-mono">{{ slug }}</span> — {{ entry.label || entry.page_id }}
                <em>({{ entry.page_type || 'landing' }}{{ entry.category ? ', ' + entry.category : '' }}{{ entry.enabled === false ? ', disabled' : '' }})</em>
              </li>
            </ul>
            <small>Page routing, slugs, and navigation get a full editor in a later phase.</small>
          </div>
        </div>
        <footer class="modal-card-footer">
          <button type="button" class="secondary-action" @click="editing = null">Cancel</button>
          <button type="button" class="primary-action" :disabled="!canSaveEdit" @click="saveEdit">
            {{ store.saving ? "Saving..." : "Save Site" }}
          </button>
        </footer>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { apiRequest, getApiEnvironment } from "../api/client";
import { useSitesStore, organizationFromBusiness, suggestSubdomain } from "../stores/sites";
import { useProfileStore } from "../stores/profile";
import { useSubdomainCheck } from "../composables/useSubdomainCheck";
import { normalizeE164, phoneError } from "../utils/phone";

const store = useSitesStore();
const profileStore = useProfileStore();
const pages = ref([]);
const editing = ref(null);
const formError = ref("");
const hostingDomainHint = "jbay.uk";
const entityTypes = ["OnlineStore", "Organization", "LocalBusiness", "HomeAndConstructionBusiness", "HealthAndBeautyBusiness", "FoodEstablishment", "ProfessionalService", "Store"];

const createSubdomain = ref("");
const createCheck = useSubdomainCheck();
const editCheck = useSubdomainCheck();

const form = reactive({ name: "", subdomain: "", org: { name: "", legal_name: "", entity_type: "OnlineStore", description: "", telephone: "", email: "", address: { locality: "", region: "" } }, seo: { google_site_verification: "", bing_site_verification: "" } });

const domainForm = reactive({ domain: "", homepage: "" });
const domainBusy = ref(false);
const domainError = ref("");

const homepagePick = ref("");
const homepageBusy = ref(false);
const homepageError = ref("");
async function setAsHomepage() {
  if (!homepagePick.value || !editing.value) return;
  homepageBusy.value = true;
  homepageError.value = "";
  try {
    const site = await store.setHomepage(editing.value.site_id, homepagePick.value, editing.value.tenant_id);
    editing.value = { ...site };
    homepagePick.value = "";
  } catch (error) {
    homepageError.value = error.message || "Failed to set homepage.";
  } finally {
    homepageBusy.value = false;
  }
}

const attachForm = reactive({ pageId: "", slug: "" });
const attachBusy = ref(false);
const attachError = ref("");
// A category page carries a catalog_grid section with a category key; attach it as page_type=category so the
// renderer/breadcrumbs treat it right. Everything else attaches as a landing page.
function categoryOfPage(page) {
  const grid = (page?.sections || []).find((s) => s && s.type === "catalog_grid" && s.category);
  return grid ? String(grid.category) : "";
}
async function attachPage() {
  if (!attachForm.pageId || !attachForm.slug || !editing.value) return;
  attachBusy.value = true;
  attachError.value = "";
  try {
    const page = pages.value.find((p) => p.page_id === attachForm.pageId) || {};
    const category = categoryOfPage(page);
    const site = await store.attachPage(
      editing.value.site_id,
      { pageId: attachForm.pageId, slug: attachForm.slug, pageType: category ? "category" : "landing", category, label: page.name },
      editing.value.tenant_id,
    );
    editing.value = { ...site };
    attachForm.pageId = "";
    attachForm.slug = "";
  } catch (error) {
    attachError.value = error.message || "Failed to attach the page.";
  } finally {
    attachBusy.value = false;
  }
}
const domainDiagnostics = ref({});

const dnsProviders = [
  { id: "route53", label: "AWS Route 53", fqdn: false },
  { id: "cloudflare", label: "Cloudflare", fqdn: false },
  { id: "godaddy", label: "GoDaddy", fqdn: false },
  { id: "namecheap", label: "Namecheap", fqdn: false },
  { id: "cpanel", label: "cPanel", fqdn: true },
  { id: "other", label: "Other / full name", fqdn: true },
];
// Custom-domain serving is production/Live-only (single prod edge Worker) — hide it in Test to avoid a dead end.
const customDomainsEnabled = computed(() => getApiEnvironment() === "live");
const dnsProvider = ref("route53");
const openStep = ref(0);
const copied = ref("");
const providerFqdn = computed(() => (dnsProviders.find((p) => p.id === dnsProvider.value) || {}).fqdn);
const providerLabel = computed(() => (dnsProviders.find((p) => p.id === dnsProvider.value) || {}).label);
const providerTip = computed(() =>
  providerFqdn.value
    ? "Enter the full Name exactly as shown (including your domain)."
    : `${providerLabel.value} adds your domain automatically — enter only the Name shown (the part before your domain).`,
);

function rootDomain(domain) {
  const parts = String(domain || "").split(".");
  return parts.length > 2 ? parts.slice(-2).join(".") : domain;
}
function hostPrefix(fullName, domain) {
  const root = rootDomain(domain);
  if (fullName === root) return "@";
  return fullName.endsWith("." + root) ? fullName.slice(0, -(root.length + 1)) : fullName;
}

const displayRecords = computed(() => {
  const domain = editing.value?.hosting?.custom_domain || "";
  return (editing.value?.domain_provisioning?.dns_records || []).map((rec) => {
    const diag = domainDiagnostics.value[rec.name];
    const resolved = diag ? diag.resolved : null;
    const isSsl = rec.name.startsWith("_acme-challenge");
    return {
      type: rec.type,
      value: rec.value,
      note: rec.note || "",
      displayName: providerFqdn.value ? rec.name : hostPrefix(rec.name, domain),
      stepLabel: isSsl ? "SSL certificate" : "Point your domain",
      badgeClass: resolved === true ? "ok" : resolved === false ? "bad" : "idle",
      badgeIcon: resolved === true ? "✓" : resolved === false ? "!" : "•",
      statusText: resolved === true ? "Detected" : resolved === false ? (diag.note || "Not found yet") : "",
    };
  });
});

// An apex domain (example.com) can't hold a plain CNAME. Guidance depends on the provider (§2.6b).
const isApexDomain = computed(() =>
  (editing.value?.domain_provisioning?.dns_records || []).some((rec) => rec.apex),
);
const apexHint = computed(() => {
  if (!isApexDomain.value) return "";
  const usingA = (editing.value?.domain_provisioning?.dns_records || []).some((rec) => rec.apex && (rec.type === "A" || rec.type === "AAAA"));
  if (usingA) return "Your root domain uses plain A/AAAA records below — these work on any provider, including Route 53.";
  const byProvider = {
    cloudflare: "At the root (@), add a CNAME to the target below — Cloudflare flattens it automatically at the apex.",
    route53: "Route 53 can't point a root domain at an external host like ours. Use a subdomain (e.g. www) for now, or move DNS to a provider with ANAME/ALIAS support — full Route 53 apex support is coming.",
    godaddy: "Use GoDaddy's forwarding/root options or a provider with ANAME/ALIAS. A plain CNAME won't work at the root.",
    namecheap: "Namecheap doesn't support ALIAS at the root — use a subdomain (e.g. www) for now, or a provider with ANAME/ALIAS.",
  };
  return byProvider[dnsProvider.value] || "At the root (@), add an ALIAS or ANAME record to the target below. A plain CNAME won't work at the apex.";
});

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = text;
    setTimeout(() => { if (copied.value === text) copied.value = ""; }, 1500);
  } catch { /* clipboard unavailable */ }
}
const DOMAIN_STATUS_LABELS = { active: "Connected & verified", pending_dns: "Waiting for DNS", pending_ssl: "Issuing certificate", failed: "Verification failed" };
const siteHasHomepage = computed(() => !!(editing.value?.pages || {})["/"]);
const domainStatusLabel = computed(() => {
  if (editing.value?.hosting?.verification?.verified) return "Connected & verified";
  return DOMAIN_STATUS_LABELS[editing.value?.domain_provisioning?.status] || "Pending verification";
});

async function connectDomain() {
  domainError.value = "";
  domainBusy.value = true;
  try {
    editing.value = await store.connectDomain(editing.value.site_id, domainForm.domain, domainForm.homepage);
    domainForm.domain = "";
    domainForm.homepage = "";
  } catch (error) {
    domainError.value = error.message || "Failed to connect domain.";
  } finally {
    domainBusy.value = false;
  }
}

async function checkDomain() {
  domainError.value = "";
  domainBusy.value = true;
  try {
    const { site, status, hint, diagnostics } = await store.checkDomain(editing.value.site_id);
    editing.value = site;
    domainDiagnostics.value = Object.fromEntries((diagnostics || []).map((d) => [d.name, d]));
    if (status !== "active") domainError.value = hint || "Not verified yet — DNS changes can take a while to propagate. Try again shortly.";
  } catch (error) {
    domainError.value = error.message || "Failed to verify domain.";
  } finally {
    domainBusy.value = false;
  }
}

async function disconnectDomain() {
  domainError.value = "";
  domainBusy.value = true;
  try {
    editing.value = await store.disconnectDomain(editing.value.site_id);
  } catch (error) {
    domainError.value = error.message || "Failed to disconnect domain.";
  } finally {
    domainBusy.value = false;
  }
}

const orgPhoneError = computed(() => phoneError(form.org.telephone));
const canCreate = computed(() => !store.saving && createCheck.state.available);
const canSaveEdit = computed(() => !store.saving && editCheck.state.available && !orgPhoneError.value);

async function loadPages() {
  try {
    const body = await apiRequest("/pages");
    pages.value = Array.isArray(body.pages) ? body.pages : [];
  } catch {
    pages.value = [];
  }
}

async function reload() {
  await Promise.all([store.load(), loadPages()]);
}

function pickCreate(value) {
  createSubdomain.value = value;
  createCheck.check(value);
}

function pickEdit(value) {
  form.subdomain = value;
  editCheck.check(value, editing.value?.site_id);
}

async function createDefault() {
  formError.value = "";
  try {
    await store.createDefault(pages.value, profileStore.business, createCheck.state.normalized || createSubdomain.value);
  } catch (error) {
    formError.value = error.message || "Failed to create site.";
  }
}

function openEdit(site) {
  editing.value = site;
  domainError.value = "";
  domainDiagnostics.value = {};
  domainForm.domain = "";
  domainForm.homepage = "";
  const org = site.organization || {};
  const address = org.address || {};
  form.name = site.name || "";
  form.subdomain = (site.hosting?.platform_hostname || "").split(".")[0] || "";
  form.org = {
    name: org.name || "", legal_name: org.legal_name || "", entity_type: org.entity_type || "OnlineStore",
    description: org.description || "", telephone: org.telephone || "", email: org.email || "",
    address: { locality: address.locality || "", region: address.region || "", street: address.street || "", postal_code: address.postal_code || "", country: address.country || "US" },
  };
  const seo = site.seo || {};
  form.seo = { google_site_verification: seo.google_site_verification || "", bing_site_verification: seo.bing_site_verification || "" };
  editCheck.check(form.subdomain, site.site_id);
}

async function saveEdit() {
  formError.value = "";
  const organization = {
    ...editing.value.organization,
    name: form.org.name || undefined,
    legal_name: form.org.legal_name || undefined,
    entity_type: form.org.entity_type || undefined,
    description: form.org.description || undefined,
    telephone: form.org.telephone ? normalizeE164(form.org.telephone) : undefined,
    email: form.org.email || undefined,
    address: Object.fromEntries(Object.entries(form.org.address).filter(([, v]) => v)),
  };
  // Preserve any existing seo fields (title_suffix, indexnow_key) and overlay the editable verification tokens.
  const seo = Object.fromEntries(Object.entries({
    ...editing.value.seo,
    google_site_verification: form.seo.google_site_verification || undefined,
    bing_site_verification: form.seo.bing_site_verification || undefined,
  }).filter(([, v]) => v !== undefined && v !== ""));
  const doc = {
    ...editing.value,
    name: form.name || editing.value.name,
    hosting: { ...editing.value.hosting, platform_subdomain: form.subdomain || undefined },
    organization: Object.fromEntries(Object.entries(organization).filter(([, v]) => v !== undefined && !(typeof v === "object" && !Object.keys(v).length))),
    seo: Object.keys(seo).length ? seo : undefined,
  };
  if (!doc.seo) delete doc.seo;
  try {
    await store.save(doc);
    editing.value = null;
  } catch (error) {
    formError.value = error.message || "Failed to save site.";
  }
}

function availabilityText(state) {
  if (!state.input) return "";
  if (state.checking) return "Checking availability…";
  if (!state.checked) return "";
  if (state.available) return `✓ ${state.hostname} is available`;
  return `✗ ${state.reason}`;
}
function availabilityClass(state) {
  if (state.checking || !state.checked || !state.input) return "field-note";
  return state.available ? "subdomain-ok" : "subdomain-bad";
}

function canonicalHost(site) {
  return site.hosting?.type === "custom" && site.hosting?.custom_domain ? site.hosting.custom_domain : site.hosting?.platform_hostname;
}
const ELIGIBILITY_LABELS = { eligible: "Indexed", pending: "Indexing pending", blocked: "Not indexed", revoked: "Indexing revoked" };
function indexLabel(site) {
  return ELIGIBILITY_LABELS[site.indexing?.eligibility] || "Not indexed";
}
function indexClass(site) {
  return site.indexing?.eligibility === "eligible" ? "active" : "archived";
}
function indexReason(site) {
  const state = site.indexing?.eligibility;
  if (state === "eligible") return "This Site is eligible for search indexing.";
  if (state === "revoked") return "Indexing was revoked because your Stripe account is restricted. Resolve it in Stripe to restore eligibility.";
  if (state === "pending") return "Almost there — search indexing needs both a verified custom domain and a verified Stripe Connect account.";
  return "Search indexing requires a verified custom domain and a verified Stripe Connect account. On the free address a Site is never indexed.";
}

onMounted(async () => {
  await profileStore.ensureLoaded();
  await reload();
  if (store.loaded && !store.sites.length && !createSubdomain.value) {
    createSubdomain.value = suggestSubdomain(profileStore.business);
    if (createSubdomain.value) createCheck.check(createSubdomain.value);
  }
});
</script>

<style scoped>
/* All colors come from the app's theme tokens (--panel/--bg/--text/--line/--accent), which flip under
   .theme-live for the dark (Live) theme — never hardcode a surface color. */
.homepage-picker {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.homepage-picker select {
  flex: 1 1 12rem;
}
.homepage-picker .attach-slug {
  flex: 0 1 10rem;
}
.subdomain-input {
  display: flex;
  align-items: stretch;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  overflow: hidden;
}
.subdomain-input input {
  border: none;
  border-radius: 0;
  flex: 1 1 auto;
  min-width: 0;
}
.subdomain-input input:focus {
  outline: none;
}
.subdomain-input:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.subdomain-suffix {
  display: flex;
  align-items: center;
  padding: 0 0.75rem;
  background: var(--bg);
  color: var(--muted);
  font-family: ui-monospace, monospace;
  white-space: nowrap;
}
.subdomain-suggestions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.35rem;
}
.subdomain-chip {
  border: 1px solid var(--line-strong);
  background: var(--bg);
  color: var(--text);
  border-radius: 999px;
  padding: 0.15rem 0.7rem;
  font-family: ui-monospace, monospace;
  font-size: 0.85em;
  cursor: pointer;
}
.subdomain-chip:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.dns-provider-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin: 0.3rem 0 0.6rem;
  font-size: 1.3rem;
  font-weight: 600;
}
.dns-provider-row select {
  flex: 0 0 auto;
  width: auto;
  padding: 0.3rem 0.6rem;
}
.dns-accordion {
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  overflow: hidden;
}
.dns-step + .dns-step {
  border-top: 1px solid var(--line-strong);
}
.dns-step-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.7rem 0.9rem;
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
  font-size: 1.35rem;
  color: var(--text);
}
.dns-step-header:hover { background: var(--accent-soft); }
.dns-step-title { font-weight: 600; flex: 1 1 auto; }
.dns-step-status { font-size: 1.2rem; color: var(--muted); }
.dns-chevron { color: var(--muted); }
.dns-badge {
  width: 1.7rem; height: 1.7rem; border-radius: 999px; flex: 0 0 auto;
  display: inline-flex; align-items: center; justify-content: center; font-size: 1.1rem; font-weight: 700;
}
.dns-badge.ok { background: #dcfce7; color: #15803d; }
.dns-badge.bad { background: #fee2e2; color: #b91c1c; }
.dns-badge.idle { background: var(--line); color: var(--muted); }
.dns-step-status.ok { color: #22c55e; }
.dns-step-status.bad { color: #f87171; }
.dns-step-body {
  display: none;
  padding: 0.2rem 0.9rem 0.9rem;
  background: var(--bg);
}
.dns-step.open .dns-step-body { display: block; }
.dns-field {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.4rem;
}
.dns-field-label {
  flex: 0 0 3.6rem;
  font-size: 1.1rem;
  text-transform: uppercase;
  font-weight: 700;
  color: var(--muted);
}
.dns-field code {
  flex: 1 1 auto;
  font-family: ui-monospace, monospace;
  background: var(--panel);
  color: var(--text);
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  padding: 0.35rem 0.6rem;
  word-break: break-all;
  font-size: 1.25rem;
}
.copy-btn {
  flex: 0 0 auto;
  background: none;
  border: none;
  color: var(--accent);
  font-weight: 600;
  cursor: pointer;
  font-size: 1.2rem;
}
.copy-btn:hover { text-decoration: underline; }
.subdomain-ok {
  color: #22c55e;
  font-weight: 600;
}
.subdomain-bad {
  color: #f87171;
  font-weight: 600;
}
</style>
