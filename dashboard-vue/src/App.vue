<template>
  <AuthPage v-if="!auth.isAuthenticated" />
  <div v-else class="app-shell" :class="{ 'sidebar-collapsed': sidebarCollapsed }" :key="auth.session?.client_id">
    <aside class="sidebar">
      <div class="brand">
        <img src="https://images.juniorbay.com/icon/favicon.png" alt="" />
        <strong>Admin Panel</strong>
      </div>
      <nav>
        <div class="nav-section-title">Main</div>
        <button
          class="nav-item"
          :class="{ active: activeView === 'dashboard' }"
          type="button"
          @click="activeView = 'dashboard'"
        >
          <span class="nav-icon" aria-hidden="true">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0 7-7 7 7M5 10v10a1 1 0 0 0 1 1h3m10-11 2 2m-2-2v10a1 1 0 0 1-1 1h-3m-6 0a1 1 0 0 0 1-1v-4a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v4a1 1 0 0 0 1 1m-6 0h6" />
            </svg>
          </span>
          <span class="nav-label">Dashboard</span>
        </button>
        <button
          class="nav-item"
          :class="{ active: activeView === 'stripeKeys' }"
          type="button"
          @click="activeView = 'stripeKeys'"
        >
          <span class="nav-icon" aria-hidden="true">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 0 1 2 2m4 0a6 6 0 0 1-7.743 5.743L11 17H9v2H7v2H4a1 1 0 0 1-1-1v-2.586a1 1 0 0 1 .293-.707l5.964-5.964A6 6 0 1 1 21 9z" />
            </svg>
          </span>
          <span class="nav-label">Stripe Keys</span>
        </button>
        <div class="nav-section-title">Catalog</div>
        <button
          class="nav-item"
          :class="{ active: activeView === 'products' }"
          type="button"
          @click="activeView = 'products'"
        >
          <span class="nav-icon" aria-hidden="true">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m21 7.5-9-4.5-9 4.5 9 4.5 9-4.5Zm0 0v9l-9 4.5m0-9v9m0-9-9-4.5m0 0v9l9 4.5" />
            </svg>
          </span>
          <span class="nav-label">Products</span>
        </button>
        <button class="nav-item" type="button" disabled>
          <span class="nav-icon" aria-hidden="true">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 12v7.5A1.5 1.5 0 0 1 18.5 21h-13A1.5 1.5 0 0 1 4 19.5V12m16 0H4m16 0h-4.5A3.5 3.5 0 0 0 19 8.5 2.5 2.5 0 0 0 14.5 7L12 12m-8 0h4.5A3.5 3.5 0 0 1 5 8.5 2.5 2.5 0 0 1 9.5 7L12 12m0 0v9" />
            </svg>
          </span>
          <span class="nav-label">Offers</span>
        </button>
        <button class="nav-item" type="button" disabled>
          <span class="nav-icon" aria-hidden="true">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5.25 18.75c4.75-.25 8.75-2.5 12-6.75m0 0 1.5 1.5m-1.5-1.5-1.5-1.5M6.75 14.25 4.5 19.5l5.25-2.25M12 3.75c3.5 1.25 6.25 4 7.5 7.5-4.75.5-8.25-1-10.5-4.5A10 10 0 0 1 12 3.75Z" />
            </svg>
          </span>
          <span class="nav-label">Landing Pages</span>
        </button>
        <button class="nav-item" type="button" disabled>
          <span class="nav-icon" aria-hidden="true">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 3.75v3m8-3v3M4.5 9.75h15m-13.5-3h12A1.5 1.5 0 0 1 19.5 8.25v10.5A1.5 1.5 0 0 1 18 20.25H6a1.5 1.5 0 0 1-1.5-1.5V8.25A1.5 1.5 0 0 1 6 6.75Zm4.5 8.25 1.5 1.5 3-4" />
            </svg>
          </span>
          <span class="nav-label">Services</span>
        </button>
        <div class="nav-section-title">Orders</div>
        <button class="nav-item" type="button" disabled>
          <span class="nav-icon" aria-hidden="true">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.25 6.75h7.5M8.25 11.25h7.5M8.25 15.75h4.5M7.5 3.75h9A1.5 1.5 0 0 1 18 5.25v13.5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 18.75V5.25a1.5 1.5 0 0 1 1.5-1.5Z" />
            </svg>
          </span>
          <span class="nav-label">Orders</span>
        </button>
        <button class="nav-item" type="button" disabled>
          <span class="nav-icon" aria-hidden="true">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.5 18a2.5 2.5 0 0 1-5 0m9-3H5.5l1.25-2.25V9a5.25 5.25 0 0 1 10.5 0v3.75L18.5 15Z" />
            </svg>
          </span>
          <span class="nav-label">Notifications</span>
        </button>
        <button class="nav-item" type="button" disabled>
          <span class="nav-icon" aria-hidden="true">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7.5 3.75h9A1.5 1.5 0 0 1 18 5.25v15l-3-1.5-3 1.5-3-1.5-3 1.5v-15a1.5 1.5 0 0 1 1.5-1.5Zm2.25 5.25h4.5m-4.5 3h4.5m-4.5 3h3" />
            </svg>
          </span>
          <span class="nav-label">Invoices</span>
        </button>
        <button class="nav-item" type="button" disabled>
          <span class="nav-icon" aria-hidden="true">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3.75 7.5h10.5v9H3.75v-9Zm10.5 3h3.25l2.75 3v3h-6v-6Zm-7.5 8.25a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Zm10.5 0a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z" />
            </svg>
          </span>
          <span class="nav-label">Shipping</span>
        </button>
        <button class="nav-item" type="button" disabled>
          <span class="nav-icon" aria-hidden="true">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.25 11.25a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.5 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM3.75 19.5a4.5 4.5 0 0 1 9 0m-1.5 0a4.5 4.5 0 0 1 9 0" />
            </svg>
          </span>
          <span class="nav-label">Customers</span>
        </button>
        <div class="nav-section-title">Settings</div>
        <button class="nav-item" type="button" disabled>
          <span class="nav-icon" aria-hidden="true">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.5 6h3m-5.25 4.5h7.5m-6 4.5h4.5m-2.25 5.25a8.25 8.25 0 1 0 0-16.5 8.25 8.25 0 0 0 0 16.5Z" />
            </svg>
          </span>
          <span class="nav-label">Configuration</span>
        </button>
      </nav>
    </aside>

    <main>
      <header class="topbar">
        <button
          class="menu-button"
          type="button"
          :aria-label="sidebarCollapsed ? 'Expand side menu' : 'Collapse side menu'"
          :aria-pressed="sidebarCollapsed"
          @click="sidebarCollapsed = !sidebarCollapsed"
        >
          <span></span><span></span><span></span>
        </button>
        <div class="user-menu" ref="userMenuRef">
          <button
            class="user-pill"
            type="button"
            :aria-expanded="userMenuOpen"
            aria-haspopup="menu"
            @click="userMenuOpen = !userMenuOpen"
          >
            <span>{{ auth.initials }}</span>
            <div>
              <strong>{{ auth.displayName }}</strong>
              <small>user</small>
            </div>
          </button>
          <div v-if="userMenuOpen" class="user-dropdown" role="menu">
            <button class="user-dropdown-item" type="button" role="menuitem" disabled>
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.75 7.5a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.5 20.25a7.5 7.5 0 0 1 15 0" />
              </svg>
              Profile
            </button>
            <button class="user-dropdown-item" type="button" role="menuitem" disabled>
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 4.5v15m12-15v15M9 8.25H3m18 7.5h-6M9 15.75a3 3 0 1 0-6 0 3 3 0 0 0 6 0Zm12-7.5a3 3 0 1 0-6 0 3 3 0 0 0 6 0Z" />
              </svg>
              Preferences
            </button>
            <button class="user-dropdown-item" type="button" role="menuitem" disabled>
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7.5 3.75h6.75L18 7.5v12.75H7.5A1.5 1.5 0 0 1 6 18.75V5.25a1.5 1.5 0 0 1 1.5-1.5Zm6.75 0V7.5H18M9 11.25h6M9 14.25h6M9 17.25h3" />
              </svg>
              Reports
            </button>
            <button class="user-dropdown-item signout-item" type="button" role="menuitem" @click="handleLogout">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6A2.25 2.25 0 0 0 5.25 5.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15M12 12h8.25m0 0-3-3m3 3-3 3" />
              </svg>
              Sign Out
            </button>
          </div>
        </div>
      </header>

      <Dashboard v-if="activeView === 'dashboard'" />
      <StripeKeys v-else-if="activeView === 'stripeKeys'" />
      <Products v-else-if="activeView === 'products'" />
    </main>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import AuthPage from "./components/AuthPage.vue";
