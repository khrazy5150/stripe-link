// What is actually IN an offer — used by the Offers cards/search and the Landing Pages search.
//
// `items[]` is a LANDING-ONLY projection of the offer (verified against real documents), so anything
// asking "everything in this offer" must read `purchase_opportunities`, which carries every stage plus a
// `placement.group` naming the role. Reading items[] is what made an order-bump product invisible on the
// Offers screen. See plans/OFFER_ITEM_VISIBILITY.md.
//
// Product resolution is injected: each screen owns its own stores, and this stays pure so it can be
// tested without Vue. `resolveProduct(id)` returns the product/service document, or null.
//
// Funnel ROLES are not read from the stored placement — they come from derivedFunnelEntries in
// purchaseFlow.js, the same derivation the diagram and the runtime use. Reading placement.group here made
// the card's counts disagree with the diagram beside them the moment a product gained a funnel price.

// Explicit .js: Vite resolves extensionless, raw node (which runs the parity tests) does not.
import { derivedFunnelEntries, offerEntries } from "./purchaseFlow.js";

export const STAGE_LANDING = "landing";

// Tenant-facing words, kept short for a card line. Matches the vocabulary of the Purchase Flow diagram.
export const FUNNEL_ROLE_LABELS = {
  order_bump: "bump",
  upsell: "upsell",
  downsell: "downsell",
};

export const ITEM_SUMMARY_MAX_NAMES = 3;
export const ITEM_SUMMARY_MAX_CHARS = 90;

// An entry's catalog id. Normalized entries expose `id`; a raw document entry has product_id/service_id.
export function itemId(entry) {
  return String(entry?.id || entry?.product_id || entry?.service_id || "");
}

// Landing entries: the offer's primary meaning. Falls back to items[] for a legacy document saved before
// purchase_opportunities existed — items[] IS the landing set, so the fallback is exact, not approximate.
export function landingEntries(offer) {
  return offerEntries(offer).filter((entry) => String(entry.stage || STAGE_LANDING) === STAGE_LANDING);
}

// Everything that is NOT on the landing page: order bumps, upsells, downsells.
export function funnelEntries(offer) {
  return offerEntries(offer).filter((entry) => String(entry.stage || STAGE_LANDING) !== STAGE_LANDING);
}

// Deduped display names for a set of entries. An unresolved id falls back to the id itself, so the UI
// degrades to something rather than to nothing.
function namesFor(entries, resolve) {
  const seen = new Set();
  const names = [];
  for (const entry of entries) {
    const id = itemId(entry);
    if (!id) continue;
    const name = resolve(id)?.name || id;
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

// Counts every funnel PLACEMENT by role — deliberately NOT deduped against the landing items.
//
// These words name funnel STEPS, not products. An upsell selling a product the customer already saw on
// the landing page (common: the same product at another price) is still a real step in the flow, and
// suppressing it made a configured upsell invisible on the card. Counting placements answers "what does
// this offer do", which is what the role words were always describing. The hover title names each one
// with its role, so a count is never ambiguous.
export function funnelRoleCounts(offer, resolve) {
  const derived = derivedFunnelEntries(offer, resolve);
  const counts = new Map();
  for (const [context, entries] of Object.entries(derived)) {
    if (!entries.length) continue;
    counts.set(FUNNEL_ROLE_LABELS[context] || "extra", entries.length);
  }
  // Funnel order, not document order, so the line reads the way the customer experiences it.
  const order = [...Object.values(FUNNEL_ROLE_LABELS), "extra"];
  return [...counts.entries()]
    .sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]))
    .map(([label, n]) => `${n} ${label}${n > 1 ? "s" : ""}`);
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
  const derived = derivedFunnelEntries(offer, resolve);
  const funnel = Object.entries(derived).flatMap(([context, entries]) =>
    entries.map((entry) => `${resolve(entry.id)?.name || entry.id} (${FUNNEL_ROLE_LABELS[context] || "extra"})`));
  if (funnel.length) parts.push(`Funnel: ${funnel.join(", ")}`);
  return parts.join("\n");
}

// Every name AND id across every stage, for search. Ids stay searchable because pasting one is a
// legitimate way to find an offer.
export function searchableItemText(offer, resolve) {
  // Search spans every stage as STORED — an id that is in the offer should be findable whether or not the
  // product still carries a funnel price today.
  const entries = [...landingEntries(offer), ...funnelEntries(offer)];
  const ids = [...new Set(entries.map(itemId).filter(Boolean))];
  return [...namesFor(entries, resolve), ...ids].join(" ");
}
