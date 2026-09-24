I think the clean solution is a "Silo Anchor"

Rather than stamping every conceivable Stripe object and hoping metadata propagates, establish a deliberate mapping:

JuniorBay
    │
    └── Tenant T123
          │
          └── Stripe acct_123
                │
                ├── Sandbox Customer cus_SANDBOX
                │       │
                │       ├── Checkout Sessions
                │       ├── PaymentIntents
                │       ├── Invoices
                │       └── Charges
                │
                └── Production Customer cus_PRODUCTION
                        │
                        ├── Checkout Sessions
                        ├── PaymentIntents
                        ├── Invoices
                        └── Charges

In other words:

Tenant is global. Stripe connected account is global. Customer becomes silo-specific.

That is potentially the missing architectural piece.

You'd have something like:

tenant_id
stripe_account_id
silo
stripe_customer_id

with a uniqueness constraint such as:

(tenant_id, silo) → exactly one Stripe Customer

Then:

cus_SANDBOX → sandbox
cus_PRODUCTION → production

becomes an authoritative mapping that your application controls.

Why Customer is particularly interesting

A huge amount of Stripe's commerce graph eventually points back toward the Customer.

For example:

Invoice
   └── customer

Subscription
   └── customer

PaymentIntent
   └── customer

Charge
   └── customer

Stripe's Invoice object, for example, has a customer reference.

Subscriptions likewise have a customer relationship and their own metadata.

So imagine Stripe sends:

invoice.payment_succeeded

and the invoice itself doesn't have:

"metadata": {
  "juniorbay_silo": "sandbox"
}

You don't have to guess.

You can resolve:

event
 ↓
invoice
 ↓
customer = cus_SANDBOX
 ↓
JuniorBay mapping
 ↓
sandbox

That's an actual authoritative lookup.

And metadata is still useful

I'd absolutely put silo metadata on objects you create:

{
  "metadata": {
    "juniorbay_silo": "sandbox"
  }
}

But I'd treat that as redundant evidence, not the sole routing mechanism.

For example:

Event
 │
 ├── account = acct_123
 │
 └── object = invoice_456
                  │
                  ├── metadata.silo = sandbox
                  │
                  └── customer = cus_SANDBOX
                                  │
                                  └── DB says sandbox

Then your webhook processor can actually detect corruption:

metadata.silo       = sandbox
customer mapping    = sandbox

→ good.

But:

metadata.silo       = production
customer mapping    = sandbox

→ STOP. This is an invariant violation.

That is much better than silently routing based on whichever field happens to be present.

There's an important Stripe gotcha

Stripe does not generally propagate metadata from one object to related objects automatically.

Stripe explicitly documents this in the Connect context: metadata set on one payment object doesn't automatically propagate to related objects such as Transfers or destination Charges; custom development is required.

So I would not design:

Checkout Session metadata
        ↓
PaymentIntent metadata
        ↓
Charge metadata
        ↓
Invoice metadata

and assume Stripe will carry your silo flag through the graph.

Instead:

Put the silo marker on every object you directly create where practical.

And independently maintain the authoritative relationships in JuniorBay.

There's another surprisingly useful mechanism: Stripe's object graph

Stripe's objects are highly interconnected.

For example, Stripe documents that an Invoice has:

customer
subscription
parent

and a Subscription has:

customer
latest_invoice

etc.

So your webhook resolver can have a deterministic strategy:

Event arrives
       │
       ▼
What Stripe account?
       │
       ▼
What object?
       │
       ▼
Does object have juniorbay_silo?
       │
       ├── YES → verify against anchor
       │
       └── NO
            │
            ▼
       Follow authoritative relationship
            │
            ▼
       Customer / Subscription / etc.
            │
            ▼
       Resolve silo

That means you don't need every event type to independently carry the silo.

One thing I would NOT use as the discriminator

Stripe's request information isn't reliable enough for this purpose.

Stripe says the Event's request.id is null when the event was automatic — for example, Stripe's automatic subscription handling.

So this:

request.id
   ↓
find originating JuniorBay request
   ↓
determine silo

would fail precisely for some of the events you're worried about.

Customer/object relationships are much stronger.

There is also a very useful distinction in Stripe's webhook architecture

Stripe already has the concept of environment separation at the webhook level:

test-mode events
live-mode events

Stripe recommends checking the Event's livemode property to determine which environment an event came from.

And the Event itself carries:

livemode: true | false

But that only helps if your JuniorBay silo corresponds directly to Stripe's test/live mode.

Your problem is that you've created:

JuniorBay:
sandbox
production

while retaining:

Stripe:
one platform

So livemode isn't sufficient if your application-level silo boundary doesn't exactly equal Stripe's environment boundary.

That's precisely why the object-anchor approach is interesting.

I think the resulting architecture is quite elegant

I'd model it like this:

                    JUNIORBAY TENANT
                           │
                           │
                    Stripe acct_123
                           │
                ┌──────────┴──────────┐
                │                     │
          SANDBOX ANCHOR        PRODUCTION ANCHOR
          Customer cus_S         Customer cus_P
                │                     │
          ┌─────┴─────┐         ┌─────┴─────┐
          │           │         │           │
       Sessions    Payments   Sessions    Payments
          │           │         │           │
          └─────┬─────┘         └─────┬─────┘
                │                     │
                └─────────┬───────────┘
                          │
                     Stripe events
                          │
                          ▼
                    acct_123 tells us
                      WHO owns it
                          │
                          ▼
                 object graph tells us
                    WHICH silo owns it

That preserves the thing you care about most:

One Stripe connected account per tenant, regardless of environment.

But it gives JuniorBay a deterministic way to answer:

Which silo does this particular Stripe object belong to?

And there's an even better variant

I would seriously consider making the Stripe Customer the silo boundary, rather than merely an object carrying a silo flag.

So:

Tenant T123
    │
    └── Stripe acct_123
          │
          ├── Stripe Customer cus_sandbox
          │       └── ALL sandbox commerce
          │
          └── Stripe Customer cus_production
                  └── ALL production commerce

Then a tenant's Stripe login/account remains unchanged.

But the merchant's customers and commerce state are separated by silo.

That gives you an incredibly clean promotion model:

Same JuniorBay tenant
Same Stripe connected account
Same Stripe login
Different Stripe customer/object graph

And it eliminates the need for a tenant.home_silo, which we were circling around earlier.

One caveat

I'd want to audit your actual Stripe object flows before declaring Customer the universal anchor. Some event types don't naturally lead back to a Customer, and some Stripe objects are created independently of a customer. For those, we'd need either a second anchor or an explicit JuniorBay mapping table.

But that's a finite engineering problem, not a reason to abandon the one-platform architecture.

In fact, after looking at Stripe's current API model, I think your instinct to preserve one Connect platform is defensible and potentially cleaner for JuniorBay. Stripe gives you the connected-account identity at the Event level, object relationships for traversing the commerce graph, and metadata for explicit application-level assertions.

The next thing I'd do is take every webhook event your stripe-link currently consumes and build a matrix:

event
→ primary object
→ has customer?
→ has subscription?
→ has payment_intent?
→ has metadata?
→ can be traced to silo anchor?
→ fallback required?

That would tell us whether this architecture can cover 100% of your actual webhook surface, rather than theorizing about Stripe in the abstract.