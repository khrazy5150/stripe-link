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
- Next axis: **goal / traffic source** as a second composition input (offer_type × goal), driven by a new
  wizard step and capability packs — see plans/LANDING_PAGE_GOAL_COMPOSITION.md.

## Follow-up — Socialite Parity

Bring stripe-cart's popular "socialite" feel into the single template as a preset family + two elements
(`profile_avatar`, brand `overlay`+`position`), reusing the legacy CSS/presets verbatim — see
plans/SOCIALITE_PARITY.md. A concrete first exercise for the element taxonomy below.

## Follow-up — Landing Page Builder Reframe

**Reclassify each element in the builder that can be added to a landing page.** One vocabulary across the
config, composer, builder panels, and saved page — the canonical key is the section `type` (no aliases).

- **Slice 1 (shipped):** the canonical **element catalog** now lives in `composition_rules.json` under
  `elements` — every section declares `label / ui (fixed|toggle|add|internal) / kind (core|capability) /
  channel (body|head|sidecar) / heading_role / repeatable / tokens`. The `section_key_by_type` aliasing is
  retired: `section_key` is identity, `governed_sections` + `offer_types[].sections` use type strings.
  Python (`domain/composition.py`) and Vue (`composables/pageComposer.js`) both expose `element` /
  `element_label` / addable-elements from it; the builder's `ELEMENT_TYPES` and `SECTION_KEY_LABELS`
  duplication is gone (labels come from the catalog). Behavior identical. (Note: a pre-existing
  `composition.overrides` keyed by the old `brand` alias would need re-toggling to `brand_label`; other
  keys unchanged.)
- **Slice 2 (next):** unify the builder's separate "Page Elements" (add) and "Page Sections" (toggle) panels
  into one catalog-driven Sections panel keyed by `ui`.
- **Later:** the catalog's `heading_role` powers plans/SEMANTIC_HTML.md; its `tokens` power
  plans/ADVANCED_COLOR_SETTINGS.md; `channel` powers the head/sidecar output in
  plans/LANDING_PAGE_GOAL_COMPOSITION.md.

## Resolution — one renderer, not two (shipped)

The Composer made preview and published *agree on which sections exist*, but they still **drew** those
sections with two different implementations: `runtime/html.py` for the published page, and hand-written Vue
markup for the builder's Live Preview. Every section was implemented twice, so every section could drift
twice. That is what produced the `client_marquee` bug: the section saved correctly, `render_client_marquee`
rendered it correctly, the composer said it was visible — and the Vue twin silently drew nothing.

The Live Preview now **renders through the published renderer**:

```
Vue builder
   | edits
   v
landing-page.json  (buildBuilderPageDocument)
   |
   +-- POST /pages/render --> render_page() --> HTML --> iframe   (Live Preview)
   |
   +-- Save --> PagesTable --> stream --> render_page() --> S3    (Published page)
```

One JSON, one renderer, two consumers. No backend work was required — `handlers/page_render.py`
(`POST /pages/render`) already accepted a draft page + offer + products and returned rendered HTML; the
builder simply had never called it. The Vue twin (~183 lines) is deleted, along with the preview-only
ConversionContext plumbing that existed to drive it.

**Consequences worth knowing:**

- Preview is debounced (~400ms) instead of keystroke-instant. That is the price of "same bytes by
  construction", and it is worth paying.
- The render POST **must** send `api_base_url`: the page document deliberately stores no legal URLs
  (`legalLinks()` returns `{}`) and `render_legal_footer` builds the platform `/legal/*` hrefs from it.
  Without it the footer links silently vanish.
- Scroll position is captured/restored across the srcdoc swap, and byte-identical HTML skips the reload.
- Because the preview is now the real renderer, it surfaces real rendering bugs the twin used to hide —
  e.g. `responsive_img()` emits a srcset over all five `IMAGE_RENDITION_WIDTHS`, but the processor writes
  renditions asynchronously (`full.webp` lands last), so a just-uploaded image can 404 briefly. The builder
  repaints the frame a few seconds after an upload to let it heal. **Do not "fix" this by probing for the
  pending rendition:** the CDN answers 403 for a missing object and caches it, which converts a
  self-healing race into a permanently broken image. The real fix belongs in the image pipeline (write all
  renditions atomically, or emit a srcset of only what exists).

**Follow-up:** the twin left dead code behind — the price-preview cluster (`previewPrices`,
`selectedPreviewPrice`, `previewDefaultPriceId`, `selectPreviewPrice`, `isPreviewPriceSelected`,
`ctaShowsPrices`, `previewCtaLabel`), `previewRefundAppliesTo` / `previewRefundReturnNote`,
`defaultLegalLinks` / `defaultFooterCopyright`, `headlineHtml`, `listicleAddLabel`, `builderLeadAction`.
Harmless but should be removed.
