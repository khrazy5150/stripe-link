// Shared price-document builders for the authoring modals (products AND services).
// Both catalog entities own a canonical prices[] on the shared Price primitive, so the
// serialization + fee math lives here once. Services route to the "digital" fee class
// (matching the backend's fee_class_for), so pass productType "service".

import { apiRequest } from "../api/client";

export function priceLocalId(prefix = "price") {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
  const cryptoApi = globalThis.crypto;
  const bytes = cryptoApi?.getRandomValues ? cryptoApi.getRandomValues(new Uint8Array(11)) : null;
  const suffix = Array.from({ length: 11 }, (_, index) => alphabet[(bytes ? bytes[index] : Math.floor(Math.random() * 62)) % alphabet.length]).join("");
  return `${prefix}_${suffix}`;
}

export function cents(value) {
  return Math.max(0, Math.round(Number(value || 0) * 100));
}

// Services share the digital fee tier (see backend fee_class_for: service -> digital).
export function platformFeeRate(productType, pricingModel) {
  if (pricingModel === "customer_chooses") return 0.05;
  return productType === "digital" || productType === "service" ? 0.15 : 0.10;
}

export function netGuaranteedCustomerAmount(netAmount, platformRate) {
  if (!netAmount) return 0;
  const stripePercentFee = 0.029;
  const stripeFixedFeeCents = 30;
  const variableRate = stripePercentFee + platformRate;
  return Math.ceil((netAmount + stripeFixedFeeCents) / (1 - variableRate));
}

export function feeBreakdown({ tenantKeyedAmount, unitAmount, platformRate, feeHandling }) {
  const stripeFee = Math.ceil(unitAmount * 0.029 + 30);
  if (feeHandling !== "net_guaranteed") {
    const platformFee = Math.ceil(unitAmount * platformRate);
    return {
      tenant_keyed_amount: tenantKeyedAmount,
      stripe_fee: stripeFee,
      platform_fee: platformFee,
      net_payout: Math.max(0, unitAmount - stripeFee - platformFee),
    };
  }
  const platformFee = Math.max(0, unitAmount - tenantKeyedAmount - stripeFee);
  return {
    tenant_keyed_amount: tenantKeyedAmount,
    stripe_fee: stripeFee,
    platform_fee: platformFee,
    net_payout: tenantKeyedAmount,
  };
}

function priceTenantKeyedAmount(priceForm, quantity) {
  if ((priceForm.pricing_model || "one_time") === "customer_chooses") {
    return (cents(priceForm.suggested_amount) || cents(priceForm.sales_price)) * quantity;
  }
  return cents(priceForm.sales_price) * quantity;
}

async function calculatePriceWithFallback({ tenantKeyedAmount, currency, productType, pricingModel, feeHandling, platformRate }) {
  try {
    const result = await apiRequest("/prices/calculate", {
      method: "POST",
      body: {
        tenant_keyed_amount: tenantKeyedAmount,
        currency: String(currency || "usd").toLowerCase(),
        product_type: productType,
        pricing_model: pricingModel,
        fee_handling: feeHandling,
        tenant_plan: "basic",
        stripe_fee_type: "domestic_card",
      },
    });
    if (Number.isFinite(Number(result.unit_amount)) && result.breakdown) {
      return { unit_amount: Number(result.unit_amount), breakdown: result.breakdown };
    }
  } catch {
    // Keep the authoring modal usable offline; persisted saves still pass server validation.
  }
  const unitAmount = feeHandling === "net_guaranteed"
    ? netGuaranteedCustomerAmount(tenantKeyedAmount, platformRate)
    : tenantKeyedAmount;
  return { unit_amount: unitAmount, breakdown: feeBreakdown({ tenantKeyedAmount, unitAmount, platformRate, feeHandling }) };
}

export async function buildPriceDocument(priceForm, productType, now) {
  const pricingModel = priceForm.pricing_model || "one_time";
  const feeHandling = priceForm.fee_handling || "standard";
  const quantity = Math.max(1, Math.round(Number(priceForm.quantity || 1)));
  const tenantKeyedAmount = priceTenantKeyedAmount(priceForm, quantity);
  const platformRate = platformFeeRate(productType, pricingModel);
  const calculation = await calculatePriceWithFallback({
    tenantKeyedAmount, currency: priceForm.currency, productType, pricingModel, feeHandling, platformRate,
  });
  const price = {
    price_id: priceForm.price_id || priceLocalId(),
    stripe_price_id: priceForm.stripe_price_id || null,
    currency: String(priceForm.currency || "usd").toLowerCase(),
    quantity,
    pricing_model: pricingModel,
    fee_handling: feeHandling,
    context: priceForm.context || "standard",
    tenant_keyed_amount: tenantKeyedAmount,
    fee_breakdown: calculation.breakdown,
    unit_amount: calculation.unit_amount,
    compare_at_unit_amount: cents(priceForm.regular_price) * quantity,
    created_at: priceForm.created_at || now,
    updated_at: now,
  };
  if (pricingModel === "customer_chooses") {
    price.min_amount = cents(priceForm.min_amount);
    price.suggested_amount = cents(priceForm.suggested_amount);
  }
  return price;
}

export function freeLeadPrice(priceId, now) {
  return {
    price_id: priceId, stripe_price_id: null, currency: "usd", quantity: 1,
    pricing_model: "one_time", fee_handling: "standard", context: "standard",
    tenant_keyed_amount: 0,
    fee_breakdown: { tenant_keyed_amount: 0, stripe_fee: 0, platform_fee: 0, net_payout: 0 },
    unit_amount: 0, compare_at_unit_amount: 0, created_at: now, updated_at: now,
  };
}
