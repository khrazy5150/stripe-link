# Managed DNS — we run the tenant's zone, so their root domain just works

**Status:** P1 + P2 BUILT 2026-10-25. Written 2026-10-25.

| | |
|---|---|
| P1 — the mail-safety gate | `domain/managed_dns.py` · `tests/test_managed_dns.py` |
| P2 — zone provisioning | `domain/cloudflare_zones.py` · `managed_zones_repository` · `managed_dns.provision()` |
| P3 — activation (serving records, Worker route, index record) | not built |
| P4 — the dashboard flow | not built |
| P5 — offboarding UI over `zone_export` / `delete_zone` | not built |

Every Cloudflare call takes an injected `opener`, so P2 is fully tested against fakes. **It cannot run
live yet**: the token has no `com.cloudflare.api.account.zone.create` (§5).

P1 is the safety gate, deliberately first: it is the only part whose failure cannot be undone, and it
needs no Cloudflare access to build or to test.

The tenant changes two nameservers at their registrar and never sees Cloudflare. We create the zone, write
every record, and the apex serves — on Route 53 domains, GoDaddy domains, anything.

## 1. Why

`plans/SITE_OBJECT.md` 2.6b ends in a hard limit: a root domain can only reach us if the tenant's DNS
provider supports ALIAS / ANAME / CNAME-flattening. Cloudflare, Namecheap, DNSimple, DNS Made Easy, NS1 and
Porkbun do. **Route 53 and GoDaddy do not**, and between them they hold an enormous share of small-business
domains. For those tenants the root domain is simply unavailable, and the fallback — connect `www`, redirect
the root — is a compromise that costs them the address they actually print on things.

The constraint is a property of *whose nameservers the domain is on*. So change that, without asking the
tenant to learn a new control panel.

## 2. The shape

1. Tenant types `example.com`. We detect their current provider from the NS records (built — 
   `dashboard/src/composables/dnsInstructions.js`) and offer two routes (§6).
2. They choose managed DNS. We `POST /zones` on **our** Cloudflare account, `type: full`.
3. Cloudflare runs its quick scan and imports what it can find. We read the zone's records back and show
   them a **review screen**: *this is what we found; anything missing will stop working.*
4. They confirm. We show the two assigned nameservers (`GET /zones/{id}`) and the exact steps for *their*
   registrar.
5. They change the NS. We poll zone status until `active`.
6. We write the serving records ourselves: a proxied record at the apex, a proxied `www`, and a Worker
   route on that zone pointing at the same Worker the platform hosts already use.
7. Universal SSL covers `example.com` and `*.example.com` automatically. No DCV delegation, no custom
   hostname, no `_acme-challenge` for the tenant to add.

**Note what disappears.** No Cloudflare for SaaS custom hostname. No ownership TXT. No DCV CNAME. No apex
proxying add-on. The whole class of problems from 2026-10-23 is a property of pointing *someone else's*
zone at us; when we hold the zone, the apex is just a proxied record and CNAME flattening is automatic.

## 3. What this buys beyond apex

- **One nameserver change instead of four records**, and nothing to mistype. Most support load on custom
  domains is a record entered at the wrong name or the wrong type.
- **We can fix things.** A broken record today needs the tenant to go and edit it; here we edit it.
  `plans/DOMAIN_HEALTH_SWEEP.md` currently reports a dead domain — with the zone in hand it could *repair*
  one, which is a materially different product.
- **Verification records write themselves** — Google Search Console, Bing, email providers. Several planned
  features ask the tenant to add a TXT somewhere.

## 4. What it costs, honestly

**We become responsible for their entire DNS, including email.** This is the whole risk and it deserves to
be stated first. If the zone goes live missing an MX record, the business stops receiving mail, and they
will not connect that to having clicked a button on our Sites screen. Cloudflare's quick scan is explicitly
best-effort — their own docs: *"not guaranteed to find all existing DNS records"*, and they name email
records and non-default DKIM selectors as the usual misses, because those cannot be enumerated without a
zone transfer.

Non-negotiable consequences:

- **The review screen is a gate, not a courtesy.** Records are shown before the nameserver change, with
  mail called out separately, and the tenant confirms. A missed MX found *before* the switch is a
  non-event; found after, it is their business email.
- **Never auto-migrate.** No flow where connecting a domain silently moves DNS.
- **Offboarding is designed before onboarding.** A tenant who leaves must be able to take their zone with
  them: export every record as a file they can hand to the next provider, and delete the zone on request.
  Holding a customer's DNS hostage is not a retention strategy, and building the exit last is how it
  happens by accident.
- **The API token can edit any tenant's DNS.** Blast radius worth naming: today's token mints custom
  hostnames; this one rewrites zones. Separate token, minimum scope, and writes limited to the records we
  own.

Smaller ones: NS changes take hours to propagate and the old provider keeps answering meanwhile; zones
accumulate on our account (no documented free-plan cap, but it is worth confirming before the hundredth);
and a domain already active in someone else's Cloudflare account cannot be added to ours.

## 4b. Decisions taken before building (2026-10-25)

**The zone is NOT part of the Site, and its lifecycle is not the Site's.** It gets its own record in
`CustomDomainsTable`, keyed by domain, `document_type: "managed_zone"` — beside the `custom_domain` index
records that already live there.

