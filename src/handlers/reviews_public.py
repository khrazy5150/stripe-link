"""Public review submission (plans/REVIEWS.md, Phase 2). Unauthenticated: a customer reaches this from an
invite link (later tokenized/verified-purchase) and leaves a review. Serves a self-contained HTML form (GET)
and accepts the submission (POST, form-encoded or JSON). Submissions land status=pending, source=first_party
for tenant moderation. Honeypot-gated; tenant + product existence validated so a bot can't seed junk targets."""
import html as html_lib
import os
import secrets
import time
from urllib.parse import parse_qs

from stripe_link.common import error_response, header_value, json_response, query_params, resolve_stripe_mode
from stripe_link.domain.documents import DocumentValidationError, validate_review
from stripe_link.repositories.documents import RepositoryError, products_repository, review_invites_repository, reviews_repository, sites_repository

HONEYPOT_FIELD = "company_website"
SCHEMA_VERSION = "2026-07-23"
_ID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _html_response(body: str, status: int = 200):
    return {"statusCode": status, "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}, "body": body}


def _new_review_id() -> str:
    return "review_" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(14))


def _form_values(event) -> dict:
    """Fields from either a JSON body or a urlencoded form POST (the no-JS form submits form-encoded)."""
    raw = (event or {}).get("body") or ""
    if not raw:
        return {}
    content_type = str(header_value(event, "Content-Type") or "").lower()
    if "application/json" in content_type or raw.strip().startswith("{"):
        try:
            import json
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}
    return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}


def _requested_mode(event, method: str) -> str:
    """The mode the REQUEST asks for.

    `resolve_stripe_mode` reads a JSON body, a query param or a header -- and this form posts back
    **urlencoded**, which is none of the three. So the POST reads its own hidden field first; without that,
    a form that rendered correctly from `?mode=live` would submit itself into the test books and the
    submission would 404 after the buyer had typed their review.
    """
    if method == "POST":
        declared = str(_form_values(event).get("mode") or "").strip().lower()
        if declared in ("live", "test"):
            return declared
    return resolve_stripe_mode(event)


def _settle_product(build_repo, tenant_id: str, product_id: str, requested: str):
    """Find the product, and report which mode's books it was found in. `(product, mode)`.

    The requested mode first. Falling back to the OTHER one is what makes invites already sitting in
    inboxes work: they were sent before the link carried a `mode` at all, so they resolve to the fail-safe
    "test" and their live product is simply not there. A product is public, read-only and tenant-scoped, so
    looking in both books costs one `get` on a path that was about to answer 404 anyway.

    Logged when it happens, because once every invite in circulation carries its mode this should stop --
    and if it does not, something new has forgotten it.
    """
    if not tenant_id or not product_id:
        return None, requested
    other = "test" if requested == "live" else "live"
    for mode in (requested, other):
        try:
            product = build_repo(mode).get(tenant_id, product_id)
        except Exception:  # noqa: BLE001 — a lookup failure in one mode must not hide the other
            product = None
        if product:
            if mode != requested:
                print(f"[review] product {product_id} found in {mode}, link asked for {requested}")
            return product, mode
    return None, requested


def handler(event, context, *, reviews_repo=None, products_repo=None, sites_repo=None, invites_repo=None):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method not in {"GET", "POST"}:
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    requested = _requested_mode(event, method)
    values = query_params(event) if method == "GET" else _form_values(event)
    tenant_id = str(values.get("tenant_id") or "").strip()
    product_id = str(values.get("product_id") or "").strip()

    # The honeypot answers before anything is looked up: a bot must not be able to tell a real product
    # from an invented one by how long the reply takes or what it says.
    if method == "POST" and str(values.get(HONEYPOT_FIELD) or "").strip():
        return _html_response(_page("Thank you!", "Your review has been received."))

    def build_repo(mode):
        return products_repo or products_repository(mode=mode)

    product, mode = _settle_product(build_repo, tenant_id, product_id, requested)
    if not product:
        return _html_response(_page("This review link is no longer valid.", "The product could not be found."), status=404)

    # Sites and invites are read from the mode the PRODUCT turned out to be in, so a healed link marks the
    # review a verified purchase and cancels the remaining emails instead of silently doing neither.
    if sites_repo is None and os.environ.get("SITES_TABLE"):
        sites_repo = sites_repository(mode=mode)
    if invites_repo is None and os.environ.get("REVIEWS_TABLE"):
        invites_repo = review_invites_repository(mode=mode)
    # ONLY A REAL BUYER. Checked before the form renders, not only before it is accepted: a form that
    # collects a review and then refuses it wastes a real person's effort, and one that renders for anyone
    # is an invitation to try.
    invite = _authorised_invite(invites_repo, tenant_id, product_id, values)
    if invite is None:
        return _not_invited()

    if method == "GET":
        return render_form(values, product, mode, sites_repo)
    return submit_review(event, values, product, mode, reviews_repo or reviews_repository(), invites_repo)


