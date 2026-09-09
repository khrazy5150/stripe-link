# Social Media Pages (link-in-bio)

Status: PLANNED, not built. Designed 2026-08-30.
Reference: Stan.store, juicy.bio, linkcloud.ai (creator link-in-bio pages).
Related: `PAGE_COMPOSER.md`, `LANDING_PAGE_GOAL_COMPOSITION.md`, `SOCIALITE_PARITY.md`,
`OFFER_MODEL_REDESIGN.md`, `SITE_OBJECT.md`, `BUSINESS_PROFILE_AND_GBP.md`, `LEAD_CAPTURE.md`.

---

## 1. What this is

A creator's single public page: cover/avatar, name, tagline, a row of social icons, then a
vertical stack of cards. Crucially — look at the Stan reference — **those cards are priced
products with buy buttons** ($459, $599/$999, $859/$1,299). This is not a "links page". It
is a **multi-opportunity commerce page** that happens to lead with identity instead of a
single offer.

That framing decides everything below.

## 2. Key decision: a COMPOSITION, not a new page type

**Cardinality: this is a ZERO-primary-offer page**, the storefront/collection shape — an identity
header plus a `catalog_grid` whose cards each resolve their own offer and link out. It therefore needs
NO exception to the "one primary offer per page" rule, which is exactly why the plumbing already
exists. The rule is stated authoritatively in `PAGE_COMPOSER.md` § *Cardinality*; do not restate it
here.

**Do not build a separate page type or renderer.** Reasons:

- The renderer already treats page role as metadata, never a branch — `documents.py:1857`:
  *"Page roles are metadata (JSON-LD @type / sitemap / robots / nav eligibility) — never a
  renderer branch."* Composition is the sanctioned lever.
- A forked page type would immediately need pricing, checkout, application fees, funnels,
  refunds and receipts dragged back in behind it, because the cards are purchases.
- `composition_rules.json` already governs "which sections exist per offer_type".

So this is a new entry in `composition_rules.json` plus a small number of new elements.

## 3. What already exists (reuse, do not rebuild)

| Need | Existing piece |
|---|---|
| Identity header + social icon row | `seller_profile` element (`html.py:4006`) — renders org identity + social links, `rel="nofollow ugc noopener"` |
| Stack of cards, each with its OWN destination | `catalog_grid` — **repeatable**, and per `html.py:1424` *"resolves each card's own offer from offers_by_id"* |
| Avatar ring/border styling | `hero_media` tokens `avatar_ring`, `avatar_border`; `profile_avatar` element planned in `SOCIALITE_PARITY.md` |
| Countdown (juicy.bio uses one) | `countdown_timer` element — already exists, repeatable:false |
| Look and feel | existing preset/token system — no new theming |
| Inline email capture alongside links | `LEAD_CAPTURE.md` + `html.py:4220` inline form (built) |

The plumbing is genuinely there. What is missing is a composition that assembles these
**without** the transactional spine.

## 4. The gap

All three current offer_types (`single`, `bundle`, `listicle`) compose to the same spine
ending `offer_price_selector` → `checkout_cta`: **one page, one conversion**. Even the
listicle is not an exception — its items are *alternatives* sharing one CTA synced to a
carousel index, not independent destinations.

Nothing today pairs an identity header with a repeated per-destination grid and omits the
single-CTA spine.

## 5. The flow (author's design, validated)

1. **Product** is created. A lead-capture target is a product.
2. **Offer** encapsulates it and becomes the conversion context the page consumes —
   here: which links/cards, in what order.
3. **Page** sees the offer's type, enables the right elements, applies presets.

This matches the existing Product → Offer → Page spine and the Conversion Context design
(offer supplies meaning, page holds layout). Adopted as-is.

---

## 6. The link model — TWO lists, not one

`organization.same_as` is an **identity assertion** list: max 6 entries, host-whitelisted
(`SAME_AS_HOSTS`), and it feeds `sameAs` in JSON-LD. It is not a display list, and it is too
small for this page (the linkcloud reference shows 7 social icons).

Keep them separate:

