# Money across silos — Stripe as the one shared book

**Status: NOT BUILT. Designed 2026-10-10** from the author's observation, after discovering that a live
sale taken through the sandbox silo is invisible in production:

> With this current architecture, a STAGING environment as I had envisioned it is impossible. What I
> think should have happened is allow the money to read from Stripe instead of reading it from our
> tables. This way the artifacts (offers, landing pages, booking, etc.) are stuck in their own silo, but
> the MONEY floats across silos per tenant.

That instinct is right, and this plan is what acting on it looks like. It is one design with four parts,
because the parts share a single premise: **Stripe is the only store both silos genuinely share.**

Everything else — offers, pages, products, bookings, carts — is per-silo by deliberate design
(`plans/SILO_MODEL.md`, and the 2026-08-02 decision in `plans/STRIPE_MODE_DECOUPLING.md`: *Axis 1 only,
no cross-silo data sharing*). The money is the one thing a tenant experiences as singular, and today it
is the one thing that gets cut in half by the silo boundary.

---

## Part 1 — Staging is a flag, not a deployment

### The requirement, separated from the mechanism

The author's goal was concrete: *launch without the AI builder, then let tenants try the AI builder on
their real data before it reaches everyone.* That decomposes into two claims that look like one:

| the goal | verdict |
|---|---|
| a tenant uses a feature that is not in production yet, **on their live data, losing nothing** | **achievable today; the machinery is already built** |
| ...in a **separate environment** | **this is what fights the architecture** |

A staging silo would start with empty tables. A tenant who built three pages and took six orders in
staging would find none of it in production the day the feature graduated — which is the *exact* failure
the author just hit with the live sandbox sale, reproduced on purpose and shipped as a feature. There is
no migration that fixes it, because the silo boundary is the thing that makes silos worth having.

### What already exists

`domain/entitlements.py` holds a per-tenant capability set, and **`ai_builder` is already a declared
capability**, with a comment in the source calling it *"Gate 1 of three"*:

```python
CAPABILITIES = {
    "landing_pages": ..., "booking": ..., "sites": ..., "collections": ...,
    "ab_testing": ..., "reviews": ..., "lead_capture": ..., "invoicing": ...,
    "custom_domains": ..., "ai_builder": ..., "bnpl": ...,
}
FREE_TIER_CAPABILITIES = frozenset({"landing_pages", "sites", "collections"})
```

`tenant_entitlement_set(tenant)` resolves what a tenant may do, already handling comped (`exempt`)
tenants and live trials. So the flow for the AI-builder example is: **ship the code to production dark,
turn the capability on for the beta tenants, leave it off for everyone else.** One silo, one dataset,
real live data, nothing stranded at graduation — the flag just goes default-on.

### The one concrete blocker

`domain/platform_subscription_sync.py:114` does a **wholesale overwrite**:

```python
updates["entitlements"] = plan_entitlements(plan)   # and line 100: updates["entitlements"] = []
```

A beta grant stored in that field is wiped by the next Stripe subscription webhook — silently, at an
unpredictable time, for a tenant mid-task. **A beta grant needs its own field** the plan sync cannot
reach:

```
tenant.beta = ["ai_builder"]      # operator-set, never written by billing
tenant_entitlement_set(...)  ->  plan ∪ free-tier ∪ beta
```

Union-only, so a tenant with no `beta` field behaves exactly as today. No migration.

### The honest cost

Production carries unfinished code behind flags. The failure mode is **a gate missed at one call site** —
the same class of defect as the Stripe-mode checks, which were got wrong twice during the mode retrofit
(once by a line-scoped grep that could not see a mode in a POST body).

The mitigation is the shape that already works here: `tests/test_table_grants.py` walks handlers
transitively and fails the build when a grant is missing. The same walk can enumerate the entry points
that touch a flagged capability and fail when one is ungated. **Write that guard before the first flag,
not after.**

### What is NOT being given up

Dev *is* staging — for the operator. What dev cannot do is carry live data, and the gap the author has
actually been feeling is not "no staging" but *"I cannot gain confidence without spending live money"* —
a different problem, addressed in `plans/CONFIDENCE_WITHOUT_LIVE_MONEY.md` and now largely built
(mode-parity tests, test-mode rehearsal, the reconciliation sweep, real-payload fixtures).

