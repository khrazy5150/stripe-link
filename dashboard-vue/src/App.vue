<template>
  <AuthPage v-if="!auth.isAuthenticated" />
  <div
    v-else
    class="app-shell"
    :class="[`theme-${activeEnvironment}`, { 'sidebar-collapsed': sidebarCollapsed }]"
    :key="auth.session?.client_id"
  >
    <aside class="sidebar">
      <div class="brand">
        <img src="https://images.juniorbay.com/icon/favicon.png" alt="" />
        <strong>Admin Panel</strong>
      </div>
      <nav>
        <template v-for="group in menuGroups" :key="group.key">
          <div class="nav-section-title">{{ group.label }}</div>
          <button
            v-for="item in group.items"
            :key="item.key"
            class="nav-item"
            :class="{ active: activeView === item.view }"
            type="button"
            :disabled="!item.enabled"
            @click="activateMenuItem(item)"
          >
            <span class="nav-icon" aria-hidden="true">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" :d="iconPaths[item.icon]" />
              </svg>
            </span>
            <span class="nav-label">{{ item.label }}</span>
          </button>
        </template>
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
        <div class="topbar-actions">
          <span class="environment-pill">{{ environmentLabel }}</span>
          <button
            class="topbar-icon-button environment-toggle-button"
            type="button"
            :aria-label="`Switch to ${activeEnvironment === 'test' ? 'live' : 'test'} environment`"
            @click="toggleEnvironment"
          >
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4.5 6.75h15v10.5h-15V6.75Zm3 3 2.25 2.25L7.5 14.25m4.5 0h4.5" />
            </svg>
          </button>
          <button class="topbar-icon-button notification-button" type="button" aria-label="Notifications">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" :d="iconPaths.bell" />
            </svg>
          </button>
        </div>
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

      <Dashboard
        v-if="activeView === 'dashboard'"
        :environment-label="environmentLabel"
        :active-environment="activeEnvironment"
        @switch-environment="switchEnvironment"
      />
      <StripeKeys v-else-if="activeView === 'stripeKeys'" />
      <Products v-else-if="activeView === 'products'" />
      <Coupons v-else-if="activeView === 'coupons'" />
      <Offers v-else-if="activeView === 'offers'" />
      <LandingPages
        v-else-if="activeView === 'landingPages'"
        :key="`landing-pages-${activeEnvironment}-${auth.session?.client_id || ''}`"
      />
    </main>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import AuthPage from "./components/AuthPage.vue";
import Coupons from "./components/Coupons.vue";
import Dashboard from "./components/Dashboard.vue";
import LandingPages from "./components/LandingPages.vue";
import Offers from "./components/Offers.vue";
import Products from "./components/Products.vue";
import StripeKeys from "./components/StripeKeys.vue";
import { iconPaths, menuGroupsForEnvironment } from "./config/menu";
import { getApiEnvironment, loadAppConfigApiBase, setApiEnvironment } from "./api/client";
import { useAuthStore } from "./stores/auth";
import { useCouponsStore } from "./stores/coupons";
import { useDashboardStore } from "./stores/dashboard";
import { useProductsStore } from "./stores/products";
import { useStripeKeysStore } from "./stores/stripeKeys";

const auth = useAuthStore();
const coupons = useCouponsStore();
const dashboard = useDashboardStore();
const products = useProductsStore();
const stripeKeys = useStripeKeysStore();
const activeView = ref("dashboard");
const activeEnvironment = ref(getApiEnvironment());
const sidebarCollapsed = ref(false);
const userMenuOpen = ref(false);
const userMenuRef = ref(null);
const menuGroups = computed(() => menuGroupsForEnvironment(activeEnvironment.value));
const environmentLabel = computed(() => activeEnvironment.value === "live" ? "Live" : "Test");

function activateMenuItem(item) {
  if (!item.enabled) return;
  activeView.value = item.view;
}

function toggleEnvironment() {
  switchEnvironment(activeEnvironment.value === "test" ? "live" : "test");
}

function switchEnvironment(environment) {
  activeEnvironment.value = environment === "live" ? "live" : "test";
  setApiEnvironment(activeEnvironment.value);
}

async function reloadActiveView() {
  dashboard.reset();
  coupons.reset();
  products.reset();
  stripeKeys.resetForCurrentTenant();
  if (activeView.value === "dashboard") {
    await dashboard.load();
  } else if (activeView.value === "products") {
    await products.load();
  } else if (activeView.value === "stripeKeys") {
    await stripeKeys.load();
  }
}

function handleLogout() {
  userMenuOpen.value = false;
  auth.logout();
}

function handleDocumentClick(event) {
  if (!userMenuRef.value?.contains(event.target)) userMenuOpen.value = false;
}

function handleKeydown(event) {
  if (event.key === "Escape") {
    userMenuOpen.value = false;
  }
}

onMounted(() => {
  document.addEventListener("click", handleDocumentClick);
  document.addEventListener("keydown", handleKeydown);
  loadAppConfigApiBase(activeEnvironment.value).then(reloadActiveView).catch(() => {});
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
    coupons.reset();
    products.reset();
    stripeKeys.resetForCurrentTenant();
    activeView.value = "dashboard";
    userMenuOpen.value = false;
  },
);

watch(activeEnvironment, async () => {
  const visibleItems = menuGroups.value.flatMap((group) => group.items);
  if (!visibleItems.some((item) => item.view === activeView.value)) {
    activeView.value = "dashboard";
  }
  await loadAppConfigApiBase(activeEnvironment.value);
  await reloadActiveView();
});
</script>
