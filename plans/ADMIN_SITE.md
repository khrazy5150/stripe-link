# Admin Site

Status: **a collection point that now has a stack under it.** §1b (review removal) is BUILT and deployed to
dev as a separate repo, `../admin-site`; everything else here remains a requirement nobody has agreed or
scheduled. The document still exists for its original purpose — so that admin-shaped requirements stop
being remembered and start being written down — the author's words, 2026-09-20: *"I probably won't remember
to do this on my own, so let's record it in the plan."*

The first entry is the one that created the need; §1b is the one that got built first, because
[[REVIEWS]] took the delete button away from tenants and something had to hold it.

**Where the code lives: `../admin-site`, a sibling repo**, like `fonts-api` and `image-processing` — not a
screen in the tenant dashboard. Three reasons, in the order they decided it:

1. **The transform budget.** `stripe-link` sits against CloudFormation's 1MB transform limit; one new API
   route failed a prod deploy on 2026-10-05, and the headroom won back since is spent on tenant features.
   An admin stack has its own 1MB and does not compete.
2. **Blast radius.** These screens suspend tenants and remove reviews. A dashboard deploy currently
   redeploys ~75 Lambdas on the money path; shipping an admin button should not.
3. **Audience and cadence.** Platform staff, not tenants. Neither release waits on the other.

What it shares with `stripe-link`, and how: the **Cognito user pool** (by parameter — one sign-in per
person), the **reviews table** (direct access, IAM scoped to the five actions it performs, no
`DeleteItem`), and **nothing in S3** — bucket grants are added when a screen needs one, because a
speculative grant is the hard thing to walk back.

---

## 1. Abuse report queue  ⭐ the reason this document exists

plans/CREATOR_LINK_POLICY.md §6 requires four things before `jbay.page` carries anyone else's traffic. Three
shipped on 2026-09-20 — the footer link, `POST /report`, and fast suspension. The fourth did not, because it
is not code:

> A real abuse address, monitored, and a written takedown process with a target response time.

**An endpoint that records reports nobody reads is worse than none**, because it implies a process that does
not exist. The intake is built; this is where acting on it lives.

What the screen needs, and why each part:

| | Why |
|---|---|
| A queue of `status: "open"` reports | The table is `abuse_reports`, keyed by `report_id`. Nothing reads it today. |
| The reported page, its URL, and the reason | `page_id`, `host`, `reason`, `detail` are all stored. |
| The reporter's optional contact | Given voluntarily; unverified. Follow-up only, never authentication. |
| **How many reports name this page** | `source_ip` is stored deliberately so the screen can answer *"one person or many?"* — the question that separates a genuine problem from a grudge. |
| One-click suspend | Already possible: `PATCH /sites/{id}/status` → `archived` takes the platform host AND `jbay.page/{username}` off the air, username still reserved, no deploy. The screen only has to call it. |
| Resolve / dismiss with a note | `status` is on the document and only ever set to `open` today. |

**The part an admin screen cannot supply**: the monitored address. A queue nobody is alerted about is the
same failure one step later. Pair the screen with a real `abuse@` that notifies a person, and let the screen
be where that person then works.

## 1b. Review removal queue (added 2026-10-15)

The same shape as §1, a different target — and the reason it lands here is a decision taken in
[[REVIEWS]]: **tenants may no longer approve, reject or delete reviews.** Only a real buyer can write one
(submission requires the invite token), every review publishes on submission, and removal moves to this
site. A tenant's lever becomes a report.

Reuse the §1 intake rather than building a second one: the same `abuse_reports` table and the same
`POST /report` endpoint, with the target being a review rather than a page.

| | Why |
|---|---|
| Reviews **held by the harm filter** | Objective matches only — phone numbers, emails, URLs, slurs. The filter never judges sentiment, so anything here is a genuine "is this publishable" question. Held, not published. |
| Reports **from tenants**, with the reason they gave | The only path by which a tenant can act at all. |
| **How many reports name this reviewer or this tenant** | Same question §1 asks of `source_ip`: one grudge or a pattern? A tenant reporting every two-star review is visible here, and that is deliberate. |
| Remove with a **reason code** | Fixed list: spam, not a customer, abusive or illegal content, personal data, wrong product, reviewer withdrawal. **"Low rating" is not on the list.** Stored on the review. |
| Dismiss with a note | A dismissed report leaves the review published, untouched. |

**The rule that makes this queue honest: a report never hides the review.** If flagging pulled a review
down pending a decision, tenants would flag every two-star review and recover curation with a delay — the
integrity promise laundered through this queue. The review stays up until the platform removes it.

