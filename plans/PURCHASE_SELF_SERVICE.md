# Self-service for a purchase: one button, one transaction, one request

**Status:** v1 BUILT, on dev and prod 2026-09-14/15 (§8 steps 1-4, plus the gate). Step 5 (policy-aware
copy) is outstanding — see §9. Supersedes the tip-specific "re-send page"
(`PAY_WHAT_YOU_WANT.md` §5g), which becomes one narrow answer from this flow.

A customer who wants to stop paying, or wants their money back, currently has two routes: find our email, or
find the tenant. This is the third and the one they will actually look for — a link at the bottom of the
page, next to the refund policy, because **that is where someone goes when they want the money to stop**
(author, 2026-09-14). Terms and Privacy are for reading; Refund is for doing.

## 1. What it is

One entry point on every page: identify ONE transaction, then do the one thing that transaction allows.

**v1 is TENANT-SCOPED** — the button handles purchases made from THAT tenant. Cross-tenant is §5a, recorded
as a later phase rather than built on speculation.

The reason is what Stripe can and cannot do. `customers/search` matches on `email` (and `phone`), but only
within ONE Stripe account, and under direct charges every tenant is their own account — there is no
cross-account search, so a tenant-agnostic lookup means fanning out over every connected account per request
against a 20-reads-per-second limit. Worse, **charges and payment intents cannot be searched by email at
all** (the searchable fields are amount, card last4, postal code, metadata, status), and a Customer object
only exists for subscriptions or when we explicitly ask for one — so an ordinary one-off purchase is
invisible to an email search. Our own orders are the real index; Stripe resolves identifiers, it does not
find purchases by email.

**The durable entry point is the RECEIPT, not the page** (author, 2026-09-14: a link-in-bio page can be
swapped by the creator, so the page a charge came from may be gone or changed). Every receipt and every
renewal notice already carries a direct link, which is page-independent. The footer button is the fallback
for someone who lost the receipt AND can still find the page — which is why losing the page is survivable,
and why the re-send path matters more than the button does.

## 2. The rule that decides what the button may do

**Actions that cost the tenant nothing are self-serve. Actions that move money are a REQUEST.**

| purchase | self-serve, immediately | a request the tenant decides |
|---|---|---|
| recurring tip / subscription | stop future charges | refund the LAST charge |
| digital product | download again | refund |
| physical product | — | refund, with the return method from the policy |
| one-off tip | — | refund (net, per `PAY_WHAT_YOU_WANT.md` §5f) |
| service / booking | cancel inside the service's window | refund outside it |

Cancelling costs the tenant nothing and refusing it only manufactures chargebacks, so it happens on the spot.
A refund moves money out of the tenant's account, so it creates a `refund_request` and the tenant answers it.

**The copy has to keep those apart.** "Cancelled" is a fact; "Requested" is a decision someone else makes.
Blurring them manufactures disputes out of disappointed expectations.

## 3. Identification: ONE transaction, never a list

**Never enumerate** (author, 2026-09-14): *"We don't volunteer this information to them — 'we see there are
3 purchases to this tenant, which one?' No. Just offer ONE (the latest by default) and if they want another,
let them submit another request."*

Two reasons, and the second is the one that is easy to miss:

1. **Privacy.** A list behind one emailed link means one leaked link exposes a purchase history.
2. **A list invites a purge.** Show someone everything they are paying for and you have built the screen
   that ends three subscriptions instead of the one they came for. That is a tenant-protection argument, and
   it points the same way as the privacy one.

The flow:

1. **The static form takes an email or a phone number**, plus an OPTIONAL approximate date ("roughly when?")
   to narrow. Nothing else — a static page cannot ask for card details.
2. The server matches and takes **the latest** matching transaction, or the one nearest the given date.
3. **One link, for that one transaction**, sent to the address or number they just proved they control.
4. **The answer is identical whether or not anything matched.** Otherwise the form is an oracle for "did
   this person buy from that creator" — a leak about someone who is not the one asking.

### What the link opens

