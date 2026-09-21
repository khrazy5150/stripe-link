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

#### Promoting a winner (undecided)

Two shapes, and they differ in what happens to the URL's identity:

- **Copy the winner's content into the tested page and republish in place.** An overwrite, so no gap. The
  URL keeps its page_id, its history, its canonical and its order attribution. Preferred.
- **Re-point the route at the winning page.** Faster, but the tenant's URL now serves a page whose identity
  was built as a variant — a different page_id, so historical order attribution splits across two pages —
  and the old page lingers unreferenced.

Either way there is no unpublish, and either way the answer has to be picked before A1 ships, because it
decides whether a variant needs to be a full page or only an artifact.

Drafts are not an option, and the reason is worth recording: `handlers/checkout.py:118` refuses a checkout
whose page is not `published` (403 `page_not_published`), so a draft variant could never convert and the
experiment would measure nothing.

Do NOT special-case crawlers by serving them the control — that is cloaking. Google's own A/B guidance is
canonical to the original, 302 rather than 301 if redirecting, and run the test no longer than needed.

## Significance: the gap that makes results actively harmful

`compute_results` returns `conversion_rate` and nothing else, and `complete_experiment` takes whatever
`winner_page_id` the tenant posts. So a tenant sees "B 12% vs A 8%" on 25 visits, crowns B, and changes
their page based on noise. That is worse than not testing, because it is confidently wrong.

Needed:

- A confidence signal per variant, and a plain-language verdict — "not enough data yet" is the honest and
  most common answer.
- A minimum before a winner can be declared, and a UI that refuses rather than warns.
- Say what is being measured: conversion rate on VIEWS counted at assignment, which is not the same as
  sessions or unique visitors, and the difference should not be discovered later.

## Phases

- **A1 — the model.** Attach experiments to a page; resolve returns the experiment definition; the Worker
  assigns, pins, proxies and pings. Disable the short-code path.
- **A2 — indexing.** Canonical to the tested URL; edge-stamped noindex by route; never bake it.
- **A3 — significance.** Confidence, a refusal to crown a winner early, and honest labels.
- **A4 — prove it.** Two real pages, a real split, a real conversion. Nothing here has ever run.

## Risks

- **The Worker serves every published page for every tenant**, and does NOT deploy with `deploy.sh`
  (`deploy/setup-cloudflare-custom-domain-worker.sh`, per zone). This is the highest-blast-radius change
  discussed so far; a bug takes down serving, not just experiments.
- A 60-second resolve cache means starting or stopping an experiment takes up to a minute to take effect.
  Acceptable, but it must be stated in the UI or it reads as a bug.
- Experiments on the test/preview hosts: out of scope, and they should stay out.

## Decisions needed

1. **Do variants get their own public URL at all?** Not routing them removes the indexing question
   entirely, at the cost of a bigger change to how a variant page is created.
2. **What is the minimum before a winner may be declared** — visits, conversions, or a confidence
   threshold? A number has to be chosen, and it will be wrong for someone.
3. **Does an experiment pause automatically** when it reaches significance, or keep running until the
   tenant stops it?
4. **How is a winner promoted** — copy its content into the tested page and republish in place (keeps the
   URL's page_id, history and attribution), or re-point the route at the winning page (faster, but splits
   attribution across two page_ids and leaves the old page unreferenced)?
