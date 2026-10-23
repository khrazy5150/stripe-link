# Domain health sweep — notice when a tenant's custom domain stops working

**Status:** BUILT 2026-10-23, not yet deployed. Written 2026-10-23.

Pieces: `src/stripe_link/domain/domain_health.py` (the decisions),
`src/handlers/domain_health_sweep.py` (the sweep), `DynamoDocumentRepository.update_domain_health`
(the targeted write), a `rate(1 day)` Schedule event on `SitesFunction`, and
`tests/test_domain_health_sweep.py`.

## 1. The problem

**Custom-domain verification is one-shot.** `check_domain` runs when the tenant clicks Verify and never
again. Nothing in the stack re-examines a domain once it has passed. There is no scheduled sweep, no
periodic Cloudflare status read, no DNS re-check.

So a store can go dark and we never know. Every one of these is silent today:

- the tenant edits their DNS and removes or mistypes a record;
- their registrar lapses, or the domain transfers and records are not carried over;
- their DNS provider migrates zones and drops a CNAME;
- Cloudflare's certificate stops renewing because the `_acme-challenge` delegation was removed;
- **the anycast IPs we publish for apex domains are reassigned** (see §2).

The first person to notice is the tenant, via traffic that stopped arriving. The dashboard will still say
*Connected & verified*, because that is a stored boolean from the day it passed.

Worth naming precisely, because it is the shape of several bugs found this week: **the stored state and
the served reality are allowed to drift, and nothing compares them.**

## 2. Why now

Apex domains (`plans/SITE_OBJECT.md` Phase 2.6b) need A records, because Route 53 — and most registrars —
cannot point a bare apex at an external hostname. The IPs to publish already exist: both Cloudflare zones
resolve to an anycast pair (`104.21.71.205`/`172.67.149.43` for jbay.uk, a different pair for jbay.be), and
setting `CloudflareApexIpv4` makes `_apex_routing_records` emit them instead of ALIAS guidance.

But they are **shared** anycast IPs on a Free-plan zone, not addresses we own. If Cloudflare reassigns one,
every tenant apex pointing at it breaks at once — and under today's behaviour, invisibly.

This sweep is what converts that risk from *catastrophic and undetected* to *annoying and reported*, which
is what makes shared IPs a reasonable starting point rather than a gamble. It is the precondition for the
apex decision, and it earns its keep on the other five failure modes regardless.

## 3. What already exists

This is assembly, not invention. Nearly every piece is built:

| piece | where | note |
|---|---|---|
| what each tenant was TOLD to create | `domain_provisioning.dns_records` on the Site | written by `connect_domain`; apex rows carry `apex: true` |
| live per-record DNS check | `diagnose_dns_records()` | DNS-over-HTTPS, per-record pass/fail, has an apex branch |
| authoritative status | `find_custom_hostname()` / `derive_status()` | Cloudflare is the authority; DNS checks only explain |
| the notification write path | `notifications_repository` (mode-scoped) + `validate_notification` | builders like `lead_notification` are the pattern |
| scheduled-sweep shape | `ReminderSweep`, `CartRecoverySweep`, `ReviewInviteSweep` | `Schedule: rate(...)` in template.yaml |

Missing: the schedule, the comparison, and a little state so it reports once rather than daily forever.

## 4. Design

### What it checks, and in what order of authority

1. **Cloudflare's own status** for the custom hostname —
   `status` and `ssl.status`. This is authoritative; the docstring on `diagnose_dns_records` already says
   so. A hostname that is `active`/`active` is healthy and the sweep stops there.
2. **Only when (1) is unhealthy**, run `diagnose_dns_records` over the STORED `dns_records` to say *which*
   record is wrong. That is what turns "your domain is down" into "the `_acme-challenge` CNAME is missing".

**The `www.` sibling is deliberately not checked.** An apex Site also provisions `www.<apex>` as a 301,
but that is best-effort (`_setup_www_redirect`) and the store serves without it. A tenant who never
created its DNS rows is in the same observable state as one whose rows broke, and without per-hostname
history the two cannot be told apart — so checking it would nag about a redirect some tenants never
wanted. The connect screen already shows those rows with a Verify button; this sweep is for regressions,
not for setup a tenant chose not to finish. Revisit if `www` ever stops being optional.

Checking Cloudflare first matters for a reason specific to apex: after we change `CloudflareApexIpv4`, a
tenant still pointing at the OLD IPs may be perfectly healthy. Re-deriving the expected records and
comparing would report every one of them as broken. **The stored record is what they were told; Cloudflare
is whether it works.** Never re-derive.

### Notice discipline

A notice needs an action the tenant must take (`feedback-notices-only-when-actionable`). So:

- a healthy domain produces **nothing** — no notification, no log noise;
- an unhealthy one produces **one** notification naming the specific record and value to fix;
- it does **not** repeat. Store `domain_provisioning.health = {state, checked_at, notified_at}` and notify
  only on a transition into unhealthy. Recovery clears the state silently.

### What it must NOT do

- **Never auto-disconnect, auto-unpublish, or de-index.** A transient DNS blip must not take a store's
  indexing with it — recovering from that costs the tenant far more than the outage. Record and report.
- **Never write the whole Site document** to record health. Use the targeted route-entry update added in
  `54fc69f`; a sweep over many Sites is exactly the fan-out that loses sibling writes
  (`feedback-shared-document-read-modify-write`).

### Scope and cost

- Live-mode Sites with a `custom_domain` only. Test-mode Sites cannot have one (`_reject_non_live_site`),
  so the sweep is live-only by construction, and each deployment sweeps its own Sites.
- One Cloudflare read plus a handful of DoH lookups per domain, and only for domains that fail the first
  check. At current volumes this is a rounding error.
- **Daily is plenty.** Every failure mode here is slow — registrar lapses, provider migrations, IP
  reassignments. A 15-minute cadence would buy nothing and multiply the API calls.

## 5. Definition of done

- A scheduled sweep reports an unhealthy custom domain once, naming the record to fix, and says nothing
  about a healthy one.
- A tenant pointing at superseded-but-working apex IPs is **not** reported as broken.
- Health state is recorded without rewriting the Site document.
- Nothing is auto-disconnected, auto-unpublished or de-indexed by the sweep.
- Tested with: a healthy domain (silent), a missing routing record, a missing DCV record, and a domain
  whose Cloudflare hostname was deleted out from under it.

All met, in `tests/test_domain_health_sweep.py`. Two cases beyond the list proved worth pinning:

- **A Cloudflare outage blames nobody.** `CustomDomainError` records no verdict and sends no notice — a
  notice there would tell a tenant to fix their DNS because our provider was down.
- **A serving domain has its DNS re-examined by nothing at all.** One test injects a diagnoser that
  raises; a second asserts the module never so much as names `custom_hostname_dns_records`. That is the
  structural guard on §4's never-re-derive rule, which is what keeps the apex migration quiet.

## 6. What this unblocks

Setting `CloudflareApexIpv4`/`IPV6` to the zones' anycast pairs, which makes apex domains work on Route 53
and every other provider — the last remaining item on `SITE_OBJECT.md` Phase 2.6b. The sequence is: this
sweep, then the apex IPs, then dedicated IPs if and when apex tenants justify the line item. By then the
migration is a known list of names (we stored what each was told) and a gradual overlap rather than a
coordinated outage.
