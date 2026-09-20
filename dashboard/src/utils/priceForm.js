// Shared price-row FORM helpers for the authoring modals (products + services).
// The form model is dollars-in-inputs; buildPriceDocument (stores/pricing.js) serializes to cents.
import { formatMoney } from "../stores/products";
import { feeBreakdown, grossedCustomerAmount, platformFeeRate } from "../stores/pricing";

export function priceFormId() {
  return `price-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function defaultPriceForm() {
  return {
    form_id: priceFormId(),
    sales_price: 0,
    regular_price: 0,
    currency: "usd",
    quantity: 1,
    pricing_model: "one_time",
    fee_handling: "standard",
    context: "standard",
    min_amount: 0,
    suggested_amount: 0,
    // Tip jar (pricing_model customer_chooses). presets are CHARGED amounts -- what the buyer taps is what
    // the buyer pays -- exactly as sales_price is for a fixed price under split/net_guaranteed.
    presets: [],
    max_amount: 0,
    allow_custom: true,
    allow_recurring: false,
    allow_one_time: true,
    recurring_interval: "month",
    // A RECURRING price (pricing_model "recurring"). Separate from the tip jar's `recurring_interval` above
    // on purpose: that one is a repeating TIP the buyer opts into, restricted to month/year (§5h), while
    // these are the subscription terms the tenant sets and Stripe stores on the Price itself.
    //
    // No interval is chosen here. "month" would be a plausible wrong answer — the same shape as the bug this
    // fixes — so the field starts empty and the form refuses to save until the tenant says.
    billing_interval: "",
    interval_count: 1,
    trial_enabled: false,
    trial_days: 7,
    // 0 = the free trial Stripe does natively. Anything else is charged once, up front, as its own line.
    trial_price: 0,
  };
}

// Stripe's four, and what the legacy builder offered. The plural is for "every 2 month(s)".
export const BILLING_INTERVALS = [
  ["day", "Daily", "day"],
  ["week", "Weekly", "week"],
  ["month", "Monthly", "month"],
  ["year", "Yearly", "year"],
];

// Stripe will not bill less often than once a year, so the ceiling is real rather than defensive.
export const MAX_INTERVAL_COUNT = { day: 365, week: 52, month: 12, year: 1 };

export function centsToMoneyInput(cents, quantity = 1) {
  return Number((Number(cents || 0) / Math.max(1, Number(quantity || 1)) / 100).toFixed(2));
}

export function priceFormFromDocument(price) {
  const quantity = Math.max(1, Number(price.quantity || 1));
  return {
    ...defaultPriceForm(),
    price_id: price.price_id || "",
    stripe_price_id: price.stripe_price_id || null,
    created_at: price.created_at || null,
    sales_price: centsToMoneyInput(price.tenant_keyed_amount ?? price.unit_amount ?? 0, quantity),
    regular_price: centsToMoneyInput(price.compare_at_unit_amount || 0, quantity),
    currency: price.currency || "usd",
    quantity,
    pricing_model: price.pricing_model || "one_time",
    fee_handling: price.fee_handling || "standard",
    context: price.context || "standard",
    min_amount: centsToMoneyInput(price.min_amount || 0, quantity),
    suggested_amount: centsToMoneyInput(price.suggested_amount || 0, quantity),
    // A legacy suggested_amount becomes the first preset, which is what it always meant -- one amount offered
    // to the buyer. The document keeps its own copy until it is migrated; this is the form's reading of it.
    presets: (Array.isArray(price.presets) && price.presets.length
      ? price.presets
      : [price.suggested_amount].filter(Boolean)
    ).map((amount) => centsToMoneyInput(amount, quantity)),
    max_amount: centsToMoneyInput(price.max_amount || 0, quantity),
    allow_custom: price.allow_custom !== false,
    allow_recurring: Boolean(price.allow_recurring),
    // Absent means yes: every jar saved before the field existed offers both, which is what it already does.
    allow_one_time: price.allow_one_time !== false,
    recurring_interval: price.recurring_interval === "year" ? "year" : "month",
    // Read from the NESTED object, which is the shape Stripe takes and the document stores. Coercing this
    // through the tip's month/year field would turn a weekly subscription into a monthly one on the way in.
    billing_interval: String(price.recurring?.interval || ""),
    interval_count: Math.max(1, Number(price.recurring?.interval_count || 1)),
    trial_enabled: Number(price.trial_period_days || 0) > 0,
    trial_days: Number(price.trial_period_days || 0) || 7,
    trial_price: centsToMoneyInput(price.trial_price || 0),
  };
}

// What ONE keyed amount means under this price's fee mode: what the customer pays, and what is left after
// Stripe's cut and the platform's. Used per preset amount in a tip jar, where "Sales price" alone says
// nothing about who covers the fees -- the point the tenant needs to see before choosing a mode.
// Approximation, like every preview here; /prices/calculate is the authority and runs on save.
export function amountPreviewFor(keyedAmount, price, productType = "digital") {
  const currency = price.currency || "usd";
  const tenantAmount = Math.max(0, Math.round(Number(keyedAmount || 0) * 100));
  const platformRate = platformFeeRate(productType, price.pricing_model);
  const unitAmount = grossedCustomerAmount(tenantAmount, platformRate, price.fee_handling);
  const breakdown = feeBreakdown({
    tenantKeyedAmount: tenantAmount, unitAmount, platformRate, feeHandling: price.fee_handling,
  });
  return {
    unitAmount,
    netPayout: breakdown.net_payout,
    pays: formatMoney(unitAmount, currency),
    keeps: formatMoney(breakdown.net_payout, currency),
  };
}

// Live preview: what the customer is charged, plus "You keep $X" on standard so the
// net-guaranteed benefit is visible. productType drives the platform-fee rate.
export function pricePreviewFor(price, productType = "physical") {
  const quantity = Math.max(1, Number(price.quantity || 1));
  const keyedSource = price.pricing_model === "customer_chooses" && Number(price.suggested_amount || 0) > 0
    ? price.suggested_amount
    : price.sales_price;
  const tenantAmount = Math.max(0, Math.round(Number(keyedSource || 0) * 100)) * quantity;
  const compareAt = Math.max(0, Math.round(Number(price.regular_price || 0) * 100)) * quantity;
  const platformRate = platformFeeRate(productType, price.pricing_model);
  const unitAmount = grossedCustomerAmount(tenantAmount, platformRate, price.fee_handling);
  const discount = compareAt > unitAmount ? Math.max(1, Math.round((1 - unitAmount / compareAt) * 100)) : 0;
  const stripeFee = unitAmount > 0 ? Math.ceil(unitAmount * 0.029) + 30 : 0;
  const platformFee = Math.round(unitAmount * platformRate);
  const netPayout = Math.max(0, unitAmount - stripeFee - platformFee);
  const note = !tenantAmount ? ""
    : price.fee_handling === "net_guaranteed" ? `includes Stripe + ${Math.round(platformRate * 100)}% platform fee`
    : price.fee_handling === "split" ? "includes half the fees — you cover the other half"
    : "";
  return {
    amount: formatMoney(unitAmount, price.currency),
    compareAt: compareAt > unitAmount ? formatMoney(compareAt, price.currency) : "",
    discount,
    note,
    youKeep: price.fee_handling !== "net_guaranteed" && tenantAmount ? formatMoney(netPayout, price.currency) : "",
  };
}

// "/month", " every 3 weeks" — what a SAVED price's amount reads as when it repeats.
//
// Mirrors recurring_suffix() in runtime/html.py, which puts the same words on the published page. The tenant
// half matters on its own: a product can carry both a one-time and a recurring price, and a picker that
// labels them "1 item - $39.00" and "1 item - $32.91" gives no way to tell which one is the subscription.
//
// Tips are excluded for the same reason as the renderer: a repeating tip's frequency is the supporter's
// choice at checkout, not a property of the price.
export function recurringSuffix(price) {
  if (!price || price.pricing_model !== "recurring") return "";
  const recurring = price.recurring;
  if (!recurring || !recurring.interval) return "";
  const interval = String(recurring.interval);
  const count = Number(recurring.interval_count || 1);
  if (!Number.isFinite(count) || count <= 1) return `/${interval}`;
  return ` every ${count} ${interval}s`;
}
