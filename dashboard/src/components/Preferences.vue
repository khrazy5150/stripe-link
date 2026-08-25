<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Preferences</h1>
        <p>Personal dashboard settings for your account</p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="loading" @click="load">
          {{ loading ? "Loading..." : "Reload" }}
        </button>
        <button class="primary-action" type="button" :disabled="saving || loading || !userId" @click="save">
          {{ saving ? "Saving..." : "Save Preferences" }}
        </button>
      </div>
    </header>

    <div v-if="error" class="keys-status-banner error">{{ error }}</div>
    <div v-else-if="message" class="keys-status-banner">{{ message }}</div>

    <section class="dashboard-card">
      <header class="dashboard-card-header"><h2>Appearance & Defaults</h2></header>
      <div class="dashboard-card-body">
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Theme</span>
            <select v-model="form.theme">
              <option value="system">System</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </label>
          <label class="offer-field">
            <span>Default Stripe Mode</span>
            <select v-model="form.default_stripe_mode">
              <option value="test">Test</option>
              <option value="live">Live</option>
            </select>
          </label>
        </div>
        <div class="offer-two-column">
          <label class="offer-field">
            <span>Default Home View</span>
            <select v-model="form.dashboard_home">
              <option value="dashboard">Dashboard</option>
              <option value="products">Products</option>
              <option value="offers">Offers</option>
              <option value="landingPages">Landing Pages</option>
              <option value="orders">Orders</option>
              <option value="customers">Customers</option>
            </select>
          </label>
        </div>
        <label class="checkbox-row">
          <input v-model="form.sidebar_collapsed" type="checkbox" />
          <span>Collapse the side menu by default</span>
        </label>
      </div>
    </section>
  </section>
</template>

<script setup>
import { reactive, ref } from "vue";
import { apiRequest, getAuthSession, getTenantId } from "../api/client";

const session = getAuthSession() || {};
const userId = session.user_id || "";
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");
const rawDoc = ref({});
const form = reactive(defaultForm());

function defaultForm() {
  return { theme: "system", default_stripe_mode: "test", dashboard_home: "dashboard", sidebar_collapsed: false };
}

function applyPreferences(preferences) {
  rawDoc.value = preferences || {};
  form.theme = preferences.theme || "system";
  form.default_stripe_mode = preferences.default_stripe_mode || "test";
  form.dashboard_home = preferences.dashboard_home || "dashboard";
  form.sidebar_collapsed = Boolean(preferences.sidebar_collapsed);
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
    const body = await apiRequest("/preferences", { params: { user_id: userId } });
    applyPreferences(body.preferences || {});
  } catch (err) {
    if (/not found/i.test(err.message)) {
      applyPreferences({});
      message.value = "No preferences saved yet. Choose your settings and save.";
    } else {
      error.value = err.message || "Failed to load preferences.";
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
    // Preserve unmanaged sections (landing_pages.custom_color_themes, authoring_defaults).
    const doc = { ...rawDoc.value };
    doc.schema_version = "2026-05-29";
    doc.document_type = "user_preferences";
    doc.tenant_id = getTenantId();
    doc.user_id = userId;
    doc.theme = form.theme;
    doc.default_stripe_mode = form.default_stripe_mode;
    doc.dashboard_home = form.dashboard_home;
    doc.sidebar_collapsed = form.sidebar_collapsed;
    doc.updated_at = Math.floor(Date.now() / 1000);
    const body = await apiRequest("/preferences", { method: "PUT", body: doc });
    applyPreferences(body.preferences || doc);
    message.value = "Preferences saved.";
  } catch (err) {
    error.value = err.message || "Failed to save preferences.";
  } finally {
    saving.value = false;
  }
}

load();
</script>
