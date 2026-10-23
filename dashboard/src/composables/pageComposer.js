// Page Composer (builder side). Imports the SAME rules file the Python publisher reads
// (src/stripe_link/composition_rules.json), so the preview and the published page make identical
// composition decisions — one source of truth. See plans/PAGE_COMPOSER.md.
import rules from "../../../src/stripe_link/composition_rules.json";

const ELEMENTS = rules.elements || {};
const GOVERNED = new Set(rules.governed_sections || []);
const OFFER_TYPES = rules.offer_types || {};
const PACKS = rules.packs || {};
const GOALS = rules.goals || {};

// Canonical composition key. Post-Builder-Reframe the key IS the section type (no aliasing).
export function sectionKey(sectionType) {
  return sectionType;
}

// Catalog metadata for a section type (label / ui / kind / channel / heading_role / tokens).
export function element(sectionType) {
  return ELEMENTS[sectionType] || {};
}

export function elementLabel(sectionType) {
  return element(sectionType).label || sectionType;
}

// Where a section renders: "body" (visible markup), "head" (meta / JSON-LD) or "sidecar" (its own artifact).
// Mirrors element_channel() in domain/composition.py. Unknown/unset defaults to "body".
export function elementChannel(sectionType) {
  return element(sectionType).channel || "body";
}

// Section types the tenant adds as body content (the "+ Add" menu).
export function addableElements() {
  return Object.entries(ELEMENTS)
    .filter(([, meta]) => meta.ui === "add")
    .map(([type, meta]) => ({ type, label: meta.label || type }));
}

function offerTypeRule(offerType) {
  return OFFER_TYPES[offerType] || OFFER_TYPES.single || { sections: [], allowed_ctas: [] };
}

// What this page's button says when the tenant has not written their own — from the SAME rules file the
// renderer reads (domain/composition.py default_cta_label), so the preview and the published page cannot
// disagree about the verb. "" = the composition has no opinion, and the caller keeps its old default.
export function defaultCtaLabel(offerType) {
  return String(rules.offer_types?.[offerType]?.default_cta_label || "");
}

export function isGoverned(sectionType) {
  return GOVERNED.has(sectionKey(sectionType));
}

// ---------------------------------------------------------------------------------------------------
// Goal axis (plans/LANDING_PAGE_GOAL_COMPOSITION.md). offer_type says WHAT the page sells; goal says WHY /
// where its traffic comes from, and enables capability packs on top of the offer_type base. Packs only ever
// union, so a page with no goal composes exactly as it did before goals existed.
// ---------------------------------------------------------------------------------------------------
// Goals a NEW page may choose — what the wizard lists. A retired goal is marked `deprecated` rather than
// deleted: deleting it would strand pages that already store it (they would stop validating, so they could
// not be saved or re-rendered). Deprecated goals stay valid and keep composing; they just aren't offered.
export function supportedGoals() {
  return Object.entries(GOALS)
    .filter(([, meta]) => !meta.deprecated)
    .map(([value, meta]) => ({
      value,
      label: meta.label || value,
      note: meta.note || "",
    }));
}

export function goalLabel(goal) {
  return (GOALS[goal] || {}).label || goal || "";
}

// Packs a goal turns on. Unknown/absent goal -> none (pre-goal behaviour).
export function goalPacks(goal) {
  return [...((GOALS[goal] || {}).packs || [])];
}

// Content-bearing element types the create wizard seeds for this goal, deduped in pack order. They render
// nothing until filled in, and are tenant-owned once seeded — the goal never retracts them.
export function packSeeds(goal) {
  const seeds = [];
  for (const name of goalPacks(goal)) {
    for (const seed of (PACKS[name] || {}).seeds || []) {
      if (!seeds.includes(seed)) seeds.push(seed);
    }
  }
  return seeds;
}

// Governed sections the goal's packs turn on. Empty until derived head/sidecar sections exist (Phase 3).
function goalSections(goal) {
  return new Set(goalPacks(goal).flatMap((name) => (PACKS[name] || {}).sections || []));
}

// Visible by DEFAULT for this offer_type + goal (before overrides).
// Sections this offer_type can NEVER show. The goal axis is union-only -- it adds and never subtracts --
// so without this the paid_ads pack unioned trust_badges and a refund policy back onto a lead page that
// sells nothing. Mirrors excluded_sections() in domain/composition.py.
export function excludedSections(offerType) {
  return new Set(offerTypeRule(offerType).excludes || []);
}

