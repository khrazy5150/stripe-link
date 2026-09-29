# Commerce eligibility: being reachable is not being authorized to transact

**Status: PHASE 1 BUILT 2026-09-28, not yet deployed. Found 2026-09-21.**

P1 is `src/stripe_link/domain/commerce_eligibility.py`, wired into `checkout.py` and `cart_checkout.py`.
It computes the verdict, records the interesting ones, and refuses nothing. `upsell.py` is NOT wired, for a
reason that turned out to be a finding of its own — see "What building P1 turned up".

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

- **P1 — observe, do not enforce. BUILT.** Compute eligibility on every transacting path and log/emit when a
  checkout WOULD be refused, while still allowing it. This is not optional caution: refusing a legitimate
  checkout is worse than the hole, and no one has ever measured what real traffic looks like on these paths.
  Ship it, watch it, and only then decide the rule is right.
- **P2 — enforce**, once P1 is quiet. One shared helper called from `checkout.py`, `cart_checkout.py` and
  `upsell.py` — which needs a page gate of its own regardless of this work.
- **P3 — the abuse lever.** A `commerce_enabled` flag at tenant (and probably Site) level, plus an admin
  action, so an abuse report can stop transactions without unpublishing a tenant's whole catalogue. Pairs
  with an archive-the-page action, which already deletes artifacts and is the only lever that reaches the
  raw artifact URL.

## What P1 emits, and how to read it

One JSON line per interesting verdict, deliberately the same shape as `common._log_auth_gap` — the repo's
other Phase 1 measurement (`plans/API_AUTHENTICATION.md`) — so two concurrent measurements are countable with
one idiom:

```json
{"commerce_eligibility": {"phase": "P1", "verdict": "not_attached", "path": "checkout",
  "tenant": "...", "page_id": "...", "identity_page_id": "...", "stripe_mode": "test",
  "undecided": false, "enforcement": "observe", "enforced": false}}
```

The ordinary attached case is **not** logged — it is every checkout the platform takes, and paying CloudWatch
to record "normal" buys nothing. What to count: `verdict = not_attached` with `undecided = false` is the hole.

**`undecided` is the number that decides whether P1 means anything.** A Sites read that raises is recorded as
`lookup_failed`, never as `not_attached`. Collapsing the two is the trap this rule was most likely to fall
into: `find_site_for_page` swallows exceptions and returns None, which is right for publishing (an artifact
must ship) and catastrophic here — a missing IAM grant would look exactly like the hole, so P1 would report a
flood of false positives and P2 would refuse every legitimate checkout on the platform. Hence the split in
`domain/sites.py`: `site_for_page` (strict, raises) alongside `find_site_for_page` (best-effort). A P1 window
that is all `undecided` has measured nothing, however quiet it looks.

**The switch.** `ELIGIBILITY_ENFORCEMENT` (template parameter `EligibilityEnforcement`): `observe` (default),
`enforce`, or `off`. An unrecognised value means `observe`, never `enforce`. `off` skips the lookup entirely —
the kill switch for the extra Dynamo read on the money path. The ordering inside `evaluate` is a cost decision
too: the Sites read alone answers the common case, and the experiments table is consulted only for a page that
turned out to be attached to nothing, so the money path pays one extra read and not two.

**Fail open on infrastructure, closed only on a definite answer.** An unreadable table, a missing table or a
broken experiments lookup never refuses, in any mode — including `enforce`. Only a successful lookup that
finds no Site can refuse.

**The grant matters as much as the code.** `SITES_TABLE` and `EXPERIMENTS_TABLE` are in `Globals`, so every
function already believed it had them; neither checkout function had the IAM read. Both now do. Without the
grant the measurement is silently all-`undecided` — which is precisely the failure that looks like success.

## What building P1 turned up

**1. The upsell path has no page identity to measure.** `upsell.py` takes `session_id`, `offer_id`,
`product_id`, `customer_id` — no `page_id`, at all — and writes `attribution.page_id = ""` on the order it
creates. There is also no session→order index to recover it from. So the upsell path cannot be measured or
enforced by page until it is GIVEN a page identity: either the funnel screen starts posting one, or an order
lookup by `session_id` is added. Wiring the existing helper into `upsell.py` would have produced a
`no_page` verdict on every post-purchase charge and looked like a clean measurement.

**2. Synthetic funnel page ids are never in a Site's `pages` map.** An upsell/thank-you artifact is
*synthesized*, not stored: `upsell_pages.py` builds a page dict with `page_id = "{source}__upsell_N"` (or
`__thank_you`, `__upsell_carousel`, `__downsell_carousel`), renders it, and never persists it. Meanwhile
`attach_funnel_slugs` points `/upsell`, `/downsell` and `/thank-you` at the **base** page_id. So a synthetic
id resolves to no Site, and the rule as written would call it `not_attached` — refusing every post-purchase
upsell the moment enforcement flipped. Today nothing reaches `/checkout` with such an id (the existing
published-gate would already 403 it, since the page isn't in the pages table either), so P1 is not exposed.
**P2 needs a third identity case:** a synthetic funnel id stands for its source page. That is a pure string
operation, deliberately NOT written yet — it has no caller, and speculative identity logic on the money path
is how this kind of rule acquires a bug nobody can reproduce.

## Decisions needed before P2

1. **The test viewer.** `{stage}-test.juniorbay.com/published/{code}` is "the canonical way to view test
   pages" and is deliberately test-mode only. Should a transaction started there be eligible? Probably yes
   for `mode=test`, never for live — but that is a decision, not an inference.
2. **Preview.** Preview renders already show a DRAFT screen instead of a working CTA, so this may need
   nothing. Confirm rather than assume.
3. ~~**Legacy pages with no Site.**~~ **ANSWERED 2026-09-28: no grandfathering, no migration.** Every page
   currently in either silo is debris and will go in the table wipe, so there is no population of legacy
   Site-less pages for P2 to protect. (The characterisation that established this: dev 9 published pages, 8
   attached, 1 orphan; prod 3 published, 2 attached, 1 orphan — and the prod orphan, a link-in-bio page, is
   not in use.) P2 can refuse "no Site at all" outright.
4. **Funnel and provisioned pages** (`attach_funnel_pages`, tip-jar provisioning) attach their pages, so they
   should pass — verify against real data before enforcing, not from the code alone.

## Related

- `plans/ARTIFACT_ACCESS_BOUNDARY.md` — closing the raw artifact URL. It removes one distribution channel
  but creates NO enforcement: the checkout href is absolute and self-contained, so re-hosted HTML still
  transacts, and attaching to a free platform host is an authorized, self-service route. The two plans are
  siblings, not substitutes; this one is the enforcement half. (That plan also supersedes the earlier idea
  of solving the artifact URL with `X-Robots-Tag` — noindex does not protect content from being fetched.)
- `plans/AB_TESTING.md` A2 — `identity_page_id`, which this rule reuses.
