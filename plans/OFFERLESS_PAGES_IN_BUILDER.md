# Offer-less pages in the builder (storefront / category / profile)

**Status:** **P1 SHIPPED** (commit `3d6dcd7`, 2026-10-22). P2–P5 not built. Decided 2026-10-22.

## 1. The finding

Storefront, category and store-profile pages are **functionally complete** — they validate, resolve their
Collection against the Site route map, render, and route on the custom domain. They are also, every one of
them, **published `noindex`**, and the tenant has no way to change that.

Two gates run in sequence at publish. Both were replayed against a Site in its best possible state
(`hosting.verification.verified = true`, `indexing.eligibility = "eligible"`, seo on, not archived, prod,
live mode, published artifact):

```
                      gate 1 (custom domain)   words   FINAL
storefront            index,follow               11    noindex,follow
category               index,follow                5    noindex,follow
profile                index,follow               15    noindex,follow
offer page (control)   index,follow              108    noindex,follow
```

- **Gate 1** — `page_robots_directive()` (`runtime/html.py:2250`). Requires a verified custom domain AND
  verified Stripe Connect. This is the convention everyone remembers, it works, and the dashboard already
  states it (`Sites.vue:1195`). **Not the problem.**
- **Gate 2** — the thin-content demotion (`runtime/publishing.py:1434`), 150 words of unique body text.
  This is what demotes all four.

### On offer pages gate 2 is correct behaviour, not a bug

```
offer page, no goal                108 words  NOINDEX
offer page, goal=paid_ads          201 words  ok
offer page, goal=search_seo        166 words  ok
offer page, goal=social            136 words  NOINDEX
offer page, goal=email_list        108 words  NOINDEX
offer page, goal=minimal           108 words  NOINDEX
```

The two goals whose packs seed `content_block` + `faq` are exactly the two that clear the floor. The goal
axis is already the escape hatch and it earns its keep. A bare page is genuinely thin.

### The three offer-less page types are the only pages with no escape hatch

- No goal step (the wizard runs Site → Type → Details for them; `wizardStepLabels`, line 4496).
- No content elements. The wizard's three steps offer store name, tagline, logo, grid picks, category and
  heading — **no prose field anywhere**.
- No builder. `editPage()` (line 7274) routes them back to the wizard via `isStorefrontPage()`.
- No warning. `thin_content_warnings()` is only surfaced through the builder's preview
  (`page_health`, `LandingPages.vue:3807`), which these pages never reach.

A profile page given a 112-word business description still measures **115 words**. There is no authoring
path to 150 for any of the three.

## 2. Decision

