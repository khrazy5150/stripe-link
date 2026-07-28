import os
from urllib.parse import urlencode

from stripe_link.common import error_response, json_response, path_params, query_params, tenant_id_from_event
from stripe_link.domain.connect_sync import site_domain_verified
from stripe_link.domain.funnels import FunnelError, post_purchase_plan, resolve_funnel_transition
from stripe_link.domain.opportunities import STAGE_POST_PURCHASE, stage_opportunities
from stripe_link.repositories.documents import (
    RepositoryError,
    offers_repository,
    pages_repository,
    products_repository,
    sites_repository,
)
from stripe_link.runtime.artifacts import artifact_paths
from stripe_link.runtime.publishing import find_site_for_page, public_url, site_page_slug


def _next_page_url(site, tenant_id, next_page_id, pages_domain):
    """The buyer-facing URL for the funnel's next page. Prefer the Site's verified custom domain at the page's
    own slug so the buyer never leaves the domain mid-funnel (plans/SITE_OBJECT.md §2.6); otherwise fall back
    to the interim platform artifact URL."""
    if site and site_domain_verified(site):
        slug = site_page_slug(site, next_page_id)
        custom_domain = str((site.get("hosting") or {}).get("custom_domain") or "")
        if slug and custom_domain:
            path = "" if slug == "/" else slug.lstrip("/")
            return f"https://{custom_domain}/{path}"
    return public_url(pages_domain, artifact_paths(tenant_id, next_page_id)["published"])


def _load_post_purchase_plan(tenant_id, page, offers_repo, products_repo):
    """The offer's derived post-purchase plan (plans/OFFER_MODEL_REDESIGN.md §6). Best-effort: any failure to
    load the offer/products yields an empty plan, so the handler falls back to legacy page-step routing rather
    than 500ing."""
    if not offers_repo or not products_repo:
        return {"strategy": "sequence", "upsells": []}
    try:
        offer = offers_repo.get(tenant_id, str(page.get("offer_id") or "")) or {}
        products_by_id = {}
        for opp in stage_opportunities(offer, STAGE_POST_PURCHASE):
            product_id = str(opp.get("product_id") or "")
            if product_id and product_id not in products_by_id:
                product = products_repo.get(tenant_id, product_id)
                if product:
                    products_by_id[product_id] = product
        return post_purchase_plan(offer, products_by_id)
    except Exception:  # noqa: BLE001 - a plan-load failure must degrade to legacy routing, never 500
        return {"strategy": "sequence", "upsells": []}


