"""POST /ai/generate -- a brief becomes a Product, an Offer and a DRAFT page.

AI_AND_COMMERCE §A.3. The order of operations is the design:

  1. Validate the brief. Nothing is spent on a brief that cannot produce a page.
  2. Take the quota slot BEFORE generating, and give it back only if WE failed. A tenant is not
     billed for our outage; a page they merely dislike still counts (author, 2026-09-27).
  3. Create the Product and Offer DETERMINISTICALLY. The platform owns every id -- a model that
     invents a product_id produces a buy button pointing at nothing.
  4. Generate ONLY the copy, against the §A.7-floored schema, grounded on the brief.
  5. Save as a draft. Never published: the tenant reviews in the builder and publishes deliberately.

REGENERATING. Pass `page_id` and only the COPY is rewritten -- the product, the offer and their
Stripe sync are left exactly alone. That is the difference between "I want different words" and "I
want a different thing", and conflating them would leave a duplicate product behind every retry. It
still costs a generation: the model ran, and releasing on taste is unbounded (author, 2026-09-27).

Runs as a JOB, which §A.3 always specified. It ran inline first and the ceiling broke exactly as
predicted, sooner: a four-fact brief took 35.3 seconds against API Gateway's hard 29-second limit.
The Lambda succeeded and wrote every document; the browser saw "Failed to fetch". The tenant was
charged a generation for work they could not see, which is the worst shape a failure can take.

So the request path QUEUES and the event path GENERATES -- the same function, invoked asynchronously
by itself. One function rather than two because the work and the queueing share all their validation,
and a second Lambda is a second thing to keep in step.

CONCURRENCY. The worker reserves 30 executions. That number exists for what it leaves behind: the
account has 1000 shared by 74 functions, so an unbounded AI spike would throttle checkout and the
Stripe webhook. An AI feature must never be able to stop payments. Excess async invocations are not
rejected -- Lambda queues them internally and drains at the reserved rate, so the reservation IS the
queue and a spike becomes a wait rather than a failure.

And a third mode: the REAPER, on a five-minute schedule. Lambda retries an async invoke twice and
then drops it silently, and a dropped job is indistinguishable from a slow one -- it would sit at
`queued` forever while the tenant's generation was never refunded. Nothing else can tell the
difference, so something has to look.
"""
import json
import os
import random
import time

from stripe_link.ai_client import AiError, generate_structured
from stripe_link.common import error_response, json_response, parse_json_body, tenant_id_from_event
from stripe_link.domain.ai_elements import assert_contracts, violations as contract_violations
from stripe_link.domain.ai_floor import assert_within_floor, claim_violations
from stripe_link.domain.ai_models import default_model
from stripe_link.domain.ai_provision import (needs_service_handoff, new_id, offer_document,
                                             page_document, product_document, provenance_block,
                                             slugify)
from stripe_link.domain import ai_generation_events as events
from stripe_link.domain.ai_models import estimate_cost
from stripe_link.domain.ai_quota import (PLATFORM_TENANT, entitlement_for, may_generate,
                                          period_key, within_platform_budget)
from stripe_link.api_auth import note_capability_decision
from stripe_link.domain.entitlements import AI_BUILDER, can_use_ai_builder
from stripe_link.domain.ai_resolvers import resolve_preset, resolve_sections, resolution_log
from stripe_link.domain.ai_schema import describe_vocabulary, page_sections_schema
from stripe_link.domain.documents import (DocumentValidationError, validate_offer_document,
                                          validate_page_document, validate_product_document)
