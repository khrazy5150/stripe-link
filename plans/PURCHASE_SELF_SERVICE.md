# Self-service for a purchase: one button, one transaction, one request

**Status:** designed 2026-09-14, not built. Supersedes the tip-specific "re-send page"
(`PAY_WHAT_YOU_WANT.md` §5g), which becomes one narrow answer from this flow.

A customer who wants to stop paying, or wants their money back, currently has two routes: find our email, or
find the tenant. This is the third and the one they will actually look for — a link at the bottom of the
page, next to the refund policy, because **that is where someone goes when they want the money to stop**
(author, 2026-09-14). Terms and Privacy are for reading; Refund is for doing.

## 1. What it is

One entry point on every page: identify ONE transaction, then do the one thing that transaction allows.

**It is TENANT-AGNOSTIC** (author). Any Junior Bay page can start a request about any Junior Bay purchase.
The footer link is identical everywhere, needs no per-page plumbing, and works from a receipt, the platform
site, or the page of a tenant the customer never bought from.

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

## 5. The cross-tenant index — a deliberate decision, not a side effect

Orders are keyed `(tenant_id, order_id)`, so today a purchase cannot be found without knowing whose it was.
Tenant-agnostic lookup needs an index on buyer email/phone that spans every tenant.

**That object is the buyer graph of the whole platform in one place.** It deserves its own access rules —
who can query it, what a query returns, what is logged — rather than arriving as a convenience. Options:

- A GSI on the orders table keyed by normalized email/phone (simplest; the index inherits the table's
  access).
- A dedicated lookup table holding only `(contact_hash -> tenant_id, order_id)`, so the index itself carries
  no readable contact data and a compromise of it yields nothing without the orders table too.

The second is the better shape and is not much more work. Decide before building.

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

- The cross-tenant contact index (§5).
- The form, and the identify-one-match logic with the neutral answer.
- The transaction page: confirm what was found, act, or "not this one?".
- **Policy-aware messaging.** Today a refund policy is text on a page. Here it decides what the button
  offers and says — "14-day window, 6 days left" versus "non-refundable" versus "return required". That is a
  real change in what the policy IS, and it is the same screen where §5f's tip wording has to land.
- Phone as a second-class path: we store a phone only when Stripe Checkout collected one, which happens only
  if the tenant enabled it. Email is primary; phone must not be promised.

## 8. Build order

1. **Footer link** next to Refund Policy, on every transactional page, tenant-agnostic.
2. **The contact index** (§5) — decide the shape first.
3. **Form → one match → one link**, with the neutral answer and a rate limit (the lead-capture abuse gate is
   the existing shape).
4. **The transaction page** with the two actions that already have back ends: cancel a subscription (built)
   and request a refund (the orphan endpoint).
5. **Policy-aware copy**, which is where §5f's tip refund rule gets written down for buyers.
6. Downloads and bookings fold in after.
