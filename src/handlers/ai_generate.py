"""POST /ai/generate -- a brief becomes a Product, an Offer and a DRAFT page.

AI_AND_COMMERCE §A.3. The order of operations is the design:

  1. Validate the brief. Nothing is spent on a brief that cannot produce a page.
  2. Take the quota slot BEFORE generating, and give it back only if WE failed. A tenant is not
     billed for our outage; a page they merely dislike still counts (author, 2026-09-27).
  3. Create the Product and Offer DETERMINISTICALLY. The platform owns every id -- a model that
     invents a product_id produces a buy button pointing at nothing.
  4. Generate ONLY the copy, against the §A.7-floored schema, grounded on the brief.
  5. Save as a draft. Never published: the tenant reviews in the builder and publishes deliberately.

Runs inline rather than as a job. §A.3 says "Step Functions (or a single worker Lambda for the MVP)";
a generation measured 13-20 seconds against API Gateway's 30-second ceiling, which is thin but real
for one page. The moment a critic pass or image work is added this must become a job -- noted here
because the ceiling is what will break first, and it will break as a timeout rather than an error.
"""
import random
import time

from stripe_link.ai_client import AiError, generate_structured
from stripe_link.common import error_response, json_response, parse_json_body, tenant_id_from_event
from stripe_link.domain.ai_floor import assert_within_floor, claim_violations
from stripe_link.domain.ai_models import default_model
from stripe_link.domain.ai_provision import (needs_service_handoff, new_id, offer_document,
                                             page_document, product_document, provenance_block,
                                             slugify)
from stripe_link.domain.ai_quota import allowance_for, may_generate, period_key
from stripe_link.domain.ai_resolvers import resolve_preset, resolve_sections, resolution_log
from stripe_link.domain.ai_schema import describe_vocabulary, page_sections_schema
from stripe_link.domain.documents import (DocumentValidationError, validate_offer_document,
                                          validate_page_document, validate_product_document)
from handlers.pages import assign_short_code
from stripe_link.domain.page_brief import BriefError, grounding_text, validate as validate_brief
from stripe_link.domain.page_brief import withheld
from stripe_link.repositories.documents import (RepositoryError, ai_provider_config_repository,
                                                ai_usage_repository, offers_repository,
                                                pages_repository, products_repository,
                                                tenant_profiles_repository)
from stripe_link.domain.documents import SUPPORTED_THEME_PRESETS

SYSTEM = (
    "You compose landing pages for an e-commerce platform. You emit ONLY structured page sections "
    "conforming to the schema -- never HTML, never markdown. The platform's renderer turns your JSON "
    "into the page.\n\n"
    "{vocabulary}\n\n"
    "Every `id` is a short unique slug. Write specific, concrete copy in a {tone} voice.\n\n"
    "STATE ONLY WHAT THE BRIEF GIVES YOU. Never invent a policy, cancellation term, guarantee, "
    "shipping promise, dosage, certification or result. If the brief does not say it, do not write "
    "it -- a page that says less is correct; a page that invents a promise is not."
)


def handler(event, context, *, products_repo=None, offers_repo=None, pages_repo=None,
            config_repo=None, usage_repo=None, tenant_repo=None, generator=None, now_fn=None,
            randomiser=None):
    if (event or {}).get("httpMethod", "POST").upper() == "OPTIONS":
        return json_response({})
    now = int((now_fn or time.time)())
    pick = randomiser or random.SystemRandom().choice
    body = parse_json_body(event) or {}
    tenant_id = tenant_id_from_event(event, body)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")

    brief = body.get("brief") if isinstance(body.get("brief"), dict) else body
    try:
        validate_brief(brief)
    except BriefError as exc:
        return error_response(str(exc), code="invalid_brief")
    if needs_service_handoff(brief):
        # Three wizards each creating services slightly differently is the two-worlds confusion
        # plans/SERVICE_WIZARD.md exists to dissolve. Refuse rather than invent a third path.
        return error_response(
            "Services are created in the Services wizard, which handles booking, hours and who "
            "performs them. Start there and generate the page afterwards.",
            status_code=409, code="service_handoff")

    mode = str(body.get("mode") or "test").strip().lower()
    mode = "live" if mode == "live" else "test"
    try:
        config_repo = config_repo or ai_provider_config_repository()
        usage_repo = usage_repo or ai_usage_repository()
        products_repo = products_repo or products_repository(mode=mode)
        offers_repo = offers_repo or offers_repository(mode=mode)
        pages_repo = pages_repo or pages_repository(mode=mode)
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")

    config = (config_repo.get(tenant_id) or {}) if hasattr(config_repo, "get") else {}
    if not config.get("provider"):
        return error_response("Turn on AI in Settings before generating a page.", code="ai_not_configured")
    model = str(config.get("model") or default_model())

    period = period_key(now)
    plan_key, exempt = _plan(tenant_id, tenant_repo)
    allowance = allowance_for(plan_key=plan_key, provider=str(config.get("provider")), exempt=exempt)
    try:
        used = usage_repo.used(tenant_id, period)
    except Exception:  # noqa: BLE001 - an unreadable counter must fail CLOSED, not hand out a free run
        return error_response("Could not check your AI allowance. Try again shortly.", code="quota_unavailable")
    allowed, why_not = may_generate(used, allowance)
    if not allowed:
        return error_response(why_not, status_code=429, code="quota_exhausted")

    # Spend the slot before the work, so two concurrent requests cannot both pass the check above.
    try:
        usage_repo.consume(tenant_id, period, at=now)
    except Exception:  # noqa: BLE001
        return error_response("Could not reserve an AI generation. Try again shortly.", code="quota_unavailable")

    try:
        result = _generate(brief, model=model, provider=str(config.get("provider")), generator=generator)
    except AiError as exc:
        # OUR failure, not their preference -- give the slot back.
        _release(usage_repo, tenant_id, period, now)
        return error_response(_message_for(exc), status_code=502, code=f"generate_{exc.kind}")

    try:
        saved = _persist(brief, result, tenant_id=tenant_id, mode=mode, now=now, pick=pick,
                         products_repo=products_repo, offers_repo=offers_repo, pages_repo=pages_repo)
    except (DocumentValidationError, RepositoryError, ValueError) as exc:
        _release(usage_repo, tenant_id, period, now)
        return error_response(f"The page could not be saved: {exc}", code="save_failed")

    return json_response({**saved,
                          "usage": {"period": period, "used": used + 1, "allowance": allowance},
                          "withheld": withheld(brief),
                          "decisions": result["decisions"],
                          "generation": {"model": model, "repairs": result["repairs"],
                                         "tokens": result["usage"]}}, status_code=201)


