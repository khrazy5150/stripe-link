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
        <img :src="assetUrl('/icon/favicon.png')" alt="" />
        <strong>Junior Bay</strong>
      </div>
      <nav>
        <template v-for="group in menuGroups" :key="group.key">
          <button
            class="nav-section-title"
            type="button"
            :aria-expanded="!isGroupCollapsed(group.key)"
            @click="toggleGroup(group.key)"
          >
            <span>{{ group.label }}</span>
            <svg
              class="nav-section-chevron"
              :class="{ collapsed: isGroupCollapsed(group.key) }"
              fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"
            >
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="m6 9 6 6 6-6" />
            </svg>
          </button>
          <button
            v-for="item in group.items"
            v-show="sidebarCollapsed || !isGroupCollapsed(group.key)"
            :key="item.key"
            class="nav-item"
            :class="{ active: activeView === item.view, locked: item.locked }"
            type="button"
            :disabled="!item.enabled"
            :title="item.locked ? 'Not included in your plan — click to upgrade' : undefined"
            @click="activateMenuItem(item)"
          >
            <span class="nav-icon" aria-hidden="true">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" :d="iconPaths[item.icon]" />
              </svg>
            </span>
            <span class="nav-label">{{ item.label }}</span>
            <svg v-if="item.locked" class="nav-lock" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16.5 10.5V7.5a4.5 4.5 0 1 0-9 0v3m-1.5 0h12a1.5 1.5 0 0 1 1.5 1.5v6a1.5 1.5 0 0 1-1.5 1.5H6a1.5 1.5 0 0 1-1.5-1.5v-6A1.5 1.5 0 0 1 6 10.5Z" />
            </svg>
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
          <span v-if="hasTestSandbox" class="environment-pill">{{ environmentLabel }}</span>
          <button
            v-if="hasTestSandbox"
            class="topbar-icon-button environment-toggle-button"
            type="button"
            :aria-label="`Switch to ${activeEnvironment === 'test' ? 'live' : 'test'} environment`"
            @click="toggleEnvironment"
          >
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4.5 6.75h15v10.5h-15V6.75Zm3 3 2.25 2.25L7.5 14.25m4.5 0h4.5" />
            </svg>
          </button>
          <button
            class="topbar-icon-button notification-button"
            type="button"
            :aria-label="notifications.unreadCount ? `Notifications (${notifications.unreadCount} unread)` : 'Notifications'"
            @click="openNotifications"
          >
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" :d="iconPaths.bell" />
            </svg>
            <span v-if="notifications.badgeLabel" class="notification-badge" aria-hidden="true">{{ notifications.badgeLabel }}</span>
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
            <button class="user-dropdown-item" type="button" role="menuitem" @click="openUserView('profile')">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.75 7.5a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.5 20.25a7.5 7.5 0 0 1 15 0" />
              </svg>
              Profile
            </button>
            <button class="user-dropdown-item" type="button" role="menuitem" @click="openUserView('preferences')">
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

      <!-- Trial / billing wall banner (plans/SAAS_BILLING_PAYWALL.md). Hidden for comped + subscribed tenants. -->
      <div v-if="billingBanner" class="billing-banner" :class="billingBanner.tone">
        <span>{{ billingBanner.text }}</span>
        <button type="button" class="billing-banner-cta" @click="activeView = 'billing'">{{ billingBanner.cta }}</button>
      </div>

      <Dashboard
        v-if="activeView === 'dashboard'"
        :environment-label="environmentLabel"
        :active-environment="activeEnvironment"
        @switch-environment="switchEnvironment"
      />
      <StripeKeys v-else-if="activeView === 'stripeKeys'" :key="`stripe-keys-${activeEnvironment}-${auth.session?.client_id || ''}`" />
      <Products v-else-if="activeView === 'products'" />
      <Coupons v-else-if="activeView === 'coupons'" />
      <Offers v-else-if="activeView === 'offers'" :key="`offers-${activeEnvironment}-${auth.session?.client_id || ''}`" />
      <Services v-else-if="activeView === 'services'" :key="`services-${activeEnvironment}-${auth.session?.client_id || ''}`" />
      <LandingPages
        v-else-if="activeView === 'landingPages'"
        :key="`landing-pages-${activeEnvironment}-${auth.session?.client_id || ''}`"
      />
      <Sites
        v-else-if="activeView === 'sites'"
        :key="`sites-${activeEnvironment}-${auth.session?.client_id || ''}`"
      />
      <Collections
        v-else-if="activeView === 'collections'"
        :key="`collections-${activeEnvironment}-${auth.session?.client_id || ''}`"
      />
      <ABTesting
        v-else-if="activeView === 'abTesting'"
        :key="`ab-testing-${activeEnvironment}-${auth.session?.client_id || ''}`"
      />
      <Configuration
        v-else-if="activeView === 'configuration'"
        :key="`configuration-${activeEnvironment}-${auth.session?.client_id || ''}`"
      />
      <Orders v-else-if="activeView === 'orders'" :key="`orders-${activeEnvironment}-${auth.session?.client_id || ''}`" />
      <Leads v-else-if="activeView === 'leads'" :key="`leads-${activeEnvironment}-${auth.session?.client_id || ''}`" />
      <Reviews v-else-if="activeView === 'reviews'" :key="`reviews-${activeEnvironment}-${auth.session?.client_id || ''}`" />
      <Customers v-else-if="activeView === 'customers'" :key="`customers-${activeEnvironment}-${auth.session?.client_id || ''}`" />
      <Invoices v-else-if="activeView === 'invoices'" :key="`invoices-${activeEnvironment}-${auth.session?.client_id || ''}`" />
      <Refunds v-else-if="activeView === 'refunds'" :key="`refunds-${activeEnvironment}-${auth.session?.client_id || ''}`" />
      <Notifications v-else-if="activeView === 'notifications'" :key="`notifications-${activeEnvironment}-${auth.session?.client_id || ''}`" />
      <Shipping v-else-if="activeView === 'shipping'" :key="`shipping-${activeEnvironment}-${auth.session?.client_id || ''}`" />
      <Billing v-else-if="activeView === 'billing'" :key="`billing-${auth.session?.client_id || ''}`" />
      <Profile v-else-if="activeView === 'profile'" :key="`profile-${auth.session?.user_id || ''}`" />
      <Preferences v-else-if="activeView === 'preferences'" :key="`preferences-${auth.session?.user_id || ''}`" />
    </main>
    <ToastHost @select="onToastSelect" />
    <!-- Branded Stripe-Connect intro: opened by ANY startConnect() entry point (stripeKeys store). -->
    <ConnectIntroModal />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import ABTesting from "./components/ABTesting.vue";
