// What is actually IN an offer — used by the Offers cards/search and the Landing Pages search.
//
// `items[]` is a LANDING-ONLY projection of the offer (verified against real documents), so anything
// asking "everything in this offer" must read `purchase_opportunities`, which carries every stage plus a
// `placement.group` naming the role. Reading items[] is what made an order-bump product invisible on the
// Offers screen. See plans/OFFER_ITEM_VISIBILITY.md.
//
// Name resolution is injected: each screen owns its own product/service stores, and this stays pure so it
// can be tested without Vue.

export const STAGE_LANDING = "landing";

// Tenant-facing words, kept short for a card line. Matches the vocabulary of the Purchase Flow diagram.
export const FUNNEL_ROLE_LABELS = {
  order_bump: "bump",
  upsell: "upsell",
  downsell: "downsell",
};

export const ITEM_SUMMARY_MAX_NAMES = 3;
export const ITEM_SUMMARY_MAX_CHARS = 90;

function opportunities(offer) {
  return Array.isArray(offer?.purchase_opportunities) ? offer.purchase_opportunities : [];
}

// An opportunity/item's catalog id, whichever kind it is.
export function itemId(entry) {
  return String(entry?.product_id || entry?.service_id || "");
}

// Landing entries: the offer's primary meaning. Falls back to items[] for a legacy document saved before
// purchase_opportunities existed — items[] IS the landing set, so the fallback is exact, not approximate.
export function landingEntries(offer) {
  const opps = opportunities(offer);
  if (opps.length) return opps.filter((o) => String(o?.stage || STAGE_LANDING) === STAGE_LANDING);
  return Array.isArray(offer?.items) ? offer.items : [];
}

// Everything that is NOT on the landing page: order bumps, upsells, downsells.
export function funnelEntries(offer) {
  return opportunities(offer).filter((o) => String(o?.stage || STAGE_LANDING) !== STAGE_LANDING);
}

// Deduped display names for a set of entries. `resolve(id)` returns a name, or "" when unknown; an
// unresolved id falls back to the id itself so the UI degrades to something rather than to nothing.
function namesFor(entries, resolve) {
  const seen = new Set();
  const names = [];
  for (const entry of entries) {
    const id = itemId(entry);
    if (!id) continue;
    const name = resolve(id) || id;
    if (!seen.has(name)) {
      seen.add(name);
      names.push(name);
    }
  }
  return names;
}

export function landingNames(offer, resolve) {
  return namesFor(landingEntries(offer), resolve);
}

// Role counts for funnel products NOT already named among the landing items. A product used as both a
// landing item and an upsell (common — the upsell is often the same product at another price) must not be
// counted again, or the card claims an extra product the offer does not have.
export function funnelRoleCounts(offer, resolve) {
  const alreadyNamed = new Set(landingNames(offer, resolve));
  const counted = new Set();
  const counts = new Map();
  for (const entry of funnelEntries(offer)) {
    const id = itemId(entry);
    if (!id) continue;
    const name = resolve(id) || id;
    if (alreadyNamed.has(name) || counted.has(name)) continue;
    counted.add(name);
    const label = FUNNEL_ROLE_LABELS[String(entry?.placement?.group || "")] || "extra";
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  return [...counts.entries()].map(([label, n]) => `${n} ${label}${n > 1 ? "s" : ""}`);
}

// The card line: landing names (capped), then role-labelled counts for the rest.
export function itemSummary(offer, resolve) {
  const names = landingNames(offer, resolve);
  const extras = funnelRoleCounts(offer, resolve);
  if (!names.length) return extras.join(", ");

  const shown = names.slice(0, ITEM_SUMMARY_MAX_NAMES);
  let text = shown.join(", ");
  if (text.length > ITEM_SUMMARY_MAX_CHARS) text = `${text.slice(0, ITEM_SUMMARY_MAX_CHARS - 1).trimEnd()}…`;
  const hidden = names.length - shown.length;
  if (hidden > 0) text += ` +${hidden} more`;
  return extras.length ? `${text} · ${extras.join(", ")}` : text;
}

// Full breakdown for the hover title, so collapsing hides nothing.
export function itemSummaryTitle(offer, resolve) {
  const parts = [`Landing: ${landingNames(offer, resolve).join(", ") || "none"}`];
  const funnel = namesFor(funnelEntries(offer), resolve);
  if (funnel.length) parts.push(`Funnel: ${funnel.join(", ")}`);
  return parts.join("\n");
}

// Every name AND id across every stage, for search. Ids stay searchable because pasting one is a
// legitimate way to find an offer.
export function searchableItemText(offer, resolve) {
  const entries = [...landingEntries(offer), ...funnelEntries(offer)];
  const ids = [...new Set(entries.map(itemId).filter(Boolean))];
  return [...namesFor(entries, resolve), ...ids].join(" ");
}
