# Copy a Landing Page Between Environments (Test ⇄ Live)

Status: **PROPOSED — awaiting sign-off.** Not built.

## Goal / use case

A tenant builds and iterates a landing page in **Test**, then wants it in **Live**
without rebuilding it by hand (and vice versa — pull a Live page back to Test to
experiment). Legacy stripe-cart had a "Copy to Live" action; this restores it under
the per-environment architecture.

A new row-menu action on the Landing Pages card:
- In **Test** → **"Copy to Live"**
- In **Live** → **"Copy to Test"**

(The target is always the *other* environment.)

## Feasibility findings (verified)

1. **Cross-env auth works.** The Cognito user pool is an *existing* pool passed to
   both stacks as a parameter, and the dashboard stores a **single access token in
   sessionStorage** (not per-env). That is exactly why the runtime Test/Live toggle
   never re-prompts for login. A `fetch` to the *other* env's API base carries the
   same `Authorization: Bearer` and authenticates. → We add a base-override to
   `apiRequest`; no auth work needed.

2. **All catalog data is per-environment.** `jb-offers-{env}`, `jb-products-{env}`,
   etc. are separate tables. A Test page references a Test `offer_id`; that offer
   (and its products/prices) does **not** exist in the Live tables. This is the core
   complexity — see "The dependency problem."

3. **A draft copy always saves.** `validate_page_document` only requires `offer_id`
   to be *present*, not to *exist*. Publishing is what loads the offer. So a page can
   be copied into the target env as a **draft** even when its offer isn't there yet;
   the missing-offer failure only surfaces if/when the tenant publishes in the target.

4. **`GET /offers/{offer_id}` exists** → usable for a pre-flight "does this page's
   offer exist in the target env?" check.

## The catalog dependency — and why Stripe does NOT block the cascade

A page is the top of a chain: **page → offer → products (with prices)**. An offer
references products via `items[].product_id` + `price_id`; a page references
`offer_id`. So a real copy must cascade the whole chain into the target env.

The worry was Stripe: test and live are separate Stripe environments, and Stripe
Product/Price objects are **immutable and per-mode** — you can't copy a Stripe price
across modes, you recreate it. **But our checkout never depends on a pre-created
Stripe price.** [checkout.py:214-231](../src/handlers/checkout.py#L214) shows: if a
price has a `stripe_price_id`, checkout uses it; if it **doesn't**, checkout builds
the charge **inline** from `price_data` — `unit_amount`, `currency`,
`recurring.interval/interval_count`, product `name`/`description` — all read straight
from the **product document**. Stripe mints the price on the fly, in whatever
env/account the request runs under.

Consequences:
1. **The full recreatable shape already lives on the product document**
   (`prices[].unit_amount`, `currency`, `pricing_model`, `recurring`, name, desc). It
   is env-agnostic. We do **not** need to embed it in the offer or the page JSON —
   and shouldn't, because that denormalization would go stale against the product.
2. **The cascade needs zero Stripe API calls.** Copying the product document to the
   target env, with the per-env Stripe references stripped, is enough — the target
   env's checkout will build `price_data` inline using the target's Stripe key.

So the cascade reduces to **document copying with two field transforms**:
- `stripe_mode`: flip `test` ↔ `live` to match the target env (products/offers carry
  a `stripe_mode` enum).
- Drop `stripe_price_id` / `stripe_product_id` (they are the *source* env's Stripe
  object ids; the target rebuilds inline). `default_price_id` (our internal id) stays.

This makes the cascade tractable enough to be **P1**, not a deferred phase.

### One caveat (advanced tenants)

A tenant who deliberately hand-linked a curated Stripe Price (`stripe_price_id` set)
loses that link in the target — the target falls back to an inline `price_data` built
from the stored amount. For the common case (platform-managed pricing via
`unit_amount`) this is invisible and correct. Advanced tenants re-link in the target
if they need a specific Stripe object. Acceptable.

## Pre-emptive robustness measure: checkout mode-guard

Independent of the copy flow, harden checkout against a **wrong-environment Stripe
id** (from a bad copy, a hand-entered id, or Stripe-dashboard tinkering — "in the
wrong environment"):

- The active Stripe key is mode-stamped (`sk_test_…` / `sk_live_…`); each
  product/offer document carries `stripe_mode`.
- At checkout, **only honor a stored `stripe_price_id` when the document's
  `stripe_mode` matches the active key's mode.** On mismatch, ignore the stale id and
  build the charge inline from `price_data` (`unit_amount`/`currency`/`recurring`) —
  always correct for the active env.
- Effect: a stray Test price id in Live (however it got there) can never mischarge or
  break checkout; it self-heals to the correct inline price. Log the mismatch for
  visibility.

This makes the platform resilient to environment mistakes at the point that matters
(the charge), not just at copy time. Small, targeted change in `checkout.py`; covered
by unit tests.

## Key decisions (need sign-off)

### D1. Target `page_id` — same id (sync) vs new id (fresh copy)

- **Option A — Same `page_id` (sync/update) [recommended].** "Copy to Live" writes
  the page to the *same* id in Live; copying again updates that same Live page. Clean
  mental model: Test is the draft of Live. Enables "fix in Test, push the fix to
  Live." Cost: overwrites the target page's content (including edits made directly in
  the target). We guard with a confirm that says whether a target page already exists.
- **Option B — New `page_id` each copy.** Every copy mints a fresh page in the
  target. No overwrite risk; but re-copying makes duplicates and there's no "update my
  Live version." 

### D2. Status the copy lands in

- **Recommended: land as a draft, but never *downgrade* an existing published
  target.** If the target page_id doesn't exist → create as **draft** (tenant reviews
  + publishes). If it exists and is **published** → update its content and **keep it
  published** (re-render), i.e. a true push-to-live. If it exists as a draft → stays a
  draft. This avoids the two bad outcomes: (a) silently publishing to Live on copy,
  and (b) silently unpublishing a Live page by copying a Test draft over it.