**What this queue must not become.** A merchant can no longer protect their own page, so the platform's
response time is now their exposure — more directly than in §1, where the reporter is usually a stranger.
A slur or a published phone number sitting live for three days because nobody read this is worse for that
merchant than the delete button they used to have. Two things keep it off this queue in the first place,
and they are part of the same design, not optional extras: the **automated harm filter** (most urgent
content never publishes) and **reviewer self-erasure** (the author withdraws their own words through a
tokenized link, no human involved). Ship those with it, not after it.

**Same caveat as §1, and sharper:** the monitored address and a target response time are the part no screen
supplies. Here a paying merchant is the one waiting.

### What shipped (dev, 2026-10-15)

`../admin-site`, 58 tests, deployed to `jb-admin-site-stack-dev`:

| Piece | Where |
|---|---|
| The allow-list — **being signed in is not being an admin** | `jb-admins-{env}`, its own table in this stack, seeded with `keith@juniorbay.com` by the deploy under a condition so a redeploy never re-enables someone deliberately disabled. Adding another admin is a row, through the screen. |
| The gate | `_admin_or_refusal`, applied in the dispatcher rather than per route — the failure mode of per-route checks is the route added later without one. There is no public route in that handler at all. |
| Reason codes, server-side | `domain/review_removal.py`. The screen renders the list the **API** returns, so a reason cannot be added by editing the front end. A test asserts `low_rating` is absent, which is what makes sentiment curation impossible rather than merely discouraged. |
| Removal is a **status**, never a delete | The row stays, the invite still points at it, and "did this ever exist" stays answerable. The IAM policy has no `DeleteItem`, so that is a property of the deploy and not of the code. |
| Release of a held review | The other half of the queue: holding without a way out would be removal with extra steps. Only a `pending` review can be released — nothing here resurrects a review removed for a reason. |
| Sign-in | Reuses `stripe-link`'s own `POST /auth/login` against the shared pool. No second sign-in to build, no second place a password is handled. |

Verified against live dev data, not only in tests: a token-less request is refused by the authorizer (401);
the allow-list admit/refuse pair answers 200/403; a real review was removed with a reason, read back from
the table carrying `removed_by`, and rolled back to its captured original.

**The intake landed the same day.** A tenant reports from the Reviews screen through `POST /reviews` with
`action: "report"` — the **authenticated** route, not the public `POST /report` this section first
proposed. Same `abuse_reports` table, so §1 and §1b remain one queue, but a different door: the public
endpoint cannot say *which tenant* filed, and "how many reports name this tenant" is the question this
section exists to ask. Reports arrive carrying `target_type: "review"`, the review's id, rating and
author, and the **verified** `reported_by`.

The admin side reads them and shows them as **notes beside a review that is still published**, in a
"Reported" view kept separate from the held queue. Mixing the two would teach the reader that a report
takes something down, which is the one thing it must never do. Each review carries the reports naming it
and the reporter's running total, so one report can be told from a pattern. Reports are **read and never
written** here — the IAM grant says so, because resolving a report is a different decision from removing a
review and has its own screen still to design.