def _plan(tenant_id, tenant_repo):
    try:
        profile = (tenant_repo or tenant_profiles_repository()).get(tenant_id) or {}
    except Exception:  # noqa: BLE001 - a missing profile is the FREE tier, never an open tap
        return "", False
    return str(profile.get("tier_id") or profile.get("billing_plan_key") or ""), bool(profile.get("billing_exempt"))


def _release(usage_repo, tenant_id, period, now):
    try:
        usage_repo.release(tenant_id, period, at=now)
    except Exception:  # noqa: BLE001 - a refund we cannot make must not mask the real error
        pass


def _generate(brief, *, model, provider, generator=None):
    sections = resolve_sections(offer_type="single", goal="")
    preset = resolve_preset(category=str(brief.get("category") or ""),
                            supported=SUPPORTED_THEME_PRESETS)
    schema = page_sections_schema(sections["value"])
    grounding = grounding_text(brief)
    system = SYSTEM.format(vocabulary=describe_vocabulary(sections["value"]),
                           tone=str(brief.get("tone") or "direct"))
    run = generator or generate_structured
    result = run(prompt=_prompt(brief, grounding), json_schema=schema, model=model,
                 provider=provider, system=system, schema_name="page_sections",
                 validate=lambda value: assert_within_floor(value, grounding), for_page=True)
    emitted = (result.get("value") or {}).get("sections") or []
    return {"sections": emitted, "preset": preset["value"], "repairs": result.get("repairs", 0),
            "usage": result.get("usage", {}),
            # Recorded so a page the tenant dislikes is arguable. "the AI chose it" is not a diagnosis.
            "decisions": resolution_log({"preset": preset, "sections": sections}),
            # Belt to the floor's braces: if anything survived the repair loop, say so rather than
            # discovering it on a published page.
            "residual_violations": claim_violations(emitted, grounding)}


def _prompt(brief, grounding):
    must_not = [str(x).strip() for x in (brief.get("must_not_say") or []) if str(x).strip()]
    lines = ["Compose the page sections for this offer.", "", "THE BRIEF -- everything you may assert:",
             grounding]
    if must_not:
        lines += ["", "NEVER say any of these:"] + [f"- {x}" for x in must_not]
    return "\n".join(lines)


def _persist(brief, result, *, tenant_id, mode, now, pick, products_repo, offers_repo, pages_repo):
    provenance = provenance_block(str(brief.get("brief_id") or ""), now)
    product_id, price_id = new_id("local", pick), new_id("price", pick)
    offer_id, page_id = new_id("offer", pick), new_id("page", pick)
    slug = slugify(brief.get("name"))

    product = product_document(brief, tenant_id=tenant_id, product_id=product_id, price_id=price_id,
                               mode=mode, now=now, provenance=provenance)
    offer = offer_document(brief, tenant_id=tenant_id, offer_id=offer_id, product_id=product_id,
                           price_id=price_id, slug=slug, mode=mode, now=now, provenance=provenance)
    page = page_document(brief, tenant_id=tenant_id, page_id=page_id, offer_id=offer_id, slug=slug,
                         sections=result["sections"], preset=result["preset"], mode=mode, now=now,
                         provenance=provenance)
    # The SHARED assigner, not a local one. Writing the page straight to the repository skipped
    # `create_page` and therefore this, and a page without a short_code is not merely missing a field:
    # the dashboard's pageUrl() keys the test viewer on it, so the card fell through to the live
    # preview distribution where no artifact exists -- a wrong host AND an S3 AccessDenied.
    assign_short_code(None, page)
    # Validate ALL THREE before writing any: a product saved beside a rejected page is the half-made
    # thing the tenant cannot finish, and validation is free next to a partial write.
    validate_product_document(product)
    validate_offer_document(offer)
    validate_page_document(page)
    products_repo.put(product)
    offers_repo.put(offer)
    pages_repo.put(page)
    return {"product": product, "offer": offer, "page": page,
            "residual_violations": result["residual_violations"]}


def _message_for(exc: AiError) -> str:
    if exc.kind == "not_entitled":
        return "This platform cannot reach the AI model right now. Nothing is wrong with your settings."
    if exc.kind == "bad_credentials":
        return "Your AI provider rejected the stored key. Reconnect it in Settings."
    if exc.kind == "throttled":
        return "The AI is busy right now. Try again in a moment — this did not use a generation."
    if exc.kind == "unusable_output":
        return ("The AI could not produce a page that met our content rules. This did not use a "
                "generation — try again, or add more detail to the brief.")
    return f"The page could not be generated: {exc.message}"
