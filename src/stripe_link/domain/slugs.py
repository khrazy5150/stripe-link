"""Slug rules for the whole application — one implementation, not one per entity.

Offers were the first thing to need slugs; products, services and anything else that earns a URL will
need exactly the same rules. Keeping them here means a new entity type inherits the rules instead of
re-deriving them slightly differently, which is how "workout-bundle" and "dietary-supplement-bundle"
came to describe the same offer.

The JS mirror is dashboard/src/composables/slugs.js. The two are held together by
tests/fixtures/slug_cases.json, which BOTH test suites run — parity by shared fixtures, because an
algorithm cannot be shared across the runtimes the way composition_rules.json is.
"""

import re

FALLBACK_SLUG = "offer"

# Dropped from generated slugs: they add length and no search value.
STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "for", "of", "with", "to", "in", "on", "at", "by", "from",
    "your", "you", "our", "my", "this", "that", "is", "are", "plus",
})


def sanitize_slug(value, fallback: str = FALLBACK_SLUG) -> str:
    """URL-safe slug: lowercase, non-alphanumerics collapsed to single hyphens, trimmed.

    Deliberately ASCII-only: a non-Latin name degrades to its ASCII remnant rather than emitting
    percent-encoded bytes, which are unreadable in a URL bar and worthless as a search signal.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or fallback


def slug_tokens(text, limit: int = 0) -> list[str]:
    """Meaningful lowercase words from free text, stop-words removed, optionally capped."""
    words = [w for w in re.split(r"[^a-z0-9]+", str(text or "").lower()) if w and w not in STOP_WORDS]
    return words[:limit] if limit else words


def unique_slug(desired, taken, fallback: str = FALLBACK_SLUG) -> str:
    """Sanitize `desired` and make it unique against `taken`, appending -2, -3, … on collision.

    `taken` is the set of slugs already in use, with the CALLER's own current slug removed — an entity
    being re-saved must not collide with itself and renumber its own live URL on every save.
    """
    base = sanitize_slug(desired, fallback)
    taken = {str(s) for s in (taken or ())}
    if base not in taken:
        return base
    candidate, suffix = base, 2
    while candidate in taken:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate
