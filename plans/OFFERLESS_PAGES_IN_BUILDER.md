# Offer-less pages in the builder (storefront / category / profile)

**Status:** **COMPLETE — P1–P5 ALL SHIPPED** 2026-10-22 (`3d6dcd7`, `2c13465`, `b1ab271`, `7607730`, `21fcd6e`). **P5 exercised for real on shop.coderbay.net 2026-10-23** (sandbox, live mode, verified custom domain): 2-URL sitemap, robots.txt, IndexNow, `/thank-you` correctly excluded. That run found a clobber in P5's own denormalization — fixed in `54fc69f`, see [[feedback-shared-document-read-modify-write]].

The outcome, proven end to end through the real publish gates on a verified custom domain:

```
storefront, as the wizard makes it      words=  11  noindex,follow   (+ warning now shown)
storefront + builder content            words= 168  index,follow
storefront + content, goal=search_seo    words= 168  index,follow  (+ structured_data composes)
```

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

### P2 — Let the builder read and write the three sections — SHIPPED 2026-10-22 (`2c13465`)

Four changes had to land together, two of which were not in the plan:

- `builderOfferType` reads `builder.offerless` first (mirrors `page_composition_key`); the flag is only set
  for a page with no `offer_id`, which is what makes the cheap read equivalent to the Python guard.
- **`builderIntent` now answers `"offerless"`.** Not in the plan and load-bearing: `offerIntent(null)`
  answers `"transaction"`, so every `intent === "transaction"` branch would have fired — minting a
  `post_checkout` thank-you page for a storefront, and enabling the `sale`/`flash_sale` priced views of an
  offer that does not exist.
- **The `offer_price_selector` push was gated on the intent alone** — the one structural push in
  `builderSectionCandidates` that did not also consult the composition. So P1's exclusion would have been
  bypassed and the page handed a price card bound to `offer_id: ""`. It now calls `sectionVisible()` like
  every push around it.
- `brand_hero` / `catalog_grid` / `seller_profile` became readable and writable, with editors.

**Grid membership stays out of the builder.** The Collection is the grid's source of truth and the publisher
re-resolves it against the Site route map on every publish, so editing the list in two places would let the
page and the Collection disagree. Dropping the guard orphaned `editOfferlessPage`, which owns exactly that,
so it kept its own menu entry ("Products & layout") instead of being deleted as dead code — removing it
would have been a capability regression dressed as a cleanup.

The emission and its inverse (`offerlessSections` / `offerlessState`) live in the shared composable, not the
component, which is both the CLAUDE.md rule and what makes `tests/test_offerless_builder_roundtrip.py`
possible: a wizard-created page round-trips through load-then-save unchanged, **section ids included** —
`section_order` and per-section overrides are keyed by id, so a renumbered id discards a tenant's
arrangement with no error.

Two existing tests needed re-pinning, each for a real reason: `test_offer_intent_derivation` asserted
`builderIntent` as one literal source line, and `test_lead_capture_page` sliced a fixed 3000 characters
after an anchor — four added lines pushed the headline fallback to offset 3315, so it reported a fallback
missing that was still there. A character count is a second fact about the file that nothing keeps true.

*Original plan for this step, kept for the record:*

`builderSectionCandidates()` cannot emit `brand_hero`, `catalog_grid` or `seller_profile` today; all six
emissions live in the wizard's document builders (lines 4840, 5021, 5031). `populateBuilderFromPage()`
cannot hydrate them either. Both need the three section types, reusing the wizard's existing field set
(headline, tagline, logo_url / collection_id, heading).

Then drop the `isStorefrontPage()` guard in `editPage()`. The wizard keeps creating these pages — it is a
good creation flow — and the builder takes over editing, exactly as it does for offer pages.

Server side needs nothing: `page_render.py:68` already accepts `offer: null` for an offer-less page, so the
preview and its `page_health` warnings work the moment the builder opens one.

### P3 — Give them the goal step — SHIPPED 2026-10-22 (`b1ab271`)

Same wizard markup as the offer path: the offer-less detail steps moved from step 2 to 3 and the shared
goal step fell into the gap, so there is one set of goal cards. Asked on **create only** — an existing
page's goal is changed in the builder's Page Settings, and re-asking it on the edit path would re-run the
seeding over content the tenant already owns.

Creating one now **continues into the builder** rather than closing the wizard. That is what makes the goal
mean anything here: seeds are empty elements in builder state, and `builderSections()` drops still-empty
elements on save, so a goal chosen and never shown to anyone seeds nothing.

**This plan was wrong about the seeds, and running it found out.** P3 was written claiming `search_seo`
already seeded `content_block` + `faq`. It seeded only `faq`; `ad_landing` is the pack with both. So the
SEO goal seeded less writing than the ads goal — backwards, since the 150-word demotion is the exact gate
the discoverability goal exists to pass. `discoverability` now seeds prose too.

**What it actually takes for a storefront to be indexed**, measured with both scaffolds filled at an
ordinary level of effort (one paragraph, three questions), on a verified custom domain:

```
products in grid     bare    + seeds filled
1                       9             125
3                      16             132
6                      27             143
12                     49             165  <- clears the floor
```

