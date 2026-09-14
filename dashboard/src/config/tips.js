// What a tip jar may offer, read from the SAME file the server validates against
// (src/stripe_link/tip_rules.json -> domain/tips.py). A form that caps at five while the server accepts
// eight is this codebase's recurring bug: two things that must agree, with nothing forcing them to.
//
// The rules file speaks in cents, like every stored amount; the authoring form speaks in dollars.
import rules from "../../../src/stripe_link/tip_rules.json";

export const TIP_RULES = rules;

// The range is the PLATFORM's, not the tenant's — so the form shows it and does not offer to change it.
export const TIP_MIN = rules.min_amount / 100;
export const TIP_MAX = rules.max_amount / 100;

export const TIP_INTERVALS = [
  { value: "day", label: "Daily" },
  { value: "week", label: "Weekly" },
  { value: "month", label: "Monthly" },
  { value: "year", label: "Yearly" },
].filter((option) => rules.intervals.includes(option.value));

// "Enter your own" is a button too, and takes one of the five places in the row.
export function maxTipPresets(allowCustom) {
  return allowCustom ? rules.max_presets_with_custom : rules.max_presets;
}
