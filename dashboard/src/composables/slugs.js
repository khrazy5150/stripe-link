// Slug rules — the JS MIRROR of src/stripe_link/domain/slugs.py.
//
// The server is always authoritative: it alone sees every existing slug at write time, and another tab can
// claim one between a preview and a save. This mirror exists so the builder can show the tenant the slug
// they will actually get, instead of one the server silently renumbers on save.
//
// The two implementations are held together by tests/fixtures/slug_cases.json, which BOTH suites run. An
// algorithm can't be shared across runtimes the way composition_rules.json is, so the FIXTURES are shared.
// Change a rule here and you must change slugs.py, or the parity test fails.

export const FALLBACK_SLUG = "offer";

export const STOP_WORDS = new Set([
  "the", "a", "an", "and", "or", "for", "of", "with", "to", "in", "on", "at", "by", "from",
  "your", "you", "our", "my", "this", "that", "is", "are", "plus",
]);

// ASCII-only on purpose: a non-Latin name degrades to its ASCII remnant rather than emitting
// percent-encoded bytes, which are unreadable in a URL bar and worthless as a search signal.
export function sanitizeSlug(value, fallback = FALLBACK_SLUG) {
  const slug = String(value ?? "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return slug || fallback;
}

export function slugTokens(text, limit = 0) {
  const words = String(text ?? "").toLowerCase().split(/[^a-z0-9]+/).filter((w) => w && !STOP_WORDS.has(w));
  return limit ? words.slice(0, limit) : words;
}

// `taken` must already have the caller's OWN current slug removed — an entity being re-saved must not
// collide with itself and renumber its own live URL.
export function uniqueSlug(desired, taken, fallback = FALLBACK_SLUG) {
  const base = sanitizeSlug(desired, fallback);
  const used = taken instanceof Set ? taken : new Set(Array.from(taken || []).map(String));
  if (!used.has(base)) return base;
  let candidate = base;
  let suffix = 2;
  while (used.has(candidate)) {
    candidate = `${base}-${suffix}`;
    suffix += 1;
  }
  return candidate;
}
