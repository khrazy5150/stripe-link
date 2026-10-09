import { defineStore } from "pinia";
import { apiRequest } from "../api/client";

function money(cents, currency = "usd") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency.toUpperCase(),
  }).format(Number(cents || 0) / 100);
}

function date(epochSeconds) {
  if (!epochSeconds) return "N/A";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
  }).format(new Date(Number(epochSeconds) * 1000));
}

export const useDashboardStore = defineStore("dashboard", {
  state: () => ({
    loading: false,
    loaded: false,
    error: "",
    products: [],
    customers: [],
    invoices: [],
    notifications: [],
    ledger: null,
  }),

  getters: {
    // NET of Stripe's fee, the platform fee and every refund — the ledger's own `net`, which is what
    // Stripe's "Net volume" shows and what the tenant's bank balance moves by.
    //
    // This used to sum `amount_paid` across orders, which made it GROSS and blind to refunds. Four
    // $1.45 sales with two refunded read as $5.80 of revenue that no longer existed; the ledger said
    // $1.14 and matched Stripe exactly. The card was labelled "Net Revenue" throughout.
    revenueCents() {
      return Number(this.ledger?.summary?.net ?? 0);
    },

    // Whether the figure above can be trusted. The ledger call is best-effort like every other load
    // here, and a silent 0 would read as "you have made no money" rather than "we could not ask".
    revenueKnown() {
      return Boolean(this.ledger?.summary);
    },

    stats(state) {
      return {
        orders: state.invoices.length,
        revenue: this.revenueKnown ? money(this.revenueCents) : "—",
        // Say which figure this is. Gross, net-of-fees and net-of-fees-and-refunds are three different
        // numbers a tenant cares about, and the old subtitle named a source ("paid invoices") rather
        // than the measure, while the title claimed the one it was not.
        revenueMeta: this.revenueKnown
          ? "After Stripe and platform fees, less refunds"
          : "Could not load the ledger",
        customers: state.customers.length,
        products: state.products.length,
      };
    },

    recentOrders(state) {
      return [...state.invoices]
        .sort((a, b) => Number(b.created_at || 0) - Number(a.created_at || 0))
        .slice(0, 10)
        .map((invoice) => ({
          date: date(invoice.created_at),
          customer: invoice.customer?.name || invoice.customer?.email || "N/A",
          amount: money(invoice.amounts?.total || invoice.amounts?.amount_due || 0),
          product: invoice.line_items?.[0]?.description || invoice.description || invoice.invoice_id || "Invoice",
        }));
    },

    recentActivity(state) {
      return [...state.notifications]
        .sort((a, b) => Number(b.created_at || 0) - Number(a.created_at || 0))
        .slice(0, 5)
        .map((notification) => ({
          title: notification.title || notification.message || notification.type || "Activity",
          time: date(notification.created_at),
        }));
    },
  },

  actions: {
    reset() {
      this.loading = false;
      this.loaded = false;
      this.error = "";
      this.products = [];
      this.customers = [];
      this.invoices = [];
      this.notifications = [];
      this.ledger = null;
    },

    async load() {
      this.loading = true;
      this.error = "";
      try {
        const [products, customers, invoices, notifications, ledger] = await Promise.all([
          apiRequest("/products").catch(() => ({ products: [] })),
          apiRequest("/customers").catch(() => ({ customers: [] })),
          apiRequest("/invoices").catch(() => ({ invoices: [] })),
          apiRequest("/notifications").catch(() => ({ notifications: [] })),
          // The ledger is the only source that nets fees and reverses refunds. Summing orders instead
          // reported $5.80 of revenue on four $1.45 sales, two of them fully refunded, when the true
          // figure was $1.14 (measured 2026-10-09, and it agreed with Stripe to the penny).
          apiRequest("/ledger").catch(() => null),
        ]);

        this.products = products.products || [];
        this.customers = customers.customers || [];
        this.invoices = invoices.invoices || [];
        this.notifications = notifications.notifications || [];
        this.ledger = ledger || null;
        this.loaded = true;
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
  },
});
