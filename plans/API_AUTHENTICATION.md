# The API never verifies who is calling

**Status: PHASE 1 BUILT 2026-09-25. Re-measured 2026-09-28: the stated precondition is MET, but the
measurement found a prerequisite nobody had written down — see "What the measurement actually says".**

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

## What the measurement actually says (re-read 2026-09-28)

Three days of real traffic, aggregated over every Lambda log group in both silos. The first read (2026-09-25)
had 20 samples and was too thin to conclude anything; this one has **1,546**.

| verdict | dev | prod |
|---|---|---|
| `would_allow` | 1,340 | 185 |
| `no_token` | 11 | 10 |
| `unreadable_token` | 0 | 0 |
| **`tenant_mismatch`** | **0** | **0** |

**`tenant_mismatch` is zero, which is the precondition this plan set.** No attack signal, and — just as
important — no legitimate admin tool that legitimately crosses tenants and would have to be accommodated.

**The `no_token` records are the finding.** They are NOT misclassified public routes, and that was the
possibility this measurement existed to rule out. Nine of prod's ten arrive inside **3.7 seconds** —
00:49:50.449 to 00:49:53.475 — across eight different dashboard screens: `/platform-billing/plans`,
`/customers`, `/notifications` ×2, `/invoices`, `/billing/connect-card` ×2, `/stripe/keys` ×2. That shape is
one dashboard page load, not a probe. Dev's eleven are `/ai/*` and `/orders` calls from CLI testing during
the AI work, which are mine and uninteresting.

### The prerequisite: the dashboard treats the token as optional

`dashboard/src/api/client.js:221` attaches the header conditionally:

```js
...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}),
```

and `getTenantId()` (`client.js:168`) falls back **past** the session:

```js
getAuthSession()?.tenant_id || getAuthSession()?.client_id
  || localStorage.getItem(TENANT_ID_STORAGE_KEY) || DEFAULT_TENANT_ID   // "tenant_demo"
```

The two halves live in different stores: the session in **sessionStorage** (per-tab, dies with the tab), the
tenant id in **localStorage** (persists). So reopening the dashboard in a fresh tab produces exactly the burst
above — tenant-scoped GETs carrying a tenant id and no token. Today they answer **200**. The moment the
authorizer lands they answer **401, on every screen**, and the app has no path back except a manual login.

Two things follow, and they are separable:

1. **A client that cannot name its caller must not issue a private request.** It should route to login rather
   than send a tenant-scoped call unauthenticated. `DEFAULT_TENANT_ID = "tenant_demo"` makes this sharper than
   "unauthenticated": a session-less dashboard doesn't merely omit identity, it *claims a specific tenant id*.
2. **Fixing (1) exposes a UX question the hole is currently masking.** Because the session is per-tab, every
   new tab genuinely has no token — and only the missing authorizer is what makes that invisible today. So
   enforcing without deciding where the session lives turns "open a new tab" into "log in again". That is a
   decision about session lifetime (localStorage, or a refresh-token flow), not a detail to be picked while
   wiring an authorizer.

**Ordering, and it is the same shape as the artifact-boundary item: the client fix ships BEFORE the
authorizer.** Reversed, the dashboard 401s in production.

**FIXED 2026-09-28 (undeployed):** the session moved to `localStorage` with a one-time migration from
`sessionStorage`, so a reopened tab keeps its token instead of keeping only its tenant id; and `apiRequest`
now fails **closed** — no `access_token` means no request, with `anonymous: true` as the explicit opt-in for
the five `/auth/*` calls that legitimately precede a session. The client deliberately does NOT keep its own
copy of the public-route list; that would drift from `api_auth.py`.

### `would_allow` does not mean the token would pass — the refresh gap

**A correction to the table above, found while fixing the client.** The shadow logger decodes claims
**without verifying the signature and without checking expiry** — by design, since it is a measurement. So
`would_allow` counts an EXPIRED token as fine, and the real authorizer will not.

That matters because nothing refreshes. `handlers/auth.py:295-296` returns `refresh_token` and `expires_in`
in the session payload, and **neither value is read anywhere** — no dashboard code touches them, and there is
no `/auth/refresh` route (no `REFRESH_TOKEN_AUTH` in `auth.py`). A Cognito access token lasts an hour by
default. So once the authorizer lands, an open dashboard starts 401ing about an hour into every session,
wherever the session is stored.

**Moving the session to localStorage makes this MORE visible, not less** — that was the right call for the
token-less-tab bug, and its direct consequence is that sessions now survive long enough to reach expiry
rather than dying with the tab. The two fixes are a pair.

**So a refresh path is a hard prerequisite for Phase 2, not a Phase 3 nicety.** Until it exists,
`would_allow = 1,340` should be read as "1,340 requests carried a token-shaped thing", which is a weaker claim
than it looks.

**BUILT 2026-09-28 (undeployed).** Verified against the live pool first: the app client already allows
`ALLOW_REFRESH_TOKEN_AUTH`, refresh tokens last 30 days, and `AccessTokenValidity` is unset — confirming the
60-minute default the problem rests on.

- `POST /auth/refresh` (`handlers/auth.refresh_session`) exchanges the refresh token via `REFRESH_TOKEN_AUTH`.
  Public by necessity and listed as such in `api_auth.py`: the refresh token IS the credential, and an expired
  access token cannot renew itself. No new IAM — `initiate_auth` is one of Cognito's unauthenticated APIs,
  which is why login already works with only the `Admin*` grants.
- The response carries **only tokens**. The caller does not get to say who it is and no user is looked up on
  its word; identity comes from the minted token, which is the thing an authorizer verifies.
- A refresh Cognito refuses answers **401**, not the generic 400, because the client's only correct reaction is
  to drop the session and show login. A 200 carrying a challenge instead of a token is also a re-login — a
  silent refresh cannot satisfy MFA enrolment.
- The refresh token is **echoed back when Cognito omits it**. It only returns a new one when rotation is
  enabled on the app client, and passing the absent value through would blank the caller's only means of ever
  refreshing again — a session that dies an hour later for no visible reason.

Client side (`dashboard/src/api/client.js`):

- `setAuthSession` stamps an absolute `expires_at`. The backend sends `expires_in`, a DURATION, which is
  useless to a page reloaded hours later — that is precisely why nothing could tell a fresh token from a dead
  one.
- Renewal is **proactive**, two minutes before expiry, because the reactive path cannot fire yet: nothing
  answers 401 today. A single-flight guard means a screen firing six requests mints one token, not six — which
  also matters if rotation is ever enabled, since the later refreshes would race against a spent token.
- A 401 still triggers **exactly one** retry, for a token rejected while our clock says it is fine (revoked
  session, skewed clock, pool-side signing change). A second 401 after a fresh token is a real refusal, and
  looping would hammer the API with an unusable credential.
- Ending a session now **notifies the app** (`jb:session-ended` → `auth.sessionEnded()`). Clearing storage
  alone was not enough: the store keeps its own copy of the session, which is what `App.vue` gates on, so a
  silent wipe left the dashboard rendered and authenticated-looking while every screen failed.

**What remains for Phase 2 is now only the authorizer itself** — the Cognito authorizer with
`DefaultAuthorizer`, `Auth: Authorizer: NONE` on the public routes, and `tenant_id_from_event` reading
`requestContext.authorizer.claims` for private ones.

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
