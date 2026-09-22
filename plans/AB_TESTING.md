# A/B testing: moving the experiment onto the page

## What already exists (more than expected)

Verified 2026-09-21. The whole chain is built and careful:

- `handlers/experiments.py` — CRUD, lifecycle (start / pause / complete), results.
- `handlers/experiments_resolve.py` — weighted assignment, a sticky cookie, control fallback for
  draft/paused, winner routing once completed.
- `Experiment.schema.json`, `ABTesting.vue`, per-mode tables, and a short code per experiment.
- Views increment through an **atomic DynamoDB `ADD`**, not a read-modify-write, so concurrent traffic
  cannot lose counts.
- Conversions attribute through `order.attribution.page_id`, which checkout already carries in session
  metadata. Each variant IS a page, so this works without a new mechanism.

**And zero experiments have ever been created in either environment.** Like booking, it is complete on
paper and has never run.

## The model is wrong for this codebase

Entry is a short code: `go.jbay.uk/{code}` -> Worker -> routes resolve -> the experiment resolver ->
302 to a variant's published page.

That was right in stripe-cart, where the short URL WAS the published page. In stripe-link a page lives at
`poliaxis-nutrition.jbay.uk/link-bio` or the tenant's own domain, and that is the URL in their ads, their
bio and their printed material. A short-code experiment therefore:

- **biases the sample** — organic traffic to the real URL never enters the experiment, so the test measures
  only the slice deliberately routed through the short link;
- changes the visible URL, off-brand and off-domain;
- leaves every existing link outside the test.

## The model it should be

**The experiment attaches to the PAGE, and the edge serves a variant at the same URL.**

