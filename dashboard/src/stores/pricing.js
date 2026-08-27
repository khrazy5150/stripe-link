// Shared price-document builders for the authoring modals (products AND services).
// Both catalog entities own a canonical prices[] on the shared Price primitive, so the
// serialization + fee math lives here once. Services route to the "digital" fee class
// (matching the backend's fee_class_for), so pass productType "service".

import { apiRequest } from "../api/client";
import { usePlatformBillingStore } from "./platformBilling";

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

// Fee rates per tier (2026-08-26 pricing pivot — mirror of backend DEFAULT_GLOBAL_BILLING_CONFIG):
// free (basic): physical 5% / service 6% / digital 7% / tip_jar 5%; premium (pro): 2% flat, tips 0%.
// Preview-only — the authoritative calc is server-side (PriceCalculationFunction reads the tenant's live
// tier_id itself). The tenant's tier comes from the billing summary via the platformBilling store.
const TIER_RATES = {
  basic: { physical: 0.05, service: 0.06, digital: 0.07, tip_jar: 0.05 },
  pro: { physical: 0.02, service: 0.02, digital: 0.02, tip_jar: 0 },
};

function tenantTier() {
  try {
    const tier = usePlatformBillingStore().current.tier_id;
    return TIER_RATES[tier] ? tier : "basic";
  } catch {
    return "basic"; // store not ready (e.g. unit context) — free-tier rates are the safe default
  }
}

export function platformFeeRate(productType, pricingModel) {
  const rates = TIER_RATES[tenantTier()];
  if (pricingModel === "customer_chooses") return rates.tip_jar;
  return rates[productType] ?? rates.digital;
}

// fee_handling -> the merchant's share of the fees (mirror of backend MERCHANT_FEE_SHARES).
export const MERCHANT_FEE_SHARES = { standard: 1, split: 0.5, net_guaranteed: 0 };

// Buyer-facing amount for any fee_handling: gross up by the buyer's share of the fees
// (standard = no gross-up, split = half, net_guaranteed = all). Preview/offline fallback only —
// the authoritative calc is the server's /prices/calculate.
export function grossedCustomerAmount(netAmount, platformRate, feeHandling) {
  const merchantShare = MERCHANT_FEE_SHARES[feeHandling] ?? 1;
  if (!netAmount || merchantShare >= 1) return netAmount || 0;
  const buyerShare = 1 - merchantShare;
  const variableRate = (0.029 + platformRate) * buyerShare;
  return Math.ceil((netAmount + buyerShare * 30) / (1 - variableRate));
}

export function netGuaranteedCustomerAmount(netAmount, platformRate) {
  return grossedCustomerAmount(netAmount, platformRate, "net_guaranteed");
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
        tenant_plan: tenantTier(),  // hint only — the server reads the tenant's live tier_id itself
        stripe_fee_type: "domestic_card",
      },
    });
    if (Number.isFinite(Number(result.unit_amount)) && result.breakdown) {
      return { unit_amount: Number(result.unit_amount), breakdown: result.breakdown };
    }
  } catch {
    // Keep the authoring modal usable offline; persisted saves still pass server validation.
  }
  const unitAmount = grossedCustomerAmount(tenantKeyedAmount, platformRate, feeHandling);
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