from handlers.pages import assign_short_code
from stripe_link.domain.documents import validate_product_ai_context
from stripe_link.domain.product_brief import brief_from_product
from stripe_link.domain.page_brief import BriefError, grounding_text, validate as validate_brief
from stripe_link.domain.page_brief import withheld
from stripe_link.repositories.documents import (RepositoryError, ai_jobs_repository,
                                                ai_provider_config_repository, ai_usage_repository,
                                                offers_repository, pages_repository,
                                                products_repository, tenant_profiles_repository)
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
            config_repo=None, usage_repo=None, tenant_repo=None, jobs_repo=None, generator=None,
            events_repo=None, now_fn=None, randomiser=None, invoker=None):
    now = int((now_fn or time.time)())
    pick = randomiser or random.SystemRandom().choice
    try:
        jobs_repo = jobs_repo or ai_jobs_repository()
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")

    # The REAPER path.
    if (event or {}).get("internal_reap"):
        return _reap(jobs_repo, usage_repo=usage_repo, now=now)

    # The EVENT path: this is the async self-invoke, doing the work the request path queued.
    if (event or {}).get("internal_job"):
        return _run_job(event, jobs_repo=jobs_repo, products_repo=products_repo,
                        offers_repo=offers_repo, pages_repo=pages_repo, usage_repo=usage_repo,
                        events_repo=events_repo, generator=generator, now=now, pick=pick)

    if (event or {}).get("httpMethod", "POST").upper() == "OPTIONS":
        return json_response({})
    if (event or {}).get("httpMethod", "").upper() == "GET":
        return _read_job(event, jobs_repo)
    body = parse_json_body(event) or {}
    tenant_id = tenant_id_from_event(event, body)
    if not tenant_id:
        return error_response("tenant_id is required.", code="missing_tenant")

    # TWO SOURCES, ONE CONTRACT. `product_id` is the fork off the product wizard: the brief is PROJECTED from
    # a product the tenant already has, plus tenant config, plus the fork's one step -- so nothing the product
    # wizard already asked is asked again (plans/AI_PAGE_BRIEF.md v2). A posted `brief` remains valid because
    # the brief IS the contract and the document names its sources: wizard, url, api, existing_product. These
    # converge on the next line; there is no second pipeline.
    fork_product_id = str(body.get("product_id") or "").strip()
    if fork_product_id:
        try:
            products_repo = products_repo or products_repository(mode=_mode_of(body))
        except RepositoryError as exc:
            return error_response(str(exc), code="repository_error")
        source_product = products_repo.get(tenant_id, fork_product_id)
        if not source_product:
            return error_response("That product was not found.", status_code=404, code="not_found")
        brief = brief_from_product(
            source_product,
            tenant_profile=_profile(tenant_id, tenant_repo),
            shipping_config=_shipping_config(tenant_id),
            overrides=body.get("ai_context") if isinstance(body.get("ai_context"), dict) else None)
    else:
        source_product = None
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

    regenerate_page_id = str(body.get("page_id") or "").strip()
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

    # The tenant decides BOTH numbers -- how many, and which counter. The period is returned rather than
    # derived, because a trial's counter is a LIFETIME one and reaching for period_key() out of habit would
    # hand a trial tenant a fresh three every calendar month (plans/AI_AND_COMMERCE_ARCHITECTURE.md §A.8).
    profile = _profile(tenant_id, tenant_repo)
    # GATE 1 -- may they use AI Builder at all? Separate from "how many", and asked first so the refusal says
    # "not on your plan" rather than "you have used 0 of 0" (plans/AI_AND_COMMERCE_ARCHITECTURE.md §A.8). A
    # verified own-key configuration passes regardless of plan: the platform is not paying for those.
    entitled = can_use_ai_builder(profile, provider_config=config, now=now)
    # A marker, deliberately not a gate: ai_builder must not become responsible for solving the
    # authorization gap. It records a capability GRANTED to a caller nobody verified, which is the count
    # that says when enforcement is safe (plans/API_AUTHENTICATION.md).
    note_capability_decision(event, capability=AI_BUILDER, tenant_id=tenant_id, granted=entitled)
    if not entitled:
        return error_response(
            "AI Builder is not included on your plan. Upgrade, or connect your own AI provider key.",
            status_code=403, code="ai_builder_not_entitled")

    # GATE 2 -- how many, and out of which counter.
    entitlement = entitlement_for(profile, provider=str(config.get("provider")), now=now,
                                  **_configured_allowances())
    allowance, period = entitlement["allowance"], entitlement["period"]

    # GATE 3 -- will we spend another platform dollar this month? Identity-independent, and therefore the
    # only control that sees abuse per-tenant caps cannot: serial trial signups, each one perfectly within
    # its own allowance. Skipped entirely for BYOK, whose spend is not ours.
    if entitlement["source"] != "byok":
        ok, why_not = within_platform_budget(_platform_spend(usage_repo, now), _platform_budget())
        if not ok:
            return error_response(why_not, status_code=429, code="platform_budget_exhausted")
    plan_key = str(profile.get("billing_plan_key") or "")
    exempt = bool(profile.get("billing_exempt"))
    # The WRITE decides, not a read before it. Checking `used` and then incrementing is two round trips with
    # a window between them: two requests at `used=2` of an allowance of 3 both passed the check and both
    # incremented, producing four generations -- under a comment asserting that could not happen. The
    # condition now lives inside the update, so the loser is refused by DynamoDB rather than by Python.
    try:
        taken = usage_repo.consume_if_available(tenant_id, period, allowance=allowance, at=now)
    except Exception:  # noqa: BLE001 - an unusable counter must fail CLOSED, not hand out a free run
        return error_response("Could not check your AI allowance. Try again shortly.", code="quota_unavailable")
    if not taken["allowed"]:
        # `may_generate` still writes the refusal, because the message a tenant reads is its job: it
        # distinguishes "not included on your plan" from "you have used this month's".
        _, why_not = may_generate(taken["used"], allowance, entitlement["source"])
        return error_response(
            why_not or "You have used your AI generations.", status_code=429, code="quota_exhausted")
    used = taken["used"] - 1  # what was already spent BEFORE this one, for the job record below

    # The PERMANENT record, written the moment the slot is spent -- not on success. The ledger answers "what
    # did we charge this tenant for?", and a generation that failed still consumed a slot until something
    # releases it (plans/AI_AND_COMMERCE_ARCHITECTURE.md §A.9). It carries its own copy of the brief because
    # the job row it references is gone in seven days.
    generation_id = new_id("gen", pick)
    event_row = events.started(
        generation_id=generation_id, tenant_id=tenant_id, job_id="", created_at=now,
        source=entitlement["source"],
        model=model, provider=str(config.get("provider")), brief=brief, stripe_mode=mode, period=period)

    job = {
        "schema_version": "2026-09-27", "document_type": "ai_generation_job",
        "tenant_id": tenant_id, "job_id": new_id("job", pick), "status": "queued",
        "brief": brief, "mode": mode, "model": model, "provider": str(config.get("provider")),
        "page_id": regenerate_page_id, "period": period,
        "usage": {"period": period, "used": used + 1, "allowance": allowance},
        "withheld": withheld(brief),
        # The correlation id, carried on all three records so one identifier follows a generation from the
        # slot it spent, through the work, to what it cost.
        "generation_id": generation_id, "event_key": event_row["event_key"],
        "source": entitlement["source"],
        # The fork's input. Present means the catalogue row already exists and the worker must build the
        # Offer and Page around it rather than minting a second product for the same thing.
        "product_id": fork_product_id,
        "created_at": now, "updated_at": now,
        # A finished job is of no interest a week later, and an abandoned one even less.
        "expires_at": now + 7 * 24 * 3600,
    }
    try:
        jobs_repo.put(job)
    except RepositoryError as exc:
        _release(usage_repo, tenant_id, period, now)
        return error_response(str(exc), code="repository_error")

    # Best-effort, and deliberately AFTER the job is safely queued: an unwritable ledger row must never fail a
    # generation the tenant has already spent a slot on. A missing row is visible in the data (the counter
    # will not reconcile) which is a better failure than a 500 after the money went.
    _record_event(events_repo, {**event_row, "job_id": job["job_id"]})
    _save_ai_context(products_repo, source_product, body.get("ai_context"), now)

    try:
        _enqueue(job, invoker)
    except Exception as exc:  # noqa: BLE001 - nothing is generating, so refund and say so
        _release(usage_repo, tenant_id, period, now)
        job = {**job, "status": "failed", "error": {"code": "enqueue_failed", "message": str(exc)}}
        jobs_repo.put(job)
        return error_response("Could not start the generation. Try again shortly.",
                              status_code=502, code="enqueue_failed")
    # 202, not 201: nothing exists yet. The dashboard polls /ai/jobs/{job_id}.
    return json_response({"job": _public(job)}, status_code=202)