// A chrome default this goal sets, or null when it has no opinion. Mirrors goal_chrome() in
// domain/composition.py — the preview and the published page must agree about whether the breadcrumb is on.
export function goalChrome(goal, key) {
  const value = (GOALS[goal] || {}).chrome || {};
  return typeof value[key] === "boolean" ? value[key] : null;
}

// The two OFFER-LESS compositions. Mirrors OFFERLESS_COMPOSITIONS / offerless_composition() /
// page_composition_key() in domain/composition.py — see plans/OFFERLESS_PAGES_IN_BUILDER.md P1 for why
// these exist at all: with no offer, composition_key() falls through to `single`, under which the price
// selector and the Buy CTA are visible. The renderer survives that (compose_page only FILTERS sections),
// the builder does not — it CONSTRUCTS them from builder state gated on isSectionVisible(), so a
// storefront opened here would be handed a price card and a Buy button for a page with nothing to sell.
export const OFFERLESS_COMPOSITIONS = ["store_profile", "storefront"];
// Order matters: a profile page may also carry a grid, and the profile block is the more specific claim.
const OFFERLESS_MARKERS = [
  ["store_profile", "seller_profile"],
  ["storefront", "catalog_grid"],
  ["storefront", "brand_hero"],
];

// Which offer-less shape a page is, or "" for an ordinary offer page. Derived from the page's own sections
// rather than a stored field, so existing pages need no migration.
export function offerlessComposition(page) {
  const present = new Set(
    ((page || {}).sections || []).filter((s) => s && typeof s === "object").map((s) => String(s.type || "")),
  );
  for (const [composition, marker] of OFFERLESS_MARKERS) {
    if (present.has(marker)) return composition;
  }
  return "";
}

// The composition for a PAGE. THE OFFER ALWAYS WINS — a link-in-bio page may carry a catalog_grid of its
// own (its excludes say so), so it must keep composing as lead_social and not as a storefront. `deriveKey`
// is the caller's own offer->key function (deriveOfferType in LandingPages.vue), kept as a parameter so
// this module stays free of the offer-shape derivation that lives there.
export function pageCompositionKey(page, offer, deriveKey) {
  // `hasOffer`, not `if (offer)`. In Python `{}` is falsy and `if offer:` reads correctly; in JS an empty
  // object is TRUTHY, so the direct translation takes the has-an-offer branch for a page that has none and
  // hands back `single` — the exact composition P1 exists to stop these pages getting, and only in the
  // builder, while the publisher went on composing them correctly. Caught by evaluating both sides against
  // each other rather than by reading them (2026-10-22).
  const hasOffer = Boolean(offer) && Object.keys(offer).length > 0;
  if (hasOffer) return deriveKey(offer);
  return offerlessComposition(page) || deriveKey(offer || {});
}

// The sections an OFFER-LESS page is made of, from the builder's state for them. Pure data, so it lives
// here rather than in the component (and so it can be tested against the documents the create wizard
// writes — see tests/test_offerless_builder_roundtrip.py).
//
// The ids are FIXED and match the wizard's exactly. A page whose section ids churn between a wizard save
// and a builder save loses its `section_order` and any per-section override keyed by id, so "brand-hero"
// stays "brand-hero" forever.
//
// `undefined` rather than "" for the optional fields: the page document is cleaned before it is sent, so an
// omitted key means "nothing here" while an empty string would persist as authored-but-blank.
export function offerlessSections(shape, state) {
  if (!shape) return [];
  const brandHero = state.brand_hero || {};
  const sections = [{
    id: "brand-hero",
    type: "brand_hero",
    headline: brandHero.headline || state.name || "",
    tagline: brandHero.tagline || undefined,
    logo_url: brandHero.logo_url || undefined,
  }];
  if (shape === "store_profile") {
    // The block derives its CONTENT (description, contact, address, hours, verified social) from the Site's
    // Organization at publish, so a heading is the only thing there is to author.
    sections.push({
      id: "seller-profile",
      type: "seller_profile",
      heading: (state.seller_profile || {}).heading || undefined,
    });
    return sections;
  }
  const grid = state.catalog_grid || {};
  // No collection_id, no grid. Not a defensive check: the Collection is the grid's source of truth, and a
  // catalog_grid with neither a collection_id nor inline items resolves to an empty grid that renders
  // nothing — persisting one would persist a blank section.
  if (grid.collection_id) {
    sections.push({
      id: "catalog-grid",
      type: "catalog_grid",
      collection_id: grid.collection_id,
      heading: grid.heading || undefined,
    });
  }
  return sections;
}