---

## Part 2 — Stripe knows four of the six components

The ledger's amounts are six additive, signed components (`domain/ledger.py:15`):

```python
AMOUNT_COMPONENTS = ("gross", "stripe_fee", "platform_fee", "tax", "cogs", "shipping_cost")
net    = gross + stripe_fee + platform_fee
profit = net + cogs + shipping_cost - tax        # cogs and shipping_cost are stored NEGATIVE
```

Of those six, **Stripe already knows four**: `gross` from the charge, `stripe_fee` and `platform_fee`
from the balance transaction, `tax` from the session's total details. Only `cogs` and `shipping_cost`
are ours and ours alone — and `plans/TRANSACTION_LEDGER_STRIPE_LINK.md` has recorded since 2026-07-23
that **neither is ever populated**, so `profit` is incomplete today regardless of which silo you ask.

This is why "read the money from Stripe" is a real design and not a slogan: a Stripe-derived view of a
tenant's money is **4/6 complete immediately**, across every silo, with no table to reconcile. Part 3 is
how it becomes 6/6.

### What is already stamped, measured not assumed

Measured against live Connect events on 2026-10-10:

| event | metadata keys | `silo` |
|---|---|---|
| `checkout.session.completed` | 14 | `sandbox` |
| `charge.refunded` | 1 | `sandbox` |
| `payment_intent.succeeded` | **0** | **absent** |

The session carries `offer_id, page_id, product_id, product_name, product_type, price_id, funnel_id,
order_bump_ids, coupon_code, tenant_id, silo, tenant_plan`. The charge carries exactly one key, because
`handlers/checkout.py:1525` sets only:

```python
payload.setdefault("payment_intent_data[metadata][silo]", silo)
```

**Two consequences worth writing down before anyone builds on this:**

1. `payment_intent_data` is **payment-mode only** — the comment two lines above says so. **Subscription
   renewals' charges carry no stamp at all.**
2. A charge stamped before that line shipped carries nothing either, which is what the 0-key
   `payment_intent.succeeded` above is.

So the stamp is *usually* on the charge and must never be *assumed* to be.

---

## Part 3 — COGS and shipping cost in Stripe metadata

Viable, and it is what turns the 4/6 above into 6/6. The two behave differently and the difference
drives the design:

**COGS is known at checkout.** It is a product field. It can be stamped in the same place `silo` already
is, and rides along at no cost:

```python
payload["payment_intent_data[metadata][cogs]"] = str(total_cogs_cents)   # negative, per the convention
```

**Shipping cost is not known at checkout.** It is known when the carrier label is bought, which is
*after* the charge. `summarize()` already says so in its own comment — *"`shipping_cost` has no source
until a carrier label is bought"*. So it needs a **metadata update on the PaymentIntent at label
purchase**: one idempotent API call, on a path that is already talking to a carrier and already writing a
shipment document.

### Constraints, all real, none fatal

- **Stripe metadata limits: 50 keys, 40 chars per key, 500 chars per value.** The session already uses
  ~14. **Per-line COGS across a multi-line cart must go on each line item's metadata, not the
  session's** — a listicle cart with a dozen lines would otherwise approach the key ceiling, and the
  failure would be a rejected checkout on the tenant's biggest order.
- **Metadata is not queryable.** You cannot ask Stripe to sum October's COGS. You list charges and sum
  locally. Fine at this volume; worth knowing before it is a reporting feature.
- **A later metadata write is not retroactive to the charge's balance transaction.** It is a side-car
  value we wrote, with Stripe's durability and none of Stripe's authority. That is the correct status for
  it — it is *our* number.

### The property that makes this correct rather than merely possible

Metadata is an **immutable snapshot at the moment of sale**. A tenant who corrects a product's cost next
month does not retroactively rewrite last month's margin. That is exactly the behaviour a ledger entry
has, and exactly the behaviour a P&L needs. Storing COGS only in the product record would give the
opposite and wrong behaviour.

### What this does NOT replace

`plans/TRANSACTION_LEDGER_STRIPE_LINK.md` stays canonical for the owning silo. This is not "delete the
ledger and read Stripe" — it is "**Stripe carries enough that any silo can reconstruct a tenant's money,
and the owning silo's ledger remains the fast, queryable, append-only copy.**" Two stores with one
source and a known direction of truth, rather than two stores that can disagree.