def _add_platform_spend(usage_repo, micros, now):
    """Accumulate platform spend on the reserved `__platform__` row. Never raises: the budget is a safety
    ceiling, and failing a finished generation over its bookkeeping would be the wrong trade."""
    if int(micros or 0) <= 0:
        return
    try:
        (usage_repo or ai_usage_repository()).add_cost(
            PLATFORM_TENANT, period_key(now), micros=int(micros), at=now)
    except Exception as exc:  # noqa: BLE001 - see docstring
        print(f"[ai] platform spend not recorded ({micros} micros): {type(exc).__name__}: {exc}")


def _platform_budget():
    """The platform's monthly AI ceiling, from the CONFIG row. Unreadable means NO ceiling, deliberately: a
    settings row that failed to load must not stop every tenant on the platform from generating."""
    try:
        from stripe_link.domain.platform_billing import ai_monthly_budget_usd, platform_billing_mode

        return ai_monthly_budget_usd(platform_billing_mode())
    except Exception:  # noqa: BLE001 - see docstring
        return 0


def _platform_spend(usage_repo, now):
    """This month's platform-paid spend so far, in micro-dollars. Unreadable counts as zero, for the same
    reason the budget does: failing closed here takes the whole platform down over a counter read."""
    try:
        return (usage_repo or ai_usage_repository()).cost(PLATFORM_TENANT, period_key(now))
    except Exception:  # noqa: BLE001
        return 0


