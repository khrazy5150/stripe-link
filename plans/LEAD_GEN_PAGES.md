# Lead-generation pages

Status: PLANNED 2026-09-10, not built. Supersedes the entry point described in
`SOCIAL_MEDIA_PAGES.md` §2 (see §2a there for why `offer_type` was the wrong lever).
Related: `SOCIAL_MEDIA_PAGES.md`, `LEAD_CAPTURE.md`, `PAGE_COMPOSER.md`, `FORM_BUILDER.md`.

---

## 1. The problem

A lead-gen offer currently builds a **checkout page with the price hidden**. Observed on a real page
2026-09-10: trust badges, a refund policy, the product name used as both brand and headline, and a
"Social page" CTA redirecting to one profile. None of that belongs on a page that sells nothing.

The composer already switches on `product_intent` (shipped 2026-09-10), which removes the price selector.
That is not enough: the seven lead-capture actions want genuinely different pages, and the composer cannot
see which action a page is for.

## 2. Seven actions, FOUR page shapes

| action | shape | CTA |
|---|---|---|
| `capture_email` | **Capture form** | the CTA *is* the form |
| `capture_phone` | Capture form | ditto |
| `capture_email_phone` | Capture form | ditto |
| `call_number` | **Call** | click-to-call |
| `external_url` | **Bridge** | one outbound button |
| `social_redirect` | **Link-in-bio** | **none** — the cards are the actions |
| ~~`open_form`~~ | **REMOVED** — see §6 | — |

## 2a. The goal axis could resurrect them — FIXED 2026-09-10

Diagnosed from a real saved document: a capture-email page carrying trust badges and a refund policy with
`composition.overrides` EMPTY. The offer_type composition omitted both; they came back anyway.

The cause is the GOAL axis. `default_visible` is `key in base OR key in goal_sections(goal)`, and the
`paid_ads` pack turns on `trust_badges` and `refund_policy`. Goals are union-only by design (so that
no-goal keeps the old behaviour and needs no migration) — they ADD and can never subtract. On a
paid-traffic CHECKOUT page that is right: cold traffic wants reassurance. On a page that takes no money it
is incoherent.

**A composition can now declare sections IMPOSSIBLE** (`offer_types.<type>.excludes`), and an exclusion
outranks BOTH the goal union and a tenant override. Everything else in the composer is a preference; this
is a statement about what the page IS. A refund policy on a page that cannot take money is not
unfashionable, it is wrong.

Mirrored in `pageComposer.js`, since preview and published each implement the visibility logic over the
shared rules file.

## 2b. The goal question: kept for three shapes, skipped for one (decided 2026-09-10)

"Should a lead-gen page have a goal at all?" was asked on the premise that nobody pays to drive traffic to
a capture page. That premise is wrong — paid lead-gen is a large category in its own right (Meta has a
"Leads" campaign objective; Google has lead-form extensions), and lead magnet + paid ads is a textbook
acquisition play. Call pages are the backbone of local-services advertising.

The useful question is not "would anyone buy traffic for this?" but "does the goal change anything here?"
After §2a's exclusion, what each goal still contributes to a lead page is its SEEDS:

| goal | sections on a lead page | seeds |
|---|---|---|
| `paid_ads` | none (excluded) | content_block, faq |
| `search_seo` | structured_data | faq |
| `social` | none | testimonials, rating, client_marquee |
| `email_list` | none | none — a tautology for a capture page |
| `minimal` | none | none |

So capture, call and bridge KEEP the step: the seeds genuinely help, and social proof on a capture page
converts.

**The link-in-bio page skips it entirely, forced to `minimal`.** It is the one shape with no question to
answer — its traffic is always a tap from a bio field — and every pack seeds the wrong thing for it.
Skipped rather than pre-answered: an option nobody should change is a question that should not be asked.

Open, noted while deciding: **`search_seo` puts `structured_data` on a lead page.** That section emits
JSON-LD, and Product markup on a page that sells nothing would be wrong. Check what it derives for these
before leaving that goal reachable.

## 3. What every lead page drops

`offer_price_selector`, `refund_policy`, `trust_badges`, `product_details`, `related_products`,
`price_highlight`, `product_carousel`.

Nothing on these pages is bought, so nothing needs pricing, reassuring or cross-selling. This is the list
that made the observed page wrong.

## 4. The four compositions

**Capture form** — `brand_label`, `hero_media` (OPTIONAL; doubles as a background image), `hero`,
`checkout_cta` (renders the inline form), `legal_footer`.
Optional adds that genuinely convert: `content_block`, `bragging_points`, `video`, `testimonials`, `faq`,
`numbered_list`.

**Call** — `brand_label`, `hero_media` (optional), `hero`, `checkout_cta` (click-to-call), `legal_footer`,
plus **`seller_profile`**. This is the local-business shape: hours, address and NAP *are* the persuasion,
and `seller_profile` already renders them. A hero is genuinely optional here.

