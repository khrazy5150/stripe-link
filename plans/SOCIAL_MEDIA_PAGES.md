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

Also note this is the same silent-drift shape as the `SENSITIVE_FIELDS` denylist: a field
that gates behaviour with nothing producing it. See the audit item in `TODO.md`.

## 8. New elements needed

- **`social_links`** — repeatable-adjacent ordered icon row (or a single element holding an
  ordered list). Reads §6's list, obeys §7.
- **`profile_avatar`** — already specified in `SOCIALITE_PARITY.md`; build there, reuse here.
- **`link_card`** *(decide)* — `catalog_grid` may already cover it, since each tile resolves
  its own offer. Only add if a card must point somewhere that is not an offer.

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
4. **Vanity URL — OPEN, author researching a domain purchase (2026-08-30).**

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

5. **Shared-origin hazard if path-on-apex is ever chosen.** Published pages already store a
   capability in localStorage (`html.py:4806-4807`): `sl_cart_id_{offerId}` (the SERVER cart
   id) and `sl_cart_{offerId}` — keyed by **offer, not tenant**. Distinct subdomains are
   distinct browser origins, so this is isolated today. On a shared apex it is not: any
   tenant's page script could read another tenant's cart ids for a visitor who used both.
   Namespace those keys by `tenant_id` before adopting any path-on-apex scheme.

6. **Add the platform hosting domain to the Public Suffix List — do this regardless.**
   Subdomains isolate storage and DOM but NOT cookies: `a.jbay.uk` can set a cookie on
   `.jbay.uk` that `b.jbay.uk` reads. PSL registration is how `github.io` and `vercel.app`
   close this. Free, independent of the vanity-URL decision, and applies to whichever domain
   ends up serving tenant content.
7. **Donation button.** Author raised it. Needs either a new CTA type or a priceless/
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
2. **P1 — verification decision (§7a)** and its implementation. Blocks the trust model.
3. **P2 — composition + `social_links` element.** New `composition_rules.json` entry,
   reusing `seller_profile` / `catalog_grid` / `profile_avatar`.
4. **P3 — override + publish gate** (`source` flag, `on_custom_domain` check).
5. **P4 — per-link analytics.**

P0 and P2 are independent of the verification decision and can start first; P3 cannot.