| | `organization.same_as` | offer social/link list |
|---|---|---|
| purpose | identity claim in structured data | what the visitor sees and taps |
| cap | 6 | higher (decide; suggest 12–20) |
| ordering | none | tenant-ordered |
| host restriction | `SAME_AS_HOSTS` only | see trust model §7 |
| feeds `sameAs` | yes | **only when verified** |

The offer's list may **derive its default** from the business profile (so a tenant fills
NAP once), but it is its own ordered, labelled list.

## 7. Trust model — reputation isolation

The codebase already implements this principle for indexing, and names it. `html.py:1193`:

> *"Everything on platform infrastructure — and any page not served on the custom domain —
> is noindex,nofollow, **the reputation-isolation floor**."*

Apply the same principle to outbound links. `on_custom_domain` is already a first-class
renderer parameter.

| Case | Renders as a link | Enters `sameAs` |
|---|---|---|
| business links, verified | yes | yes |
| tenant override, on custom domain | yes (`rel="nofollow ugc noopener"`) | **no** |
| tenant override, on platform host | **blocked at publish** | no |

Record the provenance on the object, e.g. `social_links.source: "business" | "override"`,
and have publish-time validation read it alongside `on_custom_domain` — exactly the way
`eligibility` already gates indexing.

**Two things this must get right:**

- **The reason is the URL bar, not SEO.** `noindex` protects search reputation; it does
  nothing about a human tapping a phishing link on `scammer.jbay.uk`, which is a browser-
  blocklist and registrar-abuse problem for OUR domain. Do not later reason "it's noindexed
  anyway, loosen it."
- **Gate on the domain, not on a plan tier.** A tenant bringing their own domain is not a
  purchase from us, and per the pricing pivot landing pages and Sites are free-forever —
  making arbitrary links a paid feature quietly reintroduces the paywall that was removed.

### 7a. BLOCKER — "verified" has no producer

`same_as[].verified` is **read** in two places (`html.py:3256`, `html.py:4050` — both filter
`verified is True`) and **set nowhere**. Validation only checks it is a boolean, so a client
could assert it. Consequences today:

- no social links render, anywhere, ever — the verified tier is empty by construction;
- there is **no anti-impersonation guarantee**, because "verified" is self-assertable.

The §7 model rests on "verified" meaning something. Pick one before building:

1. **`rel="me"` reverse check (recommended).** Tenant adds a link to their page on the
   social profile; we fetch and confirm it points back. This is how Mastodon and Google do
   it — cheap, no per-platform OAuth, works for every host in `SAME_AS_HOSTS`.
2. **Per-platform OAuth.** Strongest, but one integration per network. Disproportionate.
3. **Drop the pretense.** Remove `verified`, rely on the domain boundary alone. Honest, but
   forfeits `sameAs` — Google may ignore unverified identity claims anyway.

### 7a-i. DECIDED 2026-09-09, after measuring: option 1's MECHANISM is dead, its INTENT survives

Option 1 was chosen, then tested before building. A throwaway Lambda in us-west-2 (`jb-relme-probe`,
deployed, run, deleted) fetched ten allowlisted hosts. Three results changed the design:

**1. `rel="me"` is emitted by ONE host out of ten — GitHub, and only as `rel="nofollow me"`.**

*Corrected 2026-09-09, same day.* The first measurement reported ZERO because the regex required the
attribute value to be exactly `me`, so `rel="nofollow me"` — a perfectly valid multi-token `rel` — did not
match. Re-measured as a token: GitHub 5 occurrences, Instagram/TikTok/X/LinkedIn/YouTube 0.

**The decision is unchanged, and the corrected number argues for it more strongly.** A `rel="me"` parser
would verify exactly one host; the URL-presence check verifies that host AND the seven others. So: fetch
the profile, confirm the tenant's own page URL appears in the HTML. It proves the same thing — someone
controlling the profile put our URL there — without depending on an attribute only GitHub sets.

Recorded rather than quietly amended because the rest of §7a-i is measurement too, and a reader who later
finds `rel="nofollow me"` on GitHub should find it already accounted for instead of concluding the numbers
here were guessed.