**Bridge** — the thinnest: `brand_label`, `hero`, `checkout_cta`, `legal_footer`. See §5.

**Link-in-bio** — `brand_label`, `hero_media` + avatar, `social_links`, `link_cards`, `legal_footer`.
**No `checkout_cta`** — the cards are the calls to action. Optional: `content_block` for a bio line, and
`catalog_grid` when the creator wants their own commercial pages as crawlable internal cards.

## 5. The bridge page is ALWAYS `noindex, nofollow`

Not a default — a rule, with no tenant override.

A page whose purpose is to send the visitor elsewhere is a thin bridge page, the shape search engines
penalise and the cloaking risk `SOCIAL_MEDIA_PAGES.md` §8a exists to avoid. Indexing one risks the Site's
whole reputation for a page carrying no content of its own.

**It has legitimate uses beyond affiliate links** (author, 2026-09-10): redirecting traffic from a stale
but popular domain to a new one is a real and honest need. Those uses do not want indexing either — the
destination should rank, never the bridge.

Implementation: force `NOINDEX_ROBOTS` in `publishing.py` beside the existing test-mode override, which
already does exactly this for the same reason ("test data must not reach search"). The offer is in scope
there.

## 6. `open_form` is REMOVED, not deferred  ✅ DONE 2026-09-10

Its required `form_id` is read by nothing, it renders a generic email CTA, and it is blocked on a form
builder that does not exist. **Verified 2026-09-10: ZERO products use it in dev or prod**, so removal costs
no migration.

Remove from the action enum, the `expected_type` map, and the Products UI list. `FORM_BUILDER.md` can
reintroduce a form action on its own terms when there is a form to open.

## 7. The composer must see the ACTION

`compose_page(offer, page)` receives the offer, not the products — so it cannot reach
`product.lead_capture.action` today.

**Denormalise `lead_capture_action` onto the Offer**, exactly as `product_intent` already is. Offers.vue
reads the product's `lead_capture` when building `primaryCtaContract()`, so the value is in hand at the
moment the offer is written.

`composition_key(offer)` then returns `lead_capture`, `lead_call`, `lead_bridge` or `lead_social` instead of
today's single `lead_gen`. Four small entries in `composition_rules.json`; the Vue composer mirrors the same
switch, as it does now.

**Fix first: the two intent derivations disagree.** `builderIntent` falls back to the product's intent;
`deriveOfferType` reads the offer only, and the offer INDEX row stores `""` rather than null when absent. An
offer with no stored intent therefore gets a lead-gen CTA and transactional SECTIONS — which is how trust
badges and a refund policy reached the observed page. One derivation, used by both.

## 8. Element changes

- **`social_links` → platform ICONS**, not worded pills. A YouTube link should render a clickable YouTube
  glyph. The dashboard's existing icon-picker is where the set comes from.
- **`social_redirect` must NOT require a target.** Validation demands `target.type == "social"`, but a
  link-in-bio page has no single destination — the cards do. Relax it for this action.
- **Seed the page.** Nothing pre-adds `social_links` or `link_cards`, so a Social Page starts empty. The
  seeding machinery already works: the subheadline is auto-populated from the action's description today.
  It is seeding the OLD meaning, not missing.

## 9. Order

1. **§7 intent split** — one derivation. Smallest, and it is actively producing wrong pages.
2. ~~**§6 remove `open_form`**~~ ✅ DONE 2026-09-10 — no migration, as predicted.
3. **§7 action denormalisation + four compositions** — the substance.
4. **§5 bridge noindex** — one rule, beside an existing one.
5. **§8 element changes** — icons, target relaxation, seeding.
6. **Product-creation wizard** — §10. LAST, deliberately: it makes creating these pleasant, and everything
   above makes them CORRECT.

## 10. Product creation becomes a wizard (author's design)

Ask commercial intent FIRST: *"Choose whether this product collects payment or captures lead information.
Payment products are set up to charge through Stripe automatically."* → **"I want a payment"** /
**"I want to capture a lead"**.

Lead-gen then asks the action, and **skips the transactional fields entirely** — SKU, categories, price,
refund policy — which a product that is never sold has no use for. Then an OPTIONAL hero image step, since
the avatar cannot render without a hero and a page that starts with neither looks broken.

**A separate top-level section (like Services) was considered and rejected.** A lead-gen product is the
SAME entity — one `Product` document with a different `product_intent`. Services are genuinely different:
own document type, scheduling, fulfillers, calendars. Splitting the catalog would mean two lists, two CRUD
paths, two search surfaces, and an Offer that must know which to read — real cost, no new capability.
Intent is an attribute of a product, not a different kind of thing.
