<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Leads</h1>
        <p>Contacts captured from your landing page forms.</p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="!store.leads.length" @click="exportCsv">
          Export CSV
        </button>
        <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load()">
          {{ store.loading ? "Loading…" : "Reload" }}
        </button>
      </div>
    </header>

    <section class="dashboard-card">
      <header class="dashboard-card-header">
        <h2>Captured Leads</h2>
        <label class="refunds-filter">
          Status
          <select v-model="store.filterStatus">
            <option value="all">All</option>
            <option v-for="status in statuses" :key="status" :value="status">{{ leadStatusLabel(status) }}</option>
          </select>
        </label>
        <label v-if="sessionOptions.length" class="refunds-filter">
          Session
          <select v-model="store.filterSession">
            <option value="all">All leads</option>
            <option value="registrations">Any registration</option>
            <option v-for="option in sessionOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
      </header>
      <div class="dashboard-card-body">
        <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>
        <div v-else class="keys-status-banner">{{ store.message }}</div>

        <div v-if="!store.filteredLeads.length" class="product-empty-state">
          {{ store.loaded ? "No leads in this view." : "Loading…" }}
        </div>

        <div v-else class="coupon-card-grid">
          <article v-for="lead in store.filteredLeads" :key="lead.lead_id" class="coupon-card">
            <header>
              <div>
                <h3>{{ leadPrimaryContact(lead) }}</h3>
                <p class="font-mono">{{ offerName(lead.offer_id) }}</p>
                <p v-if="sessionLabel(lead)" class="font-mono">{{ sessionLabel(lead) }}</p>
              </div>
              <span class="product-status" :class="leadStatusClass(lead.status)">{{ leadStatusLabel(lead.status) }}</span>
            </header>
            <dl class="coupon-detail-list">
              <div v-if="lead.fields?.email"><dt>Email</dt><dd>{{ lead.fields.email }}</dd></div>
              <div v-if="lead.fields?.phone"><dt>Phone</dt><dd>{{ lead.fields.phone }}</dd></div>
              <div><dt>Captured</dt><dd>{{ formatDate(lead.created_at) }}</dd></div>
              <div v-if="marketingSummary(lead)"><dt>Opt-ins</dt><dd>{{ marketingSummary(lead) }}</dd></div>
            </dl>
            <div class="product-card-actions">
              <label class="offer-field lead-status-select">
                <span>Status</span>
                <select :value="lead.status" :disabled="store.saving === lead.lead_id"
                        @change="store.setStatus(lead, $event.target.value)">
                  <option v-for="status in statuses" :key="status" :value="status">{{ leadStatusLabel(status) }}</option>
                </select>
              </label>
              <button type="button" class="secondary-action compact" @click="selected = lead">View</button>
            </div>
          </article>
        </div>
      </div>
    </section>

    <div v-if="selected" class="modal-backdrop" @click.self="selected = null">
      <section class="modal-card offer-details-modal" role="dialog" aria-modal="true" aria-labelledby="leadTitle">
        <header class="modal-card-header">
          <h2 id="leadTitle">{{ leadPrimaryContact(selected) }}</h2>
          <button type="button" class="modal-close" aria-label="Close lead" @click="selected = null">×</button>
        </header>
        <div class="offer-details-body">
          <h3>Fields</h3>
          <dl class="coupon-detail-list">
            <div v-for="(value, key) in selected.fields" :key="key"><dt>{{ humanize(key) }}</dt><dd>{{ value }}</dd></div>
          </dl>
          <h3>Consent</h3>
          <dl class="coupon-detail-list">
            <div><dt>{{ offerName(selected.offer_id) }} list</dt><dd>{{ consentLabel(selected.consent?.tenant_marketing) }}</dd></div>
            <div><dt>Junior Bay list</dt><dd>{{ consentLabel(selected.consent?.platform_marketing) }}</dd></div>
          </dl>
          <h3>Source</h3>
          <dl class="coupon-detail-list">
            <div><dt>Offer</dt><dd class="font-mono">{{ selected.offer_id || "—" }}</dd></div>
            <div><dt>Page</dt><dd class="font-mono">{{ selected.page_id || "—" }}</dd></div>
            <div><dt>IP</dt><dd class="font-mono">{{ selected.provenance?.ip || "—" }}</dd></div>
            <div><dt>Captured</dt><dd>{{ formatDate(selected.created_at) }}</dd></div>
          </dl>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { apiRequest } from "../api/client";