**2. Lambda fetches BETTER than a laptop, and the HONEST user-agent beats a browser string.** Measured
from a residential IP first, which was misleading: X, Facebook and LinkedIn looked dead and were not.

| host | our URL findable from Lambda | note |
|---|---|---|
| wikipedia.org | 756 | **EXCLUDED — see 3** |
| threads.net | 40 | honest UA only (Chrome UA got a 272K empty shell) |
| x.com | 24 | |
| pinterest.com | 20 | |
| facebook.com | 15 | honest UA only (Chrome UA got `400 Error`) |
| youtube.com | 13 | |
| github.com | 6 | |
| linkedin.com | 2 | |
| instagram.com | 0 | login wall |
| tiktok.com | 0 | JS shell |

Use `JuniorBayLinkVerifier/1.0 (+https://juniorbay.com/verify)`. We never need to impersonate a
browser — the honest UA is strictly better, which is a rare and worth-keeping result.

**3. Wikipedia and Wikidata must be EXCLUDED from auto-verification.** Anyone can edit them, so a
tenant could add their own URL to a brand's article and claim `sameAs` with that brand — precisely the
impersonation vector §7 exists to prevent. The check is only meaningful where the page is controlled by
its owner. Presence is safe elsewhere because the needle is the tenant's OWN unique page URL, not a
generic domain.

**4. Instagram and TikTok cannot be verified by fetching, and no unauthenticated surface helps.**
`/embed`, `api.instagram.com/oembed` and TikTok's `/embed` all return nothing useful. TikTok's oEmbed
does work unauthenticated but returns only title/author_name/author_url — it proves a profile EXISTS,
not what it links to. Testing with a personal account changes nothing: the wall is on the REQUESTER,
not the target.

**So: a TWO-TIER model.** Verifiable hosts get `verified: true` → render AND enter `sameAs`.
Unverifiable hosts (Instagram, TikTok) render normally with `rel="nofollow ugc noopener"` and NEVER
enter `sameAs`. The UI must say they cannot be verified rather than implying they were.

**Do not conflate verification with traffic.** Verification gates `sameAs` ONLY. Every link renders and
works either way, so the two platforms that dominate link-in-bio traffic are unaffected by being
unverifiable. What is lost is a structured-data identity signal, which matters more to the Business
Profile than to a creator page.

**Path for Instagram/TikTok (author 2026-09-09):** OAuth, long-term — and it is STRONGER than any
backlink check, because the tenant authenticating with the account IS proof of control. Short term this
rides an **aggregator**, already planned for campaign publishing (`ATTENTION_PRIMITIVE.md`), which
bypasses Meta and ByteDance app review for now. Note the synergy: a tenant who connects Instagram in
order to PUBLISH has, by definition, proven they control it — connect once, use for both. So this is a
downstream benefit of planned work, not a separate integration to justify.

Also note this is the same silent-drift shape as the `SENSITIVE_FIELDS` denylist: a field
that gates behaviour with nothing producing it. See the audit item in `TODO.md`.

## 8. New elements needed

- **`social_links`** — repeatable-adjacent ordered icon row (or a single element holding an
  ordered list). Reads §6's list, obeys §7.
- **`profile_avatar`** — already specified in `SOCIALITE_PARITY.md`; build there, reuse here.
- **`link_cards`** — DECIDED, see §8a. `catalog_grid` does NOT cover the external case.

## 8a. GAP: `catalog_grid` cards are internal-only, by design

Earlier phrasing in this plan assumed `catalog_grid` would work as-is for link-in-bio. It will not.

`render_catalog_grid` builds every href as `internal_href(slug)` — a link to that offer's landing-page
slug on the Site. Its docstring states the reason: the cards exist to build *"the crawlable catalog
hierarchy that makes subfolder domain authority work."* Cards without a `home` host or a slug render as
plain unlinked tiles.

So a creator's "my YouTube channel", "my Amazon storefront" or a raw affiliate link **cannot be a
`catalog_grid` card**. That is not a bug; it is the element doing its job.

### Options considered