Two properties are pinned instead of the numbers: the grid's product titles and prices **are** indexable
content (not stripped chrome), so a real catalogue genuinely helps — an earlier reading looked worse than
reality purely because the fixture had one product; and the grid alone never clears the floor at any
catalogue size, because a page of tiles and nothing else is the doorway shape the floor exists to catch.

Three goal notes were corrected for a step that is no longer offer-only: `search_seo` still called
structured data "(later)" long after it shipped and advertised an `llms.txt` that does not exist, while
`email_list` and `minimal` said "the offer" to someone building a page that has none.

*Original plan for this step, kept for the record:*

Once P1 exists, `offer_type x goal` composes for these shapes like any other, so a storefront can be
"search-friendly" and get the same `content_block` + `faq` seeds that take an offer page from 108 to 166
words. Add the Goal step to the offer-less wizard path (`wizardStepLabels`).

### P4 — The two SEO defects found alongside — SHIPPED 2026-10-22 (`7607730`)

Catalog pages emit `CollectionPage` → `mainEntity` → `ItemList` of the grid's cards, read off the grid
**resolved** against the Site route map so it lists what a visitor sees. `ListItem` carries url + name and
deliberately **not** a nested Product/Offer — the listing page links, the product page already carries the
full markup, and restating prices would put one claim in two places that can disagree. Unlinkable entries
are dropped, matching `render_catalog_grid`. Wrapped in a `CollectionPage` only when nothing else claims to
be one, because `render_seller_profile` emits its own — an about page with a grid gets a bare `ItemList`
rather than two contradictory CollectionPage nodes for one URL. Goal-gated via `structured_data`, like an
offer page's Product markup.

**The description fix needed two attempts.** Leading with the business description for every shape — the
obvious implementation — gave a Site's storefront and its about page the same sentence word for word, which
is the duplicate footprint the fix was for. So the source now depends on the shape: an about page's subject
IS the business and leads with its description; a catalog page leads with what the page is and what is on
it. For one Site:

```
storefront  Probe Store — Good things, fairly priced. Browse 4 products.
category    Widgets from Probe Store. Browse 4 products.
profile     Probe Store has sold supplements out of Springfield, Oregon since 2014. We keep the range...
```

**P2 created an exposure that P4 had to fix.** `structured_data_warnings` opened with *"No price is shown
on this page, so no Product markup can be emitted."* On a storefront that describes correct, intended
behaviour and names nothing the tenant could do — and it was unreachable until these pages started opening
in the builder, so the fix is what exposed it. Offer-less pages are now checked against the markup *they*
can emit: an empty grid is warned about (publishing product pages fixes it), a missing business name on an
about page likewise, a working storefront not at all.

A finished storefront on a verified custom domain now publishes `index,follow`, a page-specific
description, and Organization + WebSite + CollectionPage(ItemList) + FAQPage.

*Original plan for this step, kept for the record:*

- **No structured data on storefront/category.** `render_catalog_grid()` (`html.py:7628`) emits no JSON-LD
  at all — no `CollectionPage`, no `ItemList`. The about page emits `Organization` + `CollectionPage` +
  `PostalAddress`; the two page types that actually *carry* the catalog emit nothing. Emit `CollectionPage`
  with an `ItemList` of the resolved grid items.
- **Meta description is a bare CTA.** With no `seo.description` — which the wizard never writes —
  `document_description()` falls through to the rotating CTA pool, so all three publish
  `Get yours today!`. Identical across every offer-less page on a Site, and wrong on an About page. Derive
  per shape from the Site organization / category / collection heading.

### P5 — The sitemap — SHIPPED 2026-10-22 (`21fcd6e`)

Publishing one product page on a twelve-route Site now writes six URLs — `/`, `/about`, `/gummies`,
`/protein`, `/sticks`, `/widgets` — each with `lastmod` and its own images, and leaves out the
`/gummies/sale` context view, `/upsell`, `/thank-you`, a disabled draft route, a thin-content demoted page,
and a page that has not published since this existed.

Indexability **cannot be recomputed** cheaply — the thin-content demotion depends on the rendered word
count, so only the publisher knows it and only at the moment it rendered. Each publish therefore records
`indexable` / `lastmod` / `images` on its own Site route entry (`_denormalize_page_crawl`) and the sitemap
is built from the route map. Absent `indexable` means "not published since this existed" and the page is
left out.

One entry per PAGE at its own address, keyed by page_id via `site_page_slug` — which already owns the rule
that a reserved funnel slug is not a page's address. The `/sale` and `/flash-sale` views are the same page
at a different price, so listing both would be submitting our own duplicate content.

**Two bugs the function had been carrying, neither covered — there were no tests for
`publish_site_crawl_files` at all, which is also why nothing failed when it changed:**

- The files were written under the page **currently publishing**, while `custom_domains_resolve` serves
  `/sitemap.xml` from `{target_page_id}/sitemap.xml`, the Site's **root** page. Publishing anything but the
  homepage wrote all three files to a prefix nothing reads. Harmless while the sitemap only described the
  homepage; fatal to P5.
- **IndexNow was always pinged with the root**, so publishing a product page told the crawler to re-fetch
  the one URL that had not changed. It now submits the page that published.

The denormalization sits in its **own** try, not the route-attach block below it: that block swallows
everything so a route failure cannot block a publish, so a bad Site write sharing it would have skipped
`_sync_domain_index` and left the edge resolver stale with nothing said.

*Original plan for this step, kept for the record:*

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