---

## Part 4 — The cross-silo lost sale — **BUILT 2026-10-10**

### It was not latent. It was firing, in both silos, every five minutes

The first draft of this plan predicted a false positive *"the day production takes its first order."*
Reading what the deployed sweep was actually logging, within the hour, found it already happening:

```
[ERROR] UNRECORDED STRIPE MONEY tenant=586173f0... mode=test
        {'count': 1, 'amount': 19792, 'charges': ['ch_3UOtmw21lLbLd4Y50K7lDokj']}
```

in **`jb-stripe-webhook-prod` AND `jb-stripe-webhook-dev`**, every five minutes, over a **$197.92**
charge that `jb-orders-dev` held as `order_in_1UOsq521lLbLd4Y50sXIDrlB`, `status: paid`,
`amount_total: 19792`. **Nothing was lost.** Three independent defects stacked, and only one of them was
the one this plan predicted.

### Defect 1 — a subscription charge can never be matched by PaymentIntent

The stored order has **no `payment_intent_id` field at all**. `order_record_from_invoice` keys on the
invoice (`order_{invoice_id}`), and the sweep's only lookup was `find_by_payment_intent`. So **every
subscription renewal that has ever been taken, and every one that ever will be, read as unrecorded
money.** Subscriptions shipped 2026-09-15; this was waiting from that day.

Fixed by matching the invoice *first* — an invoice charge also has a PaymentIntent, one we never store,
so asking the index about it returns nothing and looks exactly like a lost sale.

### Defect 2 — both silos list the same connected account

The two `stripe-keys` tables are per-environment (`jb-stripe-keys-v2-dev` / `-prod`), so each sweep
enumerates only its own tenants. **But they hold credentials for the same `acct_`,** because the tenant
connected Stripe in both silos. So production enumerated its copy of the tenant, listed the sandbox
silo's charges, and asked its own orders table about them.

Fixed by resolving ownership **with the same rule the webhook used when it chose where to write** —
`silo_routing.event_belongs_here`'s own logic: the stamp if there is one, else `LEGACY_SILO_FOR_MODE`.
Mirroring it is the whole point: *if the sweep and the writer disagree about ownership, the sweep reports
as missing precisely the charges the writer correctly declined.*

**The first draft of this plan got that rule wrong.** It said the fallback was *"unstamped means
sandbox, never production"* — that is the **read-side** default in `resolve_event_silo`. The **write
side**, which is what decides where an order actually lands, uses the legacy correspondence: unstamped
`test` → sandbox, unstamped **`live` → production**. Building the sweep on the read-side rule would have
made it disagree with the writer on every unstamped live charge.

### Defect 3 — the alarm was never wired

`handler` defaults `notifications_repo` to `None` for injection. `_notify_overdue` resolves it lazily
from `NOTIFICATIONS_TABLE`; **`_report_orphan_charges` did not.** So `_notify_orphans` took its
`if notifications_repo is None: return` on every scheduled run since it shipped, and both notification
tables held **zero** `orphan_charge_*` rows while the log had been screaming every five minutes.

**The detection built to end the silence was itself silent.** Same shape as `refundError` set and never
rendered, and as the fake that implemented a method the real repository lacked: the end of the path was
never exercised.

Note the ordering luck — had this been fixed first, turning the notifier on would have sent a *critical*
tenant-visible alert about correctly-recorded money every five minutes, in both silos.

### Where the stamp actually lives, verified

A subscription charge carries **no metadata of its own** — `payment_intent_data[metadata][silo]`
(`handlers/checkout.py:1525`) is **payment-mode only**, so the stamp never reaches a renewal's charge.
It does reach the subscription, and the invoice carries the subscription's metadata:

```
charge.metadata                                        {}
charge.invoice.parent.subscription_details.metadata    {... "silo": "sandbox" ...}
```

Reachable for free: **`expand[]=data.invoice` on the charges list** — the same one call, no extra round
trips.

### What shipped

