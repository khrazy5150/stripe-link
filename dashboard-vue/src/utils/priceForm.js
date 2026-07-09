// Shared price-row FORM helpers for the authoring modals (products + services).
// The form model is dollars-in-inputs; buildPriceDocument (stores/pricing.js) serializes to cents.
import { formatMoney } from "../stores/products";
import { netGuaranteedCustomerAmount, platformFeeRate } from "../stores/pricing";

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
  };
}

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
  const unitAmount = price.fee_handling === "net_guaranteed" && tenantAmount
    ? netGuaranteedCustomerAmount(tenantAmount, platformRate)
    : tenantAmount;
  const discount = compareAt > unitAmount ? Math.max(1, Math.round((1 - unitAmount / compareAt) * 100)) : 0;
  const stripeFee = unitAmount > 0 ? Math.ceil(unitAmount * 0.029) + 30 : 0;
  const platformFee = Math.round(unitAmount * platformRate);
  const netPayout = Math.max(0, unitAmount - stripeFee - platformFee);
  return {
    amount: formatMoney(unitAmount, price.currency),
    compareAt: compareAt > unitAmount ? formatMoney(compareAt, price.currency) : "",
    discount,
    note: price.fee_handling === "net_guaranteed" && tenantAmount ? `includes Stripe + ${Math.round(platformRate * 100)}% platform fee` : "",
    youKeep: price.fee_handling !== "net_guaranteed" && tenantAmount ? formatMoney(netPayout, price.currency) : "",
  };
}
