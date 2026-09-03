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
export function orderSectionKeys(keys, tenantOrder = [], goal = "") {
  const baseline = new Map(baselineOrder(goal).map((key, index) => [key, index]));
  const rank = new Map(tenantOrder.map((key, index) => [key, index]));
  const fallback = rank.size;
  const band = (key) => {
    const index = PLACEMENT_BANDS.indexOf(elementPlacement(key));
    return index === -1 ? PLACEMENT_BANDS.indexOf("free") : index;
  };
  const within = (key) =>
    rank.has(key) ? rank.get(key) : fallback + (baseline.has(key) ? baseline.get(key) : baseline.size);
  return [...keys]
    .filter((key) => elementPlacement(key) !== "none")
    .sort((a, b) => band(a) - band(b) || within(a) - within(b));
}


// The key a section is ordered by. Repeatable types can have several instances, so those key by their
// element id; everything else keys by type, which is the vocabulary the Page Sections panel already uses.
export function sectionOrderKey(section) {
  const type = section?.type || "";
  const spec = rules.elements?.[type] || {};
  return spec.repeatable && section?.id ? section.id : type;
}

// Apply placement bands + the tenant's order to real section objects. Anything the tenant has not moved
// falls back to the baseline position of its TYPE, tie-broken by current position -- so repeatable
// sections (several content_blocks, keyed by id and therefore never in the baseline) keep their relative
// order instead of collapsing together arbitrarily.
export function orderSections(sections, tenantOrder = [], goal = "") {
  const baseline = new Map(baselineOrder(goal).map((key, index) => [key, index]));
  const rank = new Map(tenantOrder.map((key, index) => [key, index]));
  const bandOf = (type) => {
    const index = PLACEMENT_BANDS.indexOf(elementPlacement(type));
    return index === -1 ? PLACEMENT_BANDS.indexOf("free") : index;
  };
  // Orders; never filters. `placement: "none"` means "not a draggable row", which is orderSectionKeys'
  // business — not "not a section". This filter was silently dropping the structured_data section from
  // every saved page, so published pages lost their Product/FAQPage JSON-LD entirely.
  return sections
    .map((section, index) => ({ section, index }))
    .sort((a, b) => {
      const band = bandOf(a.section.type) - bandOf(b.section.type);
      if (band) return band;
      const aKey = sectionOrderKey(a.section);
      const bKey = sectionOrderKey(b.section);
      const base = (key, type) =>
        rank.has(key) ? rank.get(key) : rank.size + (baseline.has(type) ? baseline.get(type) : baseline.size);
      const aRank = base(aKey, a.section.type);
      const bRank = base(bKey, b.section.type);
      return aRank - bRank || a.index - b.index;
    })
    .map((entry) => entry.section);
}


// Whether this section may appear MORE THAN ONCE on a page. Content blocks can; testimonials and FAQ
// cannot — they are one section holding many items, each with its own add control. Reads the same
// catalog the Python composer does, so the two cannot disagree.
export function isRepeatableSection(type) {
  return Boolean((rules.elements?.[type] || {}).repeatable);
}
