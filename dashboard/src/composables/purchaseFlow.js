// Purchase-flow STAGES for a SAVED offer — the data half of PurchaseFlowDiagram.
//
// The diagram component was already shared; this is what was not. Two screens described the same saved
// offer from different fields: the Offers View modal read purchase_opportunities, while the Landing Pages
// builder read the legacy items[] + funnel.* pair. Those are dual-written today, so both "worked", but
// plans/OFFER_MODEL_REDESIGN.md P4 drops the legacy fields — at which point the Landing Pages flow would
// have quietly lost its bumps and upsells with nothing failing.
//
// Reads purchase_opportunities when present and falls back to the legacy shape, so it is correct before
// AND after that migration.
//
// NOT used by the Offers EDIT form: that one describes an offer being composed and not yet saved, built
// from the live product selection with sync/extra-price warnings. Different input, different job — sharing
// it would mean one function pretending to be two.

const GROUP_ORDER_BUMP = "order_bump";
const GROUP_UPSELL = "upsell";
const GROUP_DOWNSELL = "downsell";

function entryId(entry) {
  return String(entry?.product_id || entry?.service_id || "");
}

// purchase_opportunities if the document carries them, else the legacy items[] + funnel.* pair mapped to
// the same shape. One vocabulary from here down.
function normalizedEntries(offer) {
  const opps = Array.isArray(offer?.purchase_opportunities) ? offer.purchase_opportunities : [];
  if (opps.length) {
    return opps.map((opp) => ({
      id: entryId(opp),
      price_id: opp?.price_id || "",
      group: String(opp?.placement?.group || ""),
      stage: String(opp?.stage || "landing"),
      selectable_prices: opp?.selectable_prices || [],
    }));
  }
  const funnel = offer?.funnel || {};
  const legacy = [];
  for (const item of offer?.items || []) {
    legacy.push({ id: entryId(item), price_id: item?.price_id || item?.default_price_id || "",
                  group: "main_offer", stage: "landing", selectable_prices: item?.selectable_prices || [] });
  }
  for (const [key, group, stage] of [
    ["order_bumps", GROUP_ORDER_BUMP, "checkout"],
    ["upsells", GROUP_UPSELL, "post_purchase"],
    ["downsells", GROUP_DOWNSELL, "post_purchase"],
  ]) {
    for (const entry of funnel[key] || []) {
      legacy.push({ id: entryId(entry), price_id: entry?.price_id || "", group, stage, selectable_prices: [] });
    }
  }
  return legacy;
}

/**
 * Stages for PurchaseFlowDiagram.
 * `resolveProduct(id)` -> the product document (or null). `formatAmount(unitAmount, currency)` -> string,
 * injected so each screen uses its own money formatting rather than a hardcoded currency symbol.
 */
export function stagesFromSavedOffer(offer, { resolveProduct, formatAmount }) {
  const entries = normalizedEntries(offer);
  if (!entries.length) return [];

  const priceLabel = (product, priceId) => {
    const price = (product?.prices || []).find((entry) => entry.price_id === priceId);
    return price ? formatAmount(Number(price.unit_amount || 0), price.currency) : "";
  };
  // Low–high across a tiered item's selectable prices. Returns "" when there is nothing to span (no tiers,
  // or none of their price_ids resolve), so the caller falls back to the single price.
  const priceRange = (product, selectable) => {
    const amounts = [];
    let currency = "";
    for (const tier of selectable || []) {
      const price = (product?.prices || []).find((entry) => entry.price_id === tier?.price_id);
      if (!price) continue;
      amounts.push(Number(price.unit_amount || 0));
      currency = currency || price.currency;
    }
    if (amounts.length < 2) return "";
    const low = Math.min(...amounts);
    const high = Math.max(...amounts);
    return low === high
      ? formatAmount(low, currency)
      : `${formatAmount(low, currency)} – ${formatAmount(high, currency)}`;
  };

  const card = (entry, intent) => {
    const product = resolveProduct(entry.id);
    return {
      key: `${intent}:${entry.id}`,
      intent,
      // An archived product, or one whose store has not loaded, still renders by id rather than blank.
      product: product || { name: entry.id },
      _product: product,
      _priceId: entry.price_id,
    };
  };
  const inGroup = (group) => entries.filter((entry) => entry.group === group);

  const stages = [];

  const landing = entries.filter((entry) => entry.stage === "landing");
  if (landing.length) {
    stages.push({
      key: "landing",
      label: "Landing page",
      hint: "what the customer buys",
      items: landing.map((entry) => {
        const item = card(entry, "primary");
        // A tiered item has no single price. Showing the RANGE beats naming the tier count: it tells the
        // tenant what the customer can actually pay, which is the question the diagram is answering.
        const range = priceRange(item._product, entry.selectable_prices);
        item.chips = range
          ? [range]
          : [priceLabel(item._product, entry.price_id) || "standard"];
        return item;
      }),
    });
  }

  const bumps = inGroup(GROUP_ORDER_BUMP);
  if (bumps.length) {
    stages.push({
      key: "checkout",
      label: "At checkout",
      hint: "Stripe order bump",
      items: bumps.map((entry) => {
        const item = card(entry, "cross_sell");
        item.chips = [priceLabel(item._product, entry.price_id)].filter(Boolean);
        return item;
      }),
    });
  }

  const upsells = inGroup(GROUP_UPSELL);
  const downsells = inGroup(GROUP_DOWNSELL);
  if (upsells.length) {
    const items = upsells.map((entry) => {
      const item = card(entry, "upgrade");
      item.chips = [priceLabel(item._product, entry.price_id)].filter(Boolean);
      // A downsell is the SAME product's second-chance price, paired by product id.
      const paired = downsells.find((d) => d.id === entry.id);
      if (paired) item.downsell = { amount: priceLabel(item._product, paired.price_id) };
      return item;
    });
    stages.push({
      key: "post_purchase",
      label: "After purchase",
      hint: upsells.length > 3 ? `carousel · ${upsells.length} upsells` : "one at a time",
      items,
    });
  }

  return stages.map((stage) => ({
    ...stage,
    items: stage.items.map(({ _product, _priceId, ...item }) => item),
  }));
}