def _authorised_invite(invites_repo, tenant_id: str, product_id: str, values) -> dict | None:
    """The invite this request is authorised by, or None.

    READ-ONLY: a GET must not spend the token, or opening the email twice would burn it. `_consume_invite`
    does the spending, on the POST.

    This is what closes the anonymous hole (plans/REVIEWS.md "Review integrity"). The form used to render
    for anyone holding a tenant_id and a product_id — both of which sit in the public HTML of every
    published page — and `submit_review` accepted a tokenless POST. Moderation was the only thing between
    an anonymous POST and a merchant's live page, and moderation is what this work removes.
    """
    invite_id = str(values.get("invite") or "").strip()
    token = str(values.get("token") or "").strip()
    if not invites_repo or not invite_id or not token:
        return None
    try:
        invite = invites_repo.get(tenant_id, invite_id)
    except Exception:  # noqa: BLE001 — a lookup failure is an unauthorised request, not a 500
        return None
    if not invite or invite.get("token") != token:
        return None
    # Bound to the PRODUCT as well as the order: an invite for one purchase must not review another.
    if str((invite.get("target") or {}).get("id") or "") != product_id:
        return None
    return invite


def _not_invited() -> dict:
    """What someone without a valid invite is told. The same answer for a missing token, a wrong one and an
    invite for another product, so the page cannot be used to probe which of the three it was."""
    return _html_response(_page(
        "This review link is no longer valid.",
        "Reviews can only be left from the link we email after a purchase."), status=403)


def _business_name(sites_repo, tenant_id: str) -> str:
    if not sites_repo or not tenant_id:
        return ""
    try:
        for site in sites_repo.list_for_tenant(tenant_id):
            name = str(((site or {}).get("organization") or {}).get("name") or "").strip()
            if name:
                return name
    except Exception:  # noqa: BLE001
        pass
    return ""


def render_form(params, product, mode, sites_repo):
    tenant_id = str(params.get("tenant_id") or "").strip()
    business = _business_name(sites_repo, tenant_id)
    return _html_response(_form_html(
        tenant_id, str(product.get("product_id") or ""), str(product.get("name") or "your purchase"),
        business, str(params.get("invite") or ""), str(params.get("token") or ""), mode=mode))


def submit_review(event, values, product, mode, reviews_repo, invites_repo=None):
    tenant_id = str(values.get("tenant_id") or "").strip()
    product_id = str(product.get("product_id") or "").strip()
    try:
        rating = int(str(values.get("rating") or "").strip() or 0)
    except ValueError:
        rating = 0
    now = int(time.time())
    review = {
        "schema_version": SCHEMA_VERSION, "document_type": "review", "tenant_id": tenant_id,
        "review_id": _new_review_id(), "target": {"type": "product", "id": product_id},
        "rating": rating, "author": str(values.get("author") or "").strip(),
        "body": str(values.get("body") or "").strip(), "status": "pending", "source": "first_party",
        "created_at": now, "updated_at": now,
    }
    title = str(values.get("title") or "").strip()
    if title:
        review["title"] = title
    context = (event or {}).get("requestContext") or {}
    review["provenance"] = {"ip": str((context.get("identity") or {}).get("sourceIp") or "")[:64], "submitted_at": now}
    # A valid invite token marks this a VERIFIED PURCHASE and cancels the remaining invite emails (so a
    # customer who reviews is never nagged again). Still lands `pending` — verified doesn't mean auto-published.
    invite = _consume_invite(invites_repo, tenant_id, str(values.get("invite") or ""), str(values.get("token") or ""), product_id, now)
    if invite:
        review["verified_purchase"] = True
        review["order_id"] = str(invite.get("order_id") or "")
    try:
        validate_review(review)
        reviews_repo.put(review)
    except (DocumentValidationError, RepositoryError) as exc:
        # Back to the form with what they typed still standing, not a dead end -- and carrying the same
        # mode, so a corrected resubmission lands in the books the product was actually found in.
        return _html_response(_form_html(tenant_id, product_id, str(product.get("name") or ""), "",
                                         str(values.get("invite") or ""), str(values.get("token") or ""),
                                         mode=mode, error=str(exc)), status=400)
    return _html_response(_page("Thank you!", "Your review has been submitted and will appear once it's approved."))


