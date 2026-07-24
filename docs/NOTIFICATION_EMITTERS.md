# Notification Emitters

## Status (corrected 2026-07-23)

The **notification delivery mechanics are built and live**:

- `Notification` documents in the `jb-notifications-*` table, with `type`, `severity`,
  `status` (`unread`/`read`/`archived`), `title`, `message`, `related`, `action`.
- `GET /notifications` (list) and `POST /notifications/mark-read` (mark all unread → read).
- The dashboard **Notifications** screen, and the top-bar **bell badge** that shows the
  unread count (capped at `99+`), clears on view, and polls every 60s.

An *emitter* is the small piece of code that **creates** a notification when something
happens. Contrary to the earlier version of this doc, **several emitters already exist**:

| `type` | Fires on | Where |
|--------|----------|-------|
| `order` | a completed checkout (a **sale**) | `stripe_webhook.notification_record_from_session()`, plus upsell / booking / appointment paths |
| `paid_invoice` | `invoice.paid` (subscription/renewal) | `stripe_webhook.invoice_paid_notification()` (wired) |
| `lead` | a lead capture | `leads._emit_lead_notification()` (wired) |

So the **sale, lead, and paid-invoice notifications are done.** The genuinely-missing emitter
is **`refund_request`**.

## Priorities (2026-07-23)

**Tier 1 — build now:**
1. **`refund_request` emitter** (NEW). `save_refund_request()` in `handlers/notifications.py`
   currently only stores the refund-request doc; it must also write a `warning` notification so
   the tenant is alerted. (Also consider a Stripe `charge.dispute.created` webhook branch later.)
2. **"Sale" polish** (COPY, not a new emitter). The `order` notification already fires on every
   sale; make it *read* like one — title "New sale" (💰) and keep `type: "order"` so the bell
   filters and the Notifications screen keep working. No new type (avoids breaking existing
   filters / `related.action.route`).

**Tier 2 — already done:** `lead` and `paid_invoice` emit today. No work; listed so they aren't
re-scoped. (Optional later: friendlier copy, same as the sale polish.)

**Tier 3 — Toast notifications (SHIPPED dev+prod 2026-07-23).** Transient toast pop-ups in the
dashboard for critical events, so the tenant sees them immediately without opening the bell:
   - **Sale** (🎉, auto-dismiss, click → Orders) — from a new `order` notification
   - **Refund request** (sticky, click → Refunds) — from a new `refund_request` notification
   - **Set up Stripe** (sticky, click → Stripe keys) — one-time nudge when the active env has neither
     saved keys nor a connected account

   Implementation: `stores/toasts.js` (push/dismiss, `key` de-dupe) + `components/ToastHost.vue`
   (fixed top-right stack, auto-dismiss non-sticky after ~6.5s, theme-aware). `App.vue` diffs
   *newly-arrived* unread notifications of the toast types against a per-context baseline (the
   existing backlog and env/tenant switches never re-toast), so **no backend change was needed** for
   sale/refund toasts. The "Set up Stripe" toast is driven by `stripeKeys` connection state (loaded
   once on mount), not a `Notification`. To add another toast type, extend `TOAST_TYPES` in `App.vue`.

**Later — blocked on other features (not now):**
- **`stripe_connect`** — Connect onboarding/status-change notifications (account restricted /
  connected). Pairs with the Stripe setup work.
- **`system` (Stripe key verification failure)** — emit when a tenant's key verification fails.
- **`shipping`** — needs the shipping-provider integration first.
- **`system` / support** — needs a customer-support/help-request system first.

## How to emit a notification (the pattern)

An emitter writes a `Notification` document via `notifications_repository()` (or, inside the
webhook, the already-wired `notifications_repo`). Use `notification_record_from_session()` in
`stripe_webhook.py` as the working template. The shape:

```python
{
    "schema_version": "2026-05-29",
    "document_type": "notification",
    "tenant_id": tenant_id,
    "notification_id": f"notif_{unique_source_id}",   # stable per source event → idempotent
    "type": "refund_request",                          # one of the enum values
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

- **Idempotent:** derive `notification_id` deterministically from the source event (refund
  request id, session id, etc.) so retries/duplicate deliveries overwrite rather than duplicate.
- **Best-effort, never block the primary action:** emit inside a try/except and swallow failures,
  exactly as `stripe_webhook.py` treats order/invoice/customer writes as independent side effects.
  A failed notification must never fail a payment, a refund, or a key save.
- **Right `type` and `severity`:** `error` for failures (key/shipping/connect), `warning` for
  things needing a decision (refunds), `success`/`info` for FYIs.
- **Populate `related` and `action`** so the Notifications UI can deep-link. `action.route` is a
  dashboard view key (e.g. `orders`, `shipping`, `stripeKeys`).
- The bell/badge/mark-read plumbing needs **no changes** for any emitter — writing an `unread`
  notification is enough; the bell reflects it automatically.
