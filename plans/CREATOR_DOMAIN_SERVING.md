# Link-in-bio serving on `jbay.page/{username}`

Built 2026-09-17. **Shipped dark:** `CreatorServingEnabled` defaults to `"false"` in every environment, so
nothing about today's behaviour changes until it is deliberately flipped. §5 is what has to be true first.

The domain choice, and why a cheap TLD was rejected, is plans/SOCIAL_MEDIA_PAGES.md #4. The admission ticket
is plans/CREATOR_LINK_POLICY.md. This document is only how it serves.

---

## 1. The question that shaped it

> *"Does this require a new dedicated site to be created so that jbay.page can run on them? I have the bad
> feeling that it will, which will duplicate existing infrastructure."*

No. A Site already emits **one domain-index record per surface it is reachable on** — the custom domain and
the free platform host, both projected from the same Site by `_sync_domain_index`. The creator apex is a
**third record off that same Site**. No second Site, no second publisher, no second resolver.

Everything downstream is untouched: artifact keys, the reverse proxy, Stripe-mode partitioning, the `noindex`
stamp, the 404 path, the Worker's caching.

## 2. The one real difference: where the tenant is named

A custom domain (`shop.example.com`) and a platform host (`maria.jbay.uk`) identify a tenant **by hostname**.
On a shared apex the hostname identifies nobody — every creator is `jbay.page` — so the **first path segment**
does instead.

So the index key is `jbay.page/maria`, and `_creator_lookup` (handlers/custom_domains_resolve.py) eats the
username off the front of the path before the ordinary slug machinery runs. `jbay.page/maria` is that hub's
root exactly the way `maria.jbay.uk/` is.

**Keyed per username, never one `jbay.page` record holding every creator.** That alternative reads cheaper and
is a single hot item, unbounded in size, where one tenant's publish rewrites every other tenant's routes and
one bad write takes the whole domain down.

## 3. The username is its own field, in the subdomain namespace

**Revised 2026-09-17.** The first cut derived it from the store's subdomain label — no new field, and the
namespace properties below came free. The author rejected the consequence, correctly:
`poliaxis-nutrition.jbay.uk` is a fine store address and a poor link-in-bio handle, and nobody should have to
move their shop to fix their bio link.

So `hosting.creator_username` is its own optional field, **reserved in the same registry as subdomain
labels**. That keeps the property that mattered — `maria.jbay.uk` and `jbay.page/maria` can only ever be the
same tenant — while letting the two names differ. Absent means "use the label", so every Site predating the
field already has a working username and a tenant who never picks one gets a URL rather than an error.

Sharing the namespace means it inherits, rather than reimplements, the three things a username namespace needs:

| Need | Already exists |
|---|---|
| Syntax rule | `_SUBDOMAIN_RE` + `subdomain_rule_error` |
| First-claim-wins | `SubdomainRegistry.reserve` (conditional put) |
| Reserved wordlist | `RESERVED_SUBDOMAINS` — already holds `about`, `login`, `api`, `admin`, `profile`, … |

That last row closes an open item: plans/SOCIAL_MEDIA_PAGES.md #4 says a path wordlist must exist before the
first username is claimed. It does, and it has been enforced on every Site created so far.

**Where it is asked.** In the create-page wizard, standing exactly where a Social Page skips the Goal step —
*"we cannot let the tenant get into the weeds of a site to add a username for a page"*. It is a question only
this page shape has, asked at the only moment the tenant is thinking about it. Changing it later is a Site
setting, which is where a per-Site value belongs. The wizard asks only where link-in-bio serving is actually
configured: collecting an answer with no visible effect is the same unactionable-control failure as a notice
nobody can act on.

The field is `StoreAddressField` with a `prefix` flag — a handle and a store address share a namespace, a
syntax rule and an availability check, and differ only in which side of the separator the domain sits.

**Asked as soon as the environment has an apex, not once it serves.** The first cut gated the question on
`creator_serving`, so on a stack with serving off the step silently vanished and the rail dropped to four —
reported 2026-09-17, working as designed, and the design was wrong. No handle could be claimed until the
domain went live, which means every tenant created in the meantime would have had one auto-derived from their
store label: exactly what the field exists to avoid. `GET /sites` therefore returns two separate facts —
`creator_domain` (an apex exists, so ask) and `creator_serving` (it resolves, so a hub may advertise it). The
wizard says plainly that addresses are not live yet, because claiming a name for a future URL is fine and
letting someone think it already works is not.

## 4. What serves there: the hub, and nothing else

`creator_domain_index_record` returns an **empty route table** and one `target_page_id`. That is the
reputation isolation, not an oversight: the Site's own table would expose its checkout, funnel and thank-you
pages at `jbay.page/maria/...`, putting commerce on the one domain whose whole premise is that it carries no
payment and can therefore be judged on its outbound links alone.