- Alternatives: always-draft (safe but unpublishes a live target on same-id copy), or
  mirror-source-status (copying a published Test page auto-publishes Live — too
  aggressive).

### D3. Site attachment does **not** carry

Sites are per-env; the copied page lands **unattached** in the target (badge shows
"No Site"). The tenant attaches it there via the Sites screen / the page's Attach
Site action. (With same-id sync, if a prior copy was already attached in the target,
that attachment naturally persists because it lives on the target Site's route map.)

## Design (P1 — cascade)

### Frontend

1. **`apiRequest` base-override.** Add an option `{ environment }` so a call targets
   the *other* env's API base (`API_BASES[test|live]`) with the same token/tenant_id.
2. **Row-menu action** on the Landing Pages card: "Copy to Live" / "Copy to Test"
   (label from `getApiEnvironment()`), near Duplicate.
3. **Flow `copyPageToEnvironment(page)`** — gather the chain, then copy bottom-up so
   references resolve:
   a. **Gather** from the *source* env: the page, its `offer_id`(s) (primary + any
      `catalog_grid` item offer ids), and each offer's `items[].product_id`.
      (`GET /offers/{id}`, `GET /products/{id}` as needed — most are already loaded.)
   b. **Pre-flight** the *target* env: for each of those ids, check existence
      (`GET`), to tell the tenant what will be **created** vs **overwritten**.
   c. **Confirm dialog:** target env; the counts ("1 page, 1 offer, 2 products");
      which already exist (overwrite per D1/D2); nothing blocking.
   d. **Copy bottom-up to the target base**, each with `stripe_mode` set to the target
      and `stripe_price_id`/`stripe_product_id` stripped:
      1. `POST /products` for each product (same id; D2 status rule).
      2. `POST /offers` for the offer(s) (same id; references now resolve).
      3. `POST /pages` for the page (same id; D2 status rule; unattached — D3).
   e. **Message:** "Copied '{name}' + its offer and 2 products to {Live}."

### Backend

**None.** Reuses existing `POST /products`, `POST /offers`, `POST /pages` and the
`GET` reads in the target env. Pure frontend orchestration over shared auth — the
same pattern as attach/detach/archive. (Verified: product/offer create handlers make
no Stripe API calls; Stripe pricing is realized at checkout from the document.)

## Phasing

- **P1 (this plan): cascade copy** — page + offer(s) + products, same-id sync,
  status-preserving (D2), `stripe_mode` flip + Stripe-id strip. Frontend-only.
- **P2 (future, optional):** carry a curated `stripe_price_id` across by *recreating*
  the Stripe Price in the target account via the Stripe API (only for advanced tenants
  who hand-link Stripe objects). Not needed for platform-managed pricing.

## Risks / edge cases

- **Overwrite (D1-A):** same-id copy clobbers a target page edited directly in the
  target. Mitigated by the confirm dialog naming the collision. Acceptable for a
  deliberate "push" action.
- **Token expiry mid-copy:** same failure mode as any request; surfaces as an error.
- **Analytics counters:** don't copy `analytics_summary`; the target page starts at
  zero (it's a different env's data).
- **Revision/timestamps:** bump `revision`, set target `created_at` if new else keep,
  set `updated_at` now.
- **Same-account assumption:** Test and Live are the same tenant/Cognito identity, so
  tenant scoping is identical across envs. (Not a cross-tenant copy.)

## Testing

- Unit (frontend logic if extracted): target-status resolution (new→draft;
  published target→stay published; draft target→draft); missing-offer detection.
- Manual: copy a profile page Test→Live (no offer dep) → appears as draft in Live,
  unattached. Copy an offer page whose offer is missing in Live → warned, lands as
  draft, publish in Live fails clearly until the offer exists. Re-copy (same id) →
  updates, doesn't duplicate.
