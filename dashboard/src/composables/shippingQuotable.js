// Can a buyer be shown a shipping price for this offer at all?
//
// Mirrors `shipping_is_quotable` in src/stripe_link/domain/shipping.py, and the two are held together by
// tests/test_shipping_quotable_parity.py, which runs both over the same cases. Duplicated rather than
// shared because the rule has to answer in the builder (which has the tenant's zones in hand) and at
// publish (which does not share a runtime with the browser) -- the same reason roundupEntryDefaults is
// duplicated against the renderer's own ladder.
//
// TRUE UNLESS CERTAIN, in both copies. The shipping element is the only thing on a page that collects a
// postal code, and without one Stripe gets no shipping option -- so the buyer pays nothing to post and
// nobody is told. A real order shipped a Large box for $7.83 that way (2026-10-06). Hiding the element is
// the expensive direction to be wrong in.

// The two zone rules that price by the size of the parcel. `free` and `flat` are deliberately absent:
// $7 is $7 whatever the box, and free is free. Measured on all four with an unmeasured product -- free
// and flat each returned a priced option, and only these two came back empty.
const DIMENSION_DEPENDENT_RULES = new Set(["live", "flat_rate_box"]);

export function rulesNeedDimensions(config) {
  return (config?.zones || []).some((zone) => DIMENSION_DEPENDENT_RULES.has(zone?.rule?.type || ""));
}

function positive(value) {
  const n = Number(value || 0);
  return Number.isFinite(n) && n > 0;
}

/** A usable size AND weight — the same completeness test the product screen's own notice applies. */
export function productIsMeasured(product) {
  const fulfillment = product?.fulfillment || {};
  const own = fulfillment.item_dimensions || {};
  return ["length_in", "width_in", "height_in"].every((field) => positive(own[field]))
    && positive(own.weight_lb || fulfillment.weight_lb);
}

export function shippingIsQuotable(products, config) {
  const shippable = (products || []).filter((p) => p?.fulfillment?.requires_shipping);
  if (!shippable.length) return true;          // nothing ships; the element is not offered anyway
  if (!rulesNeedDimensions(config)) return true;  // free/flat never look at a dimension
  // One measured product among several leaves the element in place. That order still cannot be packed,
  // but the honest failure is an empty option list the tenant can fix, not a parcel posted for free.
  return shippable.some(productIsMeasured);
}
