# Junior Bay as an MCP server

**Status: NOT BUILT. LOW priority — see `plans/TODO.md`.** Written 2026-10-09 from an engineering
question, not a commitment.

Expose Junior Bay's capabilities as [Model Context Protocol](https://modelcontextprotocol.io) tools, so a
tenant can operate their store from Claude (or any MCP client) conversationally: *"what sold last week",
*"build me a landing page for this product"*, *"why did that order not go through"*.

## Why this fits, when most AI-commerce features do not

**The schemas are the whole advantage.** 34 JSON schemas and a JSON-first architecture throughout. An LLM
emitting schema-valid JSON into an API that validates it is a fundamentally more reliable arrangement than
one driving a UI or generating HTML — the failure mode is a rejected document, not a page that renders
wrong in a way nobody notices until a buyer complains.

`plans/AI_AND_COMMERCE_ARCHITECTURE.md` already locks "AI page-gen emits schema-valid JSON not HTML".
**MCP is the delivery surface for something already designed**, not a new direction.

**It does not touch the transform limit.** The server is a separate deployment calling the existing 222
routes over HTTPS. No API Gateway resources, no CloudFormation ceiling, no interaction with the thing that
currently blocks every other integration (`plans/SHIPPING_BEYOND_THE_FIRST_SALE.md`, the 1,000,000-byte
SAM transform).

**The auth primitive exists.** Cognito is deployed (`cognito-stack`, `cognito-prod`) and lives outside
this stack. AutoDS's own MCP server uses exactly this shape — OAuth 2.0 against Cognito, JWT validated
against JWKS, a `client_id` allowlist — so the pattern is proven by someone else's production.

## The hard prerequisite: finish Phase 2 of API authentication

`plans/API_AUTHENTICATION.md` is further along than it looks. Phase 1 (classify and measure) shipped
2026-09-25; the refresh path and authoritative tenant resolution are built. That plan's own words:

> **What remains for Phase 2 is now only the authorizer itself.**

Until it lands, the API is in observe mode — every request logs `"enforced": false, "authoritative":
false`, and a caller who knows a `tenant_id` is that tenant.

**An MCP server is an authentication product.** The entire proposition is "let a third party act on a
tenant's behalf, safely". It cannot ship on an unenforced API, and no amount of care in the MCP layer
compensates, because the REST API remains reachable directly.

This is not a reason to defer the idea — it is a reason the idea is useful. It gives Phase 2 a concrete
consumer, and Phase 2 is worth doing on its own merits regardless.

## Phasing

### P1 — read-only

The tools that cannot hurt anyone: what sold, which orders, what is published, which pages exist, why an
order looks wrong. These are the questions a tenant actually asks, and today they answer them by clicking
through the dashboard or by asking the operator to read CloudWatch.

Read-only also lets the tool surface be designed before anything is at stake.

### P2 — writes that produce DRAFTS

Create a product, compose an offer, lay out a landing page — all as **unpublished** documents a human then
reviews and publishes in the builder. The agent proposes; the tenant disposes.

This is the sweet spot: the laborious part of the work is the JSON, which a model is good at and a person
is not, while the irreversible part stays human.

### P3 — publishing, and nothing beyond

Possibly publish-with-confirmation. **Explicitly out of scope, probably forever: anything that moves
money.** No refunds, no price changes on a live offer, no checkout mutation. The reasoning is in the
incident log of 2026-10-07/08 — a republish is what fixed the funnel and a misfired one is what served a
buyer the wrong page. An agent with a refund button is a liability, not a feature.

## Design notes

**222 routes is not 222 tools.** A good MCP server exposes perhaps 15 well-named intents that each compose
several calls — "publish a landing page for this product" rather than `POST /products`, `POST /offers`,
`POST /pages`, `POST /pages/{id}/publish`. A 1:1 mapping produces something an agent uses badly and a
person cannot reason about.

**The route classification is already the authorisation model.** `api_auth.py` holds PUBLIC/PRIVATE per
`(method, path)` and fails closed on anything unclassified. An MCP tool surface should be derived from
that table rather than maintained beside it — two lists of what is safe will disagree, and the day they
disagree is the day something public becomes writable.

**Scope tokens per tenant, not per user.** A tenant may have several operators; the token must name the
tenant whose data is in play, and `authoritative` resolution (built 2026-09-29) is what makes that
trustworthy.

## What would make this worth doing

Not "AI builds your store" — Shopify and AutoDS both ship that and it is crowded. The differentiator is
narrower and more defensible: **the output is schema-validated JSON in a system that renders it properly**,
rather than a model guessing at markup. That is only true because of decisions already made here.

If that is not the pitch, this is a feature nobody needs.

## Related

- `plans/API_AUTHENTICATION.md` — the prerequisite; Phase 2 is the authorizer
- `plans/AI_AND_COMMERCE_ARCHITECTURE.md` — the JSON-first AI generation this would deliver
- `plans/CONFIDENCE_WITHOUT_LIVE_MONEY.md` — why write tools get a draft stage