- `silo_routing.stamp_from_object(obj)` extracted; `stamp_from_event` delegates to it. One
  implementation of *where is the stamp?*, because two readers would eventually disagree and the
  disagreement would be invisible until a charge went unclaimed.
- `orphan_charges`: `invoice_id_of`, `order_id_for_invoice`, `owning_silo`, `is_ours`; `orphans()` takes
  `order_for_id`, `this_silo`, `mode`.
- The sweep expands the invoice, passes its `SILO` (already deployed: `sandbox` / `production`), builds
  the notifications repository, and reports `notified` in the tally so *found money, told nobody* cannot
  hide again.
- The fact and the notification now carry `silo`, `orphan_reason` and `invoice_id`, so a wrong alarm can
  be **argued with** rather than merely believed.

**The filter fails open in every direction**: a deployment that cannot name its silo reports everything,
an unrecognised stamp is not trusted, and a charge nothing can attribute is still reported. A false alarm
costs a look at the Stripe dashboard; a suppressed one costs a sale nobody records. That asymmetry is the
only reason the filter is allowed to exist.

### Verified against live data, not against the fakes

Run on 2026-10-10 over the last 7 days of real charges on the connected account, with the real
repositories against the real tables:

```
production  (jb-orders-prod)  ->   0 orphans of 20 charges     silo filter
sandbox     (jb-orders-dev)   ->  14 orphans of 20 charges     all outside the 6h sweep window
without either fix            ->  20 orphans of 20 charges, $3,500.43 "unrecorded"
```

**Every charge on the account was being reported as lost money.** The six the sandbox silo still holds —
the subscription charges of 10-08 through 10-10 — are now all matched by invoice, which is the whole of
what the sweep's 6-hour window ever sees. And it was not one charge: the account takes **two subscription
charges every day** ($197.92 at 06:29 and $32.91 at 08:39), so the alarm was live for roughly half of
every day, in both silos, and had been since subscriptions shipped.

The 14 remaining are real absences with a mundane cause — they predate a **Delete test data** run, which
is dev-only by design. They are far outside the sweep's window, so the deployed sweep never sees them.

**A known interaction, recorded rather than fixed:** immediately after a tenant uses *Delete test data*,
any surviving Stripe **test** charge inside the 6-hour window becomes a correct-but-useless orphan
report — the money did move and our tables genuinely no longer hold it. Test mode only, dev only, and it
ages out within six hours. Suppressing it would mean teaching the sweep about deletions, which is more
machinery than the noise justifies.

### The residual gap, stated

A **sandbox tenant's live subscription charge** is unstamped on the charge, and if its invoice is ever
unreachable the legacy rule attributes it to production. The expansion closes this in practice, and the
sweep now agrees with the writer in every case the writer can decide — which is the invariant that
matters. Routing cross-silo visibility into an operator-only report, rather than a tenant's bell, remains
future work: a notification that is usually somebody else's problem gets ignored, and then it is ignored
on the day it is real.

## What this plan deliberately does not do

- **No staging silo.** Part 1 replaces it. Reasons above, and the author's own discovery is the evidence.
- **No cross-silo reads of our own tables.** The 2026-08-02 decision stands: Axis 1 only. Everything here
  goes through Stripe, which is shared by nature, or through the tenant profile, which is not per-silo.
- **No demotion of the ledger.** Part 3 completes it; it does not replace it.
- **No new API route.** The stack is at 993,953 of 1,000,000 transform bytes
  (`plans/TRANSFORM_BUDGET.md`); roughly one route fits. Nothing here needs one — the sweep is an
  existing schedule, the metadata is an existing call, the flag is an existing profile field.

## Phasing

**P0 — the silo-aware sweep. DONE 2026-10-10.** Not the small change it looked like: three defects, two
of them unpredicted, one of which meant the alarm had never fired at all. It was not waiting for
production's first order — it was running.

**P1 — the beta-grant field. BUILT 2026-10-11, dev + prod.** `tenant.beta`, unioned in
`tenant_entitlement_set`, plus `BETA_CAPABILITIES` / `GENERAL_CAPABILITIES`.

**Two things this plan got wrong, both found building it.**

`tenant_entitlement_set` has **four** return paths, not one — comped, suspended, trial (live and
expired), and everyone else. A grant unioned into the obvious one would simply be absent for most
tenants.

