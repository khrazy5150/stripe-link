// US states and Canadian provinces as CODES, with their names for display.
//
// The State / Province field was free text with a "CA" placeholder, so tenants typed what they say out
// loud: "Wyoming", "Colorado". Three things suffer for it (2026-10-04):
//
//   - the store timezone is INFERRED from the region, and two letters of a state name is a different
//     state — "Nevada" truncates to NE, which is Nebraska, and Nevada is Pacific while Nebraska is
//     Central. The Python side carries a full-name table purely to survive this;
//   - NAP consistency and LocalBusiness JSON-LD, where "Wyoming" and "WY" are different strings to a
//     search engine reading two of your pages;
//   - carriers, which want the code.
//
// Only US and CA get a list. Most countries have no subdivision set worth constraining a form to, and a
// half-populated dropdown is worse than a text box — `subdivisionsFor` returns null and the caller keeps
// the free-text input.

export const US_STATES = [
  ["AL", "Alabama"], ["AK", "Alaska"], ["AZ", "Arizona"], ["AR", "Arkansas"], ["CA", "California"],
  ["CO", "Colorado"], ["CT", "Connecticut"], ["DE", "Delaware"], ["DC", "District of Columbia"],
  ["FL", "Florida"], ["GA", "Georgia"], ["HI", "Hawaii"], ["ID", "Idaho"], ["IL", "Illinois"],
  ["IN", "Indiana"], ["IA", "Iowa"], ["KS", "Kansas"], ["KY", "Kentucky"], ["LA", "Louisiana"],
  ["ME", "Maine"], ["MD", "Maryland"], ["MA", "Massachusetts"], ["MI", "Michigan"], ["MN", "Minnesota"],
  ["MS", "Mississippi"], ["MO", "Missouri"], ["MT", "Montana"], ["NE", "Nebraska"], ["NV", "Nevada"],
  ["NH", "New Hampshire"], ["NJ", "New Jersey"], ["NM", "New Mexico"], ["NY", "New York"],
  ["NC", "North Carolina"], ["ND", "North Dakota"], ["OH", "Ohio"], ["OK", "Oklahoma"], ["OR", "Oregon"],
  ["PA", "Pennsylvania"], ["PR", "Puerto Rico"], ["RI", "Rhode Island"], ["SC", "South Carolina"],
  ["SD", "South Dakota"], ["TN", "Tennessee"], ["TX", "Texas"], ["UT", "Utah"], ["VT", "Vermont"],
  ["VA", "Virginia"], ["WA", "Washington"], ["WV", "West Virginia"], ["WI", "Wisconsin"], ["WY", "Wyoming"],
];

export const CA_PROVINCES = [
  ["AB", "Alberta"], ["BC", "British Columbia"], ["MB", "Manitoba"], ["NB", "New Brunswick"],
  ["NL", "Newfoundland and Labrador"], ["NS", "Nova Scotia"], ["NT", "Northwest Territories"],
  ["NU", "Nunavut"], ["ON", "Ontario"], ["PE", "Prince Edward Island"], ["QC", "Quebec"],
  ["SK", "Saskatchewan"], ["YT", "Yukon"],
];

/** The list for a country, or null when the field should stay free text. */
export function subdivisionsFor(country) {
  const code = String(country || "").trim().toUpperCase().slice(0, 2);
  if (code === "US") return US_STATES;
  if (code === "CA") return CA_PROVINCES;
  return null;
}

/**
 * A stored value healed to its code: "Wyoming" -> "WY", "wy" -> "WY", "WY" -> "WY".
 *
 * Returns the ORIGINAL when nothing matches, so a value we do not recognise is preserved rather than
 * silently blanked — losing a tenant's address because a list was incomplete would be a worse bug than
 * the one this fixes.
 */
export function normalizeSubdivision(value, country) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const list = subdivisionsFor(country);
  if (!list) return raw;
  const upper = raw.toUpperCase();
  for (const [code, name] of list) {
    if (upper === code || upper === name.toUpperCase()) return code;
  }
  return raw;
}
