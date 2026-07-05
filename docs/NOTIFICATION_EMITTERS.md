# Notification Emitters (Reference — mostly not yet built)

## Status

The **notification delivery mechanics are built and live** (as of this session):

- `Notification` documents in the `jb-notifications-*` table, with `type`, `severity`,
  `status` (`unread`/`read`/`archived`), `title`, `message`, `related`, `action`.
- `GET /notifications` (list) and `POST /notifications/mark-read` (mark all unread → read).
- The dashboard **Notifications** screen, and the top-bar **bell badge** that shows the
  unread count (capped at `99+`), clears on view, and polls every 60s.

What is **mostly missing is the emitters** — the code that actually *creates* a notification
when something important happens. Today only **one** emitter exists:

- `src/handlers/stripe_webhook.py` → `notification_record_from_session()` creates a
  `type: "order"` notification on `checkout.session.completed`.

Every other `Notification.type` value is supported by the schema and counted by the bell,
but nothing produces those notifications yet. This document lists the emitters to build so
the bell becomes meaningful for more than just new orders. Build these incrementally; each
is independent.

## How to emit a notification (the pattern)

An emitter just writes a `Notification` document via `notifications_repository()` (or,
inside the webhook, the already-wired `notifications_repo`). Use
`notification_record_from_session()` in `stripe_webhook.py` as the working template. The
shape:

```python
{
    "schema_version": "2026-05-29",
    "document_type": "notification",
    "tenant_id": tenant_id,
    "notification_id": f"notif_{unique_source_id}",   # stable per source event → idempotent
    "type": "refund_request",                          # one of the enum values below
    "severity": "warning",                             # info | success | warning | error
    "title": "Refund requested",
    "message": "Ada Buyer requested a refund for Demo Product.",
    "status": "unread",
    "sort_priority": 100,                              # higher = more urgent, surfaces first
    "related": {"order_id": ..., "customer_id": ..., "refund_request_id": ...},
    "action": {"label": "Review refund", "route": "notifications"},
    "created_at": now,
    "read_at": None,
    "archived_at": None,
}
```

Design principles for every emitter:

- **Idempotent:** derive `notification_id` deterministically from the source event
  (session id, refund request id, etc.) so retries/duplicate webhook deliveries overwrite
  rather than duplicate. This mirrors the idempotency approach already used for one-click
  upsell PaymentIntents and the funnel-action design.
- **Best-effort, never block the primary action:** emit inside a try/except and swallow
  failures, exactly as `stripe_webhook.py` treats order/invoice/customer/notification
  writes as independent side effects. A failed notification must never fail a payment, a
  refund, or a key save.
- **Right `type` and `severity`:** `error` severity for failures (key/shipping/connect),
  `warning` for things needing a decision (refunds), `success`/`info` for FYIs.
- **Populate `related` and `action`** so the Notifications UI can deep-link. `action.route`
  is a dashboard view key (e.g. `orders`, `shipping`, `stripeKeys`).

## Emitters to build

| # | `type` | Trigger / where to add | Example title | Severity |
|---|--------|------------------------|---------------|----------|
| 1 | `refund_request` | When a refund is requested — `save_refund_request()` in `handlers/notifications.py` (and/or a Stripe `charge.refund*` / `charge.dispute.created` webhook branch in `stripe_webhook.py`). Currently `save_refund_request` only stores the `refund_request` doc; it should also emit a notification. | "Refund requested: {reason}" | `warning` |
| 2 | `stripe_connect` | Stripe Connect onboarding/status changes — `handlers/stripe_connect.py` callback, or a Connect `account.updated` webhook branch. Emit on failure/restricted (`error`/`warning`) and on successful connection (`success`). | "Stripe Connect account restricted" | `warning`/`error` |
| 3 | `system` (Stripe key failure) | When tenant Stripe key verification fails (`handlers/stripe_keys.py` `verify_keys`), or when webhook signature verification fails for a tenant repeatedly (`stripe_webhook.py`). | "Stripe key verification failed" | `error` |
| 4 | `shipping` | Shipping-integration failures — a future shipping **"test connection"** action and/or label-purchase/rate-fetch failures once the shipping provider integration is built. Pairs with the deferred shipping connection flow noted in the Shipping screen. | "Shipping provider connection failed" | `error` |
| 5 | `paid_invoice` | Paid-invoice notifications — a Stripe `invoice.paid` webhook branch in `stripe_webhook.py` (distinct from the one-time `order` notification), for subscription/renewal invoices. | "Invoice paid" | `success` |
| 6 | `system` ("asks for help" / support) | A customer support / help-request flow — **no support system exists yet**, so this needs that feature first. When built, emit a `system` (or a new `support` type) notification on a new help request. | "New support request" | `info` |

Notes:

- `paid_invoice`, `order`, and `refund_request` are the closest to done: the checkout
  webhook already builds order + invoice + customer records, so adding refund and
  paid-invoice notifications is mostly a matter of adding webhook branches / wiring the
  refund save, reusing `notification_record_from_session()` as a template.
- Items 4 and 6 depend on other unbuilt features (shipping provider integration; a support
  system), so they come after those.
- The bell/badge/mark-read plumbing needs **no changes** for any of these — an emitter only
  has to write an `unread` notification and the bell reflects it automatically.
