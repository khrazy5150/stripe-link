# The API never verifies who is calling

**Status: PHASE 1 BUILT 2026-09-25 (measurement only, nothing enforced).**

`tenant_id` is read from the request — body, `?tenant_id=`, `X-Tenant-Id`, `X-Client-Id` — and nothing
checks the caller. The dashboard sends `Authorization: Bearer <access_token>` on every request and **no
code in `src/` reads it.** Anyone who knows or guesses a tenant_id can act as that tenant.

The TODO entry this came from closed the one question that could have made it a false alarm: there is no
WAF, no CloudFront in front of the regional API, and the same unauthenticated request answers identically
on the execute-api URL and on `dev.juniorbay.com`. Nothing sits between the browser and the Lambda.

## What makes this hard is not the authorizer

Attaching a Cognito authorizer is a few lines. The hard part is knowing **which routes must keep working
without a token**, because both directions of error are expensive:

| mistake | consequence |
|---|---|
| a route wrongly **private** | buyers stop being able to check out, the moment enforcement lands |
| a route wrongly **public** | the hole stays open and looks closed |

There are **202 routes across 152 paths and 63 handler modules**. Fifty-eight of them are genuinely
public: Stripe's webhooks (signature-authenticated, not token-authenticated), the whole buyer purchase
flow from a published page, buyer self-service by opaque link (there are deliberately no buyer accounts),
published-page serving and resolution, public lead and review and abuse-report submission, and the OAuth
callbacks a provider redirects a browser into.

The boundary is **per method, not per path**. `POST /leads` is a stranger filling in a form; `GET /leads`
returns those strangers' email addresses. Same path, opposite answers. A test derives the set of mixed
paths from the table and asserts it is documented, so a path that becomes mixed cannot do so quietly.

## Why Python cannot verify the token itself

`src/requirements.txt` is deliberately empty — stdlib only, Stripe over `urllib`. There is no crypto
library to check an RS256 signature with, and hand-rolling RSA verification to guard every endpoint in the
product is the wrong place to be clever. **API Gateway's Cognito authorizer verifies the signature before
the Lambda runs**, and the Lambda reads `requestContext.authorizer.claims`, which it can trust precisely
because something upstream already checked it.

## Phases

### Phase 1 — classify and measure. BUILT 2026-09-25.

`stripe_link/api_auth.py` holds the boundary as data, failing **closed**: anything not named public is
private, so an endpoint nobody classified is protected by default rather than reachable by everybody.

An authorizer cannot be shadowed — it refuses before the Lambda runs — so the gap is measured from inside.
`tenant_id_from_event` is the funnel every handler already passes through, and it now emits one
`api_auth` line per private request:

```
{"api_auth": {"phase": "A1", "verdict": "tenant_mismatch", "method": "GET",
              "resource": "/orders", "claimed_tenant": "victim",
              "token_tenant": "attacker", "enforced": false}}
```

Four verdicts, and they are different problems:

- `would_allow` — a token whose identity matches the tenant asked for. What should happen.
- `no_token` — the caller sent none. Either a legitimate public caller misclassified here, or exactly the
  hole.
- `unreadable_token` — a token that decodes to no identity.
- `tenant_mismatch` — the token says one tenant, the request asks for another. **This is the attack, and
  also what a legitimate admin tool would look like.** It must be zero before enforcement.

The claims it reads are decoded **without checking the signature**. That is a measurement and never a
control — anyone can mint one, which is the whole reason verifying exists. Nothing in the logger can
raise; a handler must not fail because a measurement did.

### Phase 2 — enforce, once the logs are quiet

- A `Cognito` authorizer on the RestApi with `DefaultAuthorizer` set, and `Auth: Authorizer: NONE` on each
  of the 58 public routes. This costs no CloudFormation resources (it is method properties, not new
  resources), which matters — the stack was at the 500-resource ceiling this week.
- `tenant_id_from_event` takes the tenant from `requestContext.authorizer.claims` and **ignores the
  request** for private routes. `caller_tenant()` already reads `custom:client_id` with `sub` as the
  fallback.
- Public routes keep taking it from the request, because there is nobody to ask.

### Phase 3 — the residue

- **`sub` is the tenant only because every user is an owner today** (6 of 6 profiles in dev and prod have
  `user_id == tenant_id`, measured 2026-09-25). That is a property of the data, not of the schema. A real
  user→tenant lookup replaces `caller_tenant()`'s fallback the day a tenant has a second user.
- **Buyer-facing "public" routes are not unauthenticated, they are differently authenticated** — an
  opaque token in a link, a Stripe signature, a cart id. Those checks live in the handlers and are out of
  scope here; what this plan guarantees is that no route reaches a tenant's data on the strength of a
  guessed id alone.

## What Phase 1 deliberately does not do

It does not refuse anything. A boundary that starts refusing on its first day refuses the routes it got
wrong, and the routes it got wrong are the ones nobody tested — which in this codebase means a buyer
halfway through a checkout.
