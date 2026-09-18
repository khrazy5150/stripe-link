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

## 3. The username is the platform subdomain label

Not a new field. `maria.jbay.uk` and `jbay.page/maria` are the same tenant **by construction**, so neither can
impersonate the other — and it inherits, rather than reimplements, the three things a username namespace needs:

| Need | Already exists |
|---|---|
| Syntax rule | `_SUBDOMAIN_RE` + `subdomain_rule_error` |
| First-claim-wins | `SubdomainRegistry.reserve` (conditional put) |
| Reserved wordlist | `RESERVED_SUBDOMAINS` — already holds `about`, `login`, `api`, `admin`, `profile`, … |

That last row closes an open item: plans/SOCIAL_MEDIA_PAGES.md #4 says a path wordlist must exist before the
first username is claimed. It does, and it has been enforced on every Site created so far.

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

## 5. Before it can be flipped on

1. **plans/CREATOR_LINK_POLICY.md must ship.** Allowlist, host-derived adult warning, takedown path. These
   pages carry no payment, so the outbound link is the only lever an abuser has on the shared apex. This is
   the gate, not a nice-to-have.
2. **Buy `jbay.page`; add the zone to the same Cloudflare account.** The API token is already all-zones.
3. **Run the Worker setup once more for the new zone** — it is already zone-parameterised:
   `CLOUDFLARE_ZONE_ID=<jbay.page zone id> STACK_NAME=jb-stripe-link-stack-prod ENVIRONMENT=prod ./deploy/setup-cloudflare-custom-domain-worker.sh`
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
- **No dashboard surface yet.** Nothing shows a tenant their creator URL, and nothing lets them pick a
  username distinct from their store label. Deliberate: the URL should not be advertised before §5.1 ships.
