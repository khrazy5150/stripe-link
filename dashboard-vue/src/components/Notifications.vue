<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Notifications</h1>
        <p>Operational alerts such as new orders and paid invoices</p>
      </div>
      <div class="button-row">
        <button class="secondary-action" type="button" :disabled="loading" @click="load">
          {{ loading ? "Loading..." : "Reload" }}
        </button>
      </div>
    </header>

    <section class="dashboard-card">
      <div class="product-filter-bar">
        <label>
          Status
          <select v-model="filterStatus">
            <option value="">All</option>
            <option value="unread">Unread</option>
            <option value="read">Read</option>
          </select>
        </label>
      </div>

      <div v-if="error" class="keys-status-banner error">{{ error }}</div>
      <div v-else class="keys-status-banner">{{ message }}</div>

      <div v-if="!visibleNotifications.length" class="product-empty-state">
        {{ loaded ? "No notifications found." : "Loading notifications..." }}
      </div>

      <div v-else class="coupon-card-grid">
        <article v-for="notification in visibleNotifications" :key="notification.notification_id" class="coupon-card">
          <header>
            <div>
              <h3>{{ notification.status === "unread" ? "● " : "" }}{{ notification.title || statusLabel(notification.type) }}</h3>
              <p class="font-mono">{{ statusLabel(notification.type) }}</p>
            </div>
            <span class="product-status">{{ statusLabel(notification.severity || "info") }}</span>
          </header>
          <p class="notification-message">{{ notification.message }}</p>
          <dl class="coupon-detail-list">
            <div><dt>Status</dt><dd>{{ statusLabel(notification.status) }}</dd></div>
            <div><dt>Date</dt><dd>{{ formatDate(notification.created_at) }}</dd></div>
          </dl>
          <div class="product-card-actions">
            <button type="button" class="secondary-action" @click="selected = notification">Details</button>
          </div>
        </article>
      </div>
    </section>

    <div v-if="selected" class="modal-backdrop" @click.self="selected = null">
      <section class="modal-card product-details-modal" role="dialog" aria-modal="true" aria-labelledby="notificationDetailsTitle">
        <header class="modal-card-header">
          <h2 id="notificationDetailsTitle">Notification Details</h2>
          <button type="button" class="modal-close" aria-label="Close notification details" @click="selected = null">×</button>
        </header>
        <div class="product-details-body">
          <dl class="product-details-grid">
            <div><dt>Title</dt><dd>{{ selected.title || "—" }}</dd></div>
            <div><dt>Type</dt><dd>{{ statusLabel(selected.type) }}</dd></div>
            <div><dt>Severity</dt><dd>{{ statusLabel(selected.severity) }}</dd></div>
            <div><dt>Status</dt><dd>{{ statusLabel(selected.status) }}</dd></div>
            <div><dt>Date</dt><dd>{{ formatDate(selected.created_at) }}</dd></div>
          </dl>
          <p class="notification-message">{{ selected.message }}</p>
          <template v-if="relatedEntries(selected).length">
            <h3 class="details-subheading">Related</h3>
            <dl class="product-details-grid">
              <div v-for="[key, value] in relatedEntries(selected)" :key="key">
                <dt>{{ statusLabel(key) }}</dt><dd class="font-mono">{{ value }}</dd>
              </div>
            </dl>
          </template>
          <details class="product-json-details">
            <summary>Raw JSON</summary>
            <pre>{{ JSON.stringify(selected, null, 2) }}</pre>
          </details>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from "vue";
import { apiRequest } from "../api/client";
import { formatEpochDate, statusLabel } from "../utils/format";

const notifications = ref([]);
const loaded = ref(false);
const loading = ref(false);
const error = ref("");
const message = ref("");
const selected = ref(null);
const filterStatus = ref("");

const formatDate = formatEpochDate;

const visibleNotifications = computed(() =>
  filterStatus.value ? notifications.value.filter((item) => item.status === filterStatus.value) : notifications.value,
);

function relatedEntries(notification) {
  return Object.entries(notification.related || {}).filter(([, value]) => value !== undefined && value !== null && value !== "");
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const body = await apiRequest("/notifications");
    notifications.value = Array.isArray(body.notifications) ? body.notifications : [];
    loaded.value = true;
    const unread = notifications.value.filter((item) => item.status === "unread").length;
    message.value = notifications.value.length ? `${notifications.value.length} total · ${unread} unread.` : "";
  } catch (err) {
    error.value = err.message || "Failed to load notifications.";
  } finally {
    loading.value = false;
  }
}

load();
</script>