def _save_ai_context(products_repo, product, context, now):
    """Keep the fork step's answers on the PRODUCT, so the next generation does not ask again.

    Best-effort: the generation is already under way and its brief carried these values directly, so a failed
    write costs a retype later rather than this page. Merged onto whatever is already there, because the step
    shows a partial form and a blank field means "unchanged", not "delete what I said last time".
    """
    if not product or not isinstance(context, dict) or not context:
        return
    try:
        existing = product.get("ai_context") if isinstance(product.get("ai_context"), dict) else {}
        merged = {**existing, **{k: v for k, v in context.items() if v not in (None, "", [])},
                  "updated_at": int(now)}
        validate_product_ai_context({"ai_context": merged})
        products_repo.put({**product, "ai_context": merged, "updated_at": int(now)})
    except Exception as exc:  # noqa: BLE001 - see docstring
        print(f"[ai] ai_context not saved for {product.get('product_id')}: {type(exc).__name__}: {exc}")


def _mode_of(body):
    mode = str((body or {}).get("mode") or "test").strip().lower()
    return "live" if mode == "live" else "test"


def _shipping_config(tenant_id):
    """The tenant's shipping policy, READ rather than re-asked. Absent is fine: it means the page simply
    will not make a shipping claim, which is the field floor working as designed."""
    try:
        from stripe_link.repositories.documents import shipping_config_repository

        return shipping_config_repository().get(tenant_id) or {}
    except Exception:  # noqa: BLE001 - a missing policy is a quieter page, never a failed generation
        return {}


def _configured_allowances():
    """Trial and free allowances from the CONFIG row, so the Admin Site can change them without a deploy.

    Best-effort: an unreadable config falls back to the constants in `ai_quota`, which are documented as
    fallbacks and not as the pricing. Failing a generation because a settings row could not be read would be
    the wrong trade -- the numbers are small and bounded either way.
    """
    try:
        from stripe_link.domain.platform_billing import (free_ai_generations, platform_billing_mode,
                                                         trial_ai_generations)

        mode = platform_billing_mode()
        return {"trial_allowance": trial_ai_generations(mode), "free_allowance": free_ai_generations(mode)}
    except Exception:  # noqa: BLE001 - see docstring
        return {}


def _profile(tenant_id, tenant_repo):
    """The tenant profile the entitlement is read from. An unreadable one is the FREE tier, never an open tap.

    Returns the whole profile rather than a plan key, because the allowance now depends on the SUBSCRIPTION
    (plan key, trial state, exemption) rather than on `tier_id` -- which is the transaction-FEE tier, a
    different axis that every paid plan shares.
    """
    try:
        # TWO arguments. DynamoDocumentRepository.get is (tenant_id, document_id) and a tenant profile is
        # keyed by its own id -- every other handler calls it `get(tenant_id, tenant_id)`. Called with one,
        # it raises TypeError, the except below swallows it, and every tenant looks like they have no
        # profile. That was survivable while a missing profile fell back to a small allowance; once the
        # free tier means ZERO it silently refuses AI to everyone.
        return (tenant_repo or tenant_profiles_repository()).get(tenant_id, tenant_id) or {}
    except Exception:  # noqa: BLE001
        return {}


def _record_event(events_repo, event_row):
    """Write the permanent ledger row. Never raises: the ledger is evidence, not a gate."""
    try:
        (events_repo or ai_generation_events_repository()).put(event_row)
    except Exception as exc:  # noqa: BLE001 - see the call site
        print(f"[ai] generation event not recorded for {event_row.get('generation_id')}: "
              f"{type(exc).__name__}: {exc}")


