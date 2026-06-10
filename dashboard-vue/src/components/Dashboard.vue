<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1>Dashboard</h1>
        <p>Overview of your business metrics</p>
      </div>
      <button class="secondary-action" type="button" :disabled="store.loading" @click="store.load">
        {{ store.loading ? "Loading..." : "Refresh" }}
      </button>
    </header>

    <div class="stats-grid">
      <article class="stats-card">
        <div class="stats-icon primary" aria-hidden="true">
          <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2" />
          </svg>
        </div>
        <div class="stats-content">
          <span class="stats-label">Total Orders</span>
          <strong class="stats-value">{{ store.loading && !store.loaded ? "--" : store.stats.orders }}</strong>
          <span class="stats-meta">Lifetime &bull; Test</span>
        </div>
      </article>

      <article class="stats-card">
        <div class="stats-icon success" aria-hidden="true">
          <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z" />
          </svg>
        </div>
        <div class="stats-content">
          <span class="stats-label">Net Revenue</span>
          <strong class="stats-value">{{ store.loading && !store.loaded ? "--" : store.stats.revenue }}</strong>
          <span class="stats-meta">{{ store.stats.revenueMeta }}</span>
        </div>
      </article>

      <article class="stats-card">
        <div class="stats-icon warning" aria-hidden="true">
          <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 0 0-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 0 1 5.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 0 1 9.288 0M15 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0zm6 3a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM7 10a2 2 0 1 1-4 0 2 2 0 0 1 4 0z" />
          </svg>
        </div>
        <div class="stats-content">
          <span class="stats-label">Customers</span>
          <strong class="stats-value">{{ store.loading && !store.loaded ? "--" : store.stats.customers }}</strong>
          <span class="stats-meta">Lifetime &bull; Test</span>
        </div>
      </article>

      <article class="stats-card">
        <div class="stats-icon danger" aria-hidden="true">
          <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m20 7-8-4-8 4m16 0-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
          </svg>
        </div>
        <div class="stats-content">
          <span class="stats-label">Products</span>
          <strong class="stats-value">{{ store.loading && !store.loaded ? "--" : store.stats.products }}</strong>
          <span class="stats-meta">Lifetime &bull; Test</span>
        </div>
      </article>
    </div>

    <div v-if="store.error" class="keys-status-banner error">{{ store.error }}</div>

    <div class="dashboard-grid">
      <section class="dashboard-card recent-orders-card">
        <header class="dashboard-card-header">
          <h2>Recent Orders</h2>
          <button type="button" class="secondary-action">View All</button>
        </header>
        <div class="dashboard-table">
          <div class="dashboard-table-row table-head">
            <span>Date</span>
            <span>Customer</span>
            <span>Amount</span>
            <span>Product</span>
          </div>
          <div v-if="store.loading && !store.loaded" class="dashboard-table-row muted-row">
            <span>Loading</span><span>Backend</span><span>--</span><span>Fetching invoices</span>
          </div>
          <div v-else-if="!store.recentOrders.length" class="dashboard-table-row muted-row">
            <span>No invoices</span><span>Backend returned 0</span><span>--</span><span>Create invoices to populate this table</span>
          </div>
          <div v-for="order in store.recentOrders" :key="`${order.date}-${order.product}-${order.amount}`" class="dashboard-table-row">
            <span>{{ order.date }}</span>
            <span>{{ order.customer }}</span>
            <span>{{ order.amount }}</span>
            <span>{{ order.product }}</span>
          </div>
        </div>
      </section>

      <section class="dashboard-card activity-card">
        <header class="dashboard-card-header">
          <h2>Recent Activity</h2>
          <span class="activity-notification-dot" aria-hidden="true"></span>
        </header>
        <div class="activity-list">
          <article v-if="store.loading && !store.loaded" class="activity-item">
            <span class="activity-dot" aria-hidden="true"></span>
            <div><strong>Loading activity...</strong><span>Fetching notifications</span></div>
          </article>
          <article v-else-if="!store.recentActivity.length" class="activity-item">
            <span class="activity-dot" aria-hidden="true"></span>
            <div><strong>No recent activity</strong><span>Notifications endpoint returned 0 items</span></div>
          </article>
          <article v-for="activity in store.recentActivity" :key="`${activity.title}-${activity.time}`" class="activity-item">
            <span class="activity-dot" aria-hidden="true"></span>
            <div><strong>{{ activity.title }}</strong><span>{{ activity.time }}</span></div>
          </article>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import { onMounted } from "vue";
import { useDashboardStore } from "../stores/dashboard";

const store = useDashboardStore();

onMounted(() => {
  if (!store.loaded) store.load();
});
</script>
