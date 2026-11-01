# Delivery tracking — the writer `tracking_status` never had

## Why this exists

`buyer_guarantees.no_delivery_refund` publishes, on live pages today: *"If your order has not arrived 20
days after it ships, we refund it or send it again — your choice."* Honouring it is manual, and the next
step was to automate it.

It could not be automated, because **this system knew when a parcel shipped and never learned whether it
arrived.**

| fact | where it lives | written by |
|---|---|---|
| `shipped_at` | Shipment | both ship paths |
| `tracking_number` | Shipment | both ship paths (absent on USPS First-Class) |
| `tracking_status` | Shipment | **nothing, ever** |

`fulfilment.delivery_status` has read `shipment["tracking_status"]` since the shipping work landed, and
`fulfilment._TRACKING` maps `PRE_TRANSIT`/`TRANSIT`/`DELIVERED`/`RETURNED`/`FAILURE` — Shippo's exact
vocabulary. One reader, zero writers. The Orders screen's Status cell therefore **could not say
"Delivered"** however long a parcel had been delivered, and the adapter in `domain/shipping_providers.py`
had `rates`, `buy_label`, `carrier_accounts`, `validate_address`, `schedule_pickup` and `create_manifest`
and no tracking method at all: it bought a label and never asked again.

**A sweep on `shipped_at + 20 days` alone would have fired on every order that old, including every one
delivered on time.** A gate built from an absence, where the absence of a delivery record reads as "not
delivered" and the truth is "nobody ever looked" — `feedback_absence_reads_as_safety`, on a feature that
moves money. So tracking ingestion is the prerequisite, and it ships first and alone.

## What landed

`domain/tracking.py`, pure and provider-agnostic, plus a public webhook receiver.

**The meaning stays in `fulfilment._TRACKING`.** The feed stores the provider's own word and
`delivery_status` goes on translating it. A second copy of that table would be how two readers of one fact
come to disagree, and the existing one was already correct — it just had nothing to read.

**Shippo already sends these.** It creates a tracking webhook automatically for every label bought through
it, so the events were being generated and discarded for want of an endpoint. We register explicitly
anyway, on both paths, for two reasons that are not belt-and-braces: a tracker Shippo made carries no
`metadata`, so its events cannot be matched to a shipment without indexing a tracking number that is not
ours; and one registration path means a hand-typed number and a bought label come through the same door
rather than the manual half being the one nobody tested.

**`metadata` is the only identifier we resolve.** It holds our own `shipment_id`, which we put there, and
`find_by_id` already does a cross-tenant GSI1 lookup on it — so no new index. The payload cannot name a
tenant, an order or an amount; the worst a forged body can do is set a carrier status on a shipment whose
id it already knew.

**Authentication fails CLOSED.** Shippo's HMAC option needs their solutions team to provision a shared
secret (up to ten business days), so the mechanism available is their echoed URL token — `?token=`,
compared constant-time against Secrets Manager. With no secret the endpoint rejects everything, which is
the opposite of the Debounce key and deliberate: an unconfigured deploy must not accept anonymous writes to
delivery state, and an endpoint that silently stopped checking is worse than one plainly off. Set it with
`./deploy/shippo-webhook-secret.sh <dev|prod>`, which prints the URL to paste into Shippo.

**Only the `tracking_*` attributes are written, by name.** This document now has two writers: a carrier can
scan a parcel in the same minute a tenant voids its label or marks it shipped by hand. A read-modify-write
from the webhook would restore what it had read a moment earlier over the tenant's own change, silently
(`feedback_shared_document_read_modify_write`). `update_tracking` is a targeted `update_item` guarded by
`attribute_exists(PK)`, so an event for a shipment we never had cannot create a key-only row that
`list_for_tenant` would then hand the Orders screen as a shipment with no order and no label.

**No order write at all.** `order["fulfilment"]` is computed on every request by `fulfilment_context` from
the Shipment documents — it is never stored — so the Status cell picks a delivery up on the next read.

### Ordering, which is the part that matters

Shippo retries twice on a non-2XX and events for one parcel can arrive in either order, so "latest
received" is not "latest happened". The carrier's own `status_date` is the ordering key, and:

