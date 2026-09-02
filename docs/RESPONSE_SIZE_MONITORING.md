# Watching for the response-size cliff

## What is being measured, and why bytes

`json_response` (src/stripe_link/common.py) is the single choke point every endpoint returns through, and
it already serializes the body — so measuring costs nothing and needed no handler changes.

Responses at or above **64KB** emit a CloudWatch **Embedded Metric Format** line. EMF turns a plain log
line into a metric with no metric filter, no subscription and no extra infrastructure.

    Namespace   JuniorBay/Api
    Metric      ResponseBytes (Bytes)
    Dimensions  FunctionName, Environment
    Property    PercentOfLimit — share of the 6MB Lambda proxy ceiling

**Bytes, not record counts.** Documents vary enough in size that a count-based threshold misleads: the
offer index measured 468 bytes on one offer, but an offer with many opportunities is larger. Bytes are also
the unit the actual limit is expressed in. A "warn at 13,000 offers" rule would be guessing at a conversion
that changes every time a document gains a field.

Below 64KB nothing is emitted. Every response would otherwise log, and a response that small cannot be
near the ceiling.

## The cliff

The 6MB Lambda proxy limit does not degrade — the request fails and the screen stops loading. So the
number to watch is not "are we close" but "are we trending".

| Payload | Bytes | % of limit |
|---|---|---|
| 1,000 offers, full documents | 2.8 MB | 47% |
| 2,000 offers, full documents | 5.8 MB | **97% — effectively broken** |
| 1,000 offers, `?view=index` | 0.45 MB | 8% |
| 2,000 products (same screen loads these too) | 5.9 MB | **99%** |

Note the last row: the Offers screen loads the full product catalog as well, and product documents are
LARGER than offers (~3.1KB vs ~2.9KB). Most tenants have more products than offers, so **the product
payload reaches the cliff first**. A product index is the higher-value twin of the offer one.

## Creating the alarm

Not created here, because the notification target is a decision (email, SNS topic, Slack). When you want
it:

    aws cloudwatch put-metric-alarm \
      --alarm-name jb-api-response-size-prod \
      --namespace JuniorBay/Api --metric-name ResponseBytes \
      --dimensions Name=Environment,Value=prod \
      --statistic Maximum --period 300 --evaluation-periods 1 \
      --threshold 3145728 \
      --comparison-operator GreaterThanThreshold \
      --alarm-actions <sns-topic-arn>

**3MB — half the ceiling — is the threshold to act on, not to panic at.** It leaves room to ship the index
adoption before anything breaks. Alarming at 5MB would be alarming after the decision point has passed.

To look at the trend before any alarm exists, the metric is already in CloudWatch:

    aws cloudwatch get-metric-statistics --namespace JuniorBay/Api \
      --metric-name ResponseBytes --dimensions Name=Environment,Value=prod \
      --start-time "$(date -u -v-7d +%Y-%m-%dT%H:%M:%SZ)" \
      --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --period 86400 --statistics Maximum

## What to do when it climbs

1. **Adopt the index in the dashboard** — `GET /offers?view=index`, resolving names from the already-loaded
   product store. Roughly a 10x reduction. Do the product equivalent at the same time.
2. **Virtualize the list rendering** — window the DOM. Note this is NOT infinite scroll: the index loads
   whole, which is what keeps client-side search complete. Paginating it would leave search covering only
   what has been fetched.
3. **Only past ~13k** does the index itself need paging — and at that point search has to move server-side
   too, which is the genuinely expensive change. See plans/OFFER_ITEM_VISIBILITY.md §7.
