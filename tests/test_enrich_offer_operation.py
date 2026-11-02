"""The enrichment trigger: `operation: "enrich_offer"` on POST /ai/generate.

Folded onto that route rather than given its own, for the reason the image operation already records in
the handler — 225 Api events against a guard that trips at 240, and it is the same question about a
different thing. The tests that matter are the gates and the ledger, not the copy.
"""

import json
import unittest

from handlers.ai_generate import handler
from stripe_link.domain.semantic import MODEL_VERSION

TENANT = "t1"
OFFER = {
    "offer_id": "o1", "tenant_id": TENANT, "product_intent": "transaction",
    "purchase_opportunities": [{"stage": "landing", "product_id": "p1",
                                "prices": [{"price_id": "pr1"}]}],
}
PRODUCT = {"product_id": "p1", "tenant_id": TENANT, "name": "Whey Protein Isolate",
           "product_category": "dietary_supplement",
           "prices": [{"price_id": "pr1", "unit_amount": 4999, "currency": "usd"}]}

ANSWER = {
    "problems": ["Shakes clump"], "misconceptions": ["Isolate equals concentrate"],
    "transformations": ["From skipped recovery to a shake in seconds"],
    "objections": ["Two kilos is a commitment"],
    "audience": "lifters", "urgency": "", "acquisition": "searching for protein",
    "hierarchy": ["Health", "Supplements", "Protein"],
    "key_concepts": [{"value": "post-workout", "weight": 0.9}],
}


def event(**body):
    return {"httpMethod": "POST", "queryStringParameters": {"tenant_id": TENANT},
            "body": json.dumps({"operation": "enrich_offer", "offer_id": "o1", **body})}


class Offers:
    def __init__(self, offer=None):
        self.offer = dict(offer) if offer else None
        self.saved = None

    def get(self, _tenant, offer_id):
        return dict(self.offer) if self.offer and self.offer["offer_id"] == offer_id else None

    def put(self, document):
        self.saved = document
        return document


class Products:
    def get(self, _tenant, product_id):
        return dict(PRODUCT) if product_id == "p1" else None


class Config:
    def __init__(self, provider="bedrock"):
        self._provider = provider

    def get(self, _tenant):
        return {"provider": self._provider, "model": "sonnet-4.6"} if self._provider else {}


class Usage:
    """Mirrors the real counter's contract: `consume_if_available` decides inside the write."""

    def __init__(self, allowed=True):
        self.allowed = allowed
        self.taken = 0
        self.released = 0

    def consume_if_available(self, _tenant, _period, *, allowance=0, at=0, **_kw):
        if not self.allowed:
            return {"allowed": False, "used": allowance}
        self.taken += 1
        return {"allowed": True, "used": self.taken}

    def release(self, _tenant, _period, *, at=0):
        self.released += 1

    def list_for_tenant(self, _tenant):
        return []

    def get(self, *_a, **_k):
        return None


class Jobs:
    """Resolved at the top of `handler` for the reaper and internal-job paths, before any dispatch.
    Enrichment never touches it, but the function always has the table in production."""

    def get(self, *_a, **_k):
        return None

    def put(self, document):
        return document


class Tenants:
    def __init__(self, profile=None):
        self.profile = profile or {"tenant_id": TENANT, "billing_exempt": True,
                                   "business_name": "Poliaxis Nutrition"}

    def get(self, _tenant, _document_id=None):
        """TWO arguments. `_profile` calls `get(tenant_id, tenant_id)` because a profile is keyed by its
        own id; a one-argument fake raises TypeError, the handler swallows it, and every tenant silently
        looks profile-less — which is the trap `_profile`'s own docstring was written about."""
        return dict(self.profile)


def run(*, offers=None, usage=None, config=None, generator=None, tenants=None, **body):
    offers = offers if offers is not None else Offers(OFFER)
    usage = usage or Usage()
    response = handler(event(**body), None, offers_repo=offers, products_repo=Products(),
                       config_repo=config or Config(), usage_repo=usage, jobs_repo=Jobs(),
                       tenant_repo=tenants or Tenants(), generator=generator,
                       now_fn=lambda: 1_793_000_000)
    return response, offers, usage


