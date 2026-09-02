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

// Mirrors MAX_SEQUENTIAL_UPSELLS in domain/funnels.py: above this many upsells the runtime forces a
// carousel instead of one-at-a-time. Named rather than a bare 3, because a literal in one of three places
// is how these quietly stop agreeing.
export const MAX_SEQUENTIAL_UPSELLS = 3;

const GROUP_ORDER_BUMP = "order_bump";
const GROUP_UPSELL = "upsell";
const GROUP_DOWNSELL = "downsell";

function entryId(entry) {
  return String(entry?.product_id || entry?.service_id || "");
}

// purchase_opportunities if the document carries them, else the legacy items[] + funnel.* pair mapped to
// the same shape. One vocabulary from here down.
export function isIndexRow(offer) {
  return Array.isArray(offer?.item_ids);
}

/**
 * Every entry an offer references, normalized to {id, price_id, group, stage, selectable_prices} — from
 * ANY of the three shapes: purchase_opportunities, the legacy items[]+funnel.*, or a slim index row.
 *
 * Exported so offerItems.js reads offers through the SAME reader. It had its own, which understood two of
 * the three shapes, so an index row derived its funnel roles correctly and silently lost its landing
 * NAMES. One reader, three shapes.
 */
export function offerEntries(offer) {
  return normalizedEntries(offer);
}