def handler(event, context, *, repository=None, pages_domain=None, sites_repo=None, offers_repo=None, products_repo=None):
    method = (event or {}).get("httpMethod", "GET").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "GET":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    repository = repository or pages_repository()
    sites_repo = sites_repo or (sites_repository() if os.environ.get("SITES_TABLE") else None)
    offers_repo = offers_repo or (offers_repository() if os.environ.get("OFFERS_TABLE") else None)
    products_repo = products_repo or (products_repository() if os.environ.get("PRODUCTS_TABLE") else None)
    pages_domain = pages_domain if pages_domain is not None else os.environ.get("PAGES_DISTRIBUTION_DOMAIN", "")

    page_id = path_params(event).get("page_id")
    params = query_params(event)
    tenant_id = tenant_id_from_event(event)
    outcome = str(params.get("outcome") or "").strip().lower()
    current_step_id = str(params.get("step_id") or "").strip() or None
    session_id = str(params.get("session_id") or "").strip()

    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")
    if not page_id:
        return error_response("page_id is required.", code="missing_page")

    try:
        page = repository.get(tenant_id, page_id)
        if not page:
            return error_response("Page not found.", status_code=404, code="not_found")

        site = find_site_for_page(sites_repo, tenant_id, page_id)
        plan = _load_post_purchase_plan(tenant_id, page, offers_repo, products_repo)
        upsells = plan["upsells"]

        def _funnel_redirect(next_page_id, extra_query=None):
            """Redirect to a funnel artifact ({page_id}__…), carrying funnel_page/session so the next screen's
            island keeps the funnel context. Returns a 500 when the pages domain isn't configured."""
            url = _next_page_url(site, tenant_id, next_page_id, pages_domain)
            if not url:
                return error_response("Pages distribution domain is not configured.", status_code=500, code="pages_domain_not_configured")
            query = dict(extra_query or {})
            if session_id:
                query["session_id"] = session_id
            if query:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}{urlencode(query)}"
            return redirect_response(url)

        # Post-purchase routing when the offer derives upsells (plans/OFFER_MODEL_REDESIGN.md §6): the plan is the
        # source of truth, recomputed each hop. Strategy is derived from the upsell count.
        if upsells:
            if outcome not in ("accept", "decline"):
                return error_response("outcome must be 'accept' or 'decline'.", code="funnel_error")
            if plan["strategy"] == "carousel":
                # Carousel: the first hop (no step_id, from the Stripe success_url) → the upsell carousel. Its
                # single dismiss (step_id="upsell_carousel") → the downsell carousel when any upsell product
                # carries a downsell price, else thank-you; the downsell carousel's dismiss → thank-you. Per-card
                # Adds charge via /upsell/charge and stay on the grid, so only the dismiss reaches this router.
                if not current_step_id:
                    return _funnel_redirect(f"{page_id}__upsell_carousel", {"funnel_page": page_id})
                if current_step_id == "upsell_carousel" and any(e.get("downsell") for e in upsells):
                    return _funnel_redirect(f"{page_id}__downsell_carousel", {"funnel_page": page_id})
                return _funnel_redirect(f"{page_id}__thank_you")
            # Sequence: `step_id` carries the current 1-based sequence; the first hop has none, so it resolves to
            # upsell 1. Accept advances; decline swaps to the in-place downsell client-side then advances. Past
            # the last upsell → the synthesized thank-you screen at {page_id}__thank_you.
            current_seq = int(current_step_id) if (current_step_id or "").isdigit() else 0
            next_seq = current_seq + 1
            if next_seq <= len(upsells):
                return _funnel_redirect(f"{page_id}__upsell_{next_seq}", {"funnel_page": page_id, "funnel_step": str(next_seq)})
            return _funnel_redirect(f"{page_id}__thank_you")
        else:
            destination = resolve_funnel_transition(
                page.get("post_checkout") or {}, current_step_id=current_step_id, outcome=outcome,
            )
    except FunnelError as exc:
        return error_response(str(exc), code="funnel_error")
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")

    if destination["kind"] == "url":
        return redirect_response(destination["url"])

    next_page_id = destination["page_id"]
    next_step_id = destination.get("step_id", "")
    # A dangling or unpublished thank-you page (the editor can reference one that was never created/published)
    # would 404 the buyer at the very end of the funnel. Fall back to the entry page's success state — its
    # artifact is always published — rather than dead-ending them (P3.5 makes the thank-you page real).
    if next_step_id == "thank_you":
        try:
            thanks = repository.get(tenant_id, next_page_id) if next_page_id else None
        except RepositoryError:
            thanks = None
        if not thanks or thanks.get("status") != "published":
            entry_url = _next_page_url(site, tenant_id, page_id, pages_domain)
            if not entry_url:
                return error_response("Pages distribution domain is not configured.", status_code=500, code="pages_domain_not_configured")
            separator = "&" if "?" in entry_url else "?"
            return redirect_response(f"{entry_url}{separator}checkout=success")

    url = _next_page_url(site, tenant_id, next_page_id, pages_domain)
    if not url:
        return error_response("Pages distribution domain is not configured.", status_code=500, code="pages_domain_not_configured")

    query = {}
    if session_id:
        query["session_id"] = session_id
    if next_step_id and next_step_id != "thank_you":
        query["funnel_page"] = page_id
        query["funnel_step"] = next_step_id
    if query:
        url = f"{url}?{urlencode(query)}"
    return redirect_response(url)


def _thank_you_destination(post_checkout):
    """The offer-derived funnel terminates at the page's configured thank-you page. Raises when none is set
    (same as legacy routing) — P3.5 makes the thank-you page a required part of the post-checkout config."""
    thank_you = post_checkout.get("thank_you_page") or {}
    if thank_you.get("url"):
        return {"kind": "url", "url": thank_you["url"]}
    if thank_you.get("page_id"):
        return {"kind": "page", "page_id": thank_you["page_id"], "step_id": "thank_you"}
    raise FunnelError("post_checkout.thank_you_page is not configured.")


def redirect_response(url):
    return {
        "statusCode": 303,
        "headers": {
            "Location": url,
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Tenant-Id,X-Client-Id,X-Environment,X-Stripe-Mode",
            "Access-Control-Allow-Methods": "OPTIONS,GET",
        },
        "body": "",
    }