| | Verdict |
|---|---|
| **A — add a `url` field to `catalog_grid` items** | **No.** Silently undermines the SEO contract the element exists for, and forces the §7 trust policy to be enforced in a renderer that otherwise has nothing to do with it. |
| **B — a separate `link_cards` element, external-only** | **CHOSEN.** |
| **C — make every external destination an offer with an `external_url` CTA** | **No, as a general answer** — a whole offer, page and slug per "here's my TikTok" is absurd overhead, and it manufactures thin bridge pages, which is the cloaking risk §7 exists to avoid. Still CORRECT for the affiliate case (see below). |

### Why B

1. **The SEO contract stays intact.** `catalog_grid` is unchanged, so existing storefronts carry no
   risk and the crawlable hierarchy keeps meaning what it says.
2. **`rel` semantics are opposites.** Internal catalog links must be followable — that is the entire
   point. External UGC links must carry `rel="nofollow ugc noopener"`. One element holding both is a
   conditional that will eventually be inverted by someone who does not know why it is there.
3. **The trust policy gets ONE home.** §7's rules (verified vs override, the `on_custom_domain` gate)
   then apply to exactly one element and can be audited in one place. Allowing external links in
   `catalog_grid` too would mean enforcing the same policy in two renderers that must agree with
   nothing forcing them to — the failure shape that has bitten this codebase repeatedly (see the
   silent-agreement audit item in `TODO.md`).
4. **It matches existing practice.** `catalog_grid` already reuses `product_carousel`'s card shape and
   shares a renderer with `related_products`. Sharing markup across elements is the established pattern
   here, so this costs almost nothing.

### `link_cards` specification

- `items[]` of `{ url, label, image?, description? }` — **no `offer_id`**, no price, no `resolve_offer`.
- Reuses the `product_carousel` card shape; no new CSS beyond the icon/compact variant.
- Always `rel="nofollow ugc noopener"` and `target="_blank"`.
- Repeatable, like `catalog_grid`.
- **Never renders a checkout CTA** — per the cardinality guardrail in `PAGE_COMPOSER.md`, grid cards
  link out. This element cannot convert.
- Subject to §7: on a platform host, hosts are whitelisted; on a custom domain, any URL is allowed but
  it NEVER enters `sameAs`.
- Excluded from sitemap and structured data. It is visitor navigation, not catalog.

### The three card kinds, kept distinct

A real creator page uses more than one, which is exactly what the Stan reference shows:

| Destination | Element |
|---|---|
| the tenant's own priced offers (internal, crawlable) | `catalog_grid` |
| social profiles (icon row) | `social_links` |
| arbitrary external links | `link_cards` |
| an affiliate product the tenant genuinely *sells through* | an offer with an `external_url` CTA — option C, correct HERE because it earns a real page with its own content, analytics and disclosure |

That last row is the affiliate bridge-page case from `LEAD_CAPTURE.md`. It gets a `catalog_grid` card
like any other offer, because it has a page. The distinction is whether the destination deserves a page
of its own — sold-through products do, "here is my TikTok" does not.

## 9. Decisions to make

1. **Priceless products.** `validate_product_document` requires `default_price_id`
   unconditionally (`documents.py:637`) — no `lead_gen` exemption. A "social page product"
   therefore carries a $0 price row. Formalise that, or exempt `product_intent: lead_gen`.
2. **`offer_type: social_media` vs the redesign.** Adding a 4th offer_type is the smallest
   change and fits `composition_rules.json` today — but `OFFER_MODEL_REDESIGN.md`
   explicitly DROPS `offer_type` for derived placement. Fine to add knowingly; record it on
   that plan's migration list so it is not a surprise.
3. **Is `checkout_cta` omittable?** Every existing composition includes it. VERIFY nothing
   hard-requires it, and that `primaryCtaContract()` (`Offers.vue:1205`) can return "no
   single primary CTA" — today it always returns something, derived from
   `landingProducts[0]`.