The hub is found by `composition: "lead_social"`, stamped onto the Site's route entry at publish time by
`_denormalize_page_catalog` — the same seam `offer_id` and `category` already use. Composition is a property
of the OFFER, which the edge resolver never loads; the publisher has both in hand, so it writes it down at the
one moment it is known for certain. Deterministic by slug, so republishing cannot silently move which page a
creator URL serves.

**Always noindex**, stamped at the edge (`host_kind: "creator"`) and independently true of the artifact bytes
(`page_robots_directive` refuses `index,follow` anywhere but a verified custom domain). Decided 2026-09-17: a
shared UGC apex must never couple one creator's reputation to another's, and a link hub has almost nothing to
rank with anyway — for a creator's own name their real Instagram and TikTok profiles already outrank it, and
the traffic is definitionally referral from the bio link.

## 4b. dev vs prod: one zone, two apexes

Raised by the author 2026-09-17 — *"jbay.page should work on prod in LIVE environment. Or does it also work
in dev as well?"* — and it caught a real defect: `CreatorHostingDomain` had a single default of `jbay.page`,
so a dev stack would have written `jbay.page/{username}` records for TEST pages on the apex prod serves live
ones from. The index tables are per-environment so nothing would have collided, but the intent was wrong.

Split the way the platform host already splits:

| | Platform host | Creator apex |
|---|---|---|
| prod | `{label}.jbay.uk` | `jbay.page/{username}` |
| dev | `{label}.jbay.be` | `test.jbay.page/{username}` |

**One zone, two Worker routes.** `jbay.page/*` → the prod worker, `test.jbay.page/*` → the dev worker. Each
worker has its own environment's API base baked in by the setup script, which is what actually separates
them. That gives dev a real serving surface without buying a second domain — unlike the platform host, which
needed a whole second zone because its tenant label is a *subdomain* and a test wildcard would otherwise have
overlapped prod's.

`CreatorHostingDomain` has **no built-in default**: empty means the feature is off, which is what an
unconfigured environment should get. `deploy.sh` sets it per environment, and preserves `CreatorServingEnabled`
across an ordinary deploy rather than resetting it — the same rule platform serving already follows.

The Worker's bare-apex guard is templated (`REPLACE_WITH_CREATOR_HOST`) for the same reason: a dev worker
must not treat the prod apex as its own front door.

## 4c. Which URL the page calls its own

Added 2026-09-17 after the author published a hub and got `poliaxis-nutrition.jbay.uk/link-bio`. Correct at
the time — serving was off and the domain unbought — but it exposed that §2 only made the creator URL
**resolve**. Nothing made it the page's identity, and nothing told the tenant it existed. A URL that works
and that nobody is told about is not shipped.

A hub is attached to its Site like any other page, so it stays reachable at `{site}.jbay.uk/{slug}`. What
changed is which of the two addresses is the real one:

- The published artifact's **canonical and home_url** become the creator URL.
- The dashboard shows the creator URL for a hub, from `GET /sites` → `creator_domain` — empty until the
  environment is configured, so a tenant is never handed a URL that does not resolve.

Both take the URL **whole**, not as origin + slug: `jbay.page/maria` IS the page, where
`jbay.page/maria/link-bio` would be a slug nobody typed and nobody would share.

Still open: whether `{site}.jbay.uk/{slug}` should 301 to the creator URL rather than serve the same page at
two addresses. The canonical already says which is preferred; a redirect would make it unambiguous, at the
cost of breaking any link already shared. Worth deciding before the first tenant shares one.

## 4d. Addresses that must stop answering

Decided and built 2026-09-18. Three requests that turned out to be one mechanism: **an index record that
outlives what it pointed at, and a resolver that needs to know why.** `site_index_records()` is now the only
place that list is assembled — two callers used to build it separately, so a rule added to one simply did not
exist in the other.

| | What the record does | Why |
|---|---|---|
| Renamed handle | `status: "retired"` → 404 | A handle is an **identity**. Forwarding ties the old name to the new person forever, which is wrong for the rebrand a rename usually is. |
| Moved-from store address | `redirect_to` → 301 | An address is an **address**. Nothing about identity is at stake and the UI already promised existing links keep working. |
| Archived Site | `status: "archived"` → 404 | The tenant closed it. |

Retired names are **never released**. The reservation stays with the Site, so the row exists purely to say
"claimed, not serving" — closing a shop must not put its address back on the market.

**Sunset is archive, not a new switch.** Archiving used to keep serving, which made it a near-duplicate of the
`seo_enabled` toggle: the only functional difference between the two was one `noarchive` token, while nothing
did what a tenant winding a business down actually needs. Now there are two states with two meanings —
`seo_enabled = false` is "open, don't rank me"; `archived` is "closed". Zero Sites were archived in dev or
prod when this changed, so there was no migration and nobody to surprise. A third "disable this Site" control
was considered and rejected: three controls across two meanings would leave tenants guessing which one closes
the shop.

**The stale-record bug this uncovered.** Superseded index records were never cleaned up, so a renamed store
address kept serving the route table as it stood on the day of the rename — forever, never updating. The UI's
promise that "existing links keep working" was technically kept, by a frozen page. It is now kept by a 301.