def _consume_invite(invites_repo, tenant_id, invite_id, token, product_id, now):
    """Validate an invite token (single-use, product-bound); cancel the invite so no more emails go out.
    Returns the invite when valid, else None (an open/tokenless submission is fine — just not verified)."""
    if not invites_repo or not invite_id or not token:
        return None
    try:
        invite = invites_repo.get(tenant_id, invite_id)
    except Exception:  # noqa: BLE001
        return None
    if not invite or invite.get("token") != token or str((invite.get("target") or {}).get("id") or "") != product_id:
        return None
    if invite.get("status") == "active":
        invite["status"] = "completed"  # stop the remaining follow-ups
        invite["updated_at"] = now
        try:
            invites_repo.put(invite)
        except Exception:  # noqa: BLE001
            pass
    return invite


def _e(text) -> str:
    return html_lib.escape(str(text or ""))


_STYLE = (
    "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f6f7f9;margin:0;"
    "color:#1f2937;line-height:1.5}.wrap{max-width:34rem;margin:0 auto;padding:2.5rem 1.25rem}"
    ".card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:1.75rem}"
    "h1{font-size:1.5rem;margin:0 0 .25rem}p.sub{color:#6b7280;margin:0 0 1.25rem}"
    "label{display:block;font-weight:600;font-size:.95rem;margin:1rem 0 .35rem}"
    "input,textarea{width:100%;box-sizing:border-box;border:1px solid #d1d5db;border-radius:8px;padding:.6rem .7rem;font:inherit}"
    ".stars{display:flex;flex-direction:row-reverse;justify-content:flex-end;gap:.25rem;margin-top:.35rem}"
    ".stars input{display:none}.stars label{font-size:2rem;color:#d1d5db;cursor:pointer;margin:0}"
    ".stars input:checked~label,.stars label:hover,.stars label:hover~label{color:#f59e0b}"
    ".hp{position:absolute;left:-9999px}button{margin-top:1.5rem;width:100%;background:#4f46b5;color:#fff;border:0;"
    "border-radius:9px;padding:.8rem;font:inherit;font-weight:700;cursor:pointer}.err{color:#b91c1c;margin:.5rem 0 0}"
)


def _page(title: str, message: str) -> str:
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'><meta name=robots content='noindex,nofollow'>"
            f"<title>{_e(title)}</title><style>{_STYLE}</style></head><body><div class=wrap><div class=card>"
            f"<h1>{_e(title)}</h1><p class=sub>{_e(message)}</p></div></div></body></html>")


def _form_html(tenant_id, product_id, product_name, business, invite_id, token, *, mode: str = "test", error: str = "") -> str:
    stars = "".join(
        f"<input type=radio id=star{n} name=rating value={n}{' checked' if n == 5 else ''}>"
        f"<label for=star{n} title='{n} of 5'>&#9733;</label>"
        for n in (5, 4, 3, 2, 1)
    )
    head = _e(business) + " — " if business else ""
    err = f"<p class=err>{_e(error)}</p>" if error else ""
    return (
        f"<!doctype html><html lang=en><head><meta charset=utf-8>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'><meta name=robots content='noindex,nofollow'>"
        f"<title>Review {_e(product_name)}</title><style>{_STYLE}</style></head><body><div class=wrap><div class=card>"
        f"<h1>{head}Leave a review</h1><p class=sub>How was your {_e(product_name)}?</p>{err}"
        f"<form method=post>"
        f"<input type=hidden name=tenant_id value='{_e(tenant_id)}'>"
        f"<input type=hidden name=product_id value='{_e(product_id)}'>"
        f"<input type=hidden name=invite value='{_e(invite_id)}'>"
        f"<input type=hidden name=token value='{_e(token)}'>"
        # Carried forward because this posts urlencoded, which `resolve_stripe_mode` cannot read: a form
        # that rendered from the live books would otherwise submit itself into the test ones.
        f"<input type=hidden name=mode value='{_e(mode)}'>"
        f"<input class=hp type=text name={HONEYPOT_FIELD} tabindex=-1 autocomplete=off>"
        f"<label>Your rating</label><div class=stars>{stars}</div>"
        f"<label for=author>Your name</label><input id=author name=author maxlength=120 required>"
        f"<label for=title>Title (optional)</label><input id=title name=title maxlength=200>"
        f"<label for=body>Your review</label><textarea id=body name=body rows=4 required></textarea>"
        f"<button type=submit>Submit review</button>"
        f"</form></div></div></body></html>"
    )
