# Get Started wizard and the managed business homepage

**Status:** planned 2026-11-26. Nothing built. Decisions marked **Decided** come from the author. Items under "Open decisions" need an answer before the phase that depends on them.

## Problem

Stripe will not activate an account without a business website that shows who the seller is and how a customer reaches them. Tenants find this out halfway through Stripe onboarding, leave to build a site, and come back. Most tenants have no business name. They are individuals selling under their own name.

The setup steps tenants need are also tied to Stripe today. The "Not your account? Disconnect" check and the store photo step sit inside the Dashboard's Stripe wizard, which opens only from the "Stripe isn't connected" banner. Stripe is now optional in each mode, so a tenant who only uses Ads never sees them.

## Goal

A **Get Started** wizard that runs before Stripe and doesn't depend on it. It collects the tenant's business identity once, then creates a published **Live** Site with a **managed business homepage**. That homepage meets Stripe's website requirements and carries the signals Google uses to judge a business legitimate. The tenant can't edit it directly, and it updates when their details change. Its URL is prefilled into Stripe's onboarding form, so the tenant never stops to build a website.

One business homepage sits behind all of a tenant's landing pages. SamCart creates a business per landing page; Junior Bay makes the business a single Site that every page belongs to.

## Decided (author, 2026-11-26)

1. **Live mode owns the default Site.** The wizard builds the default Live Site. A Test copy is made with the existing Copy Site function and keeps the same name.
2. **Identity is more than a name and a URL.** The wizard collects NAP: name, address and phone. It also collects a support email, which defaults to the sign-in email. A business name is optional, because most tenants don't have one.
3. **The homepage is templated, managed and not editable.** It must pass Stripe's checks and Google's legitimacy signals. It follows changes to address, phone, support email and the other identity fields.
4. **Business-name changes must reach Stripe after onboarding.** This doesn't happen today, and the author calls it an oversight. Phase 0 tests what Stripe allows.

## What already exists (reuse, don't rebuild)

Everything below is verified in code (2026-11-26 inventory).

- **Identity lives on `Site.organization`.** It holds name, legal name, entity type, description, logo, telephone, email (with a server-owned `email_verified`), address, brands, `sources{}` provenance, `same_as`, area served and timezone ([Site.schema.json](../schemas/Site.schema.json), validator `documents.py:3111`). Plans BUSINESS_PROFILE_AND_GBP, SITE_OBJECT and SITE_AS_BUSINESS_IDENTITY all lock this as the single NAP source; no separate Business Profile entity. `TenantProfile.business_name`, `support_email` and `brand{}` are dead fields.
- **Server-side Site and page provisioning.** `handlers/tip_jar_provision.py:70` is a resumable state machine anchored on `Site.provision{source,request_id,status}`. It builds a Site and a published page (`domain/tip_jar_provision.py` `site_document` :222, `page_document` :257). This is the pattern to copy.
- **Sites and routing.** `create_site` (`sites.py:608`) stamps the mode, builds the platform hostname (`{label}.jbay.uk`), applies the per-mode Site cap and reserves the subdomain. `set_homepage` (:427) attaches a page at `/`. Page roles include `homepage`, `about`, `contact` and `legal`.
- **A business-profile page shape.** The offer-less `store_profile` composition is `brand_hero` (the single H1) plus `seller_profile`. It derives description, telephone, email, address, hours, the GBP link and verified socials from `Site.organization`, and emits a CollectionPage with the Organization as `mainEntity` (`html.py:8952`, `composition.py:308`).
- **Structured data and local signals.** `organization_node` (`html.py:6229`) emits Organization, or the right LocalBusiness subtype from `business_type`, with geo, hours, hasMap and sameAs. Shipped local-SEO work adds localized alt text and NAP captions.
- **Legal footer.** `render_legal_footer` (`html.py:9943`) links Terms, Privacy and Refund. Today those point at **Junior Bay's own** legal pages, unless the tenant overrides the URLs. Refund and guarantee wording is generated server-side from a fixed vocabulary on `TenantConfig.legal_defaults` (tenant-wide, not per Site).
- **Reply-To safety.** The support email can be published at once. It becomes the Reply-To only after the per-Site verification code; until then, mail falls back to the sign-in email (`sender_identity.py:100`).
- **Stripe OAuth prefill.** `_stripe_user_prefill` (`stripe_connect.py:55`) sends email, business name, first and last name and phone. It sends no URL.
- **Stripe → Junior Bay.** `account.updated` (`stripe_webhook.py:~687`) seeds `UserProfile.business` (not the Site) on a fill-empty-only basis and recomputes each Site's eligibility.
- **Store photo.** `PUT /tenant/avatar` (`tenant_avatar.py`) stores `TenantProfile.avatar_url`, which pages read by reference. `organization.logo` is never written by any UI.