import AuthPage from "./components/AuthPage.vue";
import Billing from "./components/Billing.vue";
import Configuration from "./components/Configuration.vue";
import ConnectIntroModal from "./components/shared/ConnectIntroModal.vue";
import Collections from "./components/Collections.vue";
import Coupons from "./components/Coupons.vue";
import Customers from "./components/Customers.vue";
import Dashboard from "./components/Dashboard.vue";
import Invoices from "./components/Invoices.vue";
import LandingPages from "./components/LandingPages.vue";
import Leads from "./components/Leads.vue";
import Reviews from "./components/Reviews.vue";
import Notifications from "./components/Notifications.vue";
import Offers from "./components/Offers.vue";
import Orders from "./components/Orders.vue";
import Preferences from "./components/Preferences.vue";
import Products from "./components/Products.vue";
import Profile from "./components/Profile.vue";
import Refunds from "./components/Refunds.vue";
import Services from "./components/Services.vue";
import Shipping from "./components/Shipping.vue";
import Sites from "./components/Sites.vue";
import StripeKeys from "./components/StripeKeys.vue";
import ToastHost from "./components/ToastHost.vue";
import { iconPaths, menuGroupsForEnvironment } from "./config/menu";
import { assetUrl, getStripeMode, loadAppConfigApiBase, setStripeMode } from "./api/client";
import { useAuthStore } from "./stores/auth";
import { useCollectionsStore } from "./stores/collections";
import { useCouponsStore } from "./stores/coupons";
import { useDashboardStore } from "./stores/dashboard";
import { useNotificationsStore } from "./stores/notifications";
import { usePlatformBillingStore } from "./stores/platformBilling";
import { useProductsStore } from "./stores/products";
import { useSitesStore } from "./stores/sites";
import { useStripeKeysStore } from "./stores/stripeKeys";
import { useToastsStore } from "./stores/toasts";

const auth = useAuthStore();
const collections = useCollectionsStore();
const coupons = useCouponsStore();
const dashboard = useDashboardStore();
const notifications = useNotificationsStore();
const platformBilling = usePlatformBillingStore();
const products = useProductsStore();
const sites = useSitesStore();
const stripeKeys = useStripeKeysStore();
const toasts = useToastsStore();

// Critical notification types that also pop a transient toast (plans/docs/NOTIFICATION_EMITTERS.md Tier 3).
const TOAST_TYPES = {
  order: { severity: "success", route: "orders", icon: "🎉" },      // 🎉 a sale
  refund_request: { severity: "warning", route: "refunds", sticky: true },
};
// Toast only NEW notifications — baseline the existing backlog on first load / after any reset, no re-toast.
let toastSeen = new Set();
let toastBaselined = false;
let notificationsPoll = null;
const activeView = ref("dashboard");
// The active Stripe MODE (test/live) — the dashboard toggle. Drives view remounts + data reloads and the theme
// class; the backend base is hostname-derived, not this value (plans/STRIPE_MODE_DECOUPLING.md).
const activeEnvironment = ref(getStripeMode());
const sidebarCollapsed = ref(false);
const userMenuOpen = ref(false);