4. **Vanity URL — DECIDED 2026-08-30: `jbay.page`, path-on-apex (`jbay.page/username`).**

   **The top constraint is surviving Instagram/TikTok link filtering.** A link-in-bio domain
   that cannot be pasted into a bio is not a product. This outranks price, length and
   semantics, and it is TESTABLE BEFORE PURCHASE: paste an existing URL on the candidate TLD
   into an IG story link, a TikTok bio and a DM.

   That test killed the earlier front-runner. `jbay.cc` ($8/yr) was chosen for brevity, then
   found to be aggressively blocked by Instagram and TikTok for malware/spam reputation — the
   byproduct of being cheap. `.win` ($4.18) was rejected for the same reason before testing.
   Corroborating evidence nobody should ignore: NO competitor uses a cheap TLD —
   linktr.ee (`.ee`), beacons.ai (`.ai`), stan.store (`.store`), juicy.bio (`.bio`). They all
   depend on passing these filters and have already solved it.

   **Why `.page` won** ($10.20/yr, the cheapest credible option):
   - **HSTS-preloaded at the TLD level.** Google Registry runs `.page` alongside `.app` and
     `.dev`; every domain is HTTPS-only, enforced by the browser. Plaintext throwaway
     phishing is impossible there, so abuse never concentrated — the exact inverse of `.cc`.
   - Confirmed to pass IG/TikTok filters; treated as a legitimate mainstream TLD.
   - **Semantically neutral**, which matters because tenants are not only creators. The same
     URL must look unremarkable for a massage therapist, a nutrition store and a creator.
   - `jbay.page/mariawendt` — 9 characters before the slash.

   Rejected: `.info` (cheap-TLD spam history — the `.cc` trap again), `.promo` (reads as
   coupon spam on a page carrying a $599 buy button), `.luxe` / `.ink` (narrow; `.ink` reads
   tattoo), `.pro` (odd for creators), `.social` (long, pricey, redundant), `.website`
   (author dislikes). Fallback if ever needed: `.store` ($42.20), proven daily by stan.store.

   **Consequences of path-on-apex — both are now REQUIRED, not optional:**
   - Namespace the localStorage cart keys by `tenant_id` first (see #5). Every creator page
     shares ONE browser origin under this scheme.
   - Put `jbay.page` on the Public Suffix List (see #6), not `jbay.uk`, if creator pages are
     where tenant content lives. Reserve a path wordlist (`/about`, `/login`, `/api`, …)
     before the first username is claimed — usernames and platform routes now share a
     namespace.

   Commerce Sites stay on `{label}.jbay.uk`; this domain carries creator pages only, which is
   the point — a blocklisting on the UGC domain must not touch marketing, dashboard, signup
   or billing.

   Superseded options (kept so the reasoning is not relitigated):

5. **Superseded vanity-URL options (2026-08-30).**

   Every competitor uses path-on-apex (`linktr.ee/name`, `beacons.ai/name`,
   `stan.store/name`, `juicy.bio/yourname`), so `{domain}/username` is the category-standard
   shape. The isolation benefit is NOT about brand perception — `linktr.ee` is obviously the
   same brand as `linktree.com`. It is that blocklists, Safe Browsing and registrar abuse
   desks act **per registered domain**: if the creator domain is flagged, marketing,
   dashboard, signup and billing keep running.

   | Option | Verdict |
   |---|---|
   | `mariawendt.jbay.uk` (subdomain) | **Works today.** Zero routing work, already origin-isolated. Customisable via CNAME to the tenant's own domain. Reads less well. |
   | `jbay.uk/username` (path on the prod hosting apex) | **No.** Collapses every tenant onto ONE browser origin — see the localStorage note below — and concentrates reputation on the domain already serving all prod Sites. |
   | `juniorbay.net/username` | **No, as things stand.** It carries `keith@juniorbay.net`, the Stripe platform account's owner email. Never co-locate tenant-overridable UGC with the email identity of the payment account: a blocklisting would hit deliverability during the very abuse incident that caused it. Viable only if that email moves first, and only after checking the `.net`'s history (the `.com` had prior spam reputation). |
   | **a dedicated cheap domain, path-on-apex** | **Preferred.** Author researching Cloudflare Registrar (at-cost, requires Cloudflare DNS — already in use). |

   Neither `jbay` domain is available: `jbay.uk` is the PROD free-tier hosting domain and
   `jbay.be` the TEST one (`sites.py:52,453`), plus `go.jbay.uk` (short links) and
   `domains.jbay.uk` (custom-domain CNAME target).

   **When buying:** check the domain's history before purchase (Wayback, Safe Browsing,
   blocklist lookups) — a recovered domain with spam history is worse than a new one, which
   is exactly the `juniorbay.com` lesson. A brand-new domain's neutral reputation is a
   feature here.

   **Do not let this gate the feature.** Ship v1 on `{label}.jbay.uk` subdomains; the page is
   identical and only the hostname changes when a vanity domain is chosen.

6. **Shared-origin hazard — now LIVE, since path-on-apex was chosen.** Published pages already store a
   capability in localStorage (`html.py:4806-4807`): `sl_cart_id_{offerId}` (the SERVER cart
   id) and `sl_cart_{offerId}` — keyed by **offer, not tenant**. Distinct subdomains are
   distinct browser origins, so this is isolated today. On a shared apex it is not: any
   tenant's page script could read another tenant's cart ids for a visitor who used both.
   Namespace those keys by `tenant_id` before adopting any path-on-apex scheme.

7. **Add the creator domain (`jbay.page`) to the Public Suffix List.**
   Subdomains isolate storage and DOM but NOT cookies: `a.jbay.uk` can set a cookie on
   `.jbay.uk` that `b.jbay.uk` reads. PSL registration is how `github.io` and `vercel.app`
   close this. Free, independent of the vanity-URL decision, and applies to whichever domain
   ends up serving tenant content.
8. **Donation button.** Author raised it. Needs either a new CTA type or a priceless/
   pay-what-you-want checkout. Out of scope for v1 unless decided otherwise.

## 10. Cleanup this supersedes

- **Retire `social_redirect`.** It is redundant: `Offers.vue:1214` handles it in the *same
  branch* as `external_url`, producing an identical CTA contract. Its required `platform`
  string is never read. Migrate existing products to `external_url` and remove the action.
- **`open_form` is inert.** It falls into the `capture_*` bucket and renders a generic
  `email` CTA; the `form_id` that validation requires is never read. Either give it a
  renderer or remove it — see the form-builder discussion (separate plan).

## 11. Also worth building (author asked for additions)

- **Per-link click analytics.** Link-in-bio pages live or die on click data; every
  competitor shows per-link clicks. Pages have `analytics_summary` (views/conversions/
  revenue) but nothing per-link. Likely the single highest-value addition after v1.
- **Mobile-first is not a nicety.** Effectively all traffic is a tap from an app's bio
  field. Design and test at 390px first.
- **Link ordering = the queued drag-reorder work.** Ordering is core here; it shares the
  ⭐ HIGH drag-reorder item already in `TODO.md`.
- **`ProfilePage` / `Person` JSON-LD**, not `Product`, for the page itself. `seller_profile`
  currently emits `CollectionPage` + `OnlineStore`; a creator page is a different @type.
- **Open Graph matters more here** than on a landing page — these get pasted into DMs and
  stories constantly. OG support exists; confirm it reads the profile, not a product.
- **Inline lead capture alongside links.** Beacons does this and it converts; the inline
  form already exists (`html.py:4220`), so it is mostly a composition question.

## 12. Phasing

1. **P0 — Business Profile social links UI.** There is NO UI for `same_as` today; it is
   validated and never enterable. Nothing here works until a tenant can enter links.
2. **P1 — verification DECIDED 2026-09-09 (§7a-i): URL-presence check, two-tier.** `rel="me"` is dead;
   the mechanism is a Lambda fetch with an honest UA looking for the tenant's own page URL. Instagram and
   TikTok are unverifiable by fetch and stay in the unverified tier until the aggregator/OAuth path lands.
   Still to implement, but no longer a decision.
3. **P2 — composition + `social_links` element.** New `composition_rules.json` entry,
   reusing `seller_profile` / `catalog_grid` / `profile_avatar`.
4. **P3 — override + publish gate** (`source` flag, `on_custom_domain` check).
5. **P4 — per-link analytics.**

P0 and P2 are independent of the verification decision and can start first; P3 cannot.