**Not built yet**: resolving or dismissing a report (the rows stay `open`), the page-report side of this
screen (§1's own queue, still unread), and the monitored address with a target response time — the part no
screen supplies, and now a paying merchant is the one waiting.

## 1c. Tenant suspension — "shut them down immediately" (added 2026-10-16)

**The gap this closes.** §1 can suspend a *Site*; nothing can suspend a *tenant*. A tenant found selling
illegal products has pages on the platform host, pages on their own custom domain, live checkout links in
the wild, and the ability to publish more while anyone is reading a report. The author's words: *"If a
tenant is found offering illegal products, I should be able to shut them down immediately."* This should
have been in §1 from the start — an abuse intake whose only remedy is per-Site is an intake that cannot
answer for the account.

### The field: its own, NOT `billing_status`

`TenantProfile.billing_status` already has a `suspended` value and it is the wrong one to reuse, for a
reason that would not show up in testing: **it is webhook-driven.** `platform_subscription_sync` writes it
from Stripe subscription events, so a `customer.subscription.updated` arriving after an abuse suspension
would overwrite it with `active` and silently un-block the tenant. Nobody would be watching, and the
evidence would be a page that came back.

So: **`TenantProfile.platform_status`**, `"active"` (absent means active) or `"suspended"`, with
`suspended_reason` from a fixed list, `suspended_by` (the admin's verified email), `suspended_at`, and a
free-text `suspension_note`. Billing and abuse are different questions about a tenant and get different
fields.

### What a suspension does, in the order it matters

1. **The pages come off the air.** Published artifacts are deleted from the pages bucket and the paths
   invalidated at CloudFront. This is the part that actually answers an illegal-products report, and it
   takes seconds rather than a deploy.
2. **Checkout refuses.** Three call sites already load the tenant profile to assert billing standing
   (`checkout`, `cart_checkout`, `upsell`); the suspension check sits beside each, on the profile already
   in hand. Links already in the wild stop taking money.
3. **The dashboard locks.** Enforced at **sign-in and refresh**, which is one place rather than seventy:
   no token, no API. An open session dies within the hour when its access token expires, and meanwhile
   publish and checkout refuse it anyway.
4. **Publishing refuses**, so a suspended tenant's page cannot be put back by any path that touches a page
   document.

### Artifacts, not documents — so it is reversible

The takedown deletes **published artifacts** and leaves every page document untouched. The tempting
alternative — flipping each page to `archived` — also runs `detach_page_from_sites` and
`deregister_page_route`, which un-suspending would not restore: the tenant would come back to pages that
are no longer in any Site's route map. Deleting artifacts changes nothing that a republish does not
rebuild, so **restore is just publishing them again**.

### Where the takedown runs: folded onto `page_publish`

`TenantProfilesTable` has no stream, so the suspension cannot propagate by itself. The admin site writes
`platform_status` and then **invokes `{prefix}-page-publish-{env}` directly** with an internal payload —
no API route, which matters because the stack is at the 1MB transform limit.

That function is the right host and not an arbitrary one: it already holds the pages bucket, the
CloudFront distribution id and the IAM to use them, and it already contains `delete_page_artifacts` and
`publish_page_document` — the two halves of suspend and restore. Putting this anywhere else would copy
artifact-path knowledge into a second place.

The invocation is synchronous and **returns what it took down**, so the admin sees "7 pages removed"
rather than trusting that something happened.

### Fail closed, deliberately unlike the gate next to it

`entitlement_gate.require_capability` fails OPEN on any lookup error, and says why: *"a cross-cutting gate
must never itself 500 a tenant action."* That is right for a plan feature and wrong here. A suspension
check that cannot read the profile must refuse, because the cost of wrongly allowing is a live illegal
page and the cost of wrongly refusing is a merchant who contacts support.

### What it deliberately does not do

- **It does not delete anything of the tenant's.** Documents, orders, products and media stay. A
  suspension is a stop, not a purge, and the evidence has to survive for whoever asks next.
- **It does not touch Stripe.** Refunds, payouts and disputes on money already taken are Stripe's to
  settle and a platform block must not strand a buyer's refund.
- **It does not notify the tenant.** No email exists for this yet, and inventing one at suspension time is
  how a holding message becomes a legal statement. They discover it at sign-in, which tells them the
  reason.

### Shipped dev 2026-10-16, and what the live run found

Verified against live dev data, end to end: suspend → the published artifact disappears from the pages
bucket; checkout for a real offer answers **403 `tenant_suspended`**; re-writing the page document (what a
tenant edit does) does **not** put it back, and the function's own log says
`Skipped publish for suspended tenant`; restore → the page is re-rendered and back in the bucket, and
checkout answers **303** to Stripe again.

**The bug only a live run could find.** The restore wrote each page document back *byte-identical*, and
DynamoDB emitted **no stream record at all** — so the restore reported "1 page" and the page stayed down.
A fake repository records a `put` either way, so every test passed. Fixed by bumping `updated_at` so the
write is a change, and the lesson is in the test's own docstring: **the restore is verified against S3,
never against its own return value.**

### Open

- **Reason codes shown to the tenant?** Today the sign-in refusal names the reason. An impersonation or
  fraud case may warrant less detail; revisit with the first real one.
- **Custom domains stay pointed at the platform** and will serve 404 once artifacts are gone. Removing the
  DNS/Cloudflare route on suspension is a separate, slower action and is not part of this.
- **No bulk or automated suspension.** One tenant, one admin, one reason, every time.

## 2. Candidates, unagreed

Collected so they are not lost. None of these is a commitment, and several may belong elsewhere.

- **Tenant list with Connect/plan/account status.** stripe-cart's platform admin did exactly this
  (`dist/dashboard/js/platform-admin.js`: `loadTenants`, `getConnectStatusBadge`, `getPlanBadge`,
  `openTenantEditModal`). Closest thing to a proven spec we have.
- **Editing a tenant's config / plan tier.** Same source. Needs a clear audit story before it exists —
  changing someone else's billing tier is not an ordinary edit.
- **Suspending a tenant**, as distinct from archiving one Site. No mechanism today.
- **Releasing a reserved username.** Deliberately impossible right now (plans/CREATOR_DOMAIN_SERVING.md §3):
  the registry never releases, which is what stops a retired handle being re-claimed and used to inherit
  someone's inbound links. If it is ever offered it belongs here, behind a quarantine, not in tenant UI.
- **The dev-only Delete Test Data action** (`handlers/admin_delete_test_data.py`) already exists and is
  gated `IsNonProd`. If an admin site appears, decide whether it moves there.

## 4. Swapping the Junior Bay PLATFORM Stripe account — RUNBOOK

Recorded 2026-09-23. **This is a runbook, not a feature.** It was deliberately NOT built as an admin
action: see "why no button" below.

### Why it will happen

The platform account is moving regardless of the current trouble — the author is changing the legal entity
from a corporation to an LLC, and a Stripe account cannot change entity. The administrative dissolution
and the unrecoverable bank account change the TIMING, not the decision. (Confirmed 2026-09-23: no money is
stranded in that account.)

### What is bound to the platform account, and what is not

| bound to the PLATFORM account | survives a swap |
|---|---|
| Connect authorisations — every tenant's `acct_…` | tenants' own Stripe accounts and logins |
| the Connect `client_id` (`ca_…`) | connected-account objects: Customers, Products, Prices |
| platform secret keys (`sk_test`/`sk_live`) | everything in our own DynamoDB tables |
| webhook endpoints + signing secrets | |
| platform-billing subscriptions (the tenant SaaS plan) | |

**Connected accounts do NOT transfer.** `acct_X` authorised to `ca_OLD` has no relationship with `ca_NEW`.
Every tenant must complete Connect OAuth again. No feature can avoid this; it is Stripe's model.

### Why it is cheap right now, and will not be

Measured 2026-09-23:

- **1** distinct connected account exists (the author's own), across both silos.
- **0** production tenants on a paid plan — both are `billing_status: trial`.
- 2 platform-billing subscriptions exist, both in **sandbox** only.

And a hard constraint: `get_platform_webhook_secret` resolves exactly **ONE** signing secret per
`(kind, mode)` (`stripe_platform_secrets.py:108`). There is no dual-secret window, so during the cutover
events signed by the other platform fail verification. With one tenant and no live traffic that window
costs nothing. Post-launch it is an outage, and closing it is real work — see
`plans/PLATFORM_ACCOUNT_CONFIG.md`.

### The runbook

Order matters. Repointing webhooks before the keys are in place loses events; swapping keys before the
endpoints exist means Stripe has nowhere to deliver.

0. **Record the baseline.** `./deploy/verify-platform-account.sh` — save the output. It names the account
   you are leaving (2026-09-23: `acct_1GdJkFEcxlWjis9i` «Junior Bay Corporation», both silos).
1. **Create the new Stripe account** under the new entity. Enable Connect.
2. **Collect the new identity**: `ca_…` test + live, `sk_test`, `sk_live`.
3. **Register webhook endpoints on the NEW account**, pointing at the SAME URLs
   (`/webhook/stripe`, `/webhook/stripe-preview`, `/webhook/platform-billing`). Capture each signing
   secret.
4. **Write keys + signing secrets into each silo's secret** — `stripe-cart/<silo>/platform/stripe`. This
   is the cutover instant; the verification gap opens here.
5. **Update the Connect client ids** — `StripeClientIdTest` / `StripeClientIdLive` — and redeploy each
   silo. **Do not skip this.** If the client id still names the old platform, tenants reconnect to the
   account you are leaving and everything LOOKS like it worked.
6. **Verify.** `./deploy/verify-platform-account.sh` must report the NEW account id and the NEW client ids
   in every silo. The script asks Stripe who the key belongs to rather than comparing bytes, which is the
   only check that can answer "which account".
7. **Re-authorise every tenant** through Connect. Today: one.
8. **Prove it end to end** — one test-mode purchase, confirm the order, the receipt and the webhook.
9. **Retire the old account** once payouts and reporting are settled.

### Why no button

Every step above is a one-time operation that can be completed by hand faster than an admin feature could
be built and reviewed — and step 7 would still be "now ask every merchant to reconnect", which is the only
expensive part. Building automation for it would be paying for a tool to do a job already finished.

**What IS worth building** is in `plans/PLATFORM_ACCOUNT_CONFIG.md`: making platform identity changeable
without a stack deploy, and closing the dual-secret gap. Those stay useful afterwards; a swap button does
not.

## 6. Plan/tier management — the Admin Site's other job (requested 2026-09-29)

The author's future tiers: **agency mode** (agencies operating the software for their clients), a **business**
tier (AI managing Google Business Profiles, regular blogs, trend checks), and **business intelligence** (AI
spotting trends and recommending offers). None priced yet; the requirement is that adding them later must not
mean a deploy.

**Mostly already true.** A tier is a `PLAN#` row in `PlatformPlansTable` — label, price, Stripe price id,
entitlements, AI allowance, sort order — and `plan_key` (stable) is already separate from `label` (display),
so renaming is a display edit. `docs/PLATFORM_PLANS.md` now carries the full "adding a new tier" audit,
including the three places a new tier still touches code. The one worth fixing before a fourth tier exists is
`PREMIUM_TIERS` in `domain/platform_signature.py`: a new paid tier would keep the free-tier email branding
until someone remembers that list.

So the Admin Site screen is a CRUD over plan rows plus the CONFIG row, and the interesting parts are the
guards rather than the form: a price change cannot edit a Stripe Price in place (create a new one and migrate),
entitlement changes apply on the tenant's next subscription webhook rather than immediately, and editing
another tenant's tier is the kind of action §3's audit question exists for.

## 5. Cost visibility — who is spending the platform's money (requested 2026-09-29)

**The author's ask:** record AWS spend in near-real time, show it in the Admin Site, and be able to spot the
big spenders per tenant.

Design lives in `plans/AI_AND_COMMERCE_ARCHITECTURE.md` §A.9. What matters for this document is what the screen
can honestly display, because two of the three cost tiers cannot say what people assume they say:

- **AI inference is exact and live.** We are in the call path, Bedrock returns token counts, and
  `ai_models.estimate_cost()` converts them with a confidence attached. It accumulates on the existing
  `ai_usage` row, so per-tenant spend needs no new storage. **This is the number the screen should lead with**,
  because it is also the only per-tenant cost that can run away.
- **Infrastructure cost per tenant is an allocation, not a measurement.** One Lambda serves every tenant and
  AWS has no tenant dimension. Anything shown here is a model and must be labelled "estimated".
- **The actual bill lags by up to a day and is account-level only.** Cost Explorer and CUR cannot be
  attributed per tenant. Their job is monthly reconciliation against tier 1 — show the drift, do not hide it.

**Two things the screen must show alongside any figure**, or it will be quietly wrong:

- `rates_verified_at` — the Bedrock rate table is hand-maintained, because AWS publishes no machine-readable
  rates for current-generation models. A cost figure with no idea how old its rates are is the
  `global_billing_config.json` trap wearing a different hat.
- Which tier a number came from. "Exact", "estimated" and "billed" must never render identically.

**Finding the big spenders:** `ai_usage` is PK `tenant_id` / SK `period`, so "all tenants for this period"
means a scan or a GSI on `period`. At current scale a scan is fine and nearly free — take the GSI when it
hurts, not before, since the stack is at **441 of 500 CloudFormation resources**.

**Blocked on the same thing as everything else here** (§3): a screen listing every tenant's spend is precisely
what must not be reachable by guessing a `tenant_id`.

## 3. Open questions, before any of it is built

> ⚠️ **Nothing here is a security boundary until the authorizer ships.** Capability and role checks in this
> repo rest on a `tenant_id` the REQUEST supplies, so an admin screen gated that way is gated against
> honesty, not against an attacker. `api_auth.resolved_tenant()` reports whether an identity was actually
> proven — it returns `authoritative: False` for every request today — and `note_capability_decision` counts
> the grants made without one. Build the screens; do not describe them as authorization until that count is
> the whole story.

- **Who is an admin, and how is that proven?** stripe-cart had `checkPlatformAdminStatus`. This repo has no
  admin role at all. This is the prerequisite for everything above — and it lands squarely on the
  ⭐⭐ authorization gap already in plans/TODO.md (no authorizer; `tenant_id` comes from the request). An
  admin surface built on top of that gap would be the worst possible place to discover it.
- **Separate deployment or a route in the existing dashboard?** A separate origin is safer and costs a build;
  a route is cheaper and puts platform-wide powers behind the same bundle every tenant loads.
- **Is any of it audited?** Suspending a page and editing a tenant's plan both want a "who did this, when"
  trail that nothing in this codebase currently writes.