import Dashboard from "./components/Dashboard.vue";
import Products from "./components/Products.vue";
import StripeKeys from "./components/StripeKeys.vue";
import { useAuthStore } from "./stores/auth";
import { useDashboardStore } from "./stores/dashboard";
import { useProductsStore } from "./stores/products";
import { useStripeKeysStore } from "./stores/stripeKeys";

const auth = useAuthStore();
const dashboard = useDashboardStore();
const products = useProductsStore();
const stripeKeys = useStripeKeysStore();
const activeView = ref("dashboard");
const sidebarCollapsed = ref(false);
const userMenuOpen = ref(false);
const userMenuRef = ref(null);

function handleLogout() {
  userMenuOpen.value = false;
  auth.logout();
}

function handleDocumentClick(event) {
  if (!userMenuRef.value?.contains(event.target)) userMenuOpen.value = false;
}

function handleKeydown(event) {
  if (event.key === "Escape") userMenuOpen.value = false;
}

onMounted(() => {
  document.addEventListener("click", handleDocumentClick);
  document.addEventListener("keydown", handleKeydown);
});

onBeforeUnmount(() => {
  document.removeEventListener("click", handleDocumentClick);
  document.removeEventListener("keydown", handleKeydown);
});

watch(
  () => auth.session?.client_id || null,
  (clientId, previousClientId) => {
    if (clientId === previousClientId) return;
    dashboard.reset();
    products.reset();
    stripeKeys.resetForCurrentTenant();
    activeView.value = "dashboard";
    userMenuOpen.value = false;
  },
);
</script>
