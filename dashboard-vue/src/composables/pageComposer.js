// Page Composer (builder side). Imports the SAME rules file the Python publisher reads
// (src/stripe_link/composition_rules.json), so the preview and the published page make identical
// composition decisions — one source of truth. See plans/PAGE_COMPOSER.md.
import rules from "../../../src/stripe_link/composition_rules.json";

const ELEMENTS = rules.elements || {};
const GOVERNED = new Set(rules.governed_sections || []);
const OFFER_TYPES = rules.offer_types || {};

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

// Visible by DEFAULT for this offer_type (before overrides).
export function defaultVisible(offerType, sectionType) {
  return (offerTypeRule(offerType).sections || []).includes(sectionKey(sectionType));
}

// Final visibility: override wins; else the offer_type default; ungoverned body elements always show.
export function isSectionVisible(offerType, sectionType, overrides) {
  const key = sectionKey(sectionType);
  if (!GOVERNED.has(key)) return true;
  const override = (overrides || {})[key];
  if (override && typeof override.enabled === "boolean") return override.enabled;
  return defaultVisible(offerType, sectionType);
}

export function governedKeys() {
  return [...(rules.governed_sections || [])];
}

export function recommendedSectionKeys(offerType) {
  return (rules.governed_sections || []).filter((key) => (offerTypeRule(offerType).sections || []).includes(key));
}

export function optionalSectionKeys(offerType) {
  return (rules.governed_sections || []).filter((key) => !(offerTypeRule(offerType).sections || []).includes(key));
}

export function allowedCtas(offerType) {
  return [...(offerTypeRule(offerType).allowed_ctas || [])];
}