def answering(value=ANSWER):
    def gen(**_kwargs):
        return {"value": value}
    return gen


class TheHappyPath(unittest.TestCase):
    def test_it_enriches_and_saves_onto_the_offer(self):
        response, offers, usage = run(generator=answering())
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(body["enriched"])
        self.assertTrue(body["saved"])
        self.assertEqual(offers.saved["semantic_model"]["facts"]["positioning"]["problems"],
                         ["Shakes clump"])
        self.assertEqual(usage.taken, 1)
        self.assertEqual(usage.released, 0)

    def test_the_saved_model_is_a_current_ai_one(self):
        """`resolve_semantic_model` returns a cached model only when it is AI and current, so a write
        that got either wrong would be silently recomputed on every read."""
        _, offers, _ = run(generator=answering())
        interpretation = offers.saved["semantic_model"]["interpretation"]
        self.assertEqual(interpretation["source"], "ai")
        self.assertEqual(interpretation["version"], MODEL_VERSION)

    def test_the_tenant_business_name_reaches_the_prompt(self):
        seen = {}

        def gen(**kwargs):
            seen.update(kwargs)
            return {"value": ANSWER}

        run(generator=gen)
        self.assertIn("Poliaxis Nutrition", seen["prompt"])
        self.assertEqual(seen["model"], "sonnet-4.6")
        self.assertEqual(seen["provider"], "bedrock")


class TheLedger(unittest.TestCase):
    """Debit first, refund on anything that did not produce enrichment."""

    def test_a_model_that_says_nothing_releases_the_slot(self):
        empty = {k: ([] if isinstance(v, list) else "") for k, v in ANSWER.items()}
        response, offers, usage = run(generator=answering(empty))
        body = json.loads(response["body"])
        self.assertFalse(body["enriched"])
        self.assertEqual(usage.released, 1)
        self.assertIsNone(offers.saved)

    def test_a_failing_provider_releases_the_slot(self):
        def boom(**_kwargs):
            raise RuntimeError("bedrock is unhappy")
        response, _, usage = run(generator=boom)
        self.assertEqual(response["statusCode"], 200)
        self.assertFalse(json.loads(response["body"])["enriched"])
        self.assertEqual(usage.released, 1)

    def test_the_deterministic_model_is_returned_when_nothing_was_produced(self):
        """The tenant pressed a button and must get an answer, not an error about someone else's outage."""
        response, _, _ = run(generator=answering({}))
        model = json.loads(response["body"])["semantic_model"]
        self.assertEqual(model["interpretation"]["source"], "deterministic")
        self.assertEqual(model["facts"]["positioning"]["problems"], [])

    def test_a_storage_failure_keeps_the_slot_but_returns_the_work(self):
        """The call was made and the tokens spent, so releasing would refund a real cost — but the tenant
        should not lose the result to a failure they cannot act on."""
        class Failing(Offers):
            def put(self, document):
                from stripe_link.repositories.documents import RepositoryError
                raise RepositoryError("table is unhappy")

        response, _, usage = run(offers=Failing(OFFER), generator=answering())
        body = json.loads(response["body"])
        self.assertTrue(body["enriched"])
        self.assertFalse(body["saved"])
        self.assertEqual(usage.released, 0)