import { useEventsStore } from "../stores/events";
import { useLeadsStore, LEAD_STATUSES, leadStatusLabel, leadStatusClass, leadPrimaryContact } from "../stores/leads";

const store = useLeadsStore();
// Registrations name their session by id; the titles and times live on the events.
const eventsStore = useEventsStore();
const offers = ref([]);
const selected = ref(null);
const statuses = LEAD_STATUSES;

onMounted(async () => {
  store.load();
  eventsStore.ensureLoaded();
  try {
    const body = await apiRequest("/offers");
    offers.value = Array.isArray(body.offers) ? body.offers : [];
  } catch {
    offers.value = [];
  }
});

function offerName(offerId) {
  return offers.value.find((offer) => offer.offer_id === offerId)?.name || offerId || "—";
}

function humanize(key) {
  return String(key || "").replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatDate(seconds) {
  if (!seconds) return "—";
  return new Date(Number(seconds) * 1000).toLocaleString();
}

function consentLabel(entry) {
  if (!entry || !entry.granted) return "No";
  if (entry.double_opt_in_confirmed === false && entry.granted) return "Pending confirmation";
  return "Yes";
}

function marketingSummary(lead) {
  const opted = [];
  if (lead.consent?.tenant_marketing?.granted) opted.push("Yours");
  if (lead.consent?.platform_marketing?.granted) opted.push("Junior Bay");
  return opted.join(", ");
}

// A registration names its session; an ordinary lead does not, and these all return "" for one.
function eventTitle(lead) {
  if (!lead?.event_id) return "";
  return eventsStore.byId(lead.event_id)?.title || lead.event_id;
}
function sessionWhen(lead) {
  const occurrence = (eventsStore.byId(lead?.event_id)?.occurrences || [])
    .find((row) => row.occurrence_id === lead?.occurrence_id);
  if (!occurrence?.starts_at) return "";
  const options = { weekday: "short", month: "short", day: "numeric",
                    hour: "numeric", minute: "2-digit" };
  if (occurrence.timezone) options.timeZone = occurrence.timezone;
  try {
    return new Date(occurrence.starts_at * 1000).toLocaleString(undefined, options);
  } catch {
    return new Date(occurrence.starts_at * 1000).toLocaleString();
  }
}
function sessionLabel(lead) {
  const title = eventTitle(lead);
  if (!title) return "";
  const when = sessionWhen(lead);
  return when ? `${title} — ${when}` : title;
}
// Only the sessions that actually have registrations: a dropdown listing every sitting a tenant ever ran
// is a filter nobody can find their session in.
const sessionOptions = computed(() => {
  const seen = new Map();
  for (const lead of store.leads) {
    if (!lead.event_id) continue;
    const value = `${lead.event_id}::${lead.occurrence_id || ""}`;
    if (!seen.has(value)) seen.set(value, sessionLabel(lead) || lead.event_id);
  }
  return [...seen].map(([value, label]) => ({ value, label }));
});

function exportCsv() {
  const rows = store.filteredLeads;
  const fieldKeys = [...new Set(rows.flatMap((lead) => Object.keys(lead.fields || {})))];
  // `event` and `session` sit beside the offer: a registrant list is the thing most likely to be exported
  // and handed to whoever is actually running the webinar.
  const headers = ["lead_id", "offer_id", "event", "session", "status", "captured_at",
                   ...fieldKeys, "tenant_optin", "junior_bay_optin"];
  const escape = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const lines = [headers.join(",")];
  for (const lead of rows) {
    const row = [
      lead.lead_id, lead.offer_id, eventTitle(lead), sessionWhen(lead), lead.status, formatDate(lead.created_at),
      ...fieldKeys.map((key) => (lead.fields || {})[key] || ""),
      lead.consent?.tenant_marketing?.granted ? "yes" : "no",
      lead.consent?.platform_marketing?.granted ? "yes" : "no",
    ];
    lines.push(row.map(escape).join(","));
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "leads.csv";
  link.click();
  URL.revokeObjectURL(url);
}
</script>
