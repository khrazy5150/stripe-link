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
export function defaultVisible(offerType, sectionType, goal = "") {
  const key = sectionKey(sectionType);
  return (offerTypeRule(offerType).sections || []).includes(key) || goalSections(goal).has(key);
}

// Final visibility: override wins; else the offer_type + goal default; ungoverned body elements always show.
export function isSectionVisible(offerType, sectionType, overrides, goal = "") {
  const key = sectionKey(sectionType);
  if (!GOVERNED.has(key)) return true;
  const override = (overrides || {})[key];
  if (override && typeof override.enabled === "boolean") return override.enabled;
  return defaultVisible(offerType, sectionType, goal);
}

export function governedKeys() {
  return [...(rules.governed_sections || [])];
}

export function recommendedSectionKeys(offerType, goal = "") {
  return (rules.governed_sections || []).filter((key) => defaultVisible(offerType, key, goal));
}

export function optionalSectionKeys(offerType, goal = "") {
  return (rules.governed_sections || []).filter((key) => !defaultVisible(offerType, key, goal));
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

// The default sequence for a page nobody has reordered. Mirrors composition.baseline_order() -- both read
// the same composition_rules.json, so they cannot drift. See plans/BUILDER_SECTION_ORDER.md 4a.
export function baselineOrder(goal = "") {
  const override = goal ? rules.goals?.[goal]?.default_order : null;
  return [...(override || rules.default_order || [])];
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
  const baseline = new Map(baselineOrder(goal).map((key, index) => [key, index]));
  const rank = new Map(tenantOrder.map((key, index) => [key, index]));
  const fallback = rank.size;
  const tail = baseline.size;
  const band = (type) => {
    const index = PLACEMENT_BANDS.indexOf(elementPlacement(type));
    return index === -1 ? PLACEMENT_BANDS.indexOf("free") : index;
  };
  const within = (entry) =>
    rank.has(entry.key) ? rank.get(entry.key) : fallback + (baseline.has(entry.type) ? baseline.get(entry.type) : tail);
  // Ties keep their incoming position, so several content blocks (all at the same baseline slot) hold their
  // relative order instead of collapsing together arbitrarily.
  return entries
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) =>
      band(a.entry.type) - band(b.entry.type) ||
      within(a.entry) - within(b.entry) ||
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