- an older reading is refused; an equal one is allowed through so a retry is idempotent rather than an error;
- an undated event never displaces a dated one;
- **`DELIVERED` is sticky** against everything except `RETURNED` and `FAILURE`, which genuinely follow it
  (a refused delivery, a return to sender). A late in-transit scan arriving after the box was on the
  doorstep is an ordinary thing for a carrier to do, and it is the one transition that would make a
  delivery guarantee pay out on an order the buyer already has;
- **`delivered_at` is written once and never moved.** A parcel delivered, returned and redelivered did
  still arrive on the first date; moving it would silently re-open a promise that had been kept.

### Absence is not a claim

`has_arrived()` returning False means *"we have no delivery for this"* — which is also the answer for every
shipment predating this feed, for every carrier that never scans, and for a parcel genuinely lost. Anything
deciding about money must treat the two apart. That is written into the function's own docstring because
the next phase is exactly the caller that would get it wrong.

## Registration is the PLATFORM's call, not the tenant's

**First shipped using the tenant's own key, and that was wrong in a way that mattered.** Shipping is BYOK
per tenant, so a tracker registered with their key reports to a webhook configured on *their* Shippo
account — which is not ours, and which no tenant is going to paste a URL into. Registration would still
succeed, so `guarantee_due.observable` would count those parcels as visible to us while no delivery ever
arrived: the sweep could then report a guarantee due on a parcel the buyer already has. The gate would be
reporting on parcels it cannot actually see, which is the exact fault it exists to prevent.

So tracking moved to **one platform account** (`src/stripe_link/shippo_tracking.py`), with one webhook
registered once. Shippo's Tracking API tracks parcels "created outside of Shippo" by carrier and tracking
number, which is what makes this possible — and it is an ordinary account, not the platform/partner
agreement BYOK exists because we could not get.

It also closes a limit this plan previously recorded as permanent: a tenant who posts at their local
counter and types the number in has no Shippo account, so there was nothing to register and their parcels
could never have a feed. They are probably the largest group of sellers here, and they were the group the
guarantee sweep could never see. Now we register their number ourselves.

It **removed** code: `orders.py` no longer resolves the tenant's config, cipher and provider to register a
hand-typed number, which is net −11 lines on the path that needed it most and could serve it least.

**It costs.** Shippo includes tracking for shipments created on the account and charges per tracking number
for everything else — which is what a tenant's label is from this account's point of view. A third-party
comparison quotes $0.02 per track; Shippo's own API pricing page says contact sales, so that figure is
unconfirmed. The module therefore registers exactly once per shipment and never polls.

**Two keys, because Shippo's test mode is the rehearsal.** Live tracks real parcels and bills; test accepts
Shippo's mock tracking numbers and costs nothing. Selected by the shipment's Stripe mode, so a test-mode
order never burns a paid track on a parcel that does not exist, and an unrecognised mode falls back to the
key that cannot spend money.

**A carrier that will not third-party track degrades correctly and needs no list.** Canada Post, Colissimo,
DHL Germany and Ontrac only track shipments created through Shippo; Australia Post, Purolator and Swyft
need a carrier account. Any of those makes `POST /tracks` fail, `register` returns `{}`, no
`tracking_registered_at` is written, and the parcel stays unobservable — so the sweep says nothing about
it. A hardcoded carrier list would only drift from Shippo's.

## The sweep — shipped

`domain/guarantee_due.py`, as a **fourth pass over the orders scan** `fee_reconciliation` already runs
every five minutes. Reading the orders table is the expensive half and it is already happening; the three
existing passes set the precedent that sharing a walk does not make two decisions one concern. No template
change at all: `StripeWebhookFunction` already held Orders, Shipments, Notifications and PlatformConfig.

**It notifies. It never refunds.** Two reasons, either sufficient: the published sentence says *"we refund
it or send it again — your choice"*, so a sweep that moved money would deny the buyer the choice the page
promised them; and nobody has asked them anything yet. What has come due is a conversation.

**Both clocks are sweepable now, which the feed made true.** `no_delivery_refund` runs from `shipped_at`
(what the sentence says), `no_tracking_update_refund` from the last scan — and from registration when there
has never been one, which is the purest case of "tracking shows no movement" rather than a case with no
clock. The other three guarantees are deliberately out: `damaged_in_transit` needs someone to look in the
box and the two price promises are about a price list, so a sweep cannot see any of them and a notice with
nothing behind it is worse than none.