The Worker already reverse-proxies published pages ("the visitor's browser only ever sees their own custom
domain"), so a variant can be served with no redirect and no URL change. Two thirds of the machinery is
already there.

### The cache decides where assignment lives

The Worker caches resolve responses for 60 seconds (`Cache-Control: public, max-age=60`). If `resolve`
picked the variant, **every visitor in that window would get the same one** — a time-bucketed split, not a
random one, which on low traffic hands one variant nearly everything.

So responsibilities split on cacheability:

| | Who | Why |
|---|---|---|
| **What the experiment is** — variants, weights, each variant's origin URL, cookie name | resolve (server) | identical for everyone, so caching is correct |
| **Who gets which** — read cookie, pin or roll | the Worker (edge) | per-request, must never be cached |
| **Counting a view** | the Worker, `waitUntil` a ping | fire-and-forget; counting must not delay the response |

Attribution needs no change: each artifact carries its own `page_id` into checkout metadata, so whichever
variant was served is what the order records.

### One assignment implementation

`/experiments/{id}/resolve` and the per-experiment short code are **disabled, not dismantled** — the code
stays, nothing routes to it, and `ABTesting.vue` stops offering the short link. Two live assignment paths
would roll separately and set separate cookies, and that kind of drift is invisible until the numbers look
wrong.

## Indexing: the trap that would cost a tenant their rankings

The requirement is that a page in an experiment is forced to NOINDEX. Implemented naively, **that
deindexes the page being tested.**

`robots` is baked into the ARTIFACT at publish time ("noindex robots directive is applied server-side at
publish"). So if a variant's artifact says `noindex`, and the Worker serves that artifact at the control's
URL, Googlebot crawling the tenant's real URL reads `noindex` — and drops the page it was meant to improve.

### Why "republish everything as noindex" is the wrong fix

The obvious answer is to republish the pages in the test as `noindex,nofollow` and restore the winner
afterwards. It fails for the same reason as the trap: **the tested URL IS the tenant's live page**, the one
with the rankings. Republishing it noindex drops it from Google for the length of the experiment, and
recovery after re-indexing takes longer than the test did. The page being tested is exactly the one that
must stay indexable.

### The rule: bake the TESTED page's identity into the variant

Solve it at publish, not at the edge — just bake the right value rather than noindex. A variant artifact is
not "a page"; it is **an alternative rendering of the tested page**, so it inherits that page's SEO
identity:

1. `canonical` → the **TESTED** URL, not the variant's own. Canonical is baked at publish from the page's
   own published URL today, so this is a real change.
2. `robots` → whatever the **TESTED** page is entitled to, normally `index,follow`. Never noindex, because
   this artifact is served at the tested URL.
3. **Do not give variants a public route.** A variant exists to be served at the tested URL; without a
   second URL there is nothing to index, nothing to noindex, and no duplicate-content question to answer.

This is simpler than stamping robots at the edge, and it takes a moving part OUT of the Worker — the
highest-blast-radius component in the system. Whichever variant is served, the response identifies itself
as the tested URL and carries the tested URL's indexing rules.

### Two representations of a variant, and the invariant that follows

The section above is right that a variant artifact inherits the tested page's identity, but it treats "a
variant" as one thing. It is two, and conflating them produced a real bug (below):

1. **Variant as an experiment artifact.** The worker swaps `origin_url` while the request stays on the
   control's URL. Nothing about the web resource changes — no redirect, no `?variant=`, no `/offer-b`.
   Googlebot sees one address serving one page, exactly as before.
2. **Variant as an independently addressable page.** A variant that someone explicitly attaches to a slug
   gets a tenant-domain URL of its own. *That* is a second indexable URL with near-identical content.

They get opposite SEO treatment, and the rule is:

> **An experiment must never cause the control/tested URL to become non-indexable** — and separately, an
> independently addressable variant must not become a competing indexable URL.

Stamping noindex on an assigned response violates the first half: it tells Google the URL it has been
ranking should be dropped, which is precisely backwards for this architecture. **This was shipped to all
three zones on 2026-09-21 and reverted the same day.** The inversion worth remembering: the check was
`running_experiment_for(page)` — which matches on `control_page_id` — so the header landed on the control
and never on the variant. The ranking page was deindexed while the actual duplicate stayed indexable.

The enforcement layer is the **resolver, not the worker**. The worker's job is `resolve → assign →
substitute origin_url`; it has no idea which page it is serving or what URL corresponds to it. The resolver
already knows the page_id, whether the page is the control, whether it is a variant, whether the experiment
is running, and what public URL the page is attached to. So the rule is checked against *the page being
served as its own resource*:

```python
if variant_of_running_experiment(page_id, experiments):   # NOT running_experiment_for(page_id, ...)
    route["noindex"] = True
```

- control URL → untouched, indexable, keeps its accumulated signals
- control URL with an artifact swapped behind it → untouched, identical to a crawler
- unattached variant → no public URL at all; nothing to crawl (the strongest case, and the default today:
  publishing does not attach, `POST /sites/{id}/attach` is a separate deliberate action)
- attached variant → `noindex` on *its own* URL

Blocking attachment outright while a page is an active variant is the stronger form of the same rule and
remains open; the noindex above is the backstop that also covers a page attached before the experiment
started.

### Lifecycle: republish in place, never unpublish

Unpublishing DELETES the published artifact (`delete_page_artifacts` on the unpublish path), so the page
404s until it is republished — an outage on the tenant's live URL, twice per experiment. Republishing in
place is enough: a save re-renders the artifact.

**The tested page is never touched when an experiment starts.** It already has what a tested page needs:
its canonical IS the tested URL, and its robots are whatever it earned. A page that has been ranking for
two months keeps serving continuously — the risky operation simply never happens. Only the NEW variant is
published, for the first time, carrying the tested page's canonical and robots and no route of its own.

- **Starts** → publish the variant(s). The tested page is untouched.
- **Control wins** → nothing to do. Stop assigning; the tested page has been serving all along.
- **Variant wins** → the one point where the tested page changes. See below.

#### Promoting a winner: re-point the route

**The ROUTE is the durable identity; the page behind it is swappable.** `Site.pages` is a slug-keyed route
map and "a page_id belongs to at most one Site", so moving a slug to a different page is one field.

This is the same architecture stripe-cart had — there the durable address was a short code and pages were
interchangeable targets; here the durable address is a real URL on the tenant's own domain. The insight
that the two are the same shape is what settles this.

So: **promotion re-points the slug at the winner.** Not "copy the winner's content into the tested page",
which was the first instinct and is wrong for three reasons:

1. **Attribution splitting is the truth, not a flaw.** Past orders carry the old page_id and future orders
   the winner's, because the page genuinely changed. Merging them under one id would destroy the thing the
   test was run to learn — did conversion improve after the switch — and the experiment already depends on
   per-page attribution to compute results at all.
2. **"Copy the content" is a deep clone.** A page document carries sections with their own ids, theme,
   composition, SEO and offer references. Rewriting all of it into the tested page would also attach the
   winner's measured performance to the loser's page_id, falsifying the record.
3. **Re-pointing needs no republish.** Under the identity rule above, a variant's canonical ALREADY points
   at the tested URL, so when it takes the route it is already correct. One field change, no artifact
   rewrite, no gap.

The loser keeps a canonical pointing at a URL that now serves the winner — harmless, because it is
unrouted and never served, and it is a useful record of what lost.

Consequence for the model: a variant IS a full page (it must be routable eventually), it simply has no
route while the experiment runs.

Drafts are not an option, and the reason is worth recording: `handlers/checkout.py:118` refuses a checkout
whose page is not `published` (403 `page_not_published`), so a draft variant could never convert and the
experiment would measure nothing.

Do NOT special-case crawlers by serving them the control — that is cloaking. Google's own A/B guidance is
canonical to the original, 302 rather than 301 if redirecting, and run the test no longer than needed.

## Significance: interpret the numbers, do not gate the tenant

`compute_results` returns `conversion_rate` and nothing else, and `complete_experiment` takes whatever
`winner_page_id` the tenant posts. stripe-cart was the same — checked 2026-09-21: no significance test, no
minimum sample, no auto-pause anywhere in it (the only `confidence` in that codebase is invoice matching).

**Keep that freedom.** The tenant decides who won. Refusing to let them is paternalistic and they may have
reasons the data cannot see — a variant that is off-brand, a seasonal deadline, a stakeholder who already
decided. No gate, and no auto-pause.

**But stop presenting noise as a result.** "B 12% vs A 8%" is not a neutral display: a bare pair of
percentages READS as an outcome. On 25 visits it is within normal variation, and a UI that shows only the
percentages has implicitly told the tenant otherwise. That is the actual defect — not the tenant's
judgement, but what the screen led them to believe.

So the results screen says what the numbers support, and the button stays:

> **Too early to tell.** B is ahead (12% vs 8%), but with 25 visits that is within normal variation.
> Around 300 visits per variant would separate a difference this size.
>
> *Declare a winner anyway →*

### The cheap version is most of the value

No statistics library and no p-value ceremony. Two honest numbers stripe-cart never showed:

1. **How far apart the variants are relative to the noise.** One formula. This is what turns "12% vs 8%"
   from a result into a question.
2. **How much longer at the current rate.** Arithmetic, and the most actionable thing a tenant can be
   told — it converts "not yet" into a decision about whether to wait.

Also state plainly what is being measured: conversion rate over VIEWS counted at assignment, which is not
sessions and not unique visitors. A tenant should not discover that difference later when the number
disagrees with their analytics.

## Phases

- **A1 — the model.** Attach experiments to a page; resolve returns the experiment definition; the Worker
  assigns, pins, proxies and pings. Disable the short-code path.
  - **A1a — the server half: DONE 2026-09-21.** `domain/experiments.py` (pure) +
    `custom_domains_resolve` returns `route.experiment` = `{experiment_id, cookie_name, variants[]}` with
    each variant's own artifact URL. `origin_url` stays the CONTROL's, so an edge that does not understand
    the block still serves the control -- which is what lets the backend ship first and makes a Worker
    rollback degrade to "no experiment" rather than to a broken page.
  - **A1b — the edge half: DONE 2026-09-21.** The Worker reads the cookie, pins or rolls, proxies that
    variant's origin_url, sets the cookie, marks the response `private, no-store` (a variant must never be
    shared between visitors by any cache) and pings `POST /experiments/{id}/view` inside `waitUntil`. A
    view counts only on a NEW assignment, never on a pinned visitor's refresh. The view endpoint is public
    and validates page_id against the experiment's own variants, because that value becomes a DynamoDB
    attribute NAME in `increment_view`. **Still to deploy: the Worker itself** --
    `deploy/setup-cloudflare-custom-domain-worker.sh`, per zone, not `deploy.sh`.
  - **A1c — disable the short-code path: DONE 2026-09-21.** One flag,
    `SHORT_CODE_ENTRY_ENABLED = False` in `domain/experiments.py`, carrying the reasoning. Creating an
    experiment no longer allocates a code or a route; `with_short_url` omits the link so nothing can show a
    tenant an address that no longer assigns anyone; `/experiments/{id}/resolve` answers **410**; the
    screen shows no short link. The assignment LOGIC is kept and still tested directly, because the edge
    implements the same rules and those tests are the record of what they are.
- **A2 — indexing: DONE 2026-09-21.** Three layers, because the tenant flow that breaks it is the common
  one — build a variant page, publish it (attached, so it bakes `index,follow` and its own canonical), THEN
  start the test:
  1. *Publishing* (`identity_page_id`): a non-control variant of a running experiment takes the TESTED
     page's identity — one substitution, from which page_type, slug, canonical, robots and home_url all
     follow. This is what makes a variant safe to serve behind the control's URL, and it is why detaching
     one is now safe too (detach republishes, and the artifact keeps the tested page's identity instead of
     collapsing to noindex). Needs a read grant on ExperimentsTable, or the lookup AccessDenies, is
     swallowed, and the variant silently bakes its own identity again.
  2. *Resolving* (`variant_of_running_experiment`): an attached variant's OWN URL is stamped noindex. The
     control's URL is deliberately untouched.
  3. *Starting* (Option A, `attached_variant_slugs`): a test refuses to start while a variant has a public
     address of its own. Fails open — the two layers above already cover it.
- **Experiment shape is immutable once started — DONE 2026-09-21.** `control_page_id` and `variants` freeze
  on `started_at`, and starting clears `stats.views_by_page`. Assignment is matched on `control_page_id`, so
  swapping it mid-flight moves the entry point to another URL while the counters — one cumulative,
  untimestamped map — merge both regimes with nothing recording which is which. That is unrecoverable, not
  merely skewed. Keyed on `started_at` rather than `running`, because pausing does not make the collected
  data compatible; a draft stays fully editable. Clearing the counters also closes "stop, edit, restart" as
  a way around the freeze. The editor mirrors the freeze so it never offers an edit the API will refuse.
- **A3 — significance: DONE 2026-09-21.** `domain/experiment_stats.py` (pure, stdlib): a two-proportion
  z-test per arm against the control, a verdict in WORDS (`clear` / `likely` / `too_close` /
  `insufficient`), relative lift, and "how much longer at the current rate" from a rule-of-thumb sample
  target. No gate and no auto-pause — when there is enough evidence is the tenant's call, and the screen
  says so in as many words.
  What it refuses to do is the substance:
  - **`None`, never a reassuring zero.** No views, nobody converted yet, or no difference to detect return
    `None`. "No evidence either way" and "measured no difference" are different statements, and a caller
    that cannot tell them apart reports the first as the second.
  - **No verdict on revenue.** These are proportion tests; revenue per view has a much wider distribution.
    Claiming significance on it with this machinery would be inventing a result.
  - **No infinite lift.** A control with a zero rate yields `lift: None` rather than a number.
  - **Elapsed time stops at completion**, so a result opened weeks later does not claim the test ran for
    weeks and dilute the rate it was actually collecting at.
- **A6 — the picker had to name pages a tenant can tell apart (2026-09-21).** Found in QA. Duplicating a
  page is the normal way to make a variant, so two identical names in the picker is the RULE, not an edge
  case — and `route.slug` does not separate them either, because slug uniqueness is enforced when a page is
  attached to a Site, not on the page itself, so duplicates genuinely share one. The picker now labels each
  page with where it is served (`Name — /slug`, or `Name — not on a site (id)`), which disambiguates them
  AND shows up-front which pages are eligible to be variants. Option A's refusal names the page as well as
  the slug for the same reason. Retired the stale "one short URL" copy in the header and the delete dialog
  while here (A1c removed that path).
  **Still open:** the workflow itself. A tenant must duplicate a page, then know to detach the duplicate,
  before a test can start. A "test a variant of this page" action that duplicates and leaves it unattached
  would remove the step nobody guesses.
- **A7 — starting a test must RE-RENDER its variants (found in QA, fixed 2026-09-21).** A2 applies at
  publish time, and the order a tenant actually works in is: build the variant, publish it, *then* start
  the test. So the artifact was rendered while the experiment did not yet exist, `identity_page_id` had
  nothing to resolve, and the variant baked its OWN identity — an interim canonical pointing at the raw
  artifact URL and, on a live custom domain, `noindex` (an unattached page is not on a custom domain).
  Served behind the tested page's URL, that is the de-indexing trap this whole phase exists to prevent.
  Caught on dev only because test-mode pages are noindex anyway, which hid half of it.
  `start_experiment` now re-puts each non-control variant so the publish stream re-renders it — **after**
  the experiment is saved as `running`, since `identity_page_id` keys off a running experiment and a
  re-render ordered before that would resolve nothing. Best-effort per page: a variant that cannot be
  re-put keeps the artifact it already had, which beats blocking the start over a transient write.
  Needs Crud on PagesTable (was Read).
  **A7b — and the substitution had to start at the SITE lookup (found in QA the same day).** Re-rendering
  alone changed nothing, because `publish_page_document` resolved the Site from the VARIANT's page_id —
  and a variant is required to be unattached (Option A), so it found no Site at all. Every substitution
  further down then operated on `site = None` and the artifact fell back to its interim identity anyway.
  `identity_page_id` now runs BEFORE `find_site_for_page`, which is also correct for everything else that
  Site is used for: an inline funnel on the variant must attach where the visitor actually is, and the
  Organization graph and chrome belong to the tested page's Site. The swallowed exception in
  `identity_page_id` now logs, because "lookup broke" and "not a variant" were indistinguishable — which
  is what made this take three passes to find.
- **A8 — the view ping was looking in the wrong mode (found in QA, fixed 2026-09-21).** Every experiment
  read zero views however much traffic it got. `experiments_view` built its repo with
  `experiments_repository()` — no mode — while the experiment had been written mode-scoped. This table is
  partitioned by KEY (the mode is baked into the SK and GSI1PK), so the mismatch did not return the wrong
  document, it returned NOTHING: every ping answered 404 and nothing was ever counted.
  The edge has no session to infer a mode from, so the only party that knows it is the resolver that built
  the block — `view_url` now carries `?mode=`, and the endpoint reads it with `resolve_stripe_mode`
  (absent ⇒ test, the fail-safe direction). No Worker change: it pings whatever URL it is handed.
  Worth remembering as a class: a mode-agnostic repo against a key-partitioned table fails SILENTLY as
  "no data", which reads exactly like "no traffic yet".
- **A4 — prove it.** Two real pages, a real split, a real conversion. Nothing here has ever run.
  **Unblocked 2026-09-21:** the screen was live-mode only (`menu.js`, `environments: ["live"]`), which made
  proving it require real money. It is now offered in TEST mode too. Safe because isolation is structural —
  `DynamoDocumentRepository` bakes the mode into the SK and GSI1PK, so a test experiment and a live one
  cannot see each other, and both the resolver and publishing build the repo from the record's own mode —
  and because test-mode pages are forced to NOINDEX_ROBOTS at publish regardless, so a sandbox experiment
  carries no SEO risk. Experiment documents now also carry `stripe_mode`; isolation never needed it, but a
  dumped document could not otherwise say which mode it belonged to.
- **A5 — promotion actually promotes: DONE 2026-09-21.** Completing now moves the tested slug to the
  winner (`repoint_to_winner`), so the improvement a tenant measured is the one they get. Before this,
  `winner_page_id` reached serving only through the short-code resolver A1c disabled — a completed
  experiment reverted to the CONTROL and the tenant kept the loser while the screen said all traffic had
  moved to the winner.
  Three things it is careful about:
  - **The loser is not displaced.** `_attach_page_to_site`'s contract is to move a slug's previous occupant
    to a slug of its own so it stays reachable — right for attaching, wrong here, where it would hand the
    loser a public URL at the moment it lost. Promotion drops it instead: unrouted, artifact intact, a
    record of what lost.
  - **Promote before recording.** Completing is what stops assignment, so a route move that failed after it
    would revert the tested URL to the loser while the tenant was told the winner was live. A failure
    refuses the completion and leaves the test running and retryable.
  - **The outcome is stored, not asserted.** `experiment.promotion` is `moved` / `not_needed` / `no_route`,
    and the screen reads it. `no_route` is not an error: a tested page with no Site slug has no address to
    move, which is unusual but legitimate.

## Risks

- **The Worker serves every published page for every tenant**, and does NOT deploy with `deploy.sh`
  (`deploy/setup-cloudflare-custom-domain-worker.sh`, per zone). This is the highest-blast-radius change
  discussed so far; a bug takes down serving, not just experiments.
- A 60-second resolve cache means starting or stopping an experiment takes up to a minute to take effect.
  Acceptable, but it must be stated in the UI or it reads as a bug.
- Experiments on the test/preview hosts: out of scope, and they should stay out.

## Decisions — all settled 2026-09-21

1. ~~Do variants get their own public URL?~~ **Settled**: no. A variant is a full page with NO route while
   the experiment runs, which removes the indexing question rather than answering it — and the route is
   what a winner is promoted by (4).
2. ~~What is the minimum before a winner may be declared?~~ **Settled**: there is none. The tenant decides,
   as in stripe-cart; the screen tells them what the data supports rather than refusing.
3. ~~Does an experiment pause automatically?~~ **Settled**: no. It runs until the tenant stops it.
4. ~~How is a winner promoted?~~ **Settled**: re-point the slug at the winner. The route is the durable
   identity, exactly as the short code was in stripe-cart.