function normalizedEntries(offer) {
  // The slim list projection (GET /offers?view=index) carries ids only. Understanding it HERE means the
  // card, its tooltip, search and the role derivation all work on an index row with no changes of their
  // own — the list screen never needs full documents.
  if (isIndexRow(offer)) {
    const landing = new Set(offer.landing_ids || []);
    return (offer.item_ids || []).map((id) => ({
      id: String(id),
      price_id: "",                       // the index does not carry prices; roles derive from the product
      group: landing.has(id) ? "main_offer" : "",
      stage: landing.has(id) ? "landing" : "checkout",
      selectable_prices: [],
    }));
  }
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

const FUNNEL_CONTEXTS = new Set([GROUP_ORDER_BUMP, GROUP_UPSELL, GROUP_DOWNSELL]);

/**
 * The chips under a LANDING product in the flow diagram: what the customer pays, then how it is priced.
 *
 * Shared because this is exactly what drifted. The edit form showed pricing SHAPE ("standard",
 * "3 quantity tiers") while the saved views showed AMOUNTS ("$39.00", "$24.22 – $55.71") — the same
 * component fed by two builders that had quietly diverged. Both facts are useful, so one function now
 * produces both and both callers use it.
 *
 * `selectablePriceIds` comes from the edit form's live config or from a saved entry's selectable_prices;
 * either way the tier RANGE is computed here rather than twice.
 */
export function landingChips({ product, selectablePriceIds = [], priceId = "", formatAmount }) {
  const prices = (product?.prices || []).filter(
    (price) => !FUNNEL_CONTEXTS.has(String(price?.context || "standard")),
  );
  const byId = (id) => prices.find((price) => String(price?.price_id || "") === String(id));
  const money = (price) => formatAmount(Number(price?.unit_amount || 0), price?.currency);
  const chips = [];

  const tiers = (selectablePriceIds || []).filter((id) => byId(id));
  if (tiers.length > 1) {
    const amounts = tiers.map((id) => Number(byId(id).unit_amount || 0));
    const low = Math.min(...amounts);
    const high = Math.max(...amounts);
    const currency = byId(tiers[0])?.currency;
    chips.push(low === high
      ? formatAmount(low, currency)
      : `${formatAmount(low, currency)} – ${formatAmount(high, currency)}`);
    chips.push(`${tiers.length} quantity tiers`);
  } else {
    const price = byId(priceId) || prices[0];
    if (price) chips.push(money(price));
  }

  // How it is priced, beyond the amount. A subscription or an active sale changes what the tenant is
  // looking at even when the headline number does not.
  if (prices.some((price) => ["recurring", "subscription"].includes(String(price?.pricing_model || "")))) {
    chips.push("subscription");
  }
  const contexts = new Set(prices.map((price) => String(price?.context || "standard")));
  if (contexts.has("sale")) chips.push("sale");
  if (contexts.has("flash_sale")) chips.push("flash sale");
  return chips;
}

/**
 * The offer's funnel entries, DERIVED from each product's pricing contexts — mirroring
 * domain/funnels.funnel_context_items, which is what the runtime charges from.
 *
 * The single implementation for BOTH the flow diagram and the offer card's role counts. Reading the
 * offer's stored `placement.group` instead would show a funnel that differs from the one that charges:
 * add a downsell price to a product and the stored placement never learns about it. Landing membership
 * stays offer data — which products are on the page, at which prices and tiers.
 *
 * Returns {order_bump: [{id, price_id}], upsell: [...], downsell: [...]} in offer order.
 */
export function derivedFunnelEntries(offer, resolveProduct) {
  const derived = { order_bump: [], upsell: [], downsell: [] };
  const seen = new Set();
  for (const entry of normalizedEntries(offer)) {
    if (!entry.id || seen.has(entry.id)) continue;
    seen.add(entry.id);
    const product = resolveProduct(entry.id);
    if (!product) continue;
    for (const context of Object.keys(derived)) {
      const price = (product.prices || []).find((p) => String(p.context || "standard") === context);
      if (price) derived[context].push({ id: entry.id, price_id: price.price_id, selectable_prices: [] });
    }
  }
  return derived;
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
  const derived = derivedFunnelEntries(offer, resolveProduct);
  const inGroup = (group) => derived[group] || [];

  const stages = [];

  const landing = entries.filter((entry) => entry.stage === "landing");
  if (landing.length) {
    stages.push({
      key: "landing",
      label: "Landing page",
      hint: "what the customer buys",
      items: landing.map((entry) => {
        const item = card(entry, "primary");
        item.chips = landingChips({
          product: item._product,
          selectablePriceIds: (entry.selectable_prices || []).map((tier) => tier?.price_id),
          priceId: entry.price_id,
          formatAmount,
        });
        if (!item.chips.length) item.chips = ["standard"];
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
      hint: upsells.length > MAX_SEQUENTIAL_UPSELLS ? `carousel · ${upsells.length} upsells` : "one at a time",
      items,
    });
  }

  return stages.map((stage) => ({
    ...stage,
    items: stage.items.map(({ _product, _priceId, ...item }) => item),
  }));
}

/**
 * A stable signature of an offer's FUNNEL entries (bump/upsell/downsell), as stored in the document.
 *
 * Exists because the Offers edit form derives its funnel live from each product's pricing contexts, while
 * the runtime (domain/funnels.funnel_context_items) reads the SAVED document. Add a downsell price to a
 * product and the edit diagram shows it immediately, but no buyer will ever see it until the offer is
 * re-saved. Comparing this signature against the same signature built from the derived funnel is how the
 * form can tell the tenant that.
 */
export function funnelSignature(offer) {
  return normalizedEntries(offer)
    .filter((entry) => entry.group !== "main_offer" && entry.stage !== "landing")
    .map((entry) => `${entry.group}:${entry.id}|${entry.price_id}`)
    .sort()
    .join(";");
}

/** The same signature shape, from the {order_bumps, upsells, downsells} block the edit form builds. */
export function funnelSignatureFromBlock(block) {
  const groups = [["order_bumps", GROUP_ORDER_BUMP], ["upsells", GROUP_UPSELL], ["downsells", GROUP_DOWNSELL]];
  const parts = [];
  for (const [key, group] of groups) {
    for (const entry of (block || {})[key] || []) {
      parts.push(`${group}:${entryId(entry)}|${entry?.price_id || ""}`);
    }
  }
  return parts.sort().join(";");
}