class TheGates(unittest.TestCase):
    def test_no_provider_configured_is_refused_before_the_counter(self):
        response, _, usage = run(config=Config(provider=""), generator=answering())
        self.assertEqual(json.loads(response["body"])["error"], "ai_not_configured")
        self.assertEqual(usage.taken, 0)

    def test_an_exhausted_allowance_is_refused(self):
        response, offers, _ = run(usage=Usage(allowed=False), generator=answering())
        self.assertEqual(response["statusCode"], 429)
        self.assertIsNone(offers.saved)

    def test_a_plan_without_ai_builder_is_refused_before_the_counter(self):
        """Asked first so the refusal says "not on your plan" rather than "you have used 0 of 0"."""
        usage = Usage()
        response, _, _ = run(usage=usage, generator=answering(),
                             tenants=Tenants({"tenant_id": TENANT, "billing_status": "inactive"}))
        self.assertEqual(response["statusCode"], 403)
        self.assertEqual(usage.taken, 0)

    def test_a_missing_offer_id_is_refused(self):
        response = handler({"httpMethod": "POST",
                            "queryStringParameters": {"tenant_id": TENANT},
                            "body": json.dumps({"operation": "enrich_offer"})}, None,
                           offers_repo=Offers(OFFER), products_repo=Products(), jobs_repo=Jobs(),
                           config_repo=Config(), usage_repo=Usage(), tenant_repo=Tenants())
        self.assertEqual(json.loads(response["body"])["error"], "missing_offer")

    def test_an_unknown_offer_is_a_404(self):
        response, _, usage = run(offers=Offers(None), generator=answering())
        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(usage.taken, 0)


class TheButtonIsGatedToo(unittest.TestCase):
    """The server refuses an unentitled or exhausted tenant (TheGates above). The BUTTON should not offer
    the click in the first place -- but disabling alone is the weaker fix, because a greyed button with no
    explanation tells a tenant nothing and the two reasons need different actions: "not on your plan" is
    an upgrade, "used them all" is a wait."""

    @property
    def offers(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[1]
                / "dashboard" / "src" / "components" / "Offers.vue").read_text()

    def test_the_button_is_disabled_when_the_tenant_cannot_generate(self):
        self.assertIn('"enriching || !canEnrich"', self.offers)

    def test_it_shows_the_SERVER_s_sentence_rather_than_rewording_it(self):
        """`ai_quota.may_generate` already writes the refusal, and its docstring says why it is the
        tenant's text rather than a log line. A second wording here would drift from it."""
        self.assertIn("enrichBlockedReason", self.offers)
        self.assertIn("enrichUsage.value.reason", self.offers)

    def test_it_is_PERMISSIVE_when_the_allowance_is_unknown(self):
        """If the usage call has not answered, the button stays enabled and the server refuses -- which it
        does anyway, with the better message. Disabling on an absent answer would block an entitled tenant
        because an unrelated fetch was slow, which is reading an absence as a verdict."""
        self.assertIn("can_generate !== false", self.offers)

    def test_the_remaining_count_is_hidden_for_a_tenant_on_their_own_key(self):
        """Their allowance is a safety ceiling, not a ration; counting it down reads as a limit they
        bought."""
        self.assertIn("billedToTenant", self.offers)

    def test_the_usage_is_not_fetched_until_an_offer_is_opened(self):
        """A tenant who never touches the panel should not pay for the call."""
        block = self.offers.split("function openOfferModal(", 1)[1][:500]
        self.assertIn("aiProviderStore.load()", block)


class ItDoesNotDisturbTheOtherOperations(unittest.TestCase):
    def test_the_operation_is_opt_in(self):
        """A body without `operation` must still reach the page path — this route's original job."""
        response = handler({"httpMethod": "POST",
                            "queryStringParameters": {"tenant_id": TENANT},
                            "body": json.dumps({"offer_id": "o1"})}, None,
                           offers_repo=Offers(OFFER), products_repo=Products(), jobs_repo=Jobs(),
                           config_repo=Config(), usage_repo=Usage(), tenant_repo=Tenants())
        self.assertNotEqual(json.loads(response["body"]).get("enriched"), True)

    def test_it_adds_no_api_route(self):
        """The whole point of folding it on. 240 is where the guard trips."""
        import pathlib
        template = (pathlib.Path(__file__).resolve().parents[1] / "template.yaml").read_text()
        self.assertNotIn("enrich", template.lower().split("events:")[0])
        self.assertLess(template.count("Type: Api"), 240)


if __name__ == "__main__":
    unittest.main()
