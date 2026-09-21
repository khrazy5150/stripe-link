# Commerce eligibility: being reachable is not being authorized to transact

**Status: planned, nothing built. Found 2026-09-21.**

Today a page that is *reachable* is a page that can *take money*. Those are two different properties, and
conflating them means every host-level control the platform has — custom-domain verification, platform-host
governance, suspending a Site — can be stepped around by detaching a page.

## What was verified, concretely

- **The artifact is publicly readable with no host check.** `https://<pages-distribution>/<page_id>/index.html`
  returns 200 and the full page. Verified against a real published page (126KB of HTML).
- **It carries a working, self-contained CTA.** The baked checkout href is absolute and complete —
  `clientID`, `offer`, `page_id`, `price_id`, `mode`, `success_url`, `cancel_url`. Nothing about it depends
  on the host it was loaded from. 55 checkout references in one artifact.
- **Checkout's only page gate is `status == "published"`.** `checkout.py:118` and `cart_checkout.py:89` both
  load the page and check that one field. Neither reads the Site, the Host header, the Origin, or the
  Referer — `grep` for those in `checkout.py` returns nothing relevant.
- **`upsell.py` has no page gate at all.** It transacts with only `assert_billing_in_good_standing`; the word
  `published` does not appear in the file.
- **The exposure is not a config slip, but it is not a designed surface either.** The distribution must be
  publicly readable because the Cloudflare Worker proxies it. The *designed* share link,
  `{stage}-test.juniorbay.com/published/{short_code}`, does NOT expose it: `test_page_serve.py` reads the
  artifact from S3 server-side and returns the bytes under the branded host. Only
  `routes_resolve.destination_url` 302s a browser to the raw artifact URL, and nothing in the dashboard
  surfaces such a link (`grep` for `cloudfront` in `dashboard/src` returns nothing).

**So:** a tenant can detach a page from their Site — removing it from every hostname the platform governs —
and keep running a fully transacting storefront on the platform's own infrastructure, reachable by anyone
they send the link to.

## What still holds, and why this is not a five-alarm fire

- `assert_billing_in_good_standing` runs **before** the page check on every transacting path. A suspended
  tenant cannot take money on ANY surface, including this one. That is a real kill switch: it stops the
  money even though it cannot stop the serving.
- An unattached page bakes `noindex,nofollow`, so this is not a search-discoverable surface. The
  distribution vector is a direct link the tenant hands out.
- `delete_page_artifacts` removes the object on unpublish/archive, so removal IS possible — it just has to
  act on the PAGE, not on a hostname.

The threat model is a **malicious tenant**, not an outside attacker: page ids and the distribution host are
not guessable, but the tenant knows their own.

## The distinction to formalize

> A page's artifact may be publicly reachable without being an SEO identity or an authorized commerce
> endpoint.

Detached must NOT mean inaccessible. There are legitimate reasons an artifact exists outside a tenant Site —
previewing, internal testing, staging, platform administration, and A/B variants. Turning detached pages into
hard 404s would break all of them to fix one of them.

## The constraint that shapes the rule

**An A/B variant must be able to transact while detached.** A visitor assigned to a variant is on the
control's URL, but the CTA they click comes from the VARIANT's artifact and carries the variant's own
`page_id` — and `order.attribution.page_id` is what conversion attribution reads. So "attached to a Site"
cannot be the eligibility test on its own; it would silently break every experiment's conversion arm.

This composes neatly with A2, which already answers exactly the right question. `identity_page_id(page)`
returns the page whose public identity an artifact carries — itself, or the control it is a variant of. So:

```
eligible_to_transact(page) ==
    tenant in good standing                  # exists today
    AND page.status == "published"           # exists today
    AND identity_page_id(page) is attached to a Site   # NEW — one concept, already built
    AND commerce not disabled for the tenant/Site      # NEW — the abuse lever
```

One expression covers both the normal case (an attached page is its own identity) and the variant case (a
detached variant borrows an attached control's identity). A page attached to nothing, standing for nothing,
is exactly the case with no legitimate claim to take money.

## Phases

- **P1 — observe, do not enforce.** Compute eligibility on every transacting path and log/emit when a
  checkout WOULD be refused, while still allowing it. This is not optional caution: refusing a legitimate
  checkout is worse than the hole, and no one has ever measured what real traffic looks like on these paths.
  Ship it, watch it, and only then decide the rule is right.
- **P2 — enforce**, once P1 is quiet. One shared helper called from `checkout.py`, `cart_checkout.py` and
  `upsell.py` — which needs a page gate of its own regardless of this work.
- **P3 — the abuse lever.** A `commerce_enabled` flag at tenant (and probably Site) level, plus an admin
  action, so an abuse report can stop transactions without unpublishing a tenant's whole catalogue. Pairs
  with an archive-the-page action, which already deletes artifacts and is the only lever that reaches the
  raw artifact URL.

## Decisions needed before P2

1. **The test viewer.** `{stage}-test.juniorbay.com/published/{code}` is "the canonical way to view test
   pages" and is deliberately test-mode only. Should a transaction started there be eligible? Probably yes
   for `mode=test`, never for live — but that is a decision, not an inference.
2. **Preview.** Preview renders already show a DRAFT screen instead of a working CTA, so this may need
   nothing. Confirm rather than assume.
3. **Legacy pages with no Site.** `site_page_slug` returns "" for them and `site_is_served` tolerates a
   missing Site. Whether "no Site at all" is grandfathered or refused decides whether P2 can ship without a
   migration.
4. **Funnel and provisioned pages** (`attach_funnel_pages`, tip-jar provisioning) attach their pages, so they
   should pass — verify against real data before enforcing, not from the code alone.

## Related

- `plans/ARTIFACT_ACCESS_BOUNDARY.md` — closing the raw artifact URL. It removes one distribution channel
  but creates NO enforcement: the checkout href is absolute and self-contained, so re-hosted HTML still
  transacts, and attaching to a free platform host is an authorized, self-service route. The two plans are
  siblings, not substitutes; this one is the enforcement half. (That plan also supersedes the earlier idea
  of solving the artifact URL with `X-Robots-Tag` — noindex does not protect content from being fetched.)
- `plans/AB_TESTING.md` A2 — `identity_page_id`, which this rule reuses.
