# Semantic HTML & Heading Structure

## Why

A correct document outline — one `<h1>`, ordered `<h2>`/`<h3>`, no skipped levels, semantic landmarks — is
foundational for SEO, accessibility, and LLM parsing. It must be a **guaranteed property of the composer +
renderer**, automatic and non-negotiable (a quality baseline, per [[LANDING_PAGE_GOAL_COMPOSITION]]), not
something a tenant configures or can break. Two worked examples (a local service page and a DTC product page)
show the target shape: a keyword `<title>`, a benefit-led `<h1>` thesis, then a stack of `<h2>` sections each
with `<h3>` sub-items (benefits, service menu, science, FAQ, social proof, CTA).

## Current reality (why this is urgent)

The renderer emits **up to three `<h1>`s on one page** — `render_seo_title` (html.py:882),
`render_brand_label` (html.py:893), and `render_hero` (html.py:1058). Content blocks render `<h3>` with no
guaranteed governing `<h2>` (skipped level). There is no outline enforcement. This is exactly the kind of
defect a strict, structural approach prevents.

## The invariant (every page, always)

- **Exactly one `<h1>`** — the hero headline (the thesis). Demote brand label + on-page SEO title to
  non-headings (a site-name `<p>`/chip, not a heading competing with the hero).
- **Top-level content sections → `<h2>`**; **sub-items within a section → `<h3>`** (benefits, service/feature
  items, FAQ questions, science points). No skipped levels; document order = reading order.
- **`<title>` is distinct from `<h1>`**: title targets search intent/keywords
  ("Mobile Massage Therapy in [City] | In-Home Massage"); the `<h1>` is the benefit thesis
  ("Professional In-Home Massage Therapy in [City]"). This reinforces the brand/SEO-title (`head` channel) vs.
  hero-headline (`<h1>` body) split from [[SOCIALITE_PARITY]].
- Semantic wrappers throughout: `<main>`, `<section>`, `<article>`, `<nav>`, `<footer>`, `<figure>`.

## Each element declares a semantic contract

Part of the element taxonomy (Builder Reframe): every element carries

- **heading role** (`h1` | `h2` | `h3` | `none`),
- **semantic wrapper** (`section` / `article` / `figure` / `nav` / `footer`),
- **landmark / ARIA** where relevant,
- optional **structured-data mapping** (FAQ → FAQPage, reviews → AggregateRating, service → Service) —
  derived, per the goal plan.

The **renderer owns heading levels** — an element's "heading" text renders at the level the outline dictates
by its position, not a tenant-chosen tag. So the outline is correct by construction.

## The content pattern (from the examples)

The body is a stack of `<h2>` sections, each optionally with `<h3>` sub-items:

- Benefits / value props (`h2` + `h3` features)
- Service menu / product features (`h2` + `h3` long-tail items)
- Science / credibility (`h2` + `h3`)
- Social proof / testimonials (`h2`)
- FAQ (`h2` + `h3` questions → FAQPage schema)
- CTA (`h2`)

So the composable content element supports: one section heading (`h2`) + N sub-items (`h3` title + body). FAQ
is the specialized case (question = `h3`, plus schema).

## Enforcement (strict)

- A **publish-time outline validator**: exactly one `<h1>`, no skipped levels, no empty headings. Block the
  egregious (zero/multiple `<h1>`); warn on the rest (quality-baseline nudges, never silent).
- Concrete first fixes: single-`h1` (hero only); demote seo_title/brand_label; ensure every content section
  has an `<h2>` before any `<h3>`.

## Ties

- **Quality baseline** — automatic, non-negotiable, warnings not gates.
- **Discoverability pack** — heading structure + structured data are derived together from the same composed
  sections.
- **Build with AI** — the AI fills a semantic skeleton (`h2`/`h3` slots) so output always has a valid outline,
  and writes a keyword `<title>` separate from the benefit `<h1>`. The skeleton is the guardrail.
- **Element taxonomy / Builder Reframe** — the semantic contract is a per-element property.

## Open decisions

- How deep sections may nest (`h3` only, or `h4` for long pages).
- Validator strictness per rule (warn vs. block).
- `<title>` generation: templated + derived (`[Service] in [City] | [Modifier]` from offer + Business Profile)
  vs. manual, vs. AI-written.