// The builder state for an offer-less page's sections, read back off a saved page. The inverse of
// offerlessSections, and kept beside it so the two cannot drift: a round trip through both must be the
// identity, which is what keeps opening one of these pages in the builder from rewriting it.
export function offerlessState(page) {
  const sections = ((page || {}).sections || []).filter((s) => s && typeof s === "object");
  const find = (type) => sections.find((s) => String(s.type || "") === type) || {};
  const hero = find("brand_hero");
  const grid = find("catalog_grid");
  const profile = find("seller_profile");
  return {
    brand_hero: {
      headline: hero.headline || "",
      tagline: hero.tagline || "",
      logo_url: hero.logo_url || "",
    },
    catalog_grid: {
      collection_id: grid.collection_id || "",
      heading: grid.heading || "",
    },
    seller_profile: {
      heading: profile.heading || "",
    },
  };
}

// The shipping element cannot live in an offer_type's section list: `single` and `bundle` cover digital
// goods too, and a shipping card on a download is nonsense. It keys on the one thing that decides it.
// Mirrors SHIPS_PHYSICAL_SECTION / default_visible() in domain/composition.py.
export const SHIPS_PHYSICAL_SECTION = "shipping";

export function defaultVisible(offerType, sectionType, goal = "", shipsPhysical = false) {
  const key = sectionKey(sectionType);
  if (excludedSections(offerType).has(key)) return false;
  // Default ON for anything that ships, like trust badges on a sales page -- and the tenant can untick
  // it. The default matters more here than anywhere else on the page: this element is the only thing
  // that collects a postcode, and without one the quote returns `needs: postal_code`, Stripe gets no
  // shipping option, and the buyer pays nothing to post with nobody told. A real order shipped a $7.83
  // parcel having collected $0 (2026-10-06).
  if (key === SHIPS_PHYSICAL_SECTION) return Boolean(shipsPhysical);
  return (offerTypeRule(offerType).sections || []).includes(key) || goalSections(goal).has(key);
}

// Final visibility: override wins; else the offer_type + goal default; ungoverned body elements always show.
export function isSectionVisible(offerType, sectionType, overrides, goal = "", shipsPhysical = false) {
  const key = sectionKey(sectionType);
  if (!GOVERNED.has(key)) return true;
  // An exclusion outranks a tenant override too: everything else here is a preference, this is a
  // statement about what the page IS.
  if (excludedSections(offerType).has(key)) return false;
  const override = (overrides || {})[key];
  if (override && typeof override.enabled === "boolean") return override.enabled;
  return defaultVisible(offerType, sectionType, goal, shipsPhysical);
}

export function governedKeys() {
  return [...(rules.governed_sections || [])];
}

export function recommendedSectionKeys(offerType, goal = "", shipsPhysical = false) {
  return (rules.governed_sections || []).filter((key) => defaultVisible(offerType, key, goal, shipsPhysical));
}

export function optionalSectionKeys(offerType, goal = "", shipsPhysical = false) {
  return (rules.governed_sections || []).filter((key) => !defaultVisible(offerType, key, goal, shipsPhysical));
}

export function allowedCtas(offerType) {
  return [...(offerTypeRule(offerType).allowed_ctas || [])];
}

// Advanced Color Settings source: the token catalog grouped by `group`, preserving declaration order.
// Each entry: { token, label, group, kind }. Adding a token to composition_rules.json surfaces it here.
export function tokenGroups() {
  const catalog = rules.token_catalog || {};
  const groups = [];
  const byName = new Map();
  for (const [token, meta] of Object.entries(catalog)) {
    const name = meta.group || "Other";
    if (!byName.has(name)) {
      const group = { name, tokens: [] };
      byName.set(name, group);
      groups.push(group);
    }
    byName.get(name).tokens.push({ token, label: meta.label || token, kind: meta.kind || "color" });
  }
  return groups;
}

