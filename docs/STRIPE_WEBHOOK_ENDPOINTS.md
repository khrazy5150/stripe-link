# Stripe webhook endpoints — which destination feeds which key

The signing secret belongs to the **endpoint**, so the only way to store one correctly is to know which
Stripe destination it came from. The names in the Stripe dashboard are free text and have twice been the
thing that made this hard, so this table is the mapping, keyed on the part that cannot drift: the **URL**.

## The mapping

| Stripe destination (name) | URL path | `kind` | Payload keys in `jb/platform-stripe/{env}` |
|---|---|---|---|
| `sandbox-connect-live-test` | `dev.juniorbay.com/webhook/stripe-preview` | `preview` | `whsec_preview_test` **and** `whsec_preview_live` (dev secret) |
| `production-connect-live-test` | `prod.juniorbay.com/webhook/stripe-preview` | `preview` | `whsec_preview_test` **and** `whsec_preview_live` (prod secret) |
| `production-billing-live` | `prod.juniorbay.com/webhook/platform-billing` | `platform_billing` | `whsec_platform_billing_live` |
| *(none registered)* | `/webhook/stripe` | `stable` | `whsec_stable_*` — **unused** |

`kind` is not configuration: it is derived from the path (`stripe_webhook.py`, `_webhook_kind`), and
`/webhook/platform-billing` is a separate function whose `WEBHOOK_KIND = "platform_billing"`.

The two `checkout.juniorbay.com` destinations belong to **stripe-cart** and feed nothing here.

## Why one endpoint fills BOTH mode slots

A connected account that authorised through **live** OAuth and then works in test mode emits
`livemode: false` events, and the **live** endpoint delivers them, signed with the **live** secret. So one
Connect destination per stack carries both modes. Measured 2026-10-12: production verified 0 of 36 such
events before this was understood.

The lookup is keyed by the **event's** mode — `webhook_secret_loader(kind, mode)` — and an empty result
returns 500 *before* the cross-mode fallback can run. A secret stored only under `_live` therefore rejects
every test-mode event outright. Hence: one endpoint, both slots, same value.

Platform billing is the exception: those are the platform's **own** account events with
`PlatformBillingMode: live`, so it is genuinely live-only and `_live` alone is honest.

## Naming

Chosen and applied in Stripe 2026-11-09, after the old names cost time twice in one day:

    {environment}-{kind}-{modes}

* **environment first**, on every destination, because pointing one at the wrong stack is the failure that
  actually hurts — endpoint drift once put a sandbox tenant's orders in `jb-orders-prod` while their
  products, upsells and dashboard lived in dev. With every name prefixed, a prefix only ever means "which
  stack" and its absence never has to be interpreted.
* **modes spelled out** (`live-test`), because the old `sandbox-preview-live` read as the live endpoint
  when it was the sandbox one — worse than vague.
* **no `preview`**: it is a Stripe API-version word that says nothing about routing, and it collides with
  the pinned `2026-05-27.preview` API version, which is a different decision entirely.

Renaming a destination is safe: the description is metadata, and a signing secret is only issued at
creation — rotating one is a separate action. Confirm with a single test event after renaming.

## Storing a secret

`./deploy/platform-stripe-secret.sh [dev|prod]`, then `./deploy/deploy.sh [dev|prod]` — the deploy is what
repoints the stack, and nothing reads a new secret until it runs. See
[[project_platform_stripe_secret]] for the 2026-11-09 outage this came out of.