**Three username changes per Site, ever** (`MAX_USERNAME_CHANGES`). Since names are never released, an
uncapped rename is an uncapped private hoard of good short names — the author's case is a novice renaming
every couple of days and quietly accumulating twenty. The count travels with each Site on `GET /sites` and is
shown in the editor *before* the change: a cap discovered at the point of refusal reads as a bug, one known in
advance is a guardrail. Renaming back to a name you already hold costs nothing.

The 404 is also the main brake on churn, and it only works because the rename does not redirect: once
renaming kills every link you have shared, renaming has a real cost.

Retired lists are **server-owned**. They decide what the edge does with an address, so a client free to seed
them could name someone else's hostname and point it at itself. The update path overwrites from the stored
document; the create path strips them.

## 4e. The Worker is NOT deployed by deploy.sh

Worth its own heading because it cost a round trip. `deploy/cloudflare-custom-domain-worker.js` is a file in
this repo that only reaches the edge when somebody runs
`deploy/setup-cloudflare-custom-domain-worker.sh` against a zone. A normal `./deploy/deploy.sh <env>` does
nothing to it. Change the file, commit it, deploy the stack, and the OLD worker is still answering every
request — which is exactly what happened on 2026-09-18: the ported error page was live in git and absent from
the internet, and only a `curl` showed it (`content-type: text/plain`, the old body).

**Anything touching that file needs a run per zone**, and the zones are environment-scoped:

```
CLOUDFLARE_ZONE_ID=d5a70f95c54659e26600cae1bb0ce48a STACK_NAME=jb-stripe-link-stack-dev  ENVIRONMENT=dev  ./deploy/setup-cloudflare-custom-domain-worker.sh   # jbay.be
CLOUDFLARE_ZONE_ID=d842792b5a5240f5518f263835220df6 STACK_NAME=jb-stripe-link-stack-prod ENVIRONMENT=prod ./deploy/setup-cloudflare-custom-domain-worker.sh   # jbay.uk
```

Verify with `curl -i`, never by reading the repo: the file says what SHOULD be at the edge, not what is.

## 5. Before it can be flipped on

1. **plans/CREATOR_LINK_POLICY.md must ship.** Allowlist, host-derived adult warning, takedown path. These
   pages carry no payment, so the outbound link is the only lever an abuser has on the shared apex. This is
   the gate, not a nice-to-have.
2. ~~**Buy `jbay.page`; add the zone.**~~ **DONE** — the zone is already on the account (verified 2026-09-18,
   id `b9b06f81f20542a12a67e9f6fb70c552`), alongside `jbay.uk` and `jbay.be`. The API token is all-zones.
3. **Run the Worker setup for the new zone, once per environment** — it is already zone-parameterised, and
   the route pattern is what separates them:
   ```
   CLOUDFLARE_ZONE_ID=<jbay.page zone id> STACK_NAME=jb-stripe-link-stack-prod ENVIRONMENT=prod \
     CLOUDFLARE_WORKER_ROUTE_PATTERN='jbay.page/*' ./deploy/setup-cloudflare-custom-domain-worker.sh
   CLOUDFLARE_ZONE_ID=<jbay.page zone id> STACK_NAME=jb-stripe-link-stack-dev  ENVIRONMENT=dev \
     CLOUDFLARE_WORKER_ROUTE_PATTERN='test.jbay.page/*' ./deploy/setup-cloudflare-custom-domain-worker.sh
   ```
   The script's zone-wide `*/*` default must NOT be used here: both environments live on this one zone, and
   a wildcard route would make them fight over it.
4. **Flip `CreatorServingEnabled=true`** for that environment and republish existing link hubs (the record is
   written on publish).
5. **Submit `jbay.page` to the Public Suffix List** (plans/SOCIAL_MEDIA_PAGES.md #6) — cookie/storage
   isolation between creators at the browser level. The list is slow; start it early.

### Already done, because it would have been a bug the moment step 4 landed

**The view beacon's `sl_vid` key is namespaced per tenant.** It was a bare `sl_vid`, which is correct exactly
as long as every Site has its own hostname — localStorage is per-origin, so the tenant boundary was doing the
work for free. `jbay.page/alice` and `jbay.page/bob` are ONE origin, and a bare key would have handed
unrelated tenants the same visitor identifier, turning a deliberately first-party token into a cross-tenant
one. Fixed in this slice rather than left as a launch note.

## 6. Known gaps

- **`jbay.page/robots.txt`** 404s. A dotted segment can never be a username (`_SUBDOMAIN_RE` rejects it), so
  it is unclaimable — but the apex should serve a real robots.txt. Cloudflare-level, not application-level.
- **The bare apex** redirects to `juniorbay.com` from the Worker. Fine as a placeholder; it is the domain's
  front door and deserves a decision.
- **No handle-change redirect.** Changing a username claims the new one and leaves the old reserved to the
  Site (the registry never releases), but the old URL stops resolving — unlike the store address, where the
  note promises existing links keep working. Decide whether a renamed hub should 301.
