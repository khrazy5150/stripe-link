# Admin Site

Status: **collection point, not a design.** Nothing here is agreed or scheduled. It exists so that admin-shaped
requirements stop being remembered and start being written down — the author's words, 2026-09-20: *"I probably
won't remember to do this on my own, so let's record it in the plan."*

The first entry is the one that created the need, and it is the only one with a deadline attached to it.

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

## 3. Open questions, before any of it is built

- **Who is an admin, and how is that proven?** stripe-cart had `checkPlatformAdminStatus`. This repo has no
  admin role at all. This is the prerequisite for everything above — and it lands squarely on the
  ⭐⭐ authorization gap already in plans/TODO.md (no authorizer; `tenant_id` comes from the request). An
  admin surface built on top of that gap would be the worst possible place to discover it.
- **Separate deployment or a route in the existing dashboard?** A separate origin is safer and costs a build;
  a route is cheaper and puts platform-wide powers behind the same bundle every tenant loads.
- **Is any of it audited?** Suspending a page and editing a tenant's plan both want a "who did this, when"
  trail that nothing in this codebase currently writes.