**The `observable` gate is the whole thing.** A shipment with no `tracking_registered_at` is skipped,
because `has_arrived` is False for a parcel never tracked, a carrier that never scans, and a parcel
genuinely lost — three different things wearing one answer. It also dates the feature for free: nothing
shipped before the feed carries a registration, so no historical order can be dragged into a promise nobody
was watching at the time.

A **returned or failed** parcel is still reported. It did not reach the buyer, which is exactly when they
are owed the refund or the resend; the Orders screen already says "Returned" beside it, so the notice adds
the promise rather than the news.

Notices are idempotent by **primary key** — `notif_guarantee_<key>_<order_id>` — so a five-minute sweep
rewrites one row instead of filling the bell. Keyed on the guarantee too, because an order can outrun both
promises and they are two different things to settle. `sort_priority` 95, above the overdue-to-ship notice
at 90: that one is a parcel the tenant still has, this is a promise already broken in the buyer's eyes.

### The bug this uncovered

`_shipment_for` was `shipments_repo.get(tenant_id, order_id)`. **A shipment is stored under its own id** —
`shp_<order_id>_outbound_1` from `shipment_id_for` — so the lookup asked DynamoDB for
`SHIPMENT#<mode>#order_1`, a key that can never exist, and got `None` every time. `has_shipped(None)` is
False, so **the overdue-to-ship notice fired on every paid order carrying a promised ship date, including
the ones already posted.** Live.

The unit test passed throughout because its fake repository was keyed by order id — the shape the bug
assumed rather than the shape the table has. Both the lookup and the fake are fixed, and the lookup is now
one shared `_ShipmentsByOrder` built the way `fulfilment_context` builds it: list the tenant's shipments,
key by `order_id`, newest wins, cached per tenant. Writing a correct lookup beside a broken one would have
been the duplicate source this repo keeps paying for.

### Withdrawing a notice whose cause is gone

Fixing the lookup stops NEW false notices and leaves every one already written sitting `unread` in a
tenant's bell. The deeper fault underneath it: **every notification emitter in this codebase writes and
none withdraws**, so a notice has always outlived its cause — a tenant who shipped the parcel still had
"Order waiting to ship" telling them to. Survivable while the notices were right; not survivable once the
pass was firing on orders already posted.

So `_clear_stale_notices` deletes anything under a pass's own prefix that the pass did not just write. The
notice now mirrors its predicate, which is what a notice was always supposed to do. The sweep runs every
five minutes, so the backlog drains itself rather than needing a migration nobody would run twice. Applied
to the guarantee notices too, so a parcel that arrives late settles the promise *and* clears the notice.

One list per tenant, and deletes only where something changed. A point delete per non-overdue order would
have been idempotent and tempting, and it is a write per order per sweep for ever on a table that is almost
always already correct.

**`skip` is load-bearing: a failed read must not become a delete.** Every predicate here depends on the
shipments table, and when it will not answer nothing looks overdue — so an unguarded clear would withdraw
every notice a tenant has on the strength of an outage. Withdrawing a true notice is worse than keeping a
stale one, because the tenant stops being told about a parcel that really is late. `_ShipmentsByOrder`
therefore keeps "this tenant has no shipments" apart from "this tenant would not answer", and only the
first permits a withdrawal.

## Next

1. **A buyer-facing claim.** "It hasn't arrived" on the order link, enabled only once the clock has run,
   opening a refund request tagged as a guarantee claim with the buyer's choice of refund or resend — the
   promise says *they* choose, so nothing should auto-refund without them.
2. **Adjudication.** With the feed live, a tenant seeing "Delivered 3 days ago" beside a claim can decline
   it with evidence. That is the real value of the feed: not detection, adjudication.
3. **Confirm the per-track price with Shippo**, and whether a label bought on another Shippo account
   counts as "created on Shippo" for ours. The $0.02 figure is a third-party one and the architecture is
   cheap to keep either way — it registers once per parcel and never polls — but the number should be
   known rather than assumed.

Deliberately not now: HMAC (blocked on Shippo's solutions team), and a tracking-number index (unnecessary
while `metadata` carries our own id).