And two of those paths hand out `set(CAPABILITIES)`, the whole catalogue. So **merely declaring an
unreleased capability would grant it to every comped account and every live trial on day one** — the one
thing a beta must not do. `GENERAL_CAPABILITIES` (the catalogue minus what is beta-only) is now what
"everything" means, and `BETA_CAPABILITIES` is empty today because everything declared has shipped.
Adding a name to it is the act of making a feature beta-only.

Deliberate: a **suspended** tenant gets no beta. The grant says which features exist, not whether the
account is in good standing, and letting it through would make an unreleased feature the one thing a
suspended tenant could still use.

A typo is refused at write time rather than ignored, and the field is declared in
`TenantProfile.schema.json` — which sets `additionalProperties: false`, so a field the Python validator
accepts and the schema does not would pass one gate and fail the other.

Union-only, so every existing tenant behaves exactly as before. No migration.

**P2 — COGS at checkout. BUILT 2026-10-11.** Completes five of the six components.

**The plan was wrong about the starting point.** It said *"COGS is known at checkout. It is a product
field."* It was not a product field — Smart Pricing's cost model (`plans/SMART_PRICING.md` §2,
`plans/INVENTORY_COST_BASIS.md`) is design-only, and neither `Product` nor `Offer` had anywhere to put a
number. So P2 included a schema change, which is the one category `CLAUDE.md` says to ask about rather
than guess. Decided with the author: **`Product.unit_cost`**, integer cents, optional — one fact about the
thing, which does not change because it is sold as an upsell, and the field a future `InventoryLot` would
derive into.

**And it found a live misstatement.** `Reports.vue` has a **Profit** row, and with `cogs` structurally
zero it has been showing revenue-net-of-fees under that word since Reports shipped — the same shape as the
Dashboard's "Net Revenue" that was really gross (fixed 2026-10-09).

### Absent is not zero

The invariant the whole slice is built on. A tenant who has not recorded a cost is not a tenant with no
costs, and treating unknown as zero fails in the direction a seller wants to believe:

- the form holds dollars as a **string**, so `""` and `"0"` stay distinct all the way down;
- the payload **omits** the key rather than sending `0`;
- every layer carries the **count of lines it could not price**;
- `summarize` answers `profit_known` / `uncosted_sales`, and Reports renders a **dash** plus *"2 sales
  have no cost recorded"* rather than a figure short by an unknown amount.

An order written before this shipped reports `known: false`, correctly. Defaulting the other way would
have declared the entire back catalogue fully costed and handed every tenant a profit equal to their
revenue — the bug, re-entering as a migration default.

### What shipped

| piece | where |
|---|---|
| `unit_cost` field + validation | `schemas/Product.schema.json`, `domain/documents.py` |
| pure cost domain | `domain/cogs.py` (new) |
| stamped into metadata | `handlers/checkout.py` (beside the `silo` and bump-postage stamps) |
| frozen on the order | `handlers/stripe_webhook.py` → `order.costs` |
| into the ledger entry | `domain/ledger.py` `_cogs_of` / `_cogs_known` |
| profit withheld when unknowable | `domain/ledger.py` `summarize`, `Reports.vue` |
| the tenant can enter it | `ProductUnitCostField.vue`, wizard **and** edit form |

**Two judgement calls worth knowing.** A **service** line counts as unpriceable rather than free — labour
cost has nowhere to live until `plans/SERVICES_IN_OFFERS.md`, and calling it zero would report a service
business's entire revenue as profit. And **bump costs ride the same wire format as `order_bump_shipping`,
multiplied by quantity**: a bump is ticked after the session exists, so checkout stamps what each *would*
cost and the webhook adds up the ones taken. Summing the unit cost once understates COGS, which is the
precise failure this component exists to stop.

Why metadata rather than a lookup at report time: it is an **immutable snapshot**. A tenant who corrects a
cost next month must not retroactively rewrite last month's margin, and a product later deleted must not
take its own history with it.

**P3 — shipping cost. BOTH HALVES BUILT 2026-10-11.** The ledger half first, then the metadata half
once the deferral's own exit condition was met — see *"Why the metadata half was deferred"* below and
*"What the deferral was actually waiting for"* after it.