def _complete_event(events_repo, job, patch):
    """Merge the outcome onto the ledger row this job created. Never raises, same reason."""
    key = str(job.get("event_key") or "")
    if not key:
        return
    try:
        (events_repo or ai_generation_events_repository()).complete(
            str(job.get("tenant_id") or ""), key, patch)
    except Exception as exc:  # noqa: BLE001
        print(f"[ai] generation event not completed for {job.get('generation_id')}: "
              f"{type(exc).__name__}: {exc}")


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
    def check(value):
        # Two independent contracts, both raising into the repair loop. The floor asks "is this claim
        # grounded"; the element contracts ask "is this the right element for it". A page can pass
        # either and fail the other -- a perfectly grounded fact in the wrong card is exactly the V1
        # failure, and it was grounded.
        assert_within_floor(value, grounding)
        assert_contracts(value)

    run = generator or generate_structured
    result = run(prompt=_prompt(brief, grounding), json_schema=schema, model=model,
                 provider=provider, system=system, schema_name="page_sections",
                 validate=check, for_page=True)
    value = result.get("value") or {}
    emitted = value.get("sections") or []
    by_id = {str(s.get("id") or ""): str(s.get("type") or "") for s in emitted if isinstance(s, dict)}
    return {"sections": emitted,
            # The model's own reasoning, kept OFF the page and ON the job: a bad element choice should
            # be readable back -- "source_fact: easy to clean -> bragging_points" says the boundary is
            # wrong -- rather than inferred from rendered HTML.
            "classification": [
                {**c, "element": by_id.get(str(c.get("section_id") or ""), "")}
                for c in (value.get("classification") or []) if isinstance(c, dict)],
            "preset": preset["value"], "repairs": result.get("repairs", 0),
            "usage": result.get("usage", {}),
            # Recorded so a page the tenant dislikes is arguable. "the AI chose it" is not a diagnosis.
            "decisions": resolution_log({"preset": preset, "sections": sections}),
            # Belt to the braces: if anything survived the repair loop, say so rather than
            # discovering it on a published page.
            "residual_violations": claim_violations(emitted, grounding) + contract_violations(emitted)}


def _prompt(brief, grounding):
    must_not = [str(x).strip() for x in (brief.get("must_not_say") or []) if str(x).strip()]
    lines = [
        "Compose the page sections for this offer.",
        "",
        # The correction to V1, said plainly. The brief is SOURCE MATERIAL, not a set of answers with
        # element assignments already implied by the question that produced them.
        "HOW TO WORK. The brief below is unstructured source material, NOT a list of things to put on "
        "the page. For each fact in it, first decide what job that fact does -- is it evidence, a "
        "feature, a benefit, an objection, a positioning line? -- and only then choose the element "
        "whose contract matches that job. Record both on the section: `source_fact` is the fact you "
        "used, `fact_kind` is the job you decided it does, `reason` is why that element fits it. A "
        "fact the tenant wanted people to know is not automatically evidence.",
        "",
        "THE BRIEF -- everything you may assert:",
        grounding]
    if must_not:
        lines += ["", "NEVER say any of these:"] + [f"- {x}" for x in must_not]
    return "\n".join(lines)


def _persist(brief, result, *, tenant_id, mode, now, pick, products_repo, offers_repo, pages_repo,
             existing_product_id=""):
    """Turn a generation into documents.

    Two entry shapes, and the difference is one question: does the catalogue row already exist? Under the
    FORK it always does -- the flow starts from a product the tenant made in the product wizard -- so this
    creates only the Offer and the Page. Minting a second product for the same thing would give the tenant a
    duplicate catalogue row and split its orders across two ids.
    """
    provenance = provenance_block(str(brief.get("brief_id") or ""), now)
    offer_id, page_id = new_id("offer", pick), new_id("page", pick)
    slug = slugify(brief.get("name"))

    product = None
    if existing_product_id:
        product = products_repo.get(tenant_id, existing_product_id)
        if not product:
            raise ValueError("The product this page was being generated for no longer exists.")
        product_id = str(product.get("product_id"))
        price_id = str(product.get("default_price_id") or "")
        if not price_id:
            prices = product.get("prices") if isinstance(product.get("prices"), list) else []
            price_id = str((prices[0] or {}).get("price_id") or "") if prices else ""
    else:
        product_id, price_id = new_id("local", pick), new_id("price", pick)
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
    # Validate BOTH before writing either: an offer saved beside a rejected page is the half-made thing the
    # tenant cannot finish, and validation is free next to a partial write.
    if not existing_product_id:
        validate_product_document(product)
    validate_offer_document(offer)
    validate_page_document(page)
    if not existing_product_id:
        products_repo.put(product)
    offers_repo.put(offer)
    pages_repo.put(page)
    return {"product": product, "offer": offer, "page": page,
            "residual_violations": result["residual_violations"]}