## Gaps the inventory found

- **Editing `Site.organization` doesn't republish anything.** Only an SEO flip, an attach or detach, a domain verification or an archive re-renders a Site's pages. So "the page reflects an address change" isn't true today, for any page.
- **Nothing pushes changes to Stripe.** There's no business-profile or Account update anywhere.
- **No locked or managed page concept.** The `provision` block explicitly leaves provisioned rows editable.
- **No per-Site legal pages.** The footer links Junior Bay's own Terms and Privacy unless the tenant overrides them.
- **Two seeds for the first Site.** The dashboard seeds it from `UserProfile.business` (`stores/sites.js` `organizationFromBusiness`), and `account.updated` seeds `UserProfile.business` too. SITE_AS_BUSINESS_IDENTITY (:582-589) leaves "where that seed should live" open as a product decision. This wizard answers it.

## What the homepage must carry

### Stripe

Stripe's account-activation guidance requires the website to show:
- customer-service contact details (phone, email, address, contact form or chat)
- a refund and dispute policy
- a return policy for physical goods
- a cancellation policy where relevant
- any legal or export restrictions

The site must be reachable without a password, and an unfinished site can delay activation. Stripe may separately verify that the seller controls the domain. ([Business website FAQ](https://support.stripe.com/questions/business-website-for-account-activation-faq), [Website checklist](https://docs.stripe.com/get-started/checklist/website))

### Google

There's no official Google list for website legitimacy. The consistent practitioner guidance is:
- NAP that is identical everywhere
- Organization or LocalBusiness structured data that matches the visible text
- contact details in visible body text, not only in a `tel:` link
- a real description of what the business sells

The platform already enforces one NAP source and derives JSON-LD from it.

### A constraint we can't template around

Every page on a platform hostname is `noindex,nofollow`. A Site becomes index-eligible only with a verified custom domain, a Stripe account with charges enabled, Live mode, and at least 150 unique words of body text, with legal boilerplate not counting (SITE_OBJECT :100-121). So:
- **Stripe** sees the homepage straight away on `{label}.jbay.uk`. Stripe reads it; it doesn't need indexing.
- **Google** only evaluates it once the tenant adds a custom domain. The page must be ready for that day, but nothing makes it rank before then.

### Homepage content

Each item is derived at render time from `Site.organization` and TenantConfig, never stored on the page.

| Section | Source | Why |
| --- | --- | --- |
| H1: business or trading name, plus photo or logo | `organization.name`, logo or avatar | Identity, one H1 |
| What we offer: a short description and links to published offers | `organization.description` plus the Site's attached offers | Stripe's "what you sell"; Google's real description |
| Contact: phone, support email, address (or service area), hours | `organization.*` | Stripe's customer-service contact; visible NAP for Google |
| Policies: refund and returns (and cancellation for subscriptions or bookings) | TenantConfig refund vocabulary | Stripe's refund, return and cancellation requirement |
| Footer: Terms, Privacy, Refund links to the **tenant's** pages | New per-Site legal pages (Phase 4) | Today these point at Junior Bay's terms |
| JSON-LD: Organization or LocalBusiness node, already emitted | `organization_node` | Matches the visible text |

## The wizard

It shows as a **Get Started** card at the top of the Dashboard until it's finished. It can be resumed, and each step saves as it goes.

1. **About you.** First and last name (prefilled from sign-up). Business name is optional; without one, the trading name is the tenant's full name, as Stripe does for individuals.
2. **How customers reach you.** Support email (defaults to the sign-in email, with an offer to verify it for Reply-To), phone, address, and business type for the right LocalBusiness subtype.
3. **What you sell.** One or two sentences, plus the refund and returns choices from the existing fixed vocabulary.
4. **Your photo or logo.** The existing store photo field.
5. **Your business page.** Junior Bay provisions the Live Site and managed homepage, publishes it and shows the URL. The tenant sees exactly what Stripe will see.
6. **Get paid (optional).** Connect Stripe for the current mode, with the URL and identity prefilled. The "Not your account? Disconnect" check moves here from the Dashboard Stripe wizard. Then the existing offer to set up the other mode.

The Dashboard's Stripe wizard is folded into step 6 and then removed. The "Stripe isn't connected" banner opens the wizard at step 6.

Writes use `sources{}: manual`, so a later fill-empty-only seed from Stripe or Google Business Profile never overwrites what the tenant typed.

## Phases

**Phase 0: Stripe spike (test mode, no code shipped)**
- Call Account update with `business_profile.{name,url,support_email,support_phone}` on a **test** connected Standard account the author owns. Record which fields Stripe accepts after onboarding.
- Confirm which `stripe_user[...]` OAuth prefill fields exist (url, street address, city, state, zip, country, business type, product description) and whether email, URL and phone must be sent together. Today we sometimes send only some of them.
- This phase decides between a **push** sync and a **notice** sync in Phase 3.

**Phase 1: wizard and provisioning (stripe-link)**
- Add a server-side `POST /onboarding/business-site` provisioner, modelled on `tip_jar_provision`. It writes `Site.organization` (sources `manual`), creates the Live Site under the cap check, creates the managed homepage, attaches it at `/` and publishes. It's idempotent on a request ID and resumable.
- Build the wizard UI, steps 1–5.
- Retire the `organizationFromBusiness` seed for the first Site.

**Phase 2: the managed homepage**
- A `business_home` composition, built on `store_profile` and `seller_profile`, plus a Page field such as `managed: "business_home"`.
- The pages API refuses edits to managed pages, server-side, with a message pointing at the Site's identity fields.
- **Republish on identity change.** Saving `Site.organization` re-renders every page on that Site, not just the managed one, because every page carries the NAP in its JSON-LD. This also fixes the gap for existing Sites.

**Phase 3: Stripe**
- Prefill `stripe_user[url]` with the Site's homepage URL, plus whichever address and description fields Phase 0 confirms.
- Move "Not your account?" into step 6. Default to "connect an existing account". Warn when a tenant connects a different account than they had before for that mode (the orphan-account history).
- Keep Stripe current after onboarding. If Phase 0 shows Stripe accepts updates, an identity save pushes the changed fields to Stripe. If it doesn't, a notice appears only while the Site and Stripe disagree, naming the field and linking to Stripe's settings.

**Phase 4: the tenant's own policy pages**
- Generate per-Site Refund and Returns pages (and Terms and Privacy, depending on the open decision below) from the existing server-side vocabulary. Attach them with the existing `legal` page role, so the footer links the tenant's pages instead of Junior Bay's.

**Phase 5: existing tenants**
- Show Get Started to tenants with no Live Site.
- For tenants who already have one, offer to adopt it: fill missing identity fields and add the managed homepage if `/` is free. If `/` is taken, ask before moving anything.

## Open decisions

1. **Home addresses.** Most tenants are individuals, often working from home. Publishing a street address is a privacy risk, but Stripe only needs one contact method and Google supports service-area businesses that hide the street. Recommendation: show city and region plus service area by default. Show the full street address only if the tenant has a premises and says so. The full address is still kept for Stripe and shipping.
2. **Which legal pages Junior Bay generates.** Stripe requires refund, returns and cancellation terms (Terms and Privacy only for India). The checkout collects buyer emails, which argues for a tenant Privacy page. Recommendation: generate Refund/Returns/Cancellation and Privacy now, Terms later. Templated legal text is not legal advice, so each page needs a short notice saying so.
3. **Photo versus logo.** The wizard collects one image. Recommendation: store it as the store photo (`TenantProfile.avatar_url`, which pages already use) and seed `organization.logo` from it when empty, so the Organization JSON-LD has a logo.
4. **Homepage description.** A template with the tenant's one or two sentences risks near-duplicate pages across tenants once they're indexable. An AI-expanded description (the existing enrich path) is more unique but costs a generation and needs review. Recommendation: the tenant's own sentences now, with an optional "expand with AI" later.
5. **Free tier.** The default Site uses the Free tier's single Live Site, so every landing page joins it. This matches "one business page behind many landing pages", but confirm it's intended.

## Risks

- **Stripe may lock Standard-account fields after onboarding.** Stripe's API docs say some properties can't be updated once onboarding starts, without listing which ([Update an account](https://docs.stripe.com/api/accounts/update)). Phase 0 exists for this.
- **Republish fan-out.** An identity save now re-renders every page on the Site. Use the existing publish stream, and watch the shared-document read-modify-write lesson: per-page writes, not one shared document.
- **Several Stripe accounts under one login.** Stripe publishes no limit on accounts per login ([Multiple accounts](https://docs.stripe.com/get-started/account/multiple-accounts)). The real risks are orphaned half-verified accounts and connecting the wrong business's account. Phase 3 covers both.