**The plan did not know this was already mostly built.** `ledger.shipping_cost_entry` exists and
`handlers/shipping.py:1397` has appended it on every outbound label purchase since labels shipped. So the
sixth component already had a supplier — for outbound.

### What was actually missing: returns

`buy_return_label` (`shipping.py:1421`) bought labels with the same `mark_purchased`, the same `cost`
block and the same carrier charge as the outbound path, and **appended no ledger entry at all.** A tenant
who accepts returns had their postage understated and their profit overstated by exactly their
return-label spend. Harmless while `profit` was structurally wrong; wrong the moment P2 made profit
readable.

**The modelling split this forced, which is the interesting part.** A return label is recorded as
`cost_adjustment` against the `shipping_cost` **component**:

- the *component* says what KIND of money it is — a dollar to a carrier is a dollar, so `profit` counts
  it either way;
- the *entry type* says WHY — and `shipping_margin` answers one narrow question, *"did what I charge for
  postage cover what posting it cost?"*. A return has no postage revenue beside it, so counting it there
  would show a tenant's outbound pricing losing money because a buyer sent something back.

`summarize` now reports `shipping_revenue_cost` (outbound only) and `return_shipping_cost` separately,
and Reports shows them as two rows — the return row hidden until there is one, because a permanent zero
teaches a tenant to stop reading the statement. Its own `entry_id` prefix too: under the outbound prefix
a return and an outbound label for the same order would collide, and the second write would replace the
first rather than add to it.

### Why the metadata half was deferred, measured rather than argued

Writing shipping cost into Stripe metadata serves exactly one consumer: **P4**, which this plan already
flags as possibly never worth building. The cost is not nominal:

- `handlers/shipping.py` has **no Stripe dependency at all** today — no PaymentIntent, no credentials, no
  `stripe_request`. It talks to carriers and our own tables. The change hands a shipping handler Stripe
  credentials and a network call on the label path.
- **Measured against the transform ceiling:** the webhook's role, which carries the StripeKeys read plus
  `secretsmanager:GetSecretValue` plus KMS, is 7,625 bytes against the shipping role's 6,474 — about
  **1,151 bytes**, from **6,047 bytes** of total remaining headroom (`plans/TRANSFORM_BUDGET.md`). That is
  **a fifth of everything left**, and the budget plan's own words are *"roughly one more route fits. Not
  two."*

**So P3's stated goal was met and its mechanism was not built.** The goal was *"profit becomes a real
number"*, and it now is: outbound labels (already), return labels (today), COGS (P2). Spending a fifth of
the remaining ceiling to make a deferred report possible is the wrong trade while that report is
hypothetical. Pick it up with P4, or after the env-var work in `plans/TRANSFORM_BUDGET.md` reclaims the
~267KB that makes the question uninteresting.

### What the deferral was actually waiting for — and it arrived

The env-var work landed the same day (`plans/TRANSFORM_BUDGET.md`), taking headroom from **6,047 bytes to
~129,000**. That was the condition this plan named, so the metadata half was built. **Measured cost: 871
bytes**, against the 1,151 estimated — *0.9% of headroom* rather than a fifth of it.

```
transformed   871,107 bytes     headroom   128,893     87.1% used
```

**The byte cost was never the only objection, and the other one deserves answering rather than
forgetting.** Writing our own numbers into Stripe and reading them back is a *backup, not a
verification*: Stripe has no independent view of what a carrier charged us, so the agreement proves
nothing about the number. But that was never this part's claim — the claim, in Part 3's own words, is *"a
side-car value we wrote, with Stripe's durability and none of Stripe's authority"*, so that **any silo
can reconstruct a tenant's money from Stripe alone**. That is a portability property, not an accuracy
one, and it is the property Part 1 needs.

### What shipped for the metadata half

- **`domain/shipping_cost_metadata.py`** — pure. `stamp(shipment_id, amount, returning=)` and
  `from_metadata`.
- **One key per LABEL, not a running total.** `sc_<ref>` outbound, `sr_<ref>` return, where `<ref>` is
  the last 8 characters of the shipment id. A running total would have to be read before being written,
  and a retried purchase would then add the same postage twice; Stripe **merges** metadata on update, so
  a key named after the shipment is idempotent by overwrite and costs no GET on a path already waiting
  on a carrier. The ref is the id's **tail** because carrier ids share a prefix — taking the front would
  make every parcel of one order write the same key.
