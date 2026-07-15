# Page Composer

## Problem

Three responsibilities were tangled together, and two of them silently disagreed:

1. **Data expansion** — `Offer → expand_offer() → ExpandedOffer`. Already unified: both the published page and
   the builder preview consume the same `expand_offer()` projection, so pricing can't drift.
2. **Page composition** — given `offer_type = listicle`, *which sections exist?* (Hero yes; Trust Badges no;
   FAQ no; Price Card yes; …). This is **business logic**, and it was decided in two places:
   - the builder's `builderSections()` (which the published page renders, baked into `page.sections`), and
   - the preview template, which rendered trust badges / elements / refund **unconditionally**.
   → trust badges appeared in the preview but vanished on the published page. **Drift.**
3. **Rendering** — `Section → Python HTML` or `Section → Vue component`. Just implementations.

## Principle

**The renderer never decides whether a section exists. The composer decides. Both renderers obey.**

```
Offer + Landing Page JSON
        │
        ▼
   Page Composer      ← ALL composition rules live here (business logic)
        │
        ▼
 Renderable Page Model (sections, each annotated visible + reason)
        │
   ┌────┴────┐
   ▼         ▼
 Vue        Python
 preview    HTML
```

Once both renderers consume the **same** composed model, "shows in preview but not on the live page" is
structurally impossible.

## The model: mark, don't remove

A composed section is annotated, not deleted:

```jsonc
{ "type": "trust_badges", "visible": false, "reason": "offer_type_default" }
{ "type": "trust_badges", "visible": true,  "reason": "user_enabled" }
```

`default ≠ forced`: an `offer_type` hides a section by default, but the tenant can opt it back in. The
composer applies `user_enabled` / `user_disabled` overrides on top of the `offer_type` defaults.

## Composition rules (v1)

`OFFER_TYPE_DEFAULT_HIDDEN` — per `offer_type`, the section types hidden by default:

- **listicle** (TikTok-Shop focus — hero + price cards + CTA only): `trust_badges`, `checkout_cta`
  (the add-to-cart lives inside the price card), `refund_policy`, `content_block`, `testimonials`,
  `rating`, `client_marquee`, `faq`, `product_details`.
- **single / bundle / lead / service / …**: nothing hidden by default (all sections visible).

Always-visible core (never hidden): `brand_label`, `hero_media`, `hero`, `offer_price_selector`,
`legal_footer` (+ `countdown_timer` when enabled).

New `offer_type`s (membership, appointment, …) just add a row — the renderers never change.

## Cross-language realization

Python renders at **publish** (static HTML, immutable pages); Vue composes + renders the **live** preview.
There is one composer decision point:

- **Phase 1 (this):** the composer lives in the builder (`sectionVisible()` / the `OFFER_TYPE_DEFAULT_HIDDEN`
  table). `builderSections()` AND the preview both consult it, so the saved/published section list and the
  preview always match. Python is the obeying renderer of the baked `page.sections`. Zero drift on what
  actually renders.
- **Phase 2:** persist `visible` + `reason` on each section; add a Python `compose_page(offer, page)` that
  re-derives visibility from a **shared rules table** (so old pages can pick up rule changes without a
  Vue round-trip), and the builder's **"Add Section" menu** groups *Recommended for this offer type* vs
  *Other available sections*, letting the tenant opt hidden sections back in (`reason: user_enabled`).

## Realization (as built)

- **Shared rules file**: `src/stripe_link/composition_rules.json` — an ALLOW-LIST of default-visible section
  keys per `offer_type` (+ `allowed_ctas`), a `governed_sections` set, and a `section_key_by_type` alias
  (brand_label→brand, offer_price_selector→offer_selector, checkout_cta→cta). Bundled with the Lambda
  (verified in the `sam build` artifact) AND imported by the Vue builder (`vite fs.allow: ['..']`). One file,
  no duplication.
- **Python** (`domain/composition.py`): `compose_page(offer, page)` filters `page.sections` by
  `is_section_visible(offer_type, type, overrides)`. `render_page` iterates only the composed list.
- **Vue** (`composables/pageComposer.js`): the same functions from the same JSON. The preview and
  `builderSections()` both call `sectionVisible()`.
- **Overrides (compact map)**: `page.composition.overrides = { <section_key>: { enabled } }` — only deviations
  from the offer_type default are stored (`toggleSection` drops the key when it equals the default). Restored
  into `builder.composition.overrides` on edit.
- **Builder UI**: a **Page Sections** panel lists the togglable governed sections (brand, trust badges,
  refund) with a Recommended/Optional tag per offer_type and a checkbox that writes an override.
- **Ungoverned body elements** (testimonials, faq, …) always render when present — adding one IS the opt-in,
  so a listicle can host them without a rule change (`default ≠ forced`). A listicle's CTA stays in the price
  card, so no standalone `checkout_cta` section is emitted for it.

## Status

- Phase 1: shipped — preview + saved list both obey `sectionVisible()`; the listicle drift is gone.
- Phase 2: shipped to dev — shared rules file, Python `compose_page`, compact overrides persisted +
  restored, and the Page Sections opt-in panel.
- Future: expose `allowed_ctas` to the ActionBar work; group the composable-element "Add" buttons under the
  same Recommended/Other framing.

## Follow-up — Landing Page Builder Reframe

**Reclassify each element in the builder that can be added to a landing page.** Recreate and reorganize the
builder so naming is consistent end to end: every addable/toggleable thing is a "section" with one canonical
key that matches the composer's `section_key` (today the builder mixes "elements" — testimonials, faq — with
"sections" — trust badges, refund — and with governed keys that alias, e.g. brand_label→brand). One
vocabulary across the config, the composer, the builder panels, and the saved page. Not yet built.
