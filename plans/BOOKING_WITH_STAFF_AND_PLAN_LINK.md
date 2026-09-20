# Booking with staff, and the plan link that makes it reachable

Two pieces, separable. (A) is a QA walk that can run today. (B) is a build that (A) does not depend on,
but which nobody — tenant or customer — can work around until it exists.

## What is actually true right now

Checked against dev and prod, 2026-09-20:

| | dev | prod |
|---|---|---|
| services | 2 | 0 |
| fulfillers | 0 | 0 |
| appointments ever created | 0 | 0 |
| tenant availability | 0 | 0 |
| Google Calendar connections | 0 | 0 |

So **no booking has ever been made in stripe-link, on either environment.** The Google Calendar mechanism
exists in code and its OAuth secrets are wired (`jb/google-oauth/*`), but it has never run here. Whatever
booking was seen working before was stripe-cart, the legacy repo.

Fulfillers and appointments are document types inside the SERVICES table (`fulfillers_repository` and
`appointments_repository` both read `SERVICES_TABLE`), which is why there is no separate table to look at.

Test coverage is real but split: `test_delegation.py` (31 fulfiller references), `test_scheduling.py` and
`test_booking.py` cover staff routing; `test_booking_credits.py` covers the credit ledger — and mentions a
fulfiller **zero times**. The two have never been exercised together, and nothing anywhere books against a
real calendar.

---

# Part A — the first real booking with staff

A QA walk, not a build. Nothing here needs new code.

## A1. Prerequisites that do not exist yet

1. **A fulfiller.** Services → the service → Fulfillers. Give them a name and email.
2. **Availability.** Tenant availability, or fulfiller hours to exercise the override in
   `test_fulfiller_hours_override_tenant`.
3. **A calendar connection — optional, and the interesting question.** With none connected, find out
   whether `reserve_route` still produces an appointment (expected: yes, with no calendar event) or fails.
   **Do this before connecting anything**: "does booking survive a tenant who never connected Google" is a
   real tenant state and is cheapest to answer now, by accident, than later by a support ticket.

## A2. The walk

Buy the **one-time** massage ($274.76 — NOT the plan; see Part B for why the plan cannot be booked yet),
then book it from the page.

## A3. What to watch, and why each one

- **Which fulfiller is assigned.** `candidate_fulfiller_ids` + the service default. With one fulfiller this
  proves only the happy path; the precedence rules are where the bugs live.
- **The slot lock.** `slot_locks_repo.claim()` runs before anything else commits. A double-book attempt in
  a second tab is the cheap way to see it work.
- **Double-booking across fulfillers.** The bug `plans/MULTI_CALENDAR_ARCHITECTURE.md` was written to fix:
  one fulfiller's busy time blocking everyone. Needs two fulfillers to see.
- **The calendar event**, if connected: right calendar, right duration (`duration_minutes` is service-level
  — the 120-minute service must produce a 120-minute event), right invitee.
- **Cancel** → the slot frees.

## A4. What this proves, and what it does not

Proves: the booking primitive, staff routing, and the calendar write, end to end, for the first time.

Does NOT touch: booking credits. A one-time purchase spends no credit, and `_spend_plan_credit` returns
`{}` the moment no `entitlement_id` is claimed.

---

# Part B — the customer's plan link

## B1. The gap

A recurring service grants credits and **no appointment** — recurring lines are deliberately excluded from
the appointment fan-out (`test_the_recurring_line_is_excluded_from_the_appointment_fan_out`). The customer
books later, spending a credit, by sending `entitlement_id` with the reservation
([booking.py:199](../src/handlers/booking.py#L199)).

Nothing ever gives them that id. `grep entitlement src/stripe_link/runtime/html.py` returns nothing: the
booking widget cannot send one, so a plan holder cannot book at all. They paid, they hold credits, and the
page offers them no way to use them.

This is not only a convenience gap. It is why the plan → booking → staff path cannot be tested end to end,
by anyone, including us.

## B2. Precedent to copy, not invent

`handlers/tip_manage.py` — `GET /tips/manage?t=<token>` — is the same shape already shipped: an opaque
token minted in the webhook, emailed, no buyer account, no password. `mint_tip_manage_link` is called from
`stripe_webhook` at exactly the point where a plan link would be minted. Appointments use the same idea with
`customer_manage_token` + `_authorized_appointment` (compare token, 403 on mismatch).

Reuse both. The entitlement already carries `customer`, so the email the spend gate checks is on hand.

## B3. Shape

1. **Mint a token** when `_grant_booking_credits()` writes the entitlement. Store it on the entitlement (or
   a token doc, as tips do — decide once, see B5).
2. **`GET /plans/manage?t=<token>`** → resolve, authorise by comparing the token exactly as
   `_authorized_appointment` does, and render: service name, credits remaining, when the cycle resets, and a
   **Book a visit** button.
3. **The booking widget accepts an `entitlement_id`** (from the link's query string) and forwards it to
   `/services/appointments/reserve`. This is the one renderer change; everything else is new surface.
4. **Email the link** on grant, and again on refill. `receipt_mailer` is already threaded through the
   webhook for exactly this kind of send.

The existing spend gate stays as the real authority: matching email, matching service, non-negative
balance. The link is discovery, not authorisation — someone who forwards the email still cannot book
against a different service or from a different address.

## B4. Sequencing

B3.1 + B3.2 first (a page that shows a plan is useful even before it can book). B3.3 makes it bookable.
B3.4 makes it discoverable without us handing over a URL.

## B5. Decisions needed before building

1. **Token storage** — on the entitlement, or a separate token doc like tips? Tips chose separate; the
   entitlement is already addressed by a derived id, so a token on it is simpler but makes rotation harder.
2. **Does the link also cancel the plan?** Tips do. A plan cancel is a Stripe subscription cancel, and
   there is already an in-app Cancel/Resume for tenants — not for buyers.
3. **Refill email every cycle, or only when the balance changed?** A daily-interval plan (which is what is
   under test right now) would otherwise email every single day.
4. **What the page shows when credits are exhausted** — "come back on the 3rd", or an upsell to a one-time
   booking at full price?

## B6. Not in scope

- §4a standing appointments (the six decisions in `plans/RECURRING_SERVICES.md` §5).
- Buyer accounts. The link-based model is deliberate and predates this.