// A theme token (e.g. cta_from) maps to the preview CSS var --preview-cta-from.
export function previewVar(token) {
  return `--preview-${String(token).replace(/_/g, "-")}`;
}

// The same token as the RENDERED page names it. Mirrors css_var_name() in runtime/html.py, which is
// what the preview frame's :root actually carries.
export function renderedVar(token) {
  return `--sl-${String(token).replace(/_/g, "-")}`;
}


// Placement governs ORDER + draggability (visibility is the separate `enabled` axis). Read from the same
// composition_rules.json the Python composer uses, so builder and renderer cannot disagree.
export const PLACEMENT_BANDS = ["lead", "pinned_top", "free", "pinned_bottom"];

export function elementPlacement(key) {
  return (rules.elements?.[key] || {}).placement || "free";
}

// Only `free` sections get a drag handle. The hero block is pinned: hero_media is the LCP element, and
// one-H1-first is an invariant the semantic outline depends on.
export function isMovable(key) {
  return elementPlacement(key) === "free";
}

// The slot vocabulary, in page order. Mirrors composition.slot_order().
export function slotOrder(goal = "") {
  const override = goal ? rules.goals?.[goal]?.slot_order : null;
  return [...(override || rules.slots || [])];
}

// Which slot each INSTANCE of an element wants. One entry for almost everything; an element that brackets
// a page declares more (event_date is ["announce", "reassure"]). Mirrors composition.element_slots().
export function elementSlots(type) {
  const spec = rules.elements?.[type] || {};
  const declared = (spec.slots || []).filter((s) => typeof s === "string");
  if (declared.length) return declared;
  return typeof spec.slot === "string" && spec.slot ? [spec.slot] : [];
}

// `ordered` (the skeleton decides) or `authored` (the tenant does). Mirrors composition.element_order_mode().
export function elementOrderMode(type) {
  return (rules.elements?.[type] || {}).order_mode === "authored" ? "authored" : "ordered";
}

// The default sequence for a page nobody has reordered. Mirrors composition.baseline_order() -- both read
// the same composition_rules.json and must DERIVE it the same way, so they cannot drift.
// See plans/BUILDER_SECTION_ORDER.md 4a/4d: derived from slots, because a hand-authored list of 39 absolute
// positions gave a new element no rule about where it belongs, and drifted until the default read as
// arbitrary. Authored elements are deliberately absent — they sort after everything with a baseline
// position, i.e. at the end of the free band, in the order they were added.
export function baselineOrder(goal = "") {
  const override = goal ? rules.goals?.[goal]?.default_order : null;
  if (override) return [...override];
  const slots = new Map(slotOrder(goal).map((slot, index) => [slot, index]));
  const tail = slots.size;
  const entries = [];
  Object.entries(rules.elements || {}).forEach(([key, spec], position) => {
    const band = spec.placement || "free";
    if (band === "none") return;
    if (band !== "free") {
      // The locked bands carry no slot and need none — band sorting dominates — but they must be here, or
      // the hero block ties on "not in the baseline" and the H1's position follows the sections array.
      entries.push([PLACEMENT_BANDS.indexOf(band), -1, 0, position, key]);
      return;
    }
    if (elementOrderMode(key) === "authored") return;
    const first = elementSlots(key)[0] || "";
    entries.push([PLACEMENT_BANDS.indexOf("free"), slots.has(first) ? slots.get(first) : tail,
                  Number(spec.rank || 0), position, key]);
  });
  entries.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2] || a[3] - b[3]);
  return entries.map((entry) => entry[4]);
}

