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
export function supportedGoals() {
  return Object.entries(GOALS).map(([value, meta]) => ({
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
