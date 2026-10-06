# Shipping Setup Wizard

**Status:** planned, LOW priority (author, 2026-10-06: *"we could mitigate that problem by creating a
wizard that will walk them through setting it up properly. Maybe write that up as a plan with low
priority."*)

**Prerequisite, already shipped:** a buyer never sees a shipping section the tenant has not finished
setting up. A setup failure (`needs: "setup"`) hides the element and the order posts free; the builder is
told instead. This plan is the mitigation for the thing that remains true after that: **the tenant can
still ship for nothing, and the only thing standing between them and that is a warning they have to
notice.**

---

## 1. The problem this solves

Shipping is not one setting. It is four, held in three different screens, and **every one of them is
silently load-bearing**:

| what | where | what happens when it is missing |
|---|---|---|
| Ship-from address | Shipping | `rate_error: no_ship_from` — no rates, element hidden, $0 collected |
| Carrier connection | Shipping → provider | `rate_error: no_provider` — same |
| At least one zone | Shipping → zones | `needs: zones` — element hidden, $0 collected |
| Item size + weight per product | each Product | nothing packable → ships free (P0a) |
| The shipping element on the page | Landing page → Page Sections | no postcode is ever collected → $0 collected |

A tenant can complete any three of these and be exactly as broken as a tenant who completed none. The
failure is always the same, it is always silent, and it always looks like success: the page publishes, the
buyer checks out, the order is paid. Only the label cost, days later, says otherwise.

Measured cost of one such page before the element became default-on: a Large box costing **$7.83**
against **$0.00** collected.

## 2. Why a wizard rather than more warnings

The warnings already exist and are not enough, for a reason this repo has met before (P0d, item
dimensions): *"fourteen empty forms is the obstacle, not one form."* A warning tells a tenant they are
broken and then leaves them to find four screens. The win is not better wording, it is **collapsing the
four screens into one ordered pass** where each step knows whether it is done.

Precedent to follow rather than invent: `measure_products` already writes item dimensions for many
products from the screen that reported them missing.

## 3. Shape

A single **"Set up shipping"** flow, reachable from the Shipping screen and from any of the warnings that
currently dead-end. Ordered by dependency, each step showing done/not-done from live state:

1. **Where do you ship from?** — one address. Pre-fill from the tenant's business profile (Stripe Connect
   already seeds NAP via `connect_sync`), so for most tenants this is a confirmation, not typing.
2. **Connect a carrier** — the existing provider connect, with the "why" stated: no carrier, no rates, no
   postage collected.
3. **Where do you ship to?** — at least one zone. Offer the two answers that cover most sellers (*my own
   country* / *everywhere*) as one click each, with the full zone editor behind "something else". The
   catch-all/domestic-only work is already built.
4. **Measure what you sell** — the `measure_products` grid, pre-filtered to unmeasured physical products,
   with the consequence named per row ("this ships free until it has a size").
5. **Check a real rate** — run the existing rate preview to a sample destination and show the price. This
   is the step that converts "I filled in forms" into "I saw it work", and it costs nothing new: the
   estimator, the box-choice explainer and the bump-postage calculator all already exist.

Finish with what it now does: *"A buyer in Chicago will be charged $6.69 to post this."*

## 4. Rules

- **Nothing is mandatory.** A tenant who wants to post things themselves and never charge for it is making
  a legitimate choice, and the flow must let them say so and stop asking. Shipping has a free mode.
- **Resumable and idempotent.** Step state is derived from the live config, never stored — a tenant who
  sets a zone in the Shipping screen sees that step already done. A stored "wizard progress" field would
  be a second copy of a fact the config already holds, and this repo has paid for that twice
  (`structured_data`, the declared-package default).
- **Entry from the failure, not only from a menu.** Each existing warning becomes a link into the step
  that fixes it. The builder's shipping warning already knows precisely which piece is missing
  (`rate_error` carries `no_provider` / `no_ship_from` / `key_unreadable`).
- **Never block publishing.** Warnings, not gates, as everywhere else
  (plans/LANDING_PAGE_GOAL_COMPOSITION.md).

## 5. Deliberately out of scope

- Onboarding generally. This is the shipping path only.
- Carrier account provisioning. Connecting an existing account is in; opening one is the carrier's job.
- Anything that writes a zone or a rate on the tenant's behalf without them seeing the number.

## 6. Why low priority

The money leak it mitigates is now closed at the point that mattered: the element is default-on for
physical offers, a half-configured tenant shows the buyer nothing rather than an error, and the builder
says what is missing and what it costs. The wizard makes a tenant **faster and less likely to give up** —
it no longer stands between them and correctly charged postage.

Worth revisiting when there are enough real tenants to see where they actually stall. Building it now
would be guessing at that.