The page states what it is about to act on — *"$11.19 on 14 Sep to Poliaxis, monthly"* — and offers the one
or two actions that transaction allows. **That is confirmation, not enumeration**: one candidate, shown so a
wrong match is visible before anything happens.

It also needs **"not this one?"**, which re-runs the form with a date rather than listing alternatives.
Without it a wrong match is a dead end, and a dead end is how a customer ends up at their bank instead.

### One request at a time

One refund per request (author). A second purchase needs a second request, which means a second
identify-and-email cycle. That is also a security property worth keeping deliberately: **a leaked link can
never sweep a history**, because it was only ever scoped to one transaction and one action.

## 4. Tokens: two lifetimes, for two reasons

The tip work landed on one TTL. This flow needs two, and each earns its own number:

| link | scope | lifetime | why |
|---|---|---|---|
| cancel a subscription | one subscription, cancel only | **long** (400 days today) | the subscription is open-ended and this is the only self-serve way to stop it |
| request a refund | one charge, one request | **short** (days) | it is about one charge, and the refund window is bounded by the policy anyway |

Both stay narrow: a token opens one action on one transaction, never an account portal. That narrowing is
what makes "a leaked link is fail-safe" true, and what pays for the long lifetime on the cancel side
(`PAY_WHAT_YOU_WANT.md` §5g).

## 5. Finding the order, and what v1 needs

Orders are keyed `(tenant_id, order_id)` with a `PaymentIntentIndex` GSI. v1 is tenant-scoped, so the tenant
is known and the match is within one tenant's orders: **email (or phone) + optional approximate date ->
latest match**.

**v1 needs no new index.** Orders are keyed `PK = tenant_id`, so once the tenant is known this is a QUERY on
that tenant with a filter on the buyer's email — not a scan, and not a cross-tenant problem. It reads that
tenant's orders per lookup, which for an action this rare is fine well past the point where anything else
here needs attention.

The index is a scale optimisation for later: a GSI on `(tenant_id, contact_key)` where `contact_key` is a
normalized, hashed email or phone — hashed so the index itself carries no readable contact data.

### 5a. Cross-tenant, deferred

Widening this so any page can start a request about any purchase needs an index spanning every tenant —
**the buyer graph of the whole platform in one place.** That object deserves its own access rules (who may
query it, what a query returns, what is logged) rather than arriving as a convenience, and the case for it
is speculative until support volume shows people genuinely arriving at the wrong page. Build it when there
is evidence, as a dedicated lookup table holding only `(contact_hash -> tenant_id, order_id)` so a
compromise of the index alone yields nothing without the orders table.

### 5b. Adding the GSI later is fine — the attribute is the part to think about

Checked 2026-09-14, because it decides how much has to be right up front:

- **A GSI can be added to a live table with no downtime and no data loss.** DynamoDB backfills it in the
  background; the table stays available throughout.
- **One GSI per stack update.** The UpdateTable API creates or deletes exactly one index per call, and
  CloudFormation treats a resource update as one atomic operation — so adding two indexes in a single deploy
  FAILS. Ours would have to land one deploy at a time.
- **A GSI only indexes items that carry its key attribute.** Orders written before we start stamping
  `contact_key` would be absent from the index (a sparse index), so they need a one-off backfill — a script
  that rewrites existing orders with the attribute.

The practical consequence: the *index* is easy to add whenever, the *attribute* is what wants to exist early.
At current volume a backfill is a short script either way, so this is not a reason to build ahead of the
feature — it IS a reason to add `contact_key` to the order record the moment this work starts, before the
index, so the backfill only ever covers history rather than history plus everything written in between.

## 6. What already exists

More than it looks, and this button is the missing front door:

- `refund_request` documents, validation, the tenant notification, and approve → reject → execute on the
  Refunds screen. **There is even a creation endpoint, `PUT /notifications/refund-requests`, that nothing
  calls.** It has been waiting for this.
- Order lookup by payment intent (the `PaymentIntentIndex` GSI), so a Stripe charge resolves to our order.
- Download links, per-offer and per-product refund policies, the token + mail pattern, and an SMS sender
  (`sms.py`) for the phone path.
- The tip cancel link (`handlers/tip_manage.py`), which becomes this flow's first action rather than a
  feature of its own.