def _rewrite(brief, result, *, tenant_id, page_id, now, pages_repo, offers_repo):
    """New copy on a page that already exists. The commercial records are not touched.

    A published page is refused rather than quietly rewritten: replacing the words under a live URL
    without the tenant asking is the one thing the draft-only rule exists to prevent.
    """
    page = pages_repo.get(tenant_id, page_id)
    if not page:
        raise ValueError("That page no longer exists.")
    if str(page.get("status") or "") == "published":
        raise ValueError("Unpublish the page first — regenerating would replace the words on a live page.")
    page = {**page, "sections": result["sections"], "updated_at": now}
    page.setdefault("theme", {})["preset"] = result["preset"]
    assign_short_code(None, page)      # older provisioned pages predate it
    validate_page_document(page)
    pages_repo.put(page)
    offer = offers_repo.get(tenant_id, str(page.get("offer_id") or "")) if page.get("offer_id") else None
    return {"product": None, "offer": offer, "page": page,
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


def _public(job: dict) -> dict:
    """What the poller sees. The brief is omitted -- the client sent it and does not need it back."""
    return {key: value for key, value in (job or {}).items() if key != "brief"}


def _enqueue(job: dict, invoker=None) -> None:
    """Hand the job to ourselves, asynchronously.

    InvocationType Event returns as soon as Lambda accepts it, so the request path answers in
    milliseconds no matter how long the generation takes. The same function on the other side means
    the work and its validation cannot drift apart.
    """
    if invoker is not None:
        invoker(job)
        return
    function_name = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "")
    if not function_name:
        raise RuntimeError("No function name to invoke; generation cannot be queued.")
    import boto3

    boto3.client("lambda").invoke(
        FunctionName=function_name,
        InvocationType="Event",
        Payload=json.dumps({"internal_job": True, "tenant_id": job["tenant_id"],
                            "job_id": job["job_id"]}).encode("utf-8"),
    )


def _read_job(event, jobs_repo):
    tenant_id = tenant_id_from_event(event)
    job_id = str(((event or {}).get("pathParameters") or {}).get("job_id") or "").strip()
    if not tenant_id or not job_id:
        return error_response("tenant_id and job_id are required.", code="missing_job")
    try:
        job = jobs_repo.get(tenant_id, job_id)
    except RepositoryError as exc:
        return error_response(str(exc), code="repository_error")
    if not job:
        return error_response("That generation was not found.", status_code=404, code="job_not_found")
    return json_response({"job": _public(job)})