const COLLAPSED_GROUPS_KEY = "jb_sidebar_collapsed_groups";
function loadCollapsedGroups() {
  try {
    const stored = JSON.parse(localStorage.getItem(COLLAPSED_GROUPS_KEY) || "[]");
    return new Set(Array.isArray(stored) ? stored : []);
  } catch {
    return new Set();
  }
}
const collapsedGroups = ref(loadCollapsedGroups());
function isGroupCollapsed(key) {
  return collapsedGroups.value.has(key);
}
function toggleGroup(key) {
  const next = new Set(collapsedGroups.value);
  next.has(key) ? next.delete(key) : next.add(key);
  collapsedGroups.value = next;
  try {
    localStorage.setItem(COLLAPSED_GROUPS_KEY, JSON.stringify([...next]));
  } catch {
    /* localStorage unavailable; collapse state is best-effort */
  }
}
const userMenuRef = ref(null);
// Overlay plan-entitlement gating: a config-enabled feature the tenant's plan doesn't include is shown LOCKED
// (greyed, with a lock) rather than hidden — clicking it routes to Billing to upgrade. During a live trial the
// tenant has all entitlements, so nothing is locked (plans/SAAS_BILLING_PAYWALL.md).
const menuGroups = computed(() =>
  menuGroupsForEnvironment(activeEnvironment.value).map((group) => ({
    ...group,
    items: group.items.map((item) => ({
      ...item,
      locked: item.enabled && platformBilling.loaded && !platformBilling.isViewAllowed(item.view),
    })),
  })),
);
const environmentLabel = computed(() => activeEnvironment.value === "live" ? "Live" : "Test");
// Live-first onboarding: the test/live toggle only appears once the tenant opts into a test sandbox. Until then
// the dashboard is live-only and never strands anyone in a hidden test mode (plans/TODO.md onboarding streamline).
const hasTestSandbox = computed(() => stripeKeys.hasTestSandbox);
function coerceModeIfNoSandbox() {
  if (activeEnvironment.value === "test" && !hasTestSandbox.value) {
    switchEnvironment("live");
  }
}

function activateMenuItem(item) {
  if (!item.enabled) return;
  // A locked (unentitled) feature routes to Billing to upgrade instead of opening the gated screen.
  activeView.value = item.locked ? "billing" : item.view;
}

const billingBanner = computed(() => {
  if (!platformBilling.loaded) return null;
  if (platformBilling.walled) {
    return { tone: "danger", text: "Your account is on hold. Contact support to continue.", cta: "Billing" };
  }
  if (platformBilling.onFreePlan) {
    return {
      tone: "info",
      text: "You're on the Free plan — your pages stay live and you keep selling. Upgrade for premium features and lower fees.",
      cta: "Upgrade",
    };
  }
  if (platformBilling.onTrial) {
    const d = platformBilling.trialDaysLeft;
    return { tone: "info", text: `${d} ${d === 1 ? "day" : "days"} left in your free trial — full access.`, cta: "Choose a plan" };
  }
  return null;
});

function toggleEnvironment() {
  switchEnvironment(activeEnvironment.value === "test" ? "live" : "test");
}

function switchEnvironment(environment) {
  activeEnvironment.value = environment === "live" ? "live" : "test";
  setStripeMode(activeEnvironment.value);
}

async function reloadActiveView() {
  dashboard.reset();
  coupons.reset();
  products.reset();
  sites.reset();  // drop the previous env's sites + hosting domain (.jbay.uk vs .jbay.be) so they repaint
  collections.reset();  // collections are per-env too; drop them so the Collections screen refetches the new env
  stripeKeys.resetForCurrentTenant();
  notifications.reset();
  // Never let one failing/slow fetch abort the whole refresh (a thrown load left the view showing the
  // previous environment's data). Views keyed on activeEnvironment reload themselves via remount.
  const safe = (p) => Promise.resolve(p).catch(() => {});
  safe(notifications.load({ silent: true }));
  // resetForCurrentTenant() above wiped modes.test/live; repopulate them (background) so the toggle-gating flag
  // (hasTestSandbox) stays accurate on any view — otherwise switching mode from a non-Payments view would drop
  // modes to empty and make the toggle disappear mid-use. On the Payments view the awaited load below covers it.
  if (activeView.value !== "stripeKeys") safe(stripeKeys.load());
  if (activeView.value === "dashboard") await safe(dashboard.load());
  else if (activeView.value === "products") await safe(products.load());
  else if (activeView.value === "coupons") await safe(coupons.load({ status: "all" }));
  else if (activeView.value === "stripeKeys") await safe(stripeKeys.load());
  else if (activeView.value === "sites") await safe(sites.load());  // repaints the env's hosting domain immediately
  else if (activeView.value === "collections") await safe(collections.load());
}

