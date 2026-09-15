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

// What the builder OFFERS, which is narrower than what the runtime accepts. Every recurring charge has to
// be acknowledged, so the charge cadence is also the email cadence — 365 charges a year would mean 365
// emails a year, and no peer offers finer than monthly for creator support. A document that somehow carries
// `week` or `day` still works end to end; it just cannot be created here.
export const TIP_INTERVALS = [
  { value: "day", label: "Daily" },
  { value: "week", label: "Weekly" },
  { value: "month", label: "Monthly" },
  { value: "year", label: "Yearly" },
].filter((option) => (rules.offered_intervals || rules.intervals).includes(option.value));

// "Enter your own" is a button too, and takes one of the five places in the row.
export function maxTipPresets(allowCustom) {
  return allowCustom ? rules.max_presets_with_custom : rules.max_presets;
}

// Starting amounts, in major units, trimmed to what the row holds. Two ladders per currency on purpose: $50
// is an ordinary one-off tip and a steep monthly commitment, so a jar that repeats gets the lower one —
// which is where membership tiers actually cluster. Turning on "enter your own" drops the top amount,
// because that is the place it takes. An unlisted currency falls back to the USD ladder.
export function recommendedTipPresets(allowRecurring, allowCustom, currency = "usd") {
  const ladders = rules.recommended[String(currency || "usd").toLowerCase()] || rules.recommended.usd;
  const ladder = allowRecurring ? ladders.recurring : ladders.one_time;
  return ladder.slice(0, maxTipPresets(allowCustom)).map((amount) => amount / 100);
}
