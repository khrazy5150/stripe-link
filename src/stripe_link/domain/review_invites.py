"""Post-purchase review invitations (plans/REVIEWS.md, Phase 2). A paid order plans a short email sequence
that asks the buyer to review the product. Kept pure so the trigger, the sweep, and the tests share one
model. Steps live on the invite record (send_at + sent_at) for idempotency; the invite is CANCELED the moment
the customer reviews (verified purchase), so no one gets nagged after they've reviewed."""
import secrets
from typing import Any

INVITE_STEPS_DAYS = (1, 3, 7, 10)  # a day/3/7/10 after the buyer would have received it
DAY_SECONDS = 86_400
# Rough shipping-estimate offset so "day 1" means ~a day after delivery, not after payment. A per-Site /
# per-product override is a future refinement; digital/service products deliver instantly (offset 0).
_SHIP_ESTIMATE_DAYS = {"physical": 5}
SCHEMA_VERSION = "2026-07-23"


def ship_offset_days(product: dict[str, Any] | None) -> int:
    return _SHIP_ESTIMATE_DAYS.get(str((product or {}).get("product_type") or ""), 0)


def new_invite_token() -> str:
    return secrets.token_urlsafe(24)


def plan_invite(*, tenant_id: str, invite_id: str, order_id: str, product: dict[str, Any], customer: dict[str, Any],
                now: int, token: str | None = None, steps_days: tuple[int, ...] = INVITE_STEPS_DAYS) -> dict[str, Any]:
    offset = ship_offset_days(product)
    steps = [{"day": d, "send_at": int(now) + (offset + d) * DAY_SECONDS, "sent_at": None} for d in steps_days]
    return {
        "schema_version": SCHEMA_VERSION, "document_type": "review_invite", "tenant_id": str(tenant_id),
        "invite_id": str(invite_id), "order_id": str(order_id or ""),
        "target": {"type": "product", "id": str((product or {}).get("product_id") or "")},
        "product_name": str((product or {}).get("name") or ""),
        "customer": {"email": str((customer or {}).get("email") or ""), "name": str((customer or {}).get("name") or "")},
        "token": token or new_invite_token(), "steps": steps, "status": "active",
        "created_at": int(now), "updated_at": int(now),
    }


def invite_sendable(invite: dict[str, Any]) -> bool:
    """A product target + a customer email are the minimum to send anything."""
    return bool(str((invite.get("customer") or {}).get("email") or "").strip()
                and str((invite.get("target") or {}).get("id") or "").strip())


def due_steps(invite: dict[str, Any], now: int) -> list[dict[str, Any]]:
    """Unsent steps whose send time has arrived — only while the invite is still active (not reviewed/canceled)."""
    if (invite or {}).get("status") != "active":
        return []
    return [s for s in (invite.get("steps") or []) if not s.get("sent_at") and int(s.get("send_at") or 0) <= int(now)]


def mark_step_sent(invite: dict[str, Any], day: int, now: int) -> dict[str, Any]:
    for step in invite.get("steps") or []:
        if step.get("day") == day:
            step["sent_at"] = int(now)
    invite["updated_at"] = int(now)
    if all(step.get("sent_at") for step in invite.get("steps") or []):
        invite["status"] = "completed"  # last step sent; nothing left to do
    return invite


def review_link(base_url: str, invite: dict[str, Any]) -> str:
    from urllib.parse import urlencode
    query = urlencode({
        "tenant_id": invite.get("tenant_id", ""),
        "product_id": (invite.get("target") or {}).get("id", ""),
        "invite": invite.get("invite_id", ""),
        "token": invite.get("token", ""),
    })
    return f"{str(base_url).rstrip('/')}/review?{query}"


def invite_email(invite: dict[str, Any], *, base_url: str, business_name: str = "") -> dict[str, str]:
    """Subject + html/text for a review-invite step. One destination (the JB form here; the Google-vs-JB choice
    is Slice C). No sentiment branching — every buyer gets the same ask."""
    import html as html_lib
    product = str(invite.get("product_name") or "your purchase")
    name = str((invite.get("customer") or {}).get("name") or "").strip()
    greeting = f"Hi {html_lib.escape(name.split()[0])}," if name else "Hi there,"
    who = html_lib.escape(business_name) if business_name else "us"
    link = review_link(base_url, invite)
    subject = f"How was your {product}?"
    html = (
        f"<div style=\"font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:32rem;margin:0 auto;color:#1f2937\">"
        f"<p>{greeting}</p>"
        f"<p>Thanks for choosing {who}! We'd love to hear how your <strong>{html_lib.escape(product)}</strong> is working out."
        f" It only takes a minute and helps other shoppers.</p>"
        f"<p style=\"text-align:center;margin:1.6rem 0\">"
        f"<a href=\"{html_lib.escape(link)}\" style=\"background:#4f46b5;color:#fff;text-decoration:none;padding:.8rem 1.4rem;border-radius:8px;font-weight:700\">Leave a review</a>"
        f"</p><p style=\"color:#6b7280;font-size:.9rem\">If you've already reviewed, thank you — you can ignore this.</p></div>"
    )
    text = f"{greeting}\n\nThanks for choosing {business_name or 'us'}! How was your {product}? Leave a review:\n{link}\n\nIf you've already reviewed, thank you."
    return {"subject": subject, "html": html, "text": text}