- **The outbound/return split is preserved in the keys**, for the reason the ledger splits them: a return
  has no postage revenue beside it, so folding the two would make a tenant's outbound pricing look like
  it loses money whenever a buyer sends something back.
- **`handlers/shipping.py` gained its first and only Stripe call**, wired into both label paths, plus
  `StripeKeysTable` read and `secretsmanager:GetSecretValue` on the role. KMS was already granted. Both
  grant guards were checked to *fail* with the grant removed, before trusting that they passed.
- **A subscription order is a skip, not a failure** — it stores no `payment_intent_id` at all (the same
  fact behind P4 defect 1), so there is nothing to mirror onto.
- **Positive magnitudes in metadata, negative in the ledger**, matching what `cogs` actually does. Part 3
  above says `# negative, per the convention`; **the code P2 shipped stores the positive magnitude** and
  `ledger.sale_entry` negates on the way in. The code is right and that comment was wrong.

**P4 — the Stripe-derived view. BUILT 2026-10-11 as a reconciliation check.**

The plan left the shape open — *"whether that becomes a screen, an operator tool, or just a
reconciliation check is a decision better made once the data is actually complete"* — and with P3
complete the data answered it. **A check, not a screen.** A screen would be a second, slower copy of
Reports reading a source with less authority; a check answers what the author actually asked for on
2026-10-07, after a live sale went missing: *"the ledger in our software must match Stripe to the
penny."*

### Stripe knows THREE of six from a charge, not four

Part 2 says four. From a **charge listing** it is three, and the difference matters because the listing
is what any sweep can afford:

| component | source | authority |
|---|---|---|
| `gross` | `charge.amount_captured` | **Stripe's** |
| `stripe_fee` | balance transaction `fee_details` | **Stripe's** |
| `platform_fee` | balance transaction `fee_details` | **Stripe's** |
| `tax` | the **session's** `total_details` — a charge does not carry its session | Stripe's, one call away |
| `cogs` | metadata we stamped at checkout (P2) | ours |
| `shipping_cost` | metadata we wrote at label purchase (P3) | ours |

`tax` is reached three ways, in descending authority, after the author's requirement that it *"work once
the tenant enables tax collection"*:

1. **the session** — Stripe's own figure, when a caller fetched one;
2. **the invoice** — also Stripe's own, and **free**, because the sweep already expands `data.invoice`
   for the silo stamp. This covers every renewal and needs no mirror. (`invoice.tax` is correct for the
   pinned API `2024-06-20`; later versions rename it `total_taxes`.)
3. **a mirrored metadata key** — ours, with Stripe's durability and none of its authority.

Zero is also the true answer for every tenant today — so `known` says which it is, instead of letting a
correct zero and an unasked question look identical.

### What "tax works when enabled" required, layer by layer

| layer | state |
|---|---|
| capture, one-off | **already worked** — `order_record_from_session` reads `total_details.amount_tax` |
| capture, renewal | **already worked** — `order_record_from_invoice` reads `invoice.tax` |
| ledger | **already worked** — `sale_entry_from_order` passes `tax`, and `profit` subtracts it |
| **Reports** | **was missing. Built.** `summarize` has returned `tax_liability` since tax was first captured and **nothing displayed it** |
| reconstruct, renewal | **built** — from the already-expanded invoice, free |
| reconstruct, one-off | reader built; `sessions` is the intended supplier (see below) |
| **enable collection** | **does not exist.** `automatic_tax` appears nowhere in `src/` |

**The Reports gap was the real one.** `gross` INCLUDES the tax the buyer paid and `profit` subtracts it
again, so **Net exceeded Profit by an amount with no row behind it** — the one thing a statement must
never do. There is now a "Sales tax collected" row between Net and Profit, negative like every other row
that leaves the tenant, hidden until there is some, and named as a **liability rather than income**: the
tenant is holding someone else's money, and calling it either earnings or an expense would be wrong in a
way an accountant would notice.

