"""Suggested Search ad copy: `operation: "ads_copy"` on POST /ai/generate.

The gates and the ledger are `generate_copy`'s and are tested there; these cover what is new: the offer
grounds the prompt, Google's limits are enforced on the answer rather than trusted, and an answer that cannot
fill Google's minimums gives the tenant their generation back.
"""

import json
import unittest

from handlers.ai_generate import handler
from stripe_link.domain import ads_copy
from test_generate_copy_operation import Config, Jobs, Tenants, Usage, body_of

TENANT = "t1"
OFFER = {"offer_id": "o1", "tenant_id": TENANT, "name": "Deep Tissue Massage",
         "purchase_opportunities": [{"stage": "landing", "product_id": "p1"}]}
PRODUCT = {"product_id": "p1", "name": "Deep Tissue Massage", "description": "A 60-minute deep tissue massage."}
ANSWER = {
    "headlines": ["Deep Tissue Massage", "Massage in St. George", "Book a 60-Minute Session",
                  "THIS HEADLINE IS FAR TOO LONG FOR GOOGLE ADS", "Deep tissue massage"],
    "descriptions": ["A 60-minute deep tissue massage in St. George.", "Book online in minutes."],
    "keywords": ["Deep Tissue Massage St George", "massage st george"],
    "phrase_keywords": ["deep tissue massage", "massage st george"],
    "negative_keywords": ["free", "jobs", "massage st george"],
}


class Offers:
    def __init__(self, offer=OFFER):
        self.offer = offer

    def get(self, _tenant, _offer_id):
        return dict(self.offer) if self.offer else None


class Products:
    def get(self, _tenant, product_id):
        return dict(PRODUCT) if product_id == "p1" else None


def run(*, answer=ANSWER, offers=None, usage=None, captured=None, **body):
    usage = usage or Usage()

    def generator(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return {"value": answer}

    response = handler(
        {"httpMethod": "POST", "queryStringParameters": {"tenant_id": TENANT},
         "body": json.dumps({"operation": "ads_copy", "offer_id": "o1", "place": "St. George, Utah",
                             "objective": "leads", "mode": "test", **body})},
        None, config_repo=Config(), usage_repo=usage, jobs_repo=Jobs(), tenant_repo=Tenants(),
        offers_repo=offers or Offers(), products_repo=Products(), generator=generator, now_fn=lambda: 1_793_000_000,
    )
    return response, usage


class SuggestedAdCopy(unittest.TestCase):
    def test_the_suggestion_fits_googles_limits(self):
        response, usage = run()
        suggestion = body_of(response)["suggestion"]
        # Too long is dropped (not cut mid-word); a case-only repeat is dropped.
        self.assertEqual(suggestion["headlines"], ["Deep Tissue Massage", "Massage in St. George", "Book a 60-Minute Session"])
        self.assertEqual(suggestion["keywords"], ["deep tissue massage st george", "massage st george"])
        # A phrase keyword already exact, and a negative that would block a keyword, are both removed.
        self.assertEqual(suggestion["phrase_keywords"], ["deep tissue massage"])
        self.assertEqual(suggestion["negative_keywords"], ["free", "jobs"])
        self.assertEqual((usage.taken, usage.released), (1, 0))

    def test_the_offer_and_place_ground_the_prompt_and_it_is_buyer_facing(self):
        captured = {}
        run(captured=captured)
        self.assertIn("Deep Tissue Massage", captured["prompt"])
        self.assertIn("A 60-minute deep tissue massage.", captured["prompt"])
        self.assertIn("St. George, Utah", captured["prompt"])
        self.assertIn("enquiries", captured["prompt"])
        self.assertTrue(captured["for_page"])
        self.assertNotIn("maxItems", json.dumps(captured["json_schema"]))

    def test_an_answer_short_of_googles_minimums_is_refunded(self):
        response, usage = run(answer={**ANSWER, "headlines": ["Only one"]})
        self.assertFalse(body_of(response)["generated"])
        self.assertEqual((usage.taken, usage.released), (1, 1))

    def test_a_model_with_nothing_to_be_about_is_not_usable(self):
        """The handler declines these before touching the counter."""
        for model in (None, {}, {"facts": {"entities": {"primary": {"name": "  "}}}}):
            self.assertFalse(ads_copy.usable(model))

    def test_a_missing_offer_is_not_found(self):
        response, usage = run(offers=Offers(None))
        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(usage.taken, 0)


class Parse(unittest.TestCase):
    def test_non_objects_produce_nothing(self):
        for answer in (None, [], "text"):
            self.assertEqual(ads_copy.parse(answer), {})