def _run_job(event, *, jobs_repo, products_repo, offers_repo, pages_repo, usage_repo, events_repo, generator,
             now, pick):
    """The event path. Every exit updates the job, because a job stuck at `running` is indistinguishable
    from one still going, and the dashboard would poll forever."""
    tenant_id = str(event.get("tenant_id") or "")
    job = jobs_repo.get(tenant_id, str(event.get("job_id") or ""))
    if not job:
        return {"ok": False, "reason": "job_not_found"}
    if job.get("status") not in ("queued", None):
        return {"ok": True, "reason": "already_" + str(job.get("status"))}   # Lambda retries at-least-once

    brief, mode = job.get("brief") or {}, str(job.get("mode") or "test")
    jobs_repo.put({**job, "status": "running", "updated_at": now})
    usage_repo = usage_repo or ai_usage_repository()
    try:
        products_repo = products_repo or products_repository(mode=mode)
        offers_repo = offers_repo or offers_repository(mode=mode)
        pages_repo = pages_repo or pages_repository(mode=mode)
        result = _generate(brief, model=str(job.get("model") or ""),
                           provider=str(job.get("provider") or ""), generator=generator)
        if job.get("page_id"):
            saved = _rewrite(brief, result, tenant_id=tenant_id, page_id=str(job["page_id"]), now=now,
                             pages_repo=pages_repo, offers_repo=offers_repo)
        else:
            saved = _persist(brief, result, tenant_id=tenant_id, mode=mode, now=now, pick=pick,
                             products_repo=products_repo, offers_repo=offers_repo, pages_repo=pages_repo,
                             existing_product_id=str(job.get("product_id") or ""))
    except AiError as exc:
        _release(usage_repo, tenant_id, str(job.get("period") or ""), now)
        jobs_repo.put({**job, "status": "failed", "updated_at": now,
                       "error": {"code": f"generate_{exc.kind}", "message": _message_for(exc)}})
        # RELEASED, not failed: the slot was given back, so the ledger must not read as a generation the
        # tenant was charged for. That distinction is the whole reason the ledger records spend rather than
        # success.
        _complete_event(events_repo, job, events.completion(
            status=events.STATUS_RELEASED, at=now, error=f"generate_{exc.kind}"))
        return {"ok": False, "reason": exc.kind}
    except Exception as exc:  # noqa: BLE001 - any failure must reach the job, or the poller hangs
        _release(usage_repo, tenant_id, str(job.get("period") or ""), now)
        jobs_repo.put({**job, "status": "failed", "updated_at": now,
                       "error": {"code": "save_failed",
                                 "message": f"The page could not be saved: {exc}"}})
        _complete_event(events_repo, job, events.completion(
            status=events.STATUS_RELEASED, at=now, error="save_failed"))
        return {"ok": False, "reason": "save_failed"}

    jobs_repo.put({**job, "status": "complete", "updated_at": now, "result": {
        **saved, "decisions": result["decisions"], "classification": result["classification"],
        "generation": {"model": job.get("model"), "repairs": result["repairs"],
                       "tokens": result["usage"]}}})
    # What it actually cost. The token counts come back from the provider; the USD is OUR arithmetic over a
    # hand-maintained rate table, so `rate_confidence` travels with it and any display must say so
    # (plans/AI_AND_COMMERCE_ARCHITECTURE.md §A.9).
    tokens = result.get("usage") or {}
    priced = estimate_cost(str(job.get("model") or ""),
                           int(tokens.get("input") or 0), int(tokens.get("output") or 0))
    _complete_event(events_repo, job, events.completion(
        status=events.STATUS_SUCCEEDED, at=now,
        input_tokens=int(tokens.get("input") or 0), output_tokens=int(tokens.get("output") or 0),
        estimated_usd=priced["usd"], rate_confidence=priced["confidence"]))
    # Feed gate 3. Only platform-paid spend counts: a BYOK generation costs the platform nothing, and
    # counting it would pause everyone else over money we never spent.
    if str(job.get("source") or "") != "byok":
        _add_platform_spend(usage_repo, events.to_micros(priced["usd"]), now)
    return {"ok": True}


# How long a job may go without finishing before it is presumed dead. Generously above the measured
# 10-35 seconds and above the worker's own 60-second ceiling, because a job waiting behind the
# concurrency reservation is still perfectly healthy -- it just has not started yet.
STALE_AFTER_SECONDS = 900


def _reap(jobs_repo, *, usage_repo=None, now: int):
    """Fail jobs nothing is going to finish, and give the tenant their generation back.

    The refund is the point. A job Lambda dropped has cost the tenant a slot for work that never
    happened, and without this the only way to notice is a support ticket weeks later about an
    allowance that does not add up.
    """
    try:
        usage_repo = usage_repo or ai_usage_repository()
        candidates = jobs_repo.unfinished()
    except Exception as exc:  # noqa: BLE001 - a reaper that crashes silently is worse than none
        return {"ok": False, "reason": f"unreadable: {exc}"}

    reaped = 0
    for job in candidates:
        age = now - int(job.get("updated_at") or job.get("created_at") or now)
        if age < STALE_AFTER_SECONDS:
            continue
        tenant_id = str(job.get("tenant_id") or "")
        _release(usage_repo, tenant_id, str(job.get("period") or ""), now)
        try:
            jobs_repo.put({**job, "status": "failed", "updated_at": now, "error": {
                "code": "abandoned",
                "message": "That generation stopped unexpectedly and did not use one of your "
                           "generations. Try again."}})
            reaped += 1
        except Exception:  # noqa: BLE001 - one unwritable row must not strand the rest
            continue
    return {"ok": True, "reaped": reaped, "examined": len(candidates)}
