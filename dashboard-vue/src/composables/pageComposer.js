// Page Composer (builder side). Imports the SAME rules file the Python publisher reads
// (src/stripe_link/composition_rules.json), so the preview and the published page make identical
// composition decisions — one source of truth. See plans/PAGE_COMPOSER.md.
import rules from "../../../src/stripe_link/composition_rules.json";

const SECTION_KEY_BY_TYPE = rules.section_key_by_type || {};
const GOVERNED = new Set(rules.governed_sections || []);
const OFFER_TYPES = rules.offer_types || {};

// Config uses friendly keys (brand_label -> brand); map a section type to its composition key.
export function sectionKey(sectionType) {
  return SECTION_KEY_BY_TYPE[sectionType] || sectionType;
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
