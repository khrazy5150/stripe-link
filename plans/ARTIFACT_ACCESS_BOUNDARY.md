# The artifact access boundary: CloudFront is an origin, not an address

**Status: planned, nothing built. Agreed 2026-09-21.**

## The invariant

> An artifact being published does not make its raw CloudFront URL a publicly accessible page.

The CloudFront URL exists because CloudFront needs somewhere to fetch the artifact from, not because a
visitor should be able to navigate there.

## Three concepts, currently two

```
Page
 ├── Artifact                → CloudFront origin URL   (implementation endpoint)
 └── Site publication
       ├── JuniorBay domain                            (public document)
       └── Tenant custom domain                        (public document)
```

`published` and `attached` already exist as separate facts. The leak is not in the data model — it is that
the serving layer never consults attachment, so "published" silently confers "publicly routable".

A detached experiment variant is coherently:

```
published        = true
attached         = false
experiment_variant = true
public_route     = false
```

**`public_route` is derived, never stored.** It follows from `site.pages`. A denormalized access-control flag
drifts from the routing table it is supposed to describe, and drift in an access-control field *is* the
security bug.

## Why not noindex

`noindex` is an SEO directive. It asks a well-behaved crawler not to list a URL; it does not stop anyone
retrieving and consuming the page. For illicit content that is no control at all. This supersedes the
earlier proposal in this repo to stamp `X-Robots-Tag` across the artifact namespace with the Worker
stripping the inherited header — if the raw URL denies, none of that is needed. Access control subsumes SEO
containment, and the SEO rule becomes boringly simple:

> SEO identity belongs to Sites, not to artifacts.

The artifact can change, the experiment can change, the visitor can be assigned a different variant, the
origin object can change — the public Site URL remains the stable identity.

## What this does NOT fix

**It does not close the commerce hole** (`plans/COMMERCE_ELIGIBILITY.md`). The baked checkout href is
absolute and self-contained and `checkout.py` performs no Origin or Referer check, so an abuser can host the
HTML anywhere — their own server, a paste site — and point it at the Junior Bay checkout endpoint. The money
still flows. They can also attach the page to a free platform host, which is an *authorized* route and
self-service.

Routing hygiene removes a distribution channel; it creates no enforcement. The levers that actually bite an
abuser are the billing/suspension gate (exists today, runs before every transaction), `commerce_enabled`
(COMMERCE_ELIGIBILITY P3), and artifact deletion on archive (exists). Build this for architectural
correctness, not as the abuse fix.

## Verified

**Consumers of the raw artifact URL** (`public_url(pages_domain, …)`):

| Caller | What it does | Survives lockdown? |
|---|---|---|
| `custom_domains_resolve.py:213`, `:121` | origin_url for the Worker to fetch (incl. A/B variants) | **yes** — add the secret header |
| `post_checkout.py:81` | redirects a **paying buyer** as funnel fallback | **NO — blocker, see P0** |
| `routes_resolve.py:52` | 302s a browser to the artifact (short-URL host) | no, but vestigial |
| `experiments_resolve.py:52` | short-code experiment resolver | already 410 (A1c) |
| `publishing.py:1187` | baked *interim canonical* for unattached pages | see P3 |

**Unaffected:** `test_page_serve.py` reads artifacts with `s3_client.get_object` against the bucket, not
over CloudFront — the branded `/published/{code}` and `/preview/{code}` viewers keep working untouched.

**The Worker already sets a request header** on the origin fetch
(`cloudflare-custom-domain-worker.js:154`, `X-Junior-Bay-Custom-Host`), so adding a shared secret is a
one-line change on that side.

## Phases

- **P0 — prerequisite: re-point the buyer-facing fallback.** `post_checkout._next_page_url` falls through to
  the raw artifact URL in two cases: no legitimate redirect base (no verified custom domain, no allowed
  origin), and *a base exists but the next page has no slug* — and funnel attachment is best-effort by
  design ("a failure here must never block publishing the artifact itself"). Closing the route before this
  is fixed breaks post-purchase upsell/downsell/thank-you **after payment**, for exactly the newest tenants
  who have not set up a domain. Also re-point `routes_resolve`'s page targets. No visible behaviour change;
  this is pure prerequisite.
- **P1 — close the route.** Worker adds a shared secret header; a CloudFront Function (viewer-request)
  rejects anything without it. Cheaper than WAF and sufficient — the secret is not protecting against an
  account insider, it is separating "the Worker" from "the internet". Rotate on deploy.
- **P2 — the preview distribution.** `PreviewDistribution` is a second artifact namespace with the same
  question. Scope it separately; preview artifacts are drafts and arguably more sensitive, not less.
- **P3 — the interim canonical.** `publishing.py:1187` bakes the CloudFront URL as canonical for unattached
  pages. Once the route denies, those pages carry a canonical pointing at a 404. A2's `identity_page_id`
  already handles variants; other unattached pages need an answer (probably: no canonical at all rather
  than a dead one).

## Risks

- **Highest blast radius in the system.** This distribution fronts every published page for every tenant.
  P1 should ship behind a mode that logs-and-allows before it denies, the same discipline as
  COMMERCE_ELIGIBILITY P1.
- **The Worker and the CloudFront Function must deploy in the right order** — secret header first
  (harmless on its own), enforcement second. Reversed, every published page 404s.
- The Worker deploys per zone via `deploy/setup-cloudflare-custom-domain-worker.sh`, NOT `deploy.sh`.
