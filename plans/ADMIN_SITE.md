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

## 3. Open questions, before any of it is built

- **Who is an admin, and how is that proven?** stripe-cart had `checkPlatformAdminStatus`. This repo has no
  admin role at all. This is the prerequisite for everything above — and it lands squarely on the
  ⭐⭐ authorization gap already in plans/TODO.md (no authorizer; `tenant_id` comes from the request). An
  admin surface built on top of that gap would be the worst possible place to discover it.
- **Separate deployment or a route in the existing dashboard?** A separate origin is safer and costs a build;
  a route is cheaper and puts platform-wide powers behind the same bundle every tenant loads.
- **Is any of it audited?** Suspending a page and editing a tenant's plan both want a "who did this, when"
  trail that nothing in this codebase currently writes.
