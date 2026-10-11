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
    // WHICH LOADS FAILED. Every fetch below is best-effort so one dead endpoint cannot blank the whole
    // screen -- but "best-effort" was implemented as `.catch(() => [])`, which renders a failed request
    // as a confident zero. A tenant with a thousand products was one network blip from being told they
    // had none, in the same typeface as the truth.
    failed: {},
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

    // Sales and refunds from the SAME source as revenue, so the two cards cannot be computed on
    // different bases. They were: revenue was net of refunds and the order count was not, which is why
    // four orders appeared to produce $1.14 with nothing on screen to explain it.
    //
    // The headline is orders that STAND. The gross count and the refund count are both named underneath,
    // because a refunded order still happened — it had a customer and a product and support — and the
    // card that hides it is the card we just fixed.
    saleCount() {
      return Number(this.ledger?.summary?.counts?.sale ?? 0);
    },

    refundCount() {
      return Number(this.ledger?.summary?.counts?.refund ?? 0);
    },

    refundedCents() {
      return Number(this.ledger?.summary?.refunded ?? 0);
    },

    stats(state) {
      return {
        // The ledger when it answered; the invoice count as the legacy fallback; a dash when NEITHER
        // came back. Without the last clause a dashboard whose every request failed reported a tidy
        // zero orders beside a dash for revenue -- half the screen admitting it did not know and the
        // other half asserting none.
        orders: this.revenueKnown
          ? this.saleCount - this.refundCount
          : (state.failed.invoices ? "—" : state.invoices.length),
        // ONLY the refund clause, or "". The environment label belongs to the component, which is where
        // every other card gets it -- returning it from here duplicated that knowledge and dropped it
        // the moment a tenant had no refunds.
        ordersMeta: this.refundCount
          ? `${this.saleCount} placed · ${this.refundCount} refunded`
          : "",
        revenue: this.revenueKnown ? money(this.revenueCents) : "—",
        // Say which figure this is. Gross, net-of-fees and net-of-fees-and-refunds are three different
        // numbers a tenant cares about, and the old subtitle named a source ("paid invoices") rather
        // than the measure, while the title claimed the one it was not.
        // Name the refunded amount when there is one. It is the figure that turns a baffling headline
        // into an explained one, and it cannot be recovered from `net` by subtraction.
        revenueMeta: !this.revenueKnown
          ? "Could not load the ledger"
          : this.refundedCents
            ? `After fees · less ${money(this.refundedCents)} refunded`
            : "After Stripe and platform fees",
        // A dash, not a zero, when the request did not come back. Same rule as Net Revenue above and
        // the Profit row in Reports: a figure we could not obtain is not the figure zero, and guessing
        // wrong in the flattering direction is no better than guessing wrong in the other one.
        customers: state.failed.customers ? "—" : state.customers.length,
        customersMeta: state.failed.customers ? "Could not load customers" : "",
        products: state.failed.products ? "—" : state.products.length,
        productsMeta: state.failed.products ? "Could not load products" : "",
      };
    },

    // RECENT ORDERS, FROM THE LEDGER -- the same source as the Orders and Net Revenue cards above it.
    // It used to read `state.invoices`, which is the INVOICES module: tenant-issued invoices, a
    // different thing entirely. A tenant with eight orders and no invoices therefore saw an empty table
    // headed "Recent Orders" sitting directly beneath a card reading "Orders 8" (reported 2026-10-11).
    //
    // Same shape of mistake as the revenue card that summed gross while calling itself net: a panel
    // reading a different source than the number it sits under. Three panels, one source, so they
    // cannot disagree.
    recentOrders(state) {
      const entries = (state.ledger?.entries || []).filter((entry) => entry.entry_type === "sale");
      return entries
        .sort((a, b) => Number(b.occurred_at || 0) - Number(a.occurred_at || 0))
        .slice(0, 10)
        .map((entry) => ({
          date: date(entry.occurred_at),
          // A buyer who checked out as a guest has no name on file. "Guest" is what happened; "N/A"
          // reads like something failed to load.
          customer: entry.customer_ref?.name || entry.customer_ref?.email || "Guest",
          // `gross` is what the buyer paid. The fee-netted figure belongs on the revenue card, not on a
          // line that answers "what did this person spend?".
          amount: money(entry.amounts?.gross || 0),
          product: entry.lines?.[0]?.name || entry.description || "Order",
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
        const failed = {};
        // Still best-effort -- one dead endpoint must not blank the dashboard -- but the failure is now
        // REMEMBERED, so the card can say "we could not ask" instead of "the answer is none".
        const attempt = (key, request) => request.catch(() => {
          failed[key] = true;
          return {};
        });
        const [products, customers, invoices, notifications, ledger] = await Promise.all([
          attempt("products", apiRequest("/products")),
          attempt("customers", apiRequest("/customers")),
          attempt("invoices", apiRequest("/invoices")),
          attempt("notifications", apiRequest("/notifications")),
          // The ledger is the only source that nets fees and reverses refunds. Summing orders instead
          // reported $5.80 of revenue on four $1.45 sales, two of them fully refunded, when the true
          // figure was $1.14 (measured 2026-10-09, and it agreed with Stripe to the penny).
          attempt("ledger", apiRequest("/ledger")),
        ]);
        this.failed = failed;

        this.products = products.products || [];
        this.customers = customers.customers || [];
        this.invoices = invoices.invoices || [];
        this.notifications = notifications.notifications || [];
        // `attempt` resolves to {} on failure, so an unreachable ledger must not read as an empty one:
        // `revenueKnown` keys on this being null, and {} would make it a confident $0.00.
        this.ledger = failed.ledger ? null : (ledger || null);
        this.loaded = true;
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
  },
});