// lead -> pinned_top -> tenant-ordered free -> pinned_bottom. Keys absent from tenantOrder fall back to
// the BASELINE order, so a tenant who never drags anything still gets a researched sequence. A key in
// neither list sorts last, never first -- an unplaced element must not jump to the top of the page.
// THE ordering rule, in one place. Everything else adapts its input to {key, type} and calls this, because
// the rule needs BOTH: the key is what the tenant's drag order is recorded against, and the type is what has
// a baseline position. Keeping two versions of this — one over keys, one over sections — is what let the
// builder's row list and the rendered page disagree: a repeatable element keys by id, which is never in the
// baseline, so the key-based version sank every content block to the end while the section-based one placed
// it correctly at its type's slot.
//
// lead -> pinned_top -> tenant-ordered free -> pinned_bottom. Entries absent from tenantOrder fall back to
// the BASELINE order of their TYPE, so a tenant who never drags anything still gets a researched sequence.
// An entry in neither list sorts last, never first — an unplaced element must not jump to the top of a page.
function orderEntries(entries, tenantOrder = [], goal = "") {
  const order = baselineOrder(goal);
  const baseline = new Map(order.map((key, index) => [key, index]));
  const rank = new Map(tenantOrder.map((key, index) => [key, index]));
  const fallback = rank.size;
  const tail = baseline.size;
  const band = (type) => {
    const index = PLACEMENT_BANDS.indexOf(elementPlacement(type));
    return index === -1 ? PLACEMENT_BANDS.indexOf("free") : index;
  };
  // A SECOND instance of a bracketing element takes the next slot its type declares, not the position of
  // the first one, so a second Date lands beside the ask. Instances past the end stay with the LAST slot.
  const slots = new Map(slotOrder(goal).map((slot, index) => [slot, index]));
  const instanceBaseline = new Map();
  const seen = new Map();
  entries.forEach((entry, index) => {
    const declared = elementSlots(entry.type);
    const count = seen.get(entry.type) || 0;
    seen.set(entry.type, count + 1);
    if (count === 0 || declared.length <= 1) return;
    const wantedSlot = declared[Math.min(count, declared.length - 1)];
    if (!slots.has(wantedSlot)) return;
    // Positioned as if it were the first element of that later slot, so it sorts AMONG that slot's members
    // rather than ahead of all of them.
    const nearest = order
      .filter((key) => (elementSlots(key)[0] || "") === wantedSlot)
      .map((key) => (baseline.has(key) ? baseline.get(key) : tail));
    instanceBaseline.set(index, nearest.length ? Math.min(...nearest) : tail);
  });
  const within = (entry, index) => {
    if (rank.has(entry.key)) return rank.get(entry.key);
    if (instanceBaseline.has(index)) return fallback + instanceBaseline.get(index);
    return fallback + (baseline.has(entry.type) ? baseline.get(entry.type) : tail);
  };
  // Ties keep their incoming position, so several content blocks (all at the same baseline slot) hold their
  // relative order instead of collapsing together arbitrarily.
  return entries
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) =>
      band(a.entry.type) - band(b.entry.type) ||
      within(a.entry, a.index) - within(b.entry, b.index) ||
      a.index - b.index)
    .map(({ entry }) => entry);
}

// Order a list of section KEYS. A bare string key is its own type; pass {key, type} when they differ, which
// is exactly the repeatable case. Filters `placement: "none"` because this builds the DRAGGABLE ROW LIST and
// a none-placed section (structured_data) has no row — that filter belongs here and nowhere else.
export function orderSectionKeys(keys, tenantOrder = [], goal = "") {
  const entries = keys.map((key) => (typeof key === "string" ? { key, type: key } : key));
  return orderEntries(entries, tenantOrder, goal)
    .filter((entry) => elementPlacement(entry.type) !== "none")
    .map((entry) => entry.key);
}


// The key a section is ordered by. Repeatable types can have several instances, so those key by their
// element id; everything else keys by type, which is the vocabulary the Page Sections panel already uses.
export function sectionOrderKey(section) {
  const type = section?.type || "";
  const spec = rules.elements?.[type] || {};
  return spec.repeatable && section?.id ? section.id : type;
}

// Order real section objects. Orders; never filters — `placement: "none"` means "not a draggable row", which
// is orderSectionKeys' business, not "not a section". This used to filter, which silently dropped the
// structured_data section from every saved page and cost those pages their Product/FAQPage JSON-LD.
export function orderSections(sections, tenantOrder = [], goal = "") {
  const entries = sections.map((section) => ({
    key: sectionOrderKey(section), type: section?.type || "", section,
  }));
  return orderEntries(entries, tenantOrder, goal).map((entry) => entry.section);
}


// Whether this section may appear MORE THAN ONCE on a page. Content blocks can; testimonials and FAQ
// cannot — they are one section holding many items, each with its own add control. Reads the same
// catalog the Python composer does, so the two cannot disagree.
export function isRepeatableSection(type) {
  return Boolean((rules.elements?.[type] || {}).repeatable);
}