function openNotifications() {
  activeView.value = "notifications";
}

function onToastSelect(toast) {
  if (toast.route) activeView.value = toast.route;
  toasts.dismiss(toast.id);
}

// Surface a toast for each newly-arrived unread critical notification. The first load after any reset just
// records the current ids as a baseline so an existing backlog (or an env/tenant switch) never spams toasts.
watch(
  () => notifications.items.map((item) => item.notification_id),
  () => {
    if (!notifications.loaded) return;
    if (!toastBaselined) {
      toastSeen = new Set(notifications.items.map((item) => item.notification_id));
      toastBaselined = true;
      return;
    }
    for (const item of notifications.items) {
      if (toastSeen.has(item.notification_id)) continue;
      toastSeen.add(item.notification_id);
      const config = TOAST_TYPES[item.type];
      if (config && item.status === "unread") {
        toasts.push({
          key: item.notification_id,
          title: item.title || "Notification",
          message: item.message || "",
          severity: config.severity,
          icon: config.icon || "",
          route: config.route,
          sticky: !!config.sticky,
        });
      }
    }
  },
);

// Reset the toast baseline whenever notifications reset (env/tenant switch), so the new context re-baselines.
watch(
  () => notifications.loaded,
  (loaded) => {
    if (!loaded) {
      toastBaselined = false;
      toastSeen = new Set();
    }
  },
);

// One-time "set up Stripe" nudge when the active environment has neither saved keys nor a connected account.
function maybeNudgeStripeSetup() {
  const mode = stripeKeys.modes?.[activeEnvironment.value];
  if (!mode) return;
  const configured = mode.saved_secret_key || mode.connect_status === "connected" || !!mode.connect_account_id;
  if (!configured) {
    toasts.push({
      key: "setup-stripe",
      title: "Finish setting up Stripe",
      message: `Connect Stripe for ${environmentLabel.value} mode to start taking payments.`,
      severity: "info",
      route: "stripeKeys",
      sticky: true,
    });
  }
}

function openUserView(view) {
  userMenuOpen.value = false;
  activeView.value = view;
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
  document.addEventListener("mousedown", handleDocumentClick);
  document.addEventListener("keydown", handleKeydown);
  loadAppConfigApiBase()
    .then(reloadActiveView)
    .then(() => stripeKeys.load())
    .then(coerceModeIfNoSandbox)
    .then(maybeNudgeStripeSetup)
    .catch(() => {});
  platformBilling.load().catch(() => {});
  // Keep the bell badge fresh while the dashboard is open.
  notificationsPoll = window.setInterval(() => {
    if (auth.isAuthenticated) notifications.load({ silent: true });
  }, 60000);
});

onBeforeUnmount(() => {
  document.removeEventListener("mousedown", handleDocumentClick);
  document.removeEventListener("keydown", handleKeydown);
  if (notificationsPoll) window.clearInterval(notificationsPoll);
});

watch(
  () => auth.session?.client_id || null,
  (clientId, previousClientId) => {
    if (clientId === previousClientId) return;
    dashboard.reset();
    coupons.reset();
    products.reset();
    stripeKeys.resetForCurrentTenant();
    // Repopulate Stripe modes for the new tenant so the toggle-gating flag (hasTestSandbox) is correct on the very
    // first (Dashboard) view, then coerce a stale test selection to live for a tenant with no sandbox. This watch
    // fires on login and on async auth resolution — often AFTER onMounted's load — and resetForCurrentTenant() just
    // emptied modes, so without this reload the test/live toggle would stay hidden until the Payments screen is
    // visited even for a tenant that has a sandbox.
    stripeKeys.load().then(coerceModeIfNoSandbox).catch(() => {});
    platformBilling.load().catch(() => {});  // refresh trial/plan/entitlements for the new tenant
    activeView.value = "dashboard";
    userMenuOpen.value = false;
  },
);

watch(activeEnvironment, async () => {
  const visibleItems = menuGroups.value.flatMap((group) => group.items);
  if (!visibleItems.some((item) => item.view === activeView.value)) {
    activeView.value = "dashboard";
  }
  // Bootstrap the per-env API base in the BACKGROUND — a slow or failing app-config fetch must not block the
  // data refresh (that was the bug: the toggle repainted the badge/theme but the awaited bootstrap gated the
  // reload, so the list kept the old environment's data). reloadActiveView falls back to the built-in per-env
  // base, so it's correct without waiting for the bootstrap.
  loadAppConfigApiBase().catch(() => {});
  await reloadActiveView();
});
</script>
