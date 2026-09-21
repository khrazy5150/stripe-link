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

The rule that avoids it:

1. **Never bake noindex into a variant's artifact.** The artifact served at the tested URL must carry the
   robots value the TESTED page is entitled to.
2. **Apply noindex at the EDGE, by route**, when a variant is requested at its own URL. The mechanism
   already exists — the Worker stamps `X-Robots-Tag: noindex, nofollow` when `route.noindex` is set, which
   is how free platform hosts are kept out of the index.
3. **Point every variant artifact's canonical at the TESTED URL**, not at its own. Canonical is baked at
   publish from the page's own published URL today, so this is a real change and not a default.

Cleaner still, and worth considering: **do not give variants a public route at all.** A variant that exists
only to be served at the tested URL has no second URL to index, which removes the question rather than
answering it. Previews already run on noindex hosts.

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
