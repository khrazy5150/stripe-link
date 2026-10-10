# The stack is 99.4% of the way to CloudFormation's ceiling

**Status: NOT BUILT. Measured 2026-10-09.** Supersedes the guesses in
`plans/SHIPPING_BEYOND_THE_FIRST_SALE.md` ("derived table names ~146KB, collapsed IAM ~100KB"), which
were estimates. These are measurements.

## The number

```
TRANSFORMED template   993,953 bytes
limit                1,000,000 bytes
headroom                 6,047 bytes   (99.4% used)
```

Read it from the deployed stack, not from `template.yaml`:

```
aws cloudformation get-template --stack-name jb-stripe-link-stack-dev --template-stage Processed
```

The source template is 218KB. **The transform is 4.5× that**, which is why reading the source tells you
nothing about the budget and why every estimate before this one was wrong.

A new route was refused on 2026-10-05. One was accepted on 2026-10-09 (`POST /orders/{order_id}/refund`),
because the webhook IAM consolidation and the dropped `OrdersTable.CreatedAtIndex` bought room in
between. **Roughly one more route fits. Not two.**

## Where the bytes are

| resource | count | bytes | share |
|---|---|---|---|
| `Lambda::Function` | 74 | 415,478 | **42%** |
| `IAM::Role` | 74 | 206,162 | 21% |
| `ApiGateway::RestApi` | 1 | 202,238 | 20% |
| `Lambda::Permission` | 219 | 77,481 | 8% |
| `DynamoDB::Table` | 46 | 31,476 | **3%** |

### Tables are not the problem, and never were

**All 46 tables are 3% of the template.** Deleting every one would buy 31KB — a fifth of what a single
real fix buys — and they are all read by live code. The phrase "slim table names" in the older plan
invited the wrong conclusion twice; deleting tables from AWS buys *nothing at all*, since the limit is on
template text.

### Dead functions are not the problem either

14 of 72 functions had zero invocations in 30 days. But they are `registration-api`, `booking-api`,
`custom-domains-api`, `reviews-public`, `support-contact`, `routes-resolve` and similar — **features
nobody has used yet on a pre-launch stack**, plus `delete-test-data`, which is dev-only by design.
Deleting them means deleting the product. At ~9KB each (function + role + permissions), even the
genuinely droppable ones total 20–30KB.

## The actual problem: 84 environment variables on every function

```
Globals:
  Function:
    Environment:
      Variables:      # 84 of them
```

Every one of the 74 functions carries all 84 — **4,887 bytes each, 362,538 bytes in total, 36% of the
entire template.** `jb-support-contact` is carrying the names of all 46 tables and every config value it
will never read.

What the 84 are: 42 table names, 20 other config, 10 urls/hosts, 7 secrets/arns, 5 buckets. ~58 bytes each.

### What each function actually needs

Measured by following the repository factories each handler calls, transitively through the domain
modules it imports:

```
TABLE env vars per handler — median 2, max 22 (stripe_webhook), min 0
heaviest: stripe_webhook 22, page_publish 14, checkout 12, ai_generate 10
```

Assuming ~40% of the non-table config is also needed, that is **~22 variables per function instead of 84**:

```
estimated saving   ~267,000 bytes  (27% of the template)
template becomes   ~727,000 bytes
headroom becomes   ~273,000 bytes   (from 6,047)
```

**Two earlier estimates in this analysis were wrong and are recorded so nobody repeats them:** counting
only `os.environ.get` calls in the handler file gives a median of 1 and wildly overstates the win, because
handlers reach env vars through imports. Counting every factory *named* in an imported module gives a
median of 39 and understates it, because `documents.py` DEFINES all 53 factories — importing it is not
calling them. The defining module has to be excluded from the walk.

## Why this is tractable

**The analysis already exists.** `tests/test_table_grants.py` computes which handler reaches which table,
transitively through domain modules and repository factories, and fails the build when a grant is
missing. It found exactly what `OrdersFunction` needed within minutes of the refund route being added.
The same walk generates the per-function env list, and the same test shape guards it.

**It is incremental.** One function at a time; every deploy strictly smaller; the suite green throughout.
No big-bang, and it can stop at any point having banked the savings so far.

**The order is obvious.** The heaviest functions are also the ones whose needs are best understood:
`stripe_webhook`, `page_publish`, `checkout`, `ai_generate`. Converting the ten largest first should bank
over 100KB.

## The risk, stated plainly

**A missing env var is a RUNTIME failure, not a deploy failure.** A function that loses
`PUBLIC_CHECKOUT_BASE_URL` deploys perfectly and breaks the first buyer who reaches it.

This is the same class of defect as everything found on 2026-10-07/08, and the mitigation is the same:
extend `test_table_grants.py` to env vars BEFORE converting anything, so the guard exists before the
change it guards. A conversion that outruns its test is how this becomes an outage.

Non-table config (`PUBLIC_CHECKOUT_BASE_URL`, `PAGES_DISTRIBUTION_DOMAIN`, the Stripe client ids) needs
the same treatment and is harder to attribute statically — it is read by name deep in domain modules. The
honest approach for those is to keep them in `Globals` at first and convert only the 42 table names,
which alone is the bulk of the win.

## Phasing

1. **Extend the grant test to env vars.** No template change. The test must be able to say, for every
   function, the exact set it reaches — and fail when the template gives it fewer.
2. **Move the 42 table names out of `Globals`**, per function, heaviest first. Measure the transformed
   size after each deploy; stop early if the numbers disappoint.
3. **Reassess.** If step 2 lands near its estimate, the ceiling stops being a design constraint and the
   remaining items (non-table config, the 219 permissions, the 202KB RestApi body) can wait.

## What this unblocks

Every integration currently queued behind "no new routes": the CJ Dropshipping webhook
(`plans/TEXTABLE_VOUCHER.md` has no such need, but `plans/MCP_SERVER.md` and any supplier callback do),
`/shipping/bump-postage` as a real endpoint rather than a body key on `rate-preview`, and the next
twenty features that each want one route.
