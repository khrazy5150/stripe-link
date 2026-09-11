# Creator link policy

Status: PLANNED 2026-09-11, not built. Answers the open item recorded at `TODO.md` ("`PLATFORM_LINKABLE_HOSTS`
is still just the 16 identity hosts … it needs an abuse story rather than a longer list"), and is the
prerequisite the `jbay.page` vanity domain has been waiting on.
Related: `SOCIAL_MEDIA_PAGES.md` §7 (trust model) and §4 (the vanity-URL decision), `LEAD_GEN_PAGES.md` §8a
(page-local links), `TODO.md`.

---

## 1. Why this exists

A link-in-bio page is a page whose entire content is **outbound links to places we do not control**. Every
other page type we render is about the tenant's own catalogue; this one is a launcher. That single difference
is what makes it the page type with a policy attached.

It is also the page type that will live on a **shared apex** — `jbay.page/username`, path-on-apex, decided
2026-08-30 (`SOCIAL_MEDIA_PAGES.md` §4). One registered domain, every creator, no origin isolation between
them. Blocklists, Safe Browsing and registrar abuse desks act per registered domain, so the blast radius of
one bad actor is every creator on the domain.

So the question this document answers is not "which links look professional". It is: **what may a page point
at, under what label, and what happens when someone abuses it** — because the answer is what keeps the domain
alive.

## 2. TWO rules, and they must not be conflated

They have different subjects, different reasons and different scopes. Every time they have been discussed
together someone has collapsed them, so they are separated here permanently.

| | **Linkability** | **Adult-content warning** |
|---|---|---|
| Question | May this become an anchor at all? | Should a visitor be warned before going? |
| Reason | The URL bar. A phishing tap on a shared domain is a browser-blocklist and registrar problem for OUR domain and every tenant on it. | Accidental exposure, and demonstrating we have a content policy. |
| Scope | **Platform hosts only.** On the tenant's own verified custom domain any destination links — the reputation at stake is theirs. | **Everywhere**, including custom domains. It is about the visitor, not our domain. |
| Failure mode | Domain blocklisted, every creator down. | Someone opens adult content unexpectedly; we look unmoderated. |
| Today | `PLATFORM_LINKABLE_HOSTS = SAME_AS_HOSTS`, 16 hosts. | Does not exist. |

**A glyph is a FOURTH thing, and not tied to any of the three above (2026-09-11).** It says only "you
recognise this place". Snapchat and OnlyFans are on a creator's hub constantly and could never be a `sameAs`,
so keying the icon table on `SAME_AS_HOSTS` meant spelling out exactly the links a link hub exists to show.
Icons are now keyed on their own table, with display names in `RECOGNISED_LABELS` -- deliberately separate
from `NETWORK_LABELS`, which is mirrored into the Business-identity picker and must keep offering only hosts a
tenant can actually claim.

**An unrecognised host gets a globe, never its spelled-out name** (author, 2026-09-11: a text pill "adversely
disrupts the organized look of the social icons"). The name moves to `aria-label` and `title`, so a screen
reader and a hover still name the destination; only the disruption is lost. A globe rather than a question
mark: the link works, we simply do not know where it goes, and the tenant typed it on purpose.

**Glyphs, noted here because it is the same confusion in miniature (2026-09-11).** LinkedIn was rendering as a
worded pill because simple-icons had removed it at LinkedIn's request — and that request is about one library
redistributing the asset, NOT a rule against showing a LinkedIn icon on a link to a LinkedIn profile, which is
ordinary nominative use and what every product in this category does. "We cannot source it from there" was
read as "we may not show it". It is now hand-drawn in `domain/network_icons_manual.py`, rendered and compared
against the real mark before shipping, and kept out of the generated file so a refresh cannot delete it.

A third rule already exists and is untouched here: **`sameAs`** — the machine-readable identity claim, gated on
the allowlist AND on server-owned verification. Page-local links never enter it (`LEAD_GEN_PAGES.md` §8a).
Three rules, three reasons, one shared temptation to merge them.

## 3. The allowlist is the abuse story

Stated plainly because it decides the launch order: **these pages carry no payment.** `lead_social` is the one
composition with no `checkout_cta` at all. So a bad actor on `jbay.page` has exactly one lever — the outbound
link — and `PLATFORM_LINKABLE_HOSTS` is the thing standing in front of it.

That has a consequence the author and I converged on 2026-09-11: **widening the list and launching `jbay.page`
are the same decision.** Path-on-apex makes it tighter, not looser, because a subdomain at least gets origin
isolation and a shared apex gets none.

Also recorded so it is not re-derived: **custom domains do not isolate bad actors.** A bad actor will not buy
one — the free disposable shared host is the whole attraction. Custom domains are a lifeboat for *legitimate*
tenants, so a `jbay.page` blocklisting does not sink them too. The isolation runs the opposite way from how it
first reads.

And separately: **illicit goods sold through Stripe is a different risk with a different control** (Connect
underwriting, account termination). It threatens the platform account, not the domain. Neither control
substitutes for the other.

## 4. A creator-shaped allowlist, not the identity one

`PLATFORM_LINKABLE_HOSTS` is literally `SAME_AS_HOSTS` — a list built to answer *"which hosts can make a
credible identity claim"*. It contains Crunchbase, the Better Business Bureau and Wikidata, and it contains no
Substack, Patreon, Amazon, Etsy, Spotify, Twitch, Bandcamp or Ko-fi.

So on the free host today a creator cannot link their **Substack or their Patreon**. That is a much more common
case than the adult one, and it would make `jbay.page` feel broken on day one.

**Split the constant.** `SAME_AS_HOSTS` keeps its 16 and keeps its job (identity claims). A new, larger
`CREATOR_LINKABLE_HOSTS` governs what may be linked from a platform-hosted page. The identity list stays a
subset. Reusing one list for two questions is how it came to be wrong for both.

Sizing principle: large enough that a normal creator page has no dead tiles, curated enough that every entry
was looked at by a person. Not an open redirect, not a hundred-host free-for-all.

## 5. The adult-content warning

### 5a. Host-derived, never tenant-declared (author, 2026-09-11)

Do not ask the tenant to flag their own links. A checkbox nobody ticks is a decorative control, and it puts us
in the position of accepting a creator's word about their own content. **Derive it from the destination host,
assuming the worst the platform's own policy permits.**

### 5b. The test: is this class of URL PREDOMINANTLY adult?

"Does the platform permit adult content?" is the wrong question. It is true of most large UGC platforms, so it
over-fires — and a warning that appears on almost everything stops carrying information. People click through
it reflexively, which destroys the value of the one that matters.

The question that predicts the destination is whether the host is *informative*. For OnlyFans and Fansly the
URL is the signal: paid creator content is the entire business model. For X the URL tells you nothing — the
same domain hosts news organisations, governments and every B2B brand.

### 5c. Verdicts

| Warn | Reason |
|---|---|
| `onlyfans.com`, `fansly.com` | Adult content is the platform's principal business. The host is the signal. |

| No warning | Reason |
|---|---|
| instagram, tiktok, youtube, facebook, threads, linkedin, pinterest, github | Adult content banned outright by the platform. |
| bbb, crunchbase, trustpilot, yelp, wikipedia, wikidata | Not creator UGC in any relevant sense. |
| **x.com / twitter.com** | **Permits adult content, but is overwhelmingly not that.** See below. |
| patreon, reddit, discord, ko-fi, gumroad (when added) | Permit it in a gated corner while being predominantly something else. Reddit is parked for its own study. |

**X, decided 2026-09-11.** It permits adult content — and warning on every X link would put an adult warning on
a nutrition store's X profile. Residual risk stated plainly: someone can put an adult X profile on a hub and it
will not warn. That is the right trade, and it is the one every competitor makes.

### 5d. The interstitial

**Every click, no per-visitor memory.** Observed on linkcloud.ai and link.me: both warn on every tap. Two
patterns in the wild — a modal ("Age Warning (18+) … Cancel / I'm 18+") and an in-place card blur ("Mature
Content Disclaimer … Continue (18+)"). Either shape works.

Remembering the choice would also mean storage on `jbay.page`, a **single shared origin across every creator
page** — the exact hazard `SOCIAL_MEDIA_PAGES.md` §6 flags for the cart keys. Warning every time needs no
storage at all. Matching the category and avoiding new shared-origin state are the same decision here.

**Keep the wording hedged**: "This link *may* contain adult content." That is a claim about the PLATFORM, which
is what we actually know. "This link contains adult content" is a claim about the creator, which we do not know
and must not assert about a named person.

**It is not age verification.** A one-tap attestation stops nobody who means it. It earns its place by
preventing accidental exposure and by demonstrating a content policy — which is what a registrar abuse desk
looks for. The age-assurance statutes (several US states, the UK Online Safety Act) bind the site HOSTING adult
content, not a page linking to it. Have that reading confirmed by counsel before relying on it.

### 5e. What this buys

With the warning in place, **OnlyFans and Fansly go ON the allowlist rather than being excluded.** We label
rather than host. That is a better position than a ban, and it avoids deciding a content policy by omission —
"not yet vetted" and "named and excluded" are different choices, and drifting into the second by way of the
first is how a policy ends up unwritten and unevenly applied.

Author's framing, adopted: linking to OnlyFans is not a Stripe violation; selling adult content through Stripe
Checkout is. Confirm against Stripe's current restricted-business list, since that governs the platform account.

## 6. Reporting and takedown

**The substantive half of the abuse story, and the part with no UI today.** link.me carries a `Report` link in
its page footer beside Privacy Policy and Terms.

- A `Report` link in the footer of every platform-hosted creator page.
- A report endpoint (public, unauthenticated, rate-limited — the same abuse-story requirement the click-ingest
  endpoint has, `SOCIAL_MEDIA_PAGES.md` §11).
- A real abuse address, monitored, and a written takedown process with a target response time.
- The ability to unpublish a page and suspend a username fast, without a deploy.

A registrar does not ask whether you have an interstitial. It asks what you do when someone abuses the domain.

## 7. Staleness is the failure mode

X's policy **changed** — it did not always permit this. A host table that encodes platform policy silently goes
wrong, which is the drift shape that has caught this codebase repeatedly (`same_as[].verified` read but never
written; two index projections missing a field; `PLATFORM_LINKABLE_HOSTS` itself).

- Stamp the table with a `reviewed` date.
- A test that FAILS when that date is older than a year. Surfacing beats remembering.
- Every host entry carries its reason in the table, so a reviewer can re-check the claim rather than re-derive
  the decision.

## 8. Order

1. **`CREATOR_LINKABLE_HOSTS`** — split the constant, curate the list, keep `SAME_AS_HOSTS` as it is. Smallest,
   and it is the one already producing dead tiles on a free host.
2. **The adult warn-list + interstitial.** Ships with OnlyFans/Fansly added to the allowlist in the same change,
   because the warning is what makes their inclusion defensible.
3. **Report + takedown.** Before `jbay.page` serves anything, not after.
4. **`jbay.page` launch** — routing, username claiming, the reserved path wordlist, PSL registration, and the
   `tenant_id`-namespaced localStorage keys (`SOCIAL_MEDIA_PAGES.md` §6/§7). Its own plan; this one is its
   admission ticket.

Nothing here gates the FEATURE: v1 link-in-bio pages work today on `{label}.jbay.uk` subdomains, and only the
hostname changes later (`SOCIAL_MEDIA_PAGES.md` §5, "do not let this gate the feature").

## 9. Open

- **Every platform-policy claim in §5c needs verifying against current policy before it ships.** They are
  written from knowledge with a cutoff, and that is precisely the staleness §7 is about.
- Where does the warning live — modal or card blur? Both are proven; pick one on design grounds.
- Does the warning apply to `link_cards` as well as `social_links`? It should: same destinations, same risk.
  The §7 linkability rule already governs both.
- A host on the allowlist that is NOT predominantly adult but whose specific URL is (an adult X profile) is
  accepted risk, not an oversight. Revisit only with evidence of actual abuse.
- Reddit: parked for its own study, per `TODO.md`. Do not decide it here.
