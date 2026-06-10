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
  }),

  getters: {
    paidInvoices(state) {
      return state.invoices.filter((invoice) => {
        return invoice.status === "paid" || Number(invoice.amounts?.amount_paid || 0) > 0;
      });
    },

    revenueCents() {
      return this.paidInvoices.reduce((sum, invoice) => {
        return sum + Number(invoice.amounts?.amount_paid || invoice.amounts?.total || 0);
      }, 0);
    },

    stats(state) {
      return {
        orders: state.invoices.length,
        revenue: money(this.revenueCents),
        revenueMeta: this.paidInvoices.length ? "From paid invoices" : "No paid invoices yet",
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
    },

    async load() {
      this.loading = true;
      this.error = "";
      try {
        const [products, customers, invoices, notifications] = await Promise.all([
          apiRequest("/products").catch(() => ({ products: [] })),
          apiRequest("/customers").catch(() => ({ customers: [] })),
          apiRequest("/invoices").catch(() => ({ invoices: [] })),
          apiRequest("/notifications").catch(() => ({ notifications: [] })),
        ]);

        this.products = products.products || [];
        this.customers = customers.customers || [];
        this.invoices = invoices.invoices || [];
        this.notifications = notifications.notifications || [];
        this.loaded = true;
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
  },
});
