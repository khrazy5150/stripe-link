# Platform account identity as configuration

Status: **PROPOSED (2026-09-23). Not built.** Written after the platform-account swap runbook
(`plans/ADMIN_SITE.md` §4) exposed how the identity is currently wired.

## What this is for

The Junior Bay platform Stripe account is changing — the entity is moving from a corporation to an LLC,
and a Stripe account cannot change entity. The swap itself is a runbook, not a feature. This document is
about the two things that make the swap awkward and that stay useful long after it:

1. platform identity cannot be changed without a **stack deploy**;
2. there is no **dual-secret window**, so a swap has an unavoidable verification gap.

Neither matters much today — one connected account, no live traffic. Both are expensive post-launch, which
is the only reason to write this down now.

## How identity is wired today

Split across two mechanisms, for no reason anyone recorded:

| what | where | changing it needs |
|---|---|---|
| `sk_test`, `sk_live` | Secrets Manager, one secret per silo | a secret write (no deploy) |
| `whsec_*` per (kind, mode) | the same secret | a secret write (no deploy) |
| Connect `client_id` (`ca_…`) | **CloudFormation parameters** `StripeClientIdTest` / `StripeClientIdLive` → Lambda env | **a stack deploy** |

The keys are already runtime configuration; the client ids are build-time parameters. So a swap is half a
secret write and half a deploy, and the half that needs a deploy is the half that decides **which platform
a tenant's OAuth authorises against** — the one most damaging to get wrong, because a stale client id
sends tenants to reconnect to the account you are leaving and every screen reports success.

## Proposal A — one home for platform identity

Move the Connect client ids into the **same per-silo secret** that already holds the keys, read through
`stripe_platform_secrets.py` like everything else. Keep the CloudFormation parameters as a fallback so
nothing breaks mid-migration, then retire them.

Result: platform identity becomes **one write, no deploy** — and the runbook's steps 4 and 5 collapse into
a single atomic change, which removes the window in which keys and client id disagree.

This is also the substrate an admin surface would sit on later. A "swap platform account" screen is only
possible at all once identity is data; today it would have to trigger a CloudFormation deploy, which is
not a thing a web form should do.

## Proposal B — a dual-secret window

`get_platform_webhook_secret` resolves exactly ONE signing secret per `(kind, mode)`
(`stripe_platform_secrets.py:108` — `_first_non_empty` over a list of aliases, first match wins). During a
swap, events signed by the other platform fail verification for as long as the cutover takes.

**Cost today: nothing.** One tenant, no live traffic, and Stripe retries for days — so anything missed
arrives once the new secret is in place.

**Cost post-launch: an outage on the money path.** Every merchant's checkout webhooks fail verification
until every endpoint is repointed, and Stripe's retry budget is finite.

The fix is to accept a LIST of acceptable signing secrets and verify against each, so old and new are both
valid for the length of a migration. Small, and only worth doing before the platform carries traffic that
cannot be dropped. Explicitly NOT needed for the current swap.

## Proposal C — verification, already built

`deploy/verify-platform-account.sh` (2026-09-23) reports, per silo, which Stripe account each key actually
opens — by asking Stripe, not by comparing bytes. A fingerprint can only say two silos hold the same key;
it cannot say **which account** that key belongs to, and after a swap that is the only question worth
asking.

It prints keys as prefix + last-4 + a short digest, never in full, and it names a revoked or restricted
key plainly — which is exactly the condition a swap is trying to escape.

Recorded baseline, 2026-09-23: both silos → `acct_1GdJkFEcxlWjis9i` «Junior Bay Corporation»,
`charges_enabled=true`, `payouts_enabled=true`, sharing one Connect client id pair.

## Order, and what is actually required

- **For the imminent swap:** C (done) and the runbook. A and B are not prerequisites.
- **A** before any admin surface touches platform identity, and ideally before the swap — it makes steps 4
  and 5 atomic, which removes the worst failure mode (keys swapped, client id stale).
- **B** before the platform carries live traffic that cannot tolerate a verification gap. Not before.

## Relationship to other plans

- `plans/ADMIN_SITE.md` §4 holds the runbook and the reasoning for why the swap is not a feature.
- `plans/SILO_MODEL.md` records the decision to keep ONE platform account shared by all silos, so that a
  tenant's Stripe relationship does not fracture when they move between silos. This document does not
  reopen that: it is about changing WHICH single account, not about having several.