The reason is disconnect. A tenant who disconnects their custom domain today loses `domain_provisioning`,
and that is correct: it describes a Site's claim on a hostname. If the zone lived there, disconnecting
would orphan a Cloudflare zone that is still authoritative for the tenant's entire domain — their mail
included — with nothing in our data tracking it. **Disconnecting a Site must never delete a zone**, and
the only way to guarantee that is for the zone not to be the Site's to delete.

**No Cloudflare for SaaS custom hostname on a managed zone.** Once we hold the zone, the apex is a
proxied record in a zone we control, flattening is automatic, Universal SSL covers `example.com` and
`*.example.com`, and a Worker route on that zone sends requests through the same Worker the platform
hosts use. Custom hostnames, DCV delegation and the ownership token all exist to make SOMEONE ELSE'S
zone point at us; none of them apply when the zone is ours. The resolver still needs its
`custom_domain` index record — that is how the Worker learns what to serve — so that path is unchanged.

**The review gate compares, it does not trust.** Cloudflare's import scan is best-effort and says so. So
the review does not display the scan's output and ask for a nod; it independently resolves the domain's
MX, SPF, DKIM and DMARC over DoH and compares them against what the scan imported. A discrepancy blocks.
This is the same rule the domain health sweep is built on: stored state and served reality are allowed to
drift, so something has to compare them — and here the cost of not comparing is a tenant's email.

**Absence of mail does NOT block — a failed lookup does** (refined 2026-10-25, on the right question:
*what are the solutions when absence is found?*). Three states hide behind "no MX", and flattening them
is what makes a gate either useless or infuriating:

| state | what it means | what we do |
|---|---|---|
| asked, found nothing | web-only domain, or mail lives on another name | **allow**, after asking once |
| asked, found an MX the scan missed | the case this gate exists for | **block**, naming the record |
| could not ask | our lookup failed, not their DNS | **block**, and say it is ours |

The third was the hole. An empty result means one of two opposite things and only the caller knows
which, so `review()` takes `observed_complete` as a **required** keyword with no default: the
safe-looking answer cannot be reached by forgetting an argument. Inferring "no mail" from silence is how
our own failed lookup becomes a tenant's outage, and it is the same mistake `DOMAIN_HEALTH_SWEEP.md`
refuses to make when Cloudflare is unreachable.

**One contradiction blocks on its own: SPF present, no MX.** A domain publishing SPF is a domain that
sends mail, so that pair is not a mail-less domain — it is a partial answer. And it is precisely the
shape a partial answer takes, because SPF is a single TXT at the apex while MX enumeration is the part
that fails.

## 5. Open questions

- **Zones per account** on our plan — confirm with Cloudflare before this scales. (Account currently
  holds 3 zones, all Free: jbay.be, jbay.page, jbay.uk.)
- **RESOLVED, and it is a prerequisite:** the existing Cloudflare API token **cannot create zones**.
  Probed 2026-10-25: `POST /zones` returns *"Requires permission
  com.cloudflare.api.account.zone.create to create zones for the selected account"*. It also cannot read
  its own permission groups (403), so it is scoped to named zones — meaning it could not write DNS or
  Worker routes on a tenant zone either, since that zone does not exist when the token is scoped.
  Per §4 this wants a SEPARATE token rather than widening the existing one: the custom-hostname token
  stays narrow, and the managed-DNS token's larger blast radius is visible as its own credential.
  **The permission is `Zone | Zone | Edit`, not an account-scoped one** — Cloudflare's permission
  reference has no account-scoped "Zone" group; the account-looking string in the error
  (`com.cloudflare.api.account.zone.create`) is the zone RESOURCE scope, not an account permission. What
  makes a zone-scoped permission able to create a zone is Zone Resources = *all zones in the account*,
  since the policy has to cover zones that do not exist when it is written. Setup lives in
  `deploy/cloudflare-dns-token.sh`, which probes before storing.
- **Worker routes on a tenant zone**: we own the zone, so the API allows it, but the route must be added
  per zone and counts against route limits. Alternative is Orange-to-Orange with a custom hostname, which a
  third-party source says requires the two zones to be in *different* accounts — unverified, and moot if we
  do not use SaaS hostnames at all.
- **Email-provider detection**: can we recognise Google Workspace / Microsoft 365 / common hosts from the
  scanned records and say "we found your Google Workspace mail" in words, rather than listing MX rows a
  tenant cannot evaluate? This is the difference between a review screen that works and one that gets
  clicked through.
- **Registrar-specific NS instructions** — Route 53, GoDaddy, Namecheap at minimum; the detection to pick
  the right one already exists.

## 6. The two routes we offer

Both stay. The tenant picks:

| | Managed DNS (recommended) | Keep your DNS |
|---|---|---|
| Tenant does | changes 2 nameservers, once | adds 2–4 records |
| Root domain | works everywhere | only on an ALIAS/ANAME/flattening provider |
| Route 53 / GoDaddy | works | `www` only, root redirects to it |
| We can repair it | yes | no |
| Their other DNS | ours to carry — see §4 | untouched |

Recommend managed DNS, default to it, and never make it the only way: a tenant with existing DNS they trust
or an IT department that owns it must be able to decline and still connect a domain.

## 7. Definition of done

- A Route 53 tenant connects `example.com`, changes two nameservers, and the root serves — no `www`, no
  redirect, no add-on.
- No tenant's mail breaks. The review screen names mail explicitly and is impossible to skip.
- A tenant can export their zone and leave at any time, and the flow for doing so ships with the feature.
- `plans/DOMAIN_HEALTH_SWEEP.md` keeps working: a managed zone that stops serving is still reported.
- Keeping your own DNS remains fully supported.