## 7. What does not exist

- The `contact_key` attribute on orders (§5) — the index itself can wait.
- The form, and the identify-one-match logic with the neutral answer.
- The transaction page: confirm what was found, act, or "not this one?".
- **Policy-aware messaging.** Today a refund policy is text on a page. Here it decides what the button
  offers and says — "14-day window, 6 days left" versus "non-refundable" versus "return required". That is a
  real change in what the policy IS, and it is the same screen where §5f's tip wording has to land.
- Phone as a second-class path: we store a phone only when Stripe Checkout collected one, which happens only
  if the tenant enabled it. Email is primary; phone must not be promised.

## 8. Build order

1. **Footer link** next to Refund Policy, on every transactional page, scoped to that page's tenant.
2. **`contact_key` on the order record** (§5b) — no index yet; the attribute wants to exist before one so a
   later backfill covers history only.
3. **Form → one match → one link**, with the neutral answer and a rate limit (the lead-capture abuse gate is
   the existing shape).
4. **The transaction page** with the two actions that already have back ends: cancel a subscription (built)
   and request a refund (the orphan endpoint).
5. **Policy-aware copy**, which is where §5f's tip refund rule gets written down for buyers.
6. Downloads and bookings fold in after.


## 9. What v1 shipped, and what it did not

**Shipped** (`handlers/purchase_manage.py`, `domain/purchase_lookup.py`, `runtime/purchase_pages.py`):

- The way in: a block on `/legal/refund` ("Cancel a payment or ask for a refund"), reached from the footer's
  Refund Policy link, which now carries `?tenant=`. Not a second footer link — that competed with the page
  it pointed at.
- `GET ?tenant=` the form (email or phone, optional approximate date — never a card number).
- `POST action=lookup` -> ONE order (latest, or nearest the date), a token scoped to it, and a link emailed
  to the address ON THE ORDER rather than the one typed. Identical answer on a hit and a miss.
- `GET ?t=` the transaction page: what we found, stated, with only the actions it allows, and "Not this
  one?" back to the form.
- `POST action=cancel` -> `cancel_at_period_end` on the subscription, immediately. Not an immediate delete:
  they paid for the period they are in, and taking it away is a refund nobody asked for.
- `POST action=refund` -> a `refund_request` in the tenant's existing queue, with their notification. The
  copy says REQUESTED, never refunded.
- `contact_keys` + `subscription_id` on new orders. Older orders still match, because `order_contact_keys`
  computes from `customer.email` when the stored field is absent — which is why v1 needed no backfill and no
  index.

**The gate** (shipped 2026-09-15). The lookup POST is unauthenticated and, unthrottled, amplified one HTTP
request into a full read of a tenant's order list IN BOTH MODES plus an outbound email — with the tenant id
sitting in a public footer URL. Three cheap defences, all of which run before any of that work:

- The **honeypot** the lead forms already use — one hidden field, one name across the product.
- **Per (tenant, contact): one lookup per 15 minutes.** Caps both halves: the same address cannot be mailed
  repeatedly, and the same contact cannot make us re-read the orders.
- **Per tenant: 20 per hour.** Someone enumerating DIFFERENT addresses is invisible to the first counter.

Two properties worth keeping: a throttled request returns the SAME page as any other, or the gate itself
leaks which addresses matched; and the gate **fails open** — a counter table that is unavailable must not
take the cancel-my-subscription path down with it, since being wrong that way costs a few reads and being
wrong the other way costs a customer who cannot stop a recurring charge.

**Not built yet:**

1. **Policy-aware copy** (§8 step 5). The transaction page shows the order's refund-policy label if it has
   one; it does not yet compute "6 days left" versus "outside the window" versus "non-refundable", which is
   where `PAY_WHAT_YOU_WANT.md` §5f's tip rule finally gets written for buyers.
2. **Phone delivery.** The form accepts a phone number and matches on it, but the link is only ever emailed,
   because that is the address the order carries. SMS delivery would use `sms.py`.
3. **Re-download** for digital products, and booking cancellation — §2 lists them; neither is wired.