**Route offer-less pages through the real builder** (author's choice, 2026-10-22), rather than adding prose
fields to the wizard. The builder already owns content elements, the live preview, the page-health warning,
placement bands and `section_order`. A second authoring surface would drift from it, and would have to grow
its own copy of all four.

## 3. The prerequisite nobody expects

An offer-less page has no offer, so `composition_key({})` returns **`single`** — and under `single`:

```
offer_price_selector   governed=True   visible=True
checkout_cta           governed=True   visible=True
hero                   governed=True   visible=True
trust_badges           governed=True   visible=True
```

`builderSectionCandidates()` *constructs* sections from builder state gated on `sectionVisible(key)`. Open a
storefront in the builder today and it would offer — and emit — a price selector and a Buy CTA on a page
with nothing to sell. **This is why the guard exists.** The guard is a symptom; the missing composition
entry is the cause.

The renderer is unaffected only by luck of direction: `compose_page()` filters `page.sections` and derives
head/shipping, it never *adds* body sections, and `brand_hero` / `catalog_grid` / `seller_profile` are
ungoverned so they always pass. Nothing protects the builder, which writes rather than reads.

## 4. Work

In dependency order. Each step is independently shippable.

### P1 — Teach composition the three shapes — SHIPPED 2026-10-22 (`3d6dcd7`)

Built as **two** compositions, not three: `storefront` serves the storefront homepage *and* category pages,
because their section lists are identical — splitting them the day they genuinely differ is additive.
`store_profile` is the other. Both derive from the page's own sections (`offerless_composition`), and
`page_composition_key(page, offer)` puts the offer first so a link-in-bio page holding a `catalog_grid`
still composes as `lead_social`. `composition_key(offer)` is unchanged.

Two things the tests caught that reading had not:

- `tests/test_tip_jar.py` pins, as an exact set, that the tip-jar element is offered on the link hub and
  nowhere else. Both new types failed it. Honoured rather than loosened — a recorded decision outranks a
  fresh "seems plausible".
- **The Vue mirror disagreed with Python.** `if offer:` is right in Python (`{}` is falsy); the direct
  translation `if (offer)` is wrong in JS (`{}` is truthy), so the builder would have composed these pages
  as `single` — the very thing P1 exists to prevent — while the publisher composed them correctly. Pinned
  by `tests/test_offerless_composition_parity.py`, which evaluates both sides against each other and was
  verified to go red on the bug.

One property worth knowing before P2: `is_section_visible` short-circuits on ungoverned keys *before*
consulting `excludes`, so an exclusion is render-enforced for a governed section and
**builder-enforced only** for an ungoverned one. That is fine — the Add-content menu is the only way such
a section enters a document — but it means P2 must not assume the renderer will filter them.

*Original plan for this step, kept for the record:*

`composition_rules.json` gains `offer_types` entries for `storefront`, `category`, `profile`, and
`composition_key()` / `deriveOfferType()` learn to return them for an offer-less page. Derive the key from
the page's own sections — the same signal `is_offerless_page()` and `pageAttachKind()` already use — not
from a new stored field, so existing pages need no migration.

Base sections per shape:

| Shape | Sections | Excludes |
|---|---|---|
| `storefront` | `brand_hero`, `catalog_grid`, `legal_footer` | price/CTA/refund/shipping/countdown |
| `category` | `brand_hero`, `catalog_grid`, `legal_footer` | same |
| `profile` | `brand_hero`, `seller_profile`, `legal_footer` | same, plus `catalog_grid` |

All three allow the content-bearing elements: `content_block`, `faq`, `photo`, `info_cards`,
`client_marquee`, `testimonials`, `rating`.

Pinned by a test asserting no transactional section is visible under any of the three — the regression that
would otherwise put a Buy button on an About page.

### P2 — Let the builder read and write the three sections

`builderSectionCandidates()` cannot emit `brand_hero`, `catalog_grid` or `seller_profile` today; all six
emissions live in the wizard's document builders (lines 4840, 5021, 5031). `populateBuilderFromPage()`
cannot hydrate them either. Both need the three section types, reusing the wizard's existing field set
(headline, tagline, logo_url / collection_id, heading).

Then drop the `isStorefrontPage()` guard in `editPage()`. The wizard keeps creating these pages — it is a
good creation flow — and the builder takes over editing, exactly as it does for offer pages.

Server side needs nothing: `page_render.py:68` already accepts `offer: null` for an offer-less page, so the
preview and its `page_health` warnings work the moment the builder opens one.

### P3 — Give them the goal step

Once P1 exists, `offer_type x goal` composes for these shapes like any other, so a storefront can be
"search-friendly" and get the same `content_block` + `faq` seeds that take an offer page from 108 to 166
words. Add the Goal step to the offer-less wizard path (`wizardStepLabels`).

### P4 — The two SEO defects found alongside

- **No structured data on storefront/category.** `render_catalog_grid()` (`html.py:7628`) emits no JSON-LD
  at all — no `CollectionPage`, no `ItemList`. The about page emits `Organization` + `CollectionPage` +
  `PostalAddress`; the two page types that actually *carry* the catalog emit nothing. Emit `CollectionPage`
  with an `ItemList` of the resolved grid items.
- **Meta description is a bare CTA.** With no `seo.description` — which the wizard never writes —
  `document_description()` falls through to the rotating CTA pool, so all three publish
  `Get yours today!`. Identical across every offer-less page on a Site, and wrong on an About page. Derive
  per shape from the Site organization / category / collection heading.

### P5 — The sitemap (separate, larger)

`publish_site_crawl_files()` (`publishing.py:1705`) writes **exactly one URL**, the homepage. Even once
these pages are indexable, nothing advertises them. Tracked separately — it is a Site-level change, not a
page-level one.

## 5. Definition of done

- A storefront, category or profile page opens in the builder, takes content elements, and shows the same
  live preview and page-health warnings an offer page does.
- No transactional section is reachable on any of the three (test-pinned).
- A tenant who adds content can get the page over 150 words and see it publish `index,follow` on a verified
  custom domain.
- Storefront and category pages emit `CollectionPage` + `ItemList`.
- No page publishes `Get yours today!` as its meta description.

## 6. What was explicitly ruled out

- **Prose fields in the wizard** — ships faster, but a second authoring surface that drifts from the
  builder and carries neither the preview nor the health warning.
- **Lowering the 150-word floor.** The floor is right; these pages are genuinely thin. Lowering it to let
  an 11-word page index is the doorway shape the gate exists to prevent.
- **Exempting offer-less pages from the thin-content gate.** Same objection, with the added cost that the
  exemption would have to be remembered forever.
