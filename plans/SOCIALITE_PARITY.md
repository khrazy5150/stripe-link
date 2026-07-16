# Socialite Parity

## Why

Stripe-cart's most popular template, **socialite**, put a "face behind the business" above the fold (a profile
avatar) and baked the brand name *into* the hero image (so toggling it never shifts layout), with a set of
social-media color presets. Now that stripe-link uses one template + the Page Composer + presets, "socialite"
isn't a template to resurrect — it's **a preset family + two elements**. This plan brings that feel into the
single template and reuses the legacy CSS/presets verbatim (stripe-cart is the behavioral spec — don't
reinvent). Ties to [[PAGE_COMPOSER]] (elements/channels) and the goal axis
([[LANDING_PAGE_GOAL_COMPOSITION]]).

## Source (turnkey — lift, don't rewrite)

- `stripe-cart/templates/socialite.js`
  - `TEMPLATE_COLOR_SCHEMES` (~lines 40–100): the palettes (LinkedIn Blue, Instagram Gradient, TikTok Dark,
    + a couple more incl. YouTube Red). Each carries `bg / card / ink / muted / brand / accent /
    headlineColor / ctaGradient[2] / ctaText / ctaLayeredEffect? / chip{Bg,Text,Border} /
    savings{Bg,Text,Border} / avatarGradient? / avatarBorder / isDark`.
  - Hero-overlay CSS (~lines 743–749):
    - `.sl-hero-brand{position:absolute;top:16px;right:16px;background:rgba(0,0,0,.5);
      backdrop-filter:blur(8px);padding:8px 14px;border-radius:999px;font:700 11px;letter-spacing:.1em;
      text-transform:uppercase;color:rgba(255,255,255,.9)}` + `.sl-hero-brand-dot` (brand-colored dot).
    - `.sl-avatar-wrap{position:absolute;bottom:-58px;left:24px;z-index:10}` (+ optional gradient ring when
      `avatarGradient`), `.sl-avatar{115px circle;4px border}`, `.sl-avatar-placeholder` (initials on a
      brand→accent gradient).
  - CTA gradient: `linear-gradient(135deg, ctaGradient[0], ctaGradient[1])` (+ layered effect for TikTok).
- Section schema: `stripe-cart/dist/dashboard/js/template-schemas.js` (~line 227) — socialite = Universal
  Bundle + `lpAvatarImage` (avatar-picker) in the hero section + `seo_title` as the brand.

## Deliverable 1 — Social presets (independent, low risk, ship first)

Port `TEMPLATE_COLOR_SCHEMES` into stripe-link presets (Vue `universalBundlePresets` + the server/preview
token blocks). Two new gradient-capable tokens are the only real additions:

- `--sl-cta-bg` — solid color OR `linear-gradient(...)` (drives the buy button). Existing solid presets set it
  to their brand color; social presets set the gradient.
- `--sl-avatar-ring` — the gradient ring behind the avatar (Instagram/TikTok); empty = plain bordered avatar.

Palette-key → token mapping (mechanical; most already exist): `brand→--sl-brand`, `accent→--sl-accent`,
`bg→--sl-background`, `card→--sl-price-card-bg`, `ink→--sl-text`, `muted→--sl-muted`,
`headlineColor→--sl-headline`, `chip*→--sl-trust-badge-*`, `savings*→--sl-savings-*`,
`ctaGradient→--sl-cta-bg`, `avatarGradient→--sl-avatar-ring`, `avatarBorder→--sl-avatar-border`,
`isDark→dark theme flag`.

## Deliverable 2 — `profile_avatar` element

The "face behind the business" — a circular avatar overlapping the hero (bottom-left). Element taxonomy:

- **type** `profile_avatar`, **channel** `body` (hero overlay), **kind** `capability`.
- **offer_types** service / appointment (recommended); hidden elsewhere by default — the composer already
  does this.
- **data**: an image field now; **later derives from the Business Profile / practitioner**
  ([[BUSINESS_PROFILE_AND_GBP]]) so it isn't re-uploaded per page.
- **render**: lift `.sl-avatar-wrap` / `.sl-avatar` / placeholder CSS; needs the hero as a positioning
  context.

## Deliverable 3 — Brand overlay (+ positionable, our improvement)

The brand as a hero chip, from the SEO Title. Extend the existing brand element rather than add a section:

- **channels**: `head` (SEO title ALWAYS sets `<title>`) + optional `body` (the chip). A `show_on_page`
  toggle controls only the visible chip — matches legacy ("stays in `<title>` when unchecked").
- **placement**: `above` (today's separate label) | `overlay` (on the hero).
- **position** (overlay only, improves on legacy's fixed top-right): `top-left | top-right | bottom-left |
  bottom-right` → four corner classes over the lifted `.sl-hero-brand` base.
- **render**: lift `.sl-hero-brand` + dot; because it's on the hero, toggling it never shifts layout (the
  space-saving win).

## The one shared prerequisite

The avatar and brand chip are both hero overlays, so the hero container becomes a positioning context
(`position: relative`) and both must stack cleanly on mobile. Do this once; every preset inherits it.

## Phasing

1. **Presets** — port palettes + add `--sl-cta-bg` / `--sl-avatar-ring` tokens. Independent; ship first.
2. **profile_avatar** element (service/appointment-scoped via the composer).
3. **Brand overlay** — placement + position + show_on_page.
4. Later: derive avatar + brand from the Business Profile.

## Open decisions

- Full palette list to port (confirm YouTube Red + any others beyond the three read).
- Default brand placement per offer_type/preset (overlay for social presets, above for others?).
- Whether `profile_avatar` is its own element or a field on the hero_media section (leaning: own element, for
  composer/offer_type scoping).
