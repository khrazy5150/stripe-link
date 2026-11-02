# Junior Bay as an MCP server

**Status: NOT BUILT. LOW priority — see `plans/TODO.md`.** Written 2026-10-09 from an engineering
question, not a commitment. **Updated 2026-11-01**: the prerequisite below has SHIPPED, and the commercial
case changed — see the two sections at the end.

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

## The hard prerequisite: finish Phase 2 of API authentication — **DONE 2026-10-11**

> Verified 2026-11-01: a private route with no token returns **401 on both dev and prod**
> (`GET /products?tenant_id=…`). The authorizer is enforcing, so "a caller who knows a `tenant_id` is
> that tenant" is no longer true and the blocker this section describes is cleared. The rest of the
> section is kept as the record of why it blocked.


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


---

## Why this got more interesting (2026-11-01)

The original case was architectural: schemas make an LLM a reliable client. That still holds. What changed
is a **commercial** argument nobody had made, and it is the stronger one.

### A subscription is not an API key

`ai_byok.py` already lets a tenant supply their own Anthropic or OpenAI key and be billed directly — so
"not our tokens" is a solved shape for anyone holding an **API key**.

It cannot be solved for anyone holding a **subscription**. Claude Pro and ChatGPT Plus are separate
products from their vendors' APIs, with separate billing and no key to paste into BYOK. A subscriber who
wants to use what they already pay for would have to open a second, separately-billed API account.

**MCP is the only mechanism that reaches them**, because the inference happens inside the client their
subscription already pays for. Junior Bay supplies tools; the model is theirs. That population is not
reachable by any other door, and it is growing.

Treat it as a **distribution play rather than a cost play**: "start a store from inside Claude" is a reason
to choose this platform over Shopify for a specific kind of user. The inference saving is a bonus, and a
smaller one than it looks — see the next point.

### Three doors, split by who is driving

MCP does not replace Bedrock or BYOK. The three serve different *drivers*, and the split is not about how
fine-grained the work is:

| Door | Driver | Fits |
|---|---|---|
| **Builder** | tenant, direct manipulation, live preview | visual nudging, layout, picking images |
| **MCP** | tenant delegating — says *what*, not *how* | setup, bulk content, "a lead page for X", data questions |
| **Bedrock / BYOK** | the platform itself, no human present | publish-time copy, SEO titles, alt text, analysis |

**The third row can never move to MCP.** Publish-time SEO, description enrichment, localized alt text and
the default landing copy fire when a page publishes, possibly at 3am, with nobody in a chat window. MCP has
no session to run in. That is structural and no tool design fixes it — so the Bedrock bill does not go away,
it shrinks by whatever share of tokens is interactive authoring.

The *soft* limit is the feedback loop: "move that section up" is awkward in chat because the tenant cannot
see the result, not because the tool cannot do it. MCP can return images, so a mutation that returns a
rendered preview closes much of that gap. Design around it rather than treating it as a wall.

## The implementation rule: a thin adapter, not a second code path

The design notes above already say the TOOL SURFACE should derive from `api_auth.py` rather than be
maintained beside it. The same rule has to hold one layer down, for the **implementation**.

The temptation is to give MCP its own handlers that build offers and pages directly. Do that and there are
two implementations of "create a lead page", and they drift: a goal pack ships to the dashboard and not to
MCP, or validation tightens on one side only, and the two doors quietly disagree about what a valid offer
is. That is the duplicate-source fault this repo keeps paying for — it appeared three separate times on
2026-11-01 alone (`build()` substituting a field a caller forgot, a status map that nearly got a second
copy, a shipment lookup whose test fake encoded the bug's assumption rather than the table's shape).

So: **the MCP server calls the same domain layer the dashboard calls.** Tool definitions are a new
vocabulary for describing intent; everything underneath stays one implementation. That is also what
protects the differentiator — composition rules, goal packs, the offer model and publish-time SEO live in
the spine, so the platform's opinion travels through whichever door someone came in.

### What that costs, measured

A plausible v1 surface is offers, products, pages, config and collections — **1,270 lines of handler code
with 48 `event` call sites**, not the 26,237 lines across all 75 handler modules. The rest is webhooks,
shipping and reconciliation, which an MCP server does not need.

The shape is already close. `create_offer` is representative:

```python
def create_offer(event, repository, products_repo=None, mode="test", ...):
    document = parse_json_body(event)     # the only use of `event`
    ...orchestration over `document` + injected repos...
    return json_response(...)
```

Repos are already dependency-injected across these modules, which is why they are unit-testable with no
AWS and no mocking framework. The extraction is therefore mechanical: lift `tenant_id`, `mode` and the body
into parameters, leave a thin event wrapper.

```python
def save_offer(document, *, tenant_id, mode, repository, ...): ...   # the spine
def create_offer(event, repository, ...):                            # wrapper
    return json_response(save_offer(parse_json_body(event), ...))
```

**`offers.py` first** — at 533 lines it holds the most orchestration (semantic analysis, naming, slug
derivation) and is the one most likely to hold a surprise. If it extracts cleanly the other four will.

This is worth doing **whether or not MCP ships**: handler logic becomes testable without synthesising API
Gateway events.

### Sequencing: defer OAuth until demand is proven

The tools are the easy part; **auth is the whole cost**. Remote MCP is OAuth 2.1 with dynamic client
registration, and DCR is where this gets unpleasant even with Cognito already deployed.

So do the spine extraction and a **local** MCP server first — one the tenant runs, authenticating with an
existing Junior Bay token. No OAuth, no new infrastructure, a week or two of real work. It answers the only
question that matters: do tenants use it? If yes, pay for the hosted OAuth version knowing the demand is
real. If no, the spine extraction was worth having anyway.