**The one-off reconstruction gap, stated rather than papered over.** A charge does not carry its session.
Mirroring the tax onto the PaymentIntent would need Stripe credentials threaded into
`persist_checkout_session_completed` — the most critical path in the system — for a figure the ledger
already holds; fetching the session on demand costs one call per charge, which an operator asking about
one tenant and one period can afford and a five-minute sweep cannot. **The second is intended.** The
metadata key is read now so that enabling tax does not also require changing the reader.

### Only the three are reconciled

`cogs` and `shipping_cost` are **reconstructed and never asserted against**. Comparing them with the
ledger they were copied from would be reading back our own writes and calling the agreement a check.

### What shipped

- **`domain/reconciliation.py`** — pure. `components_from_charge` (all six, in the ledger's sign
  convention, plus a `known` map), `summarize_charges` (the Stripe-derived view, same shape as
  `ledger.summarize`), `audit` (per-charge ledger comparison), `describe`.
- **`fees_from_balance_transaction` extracted** into `domain/fee_reconciliation.py`;
  `stripe_webhook.fees_from_payment_intent` now delegates. One implementation of *which `fee_details`
  entry is Stripe's own* — the rule being that `txn.fee` is the **total**, so reading it as the Stripe
  fee charges the tenant for the platform's own cut.
- **It rides the orphan pass's existing listing.** No new Lambda, no new route, no second API call —
  `data.balance_transaction` is simply a second `expand[]` on the call already being made. (That forced
  the params from a dict to a list of pairs: **a dict cannot carry two `expand[]` keys**, and the second
  would have been silently dropped.)
- **Bounded by deterministic entry ids.** `sale_entry_ids` builds the candidates — `le_sale_<pi>`, and
  `le_sale_order_<invoice>` for a renewal, invoice first — so the check is a point read per charge. The
  first draft compared window totals, which meant reading a tenant's **entire financial history every
  five minutes**, costing more the longer they had been successful.
- **A charge with no entry is NOT reported here.** That is the orphan pass's finding, in the same loop;
  reporting it twice would double every alarm for one missing sale. `unmatched` counts them so the two
  tallies read together.
- **Fees are not compared until Stripe has settled them.** Ours is an estimate by design and the sweep's
  own job is to true it up — comparing an unsettled charge would report the sweep's pending work as a
  discrepancy, every five minutes, for fifteen minutes, on every sale.
- **Scoped by the same ownership rule as the orphan pass.** Both deployments hold credentials for the
  same connected account, so an unscoped total would be a confident sum of two silos' takings — P4
  defect 2, arriving a second time through a new door.
- **Reports, never corrects.** Both money bugs so far were a missing event and a mis-keyed write;
  neither is fixed by nudging a total until it matches, and a self-correcting ledger would have hidden
  both.

### Verified live on dev, including that the check itself runs

```
'ledger_drift': {'examined': 2, 'matched': 2, 'unmatched': 0, 'failed': 0, 'fee_checked': 2}
```

`fee_checked` exists because "no findings" and "the fee half never ran" look identical in a tally. The
fee comparison only happens when the caller expanded `balance_transaction`, so a listing that forgot the
expand would report perfect agreement forever. Two of two charges had their fees genuinely compared.

That counter is this plan's own lesson applied to its own code: **three of the four defects P4 fixed were
code present and never reached**, each found only by a human reading a dashboard by eye a day later.

### A bug this found in its own first draft

`describe` keyed its message off `net`. **A sale we never recorded that was later refunded nets to zero
on both sides** — so the summary read *"ahead by 0 cents"* while gross was out by the whole sale. The
figure that decides the verdict is now the figure that gets named. Written down because the same
instinct — summarise with the headline number — produced it, and will again.

## Related

- `plans/SILO_MODEL.md` — the boundary this works within; S3 is the resolver Part 4 reuses
- `plans/STRIPE_MODE_DECOUPLING.md` — the 2026-08-02 "Axis 1 only" decision
- `plans/TRANSACTION_LEDGER_STRIPE_LINK.md` — the ledger Parts 2–3 complete rather than replace
- `plans/FEE_RECONCILIATION.md` — the sweep Part 4 fixes
- `plans/CONFIDENCE_WITHOUT_LIVE_MONEY.md` — the problem staging was really being asked to solve
- `plans/TRANSFORM_BUDGET.md` — why nothing here is a new route
