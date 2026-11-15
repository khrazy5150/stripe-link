"""The paid offer shown the instant a FREE registration succeeds (plans/POST_REGISTRATION_OFFER.md P1).

The whole feature rests on one guarantee: a `post_registration` price can never reach the one-click charge.
That stage exists for a buyer whose card is already attached to a PaymentIntent. A registrant has handed
over an email address and nothing else, so one-clicking them produces a failed charge, not a sale.

Two independent allowlists already enforce it — `post_purchase_plan` selects on `upsell`/`downsell`, and
`process_upsell` refuses anything outside `allowed_price_contexts`. Neither was written with this context in
mind, which is exactly why both are asserted here: a guarantee that holds by coincidence is one nobody
notices breaking. The listicle test covers the opposite failure, a DENYlist that lets a new context through
because it has never heard of it.
"""
import unittest

from stripe_link.domain.funnels import (
    POST_REGISTRATION_CONTEXT,
    post_purchase_plan,
    post_registration_offer,
)
from stripe_link.domain.opportunities import (
    STAGE_POST_REGISTRATION,
    opportunities_from_offer,
    stage_opportunities,
)
from stripe_link.domain.pricing import _LISTICLE_EXCLUDED_CONTEXTS


def _product(product_id, prices):
    return {"product_id": product_id, "name": product_id, "prices": prices}


PREP_KIT = _product("prod_kit", [
    {"price_id": "price_kit_reg", "context": "post_registration", "unit_amount": 2700, "currency": "usd"},
    {"price_id": "price_kit_std", "context": "standard", "unit_amount": 14700, "currency": "usd"},
])


class WhatRegistrationOffers(unittest.TestCase):
    def setUp(self):
        self.products = {"prod_kit": PREP_KIT}
        # A webinar offer: the registration itself is free, so the only opportunity is the paid add-on.
        self.offer = {"purchase_opportunities": [
            {"stage": STAGE_POST_REGISTRATION, "product_id": "prod_kit", "price_id": "price_kit_reg",
             "quantity": 1, "placement": {"surface": "upsell"}},
        ]}

    def test_the_post_registration_price_is_what_gets_offered(self):
        found = post_registration_offer(self.offer, self.products)
        self.assertEqual((found["product_id"], found["price_id"]), ("prod_kit", "price_kit_reg"))

    def test_the_offer_is_the_27_dollar_price_not_the_147_dollar_one(self):
        # The product carries both; the context picks which one the button may quote.
        self.assertEqual(post_registration_offer(self.offer, self.products)["price"]["unit_amount"], 2700)

    def test_a_product_without_that_context_is_not_an_offer(self):
        plain = {"prod_kit": _product("prod_kit", [
            {"price_id": "price_kit_std", "context": "standard", "unit_amount": 14700, "currency": "usd"},
        ])}
        self.assertIsNone(post_registration_offer(self.offer, plain))

    def test_deleting_the_price_retires_the_offer_with_no_offer_re_save(self):
        # Why this is derived from pricing rather than stored on the offer: the offer document below still
        # names the opportunity, and it must stop resolving the moment the price goes.
        gone = {"prod_kit": _product("prod_kit", [
            {"price_id": "price_kit_std", "context": "standard", "unit_amount": 14700, "currency": "usd"},
        ])}
        self.assertIsNone(post_registration_offer(self.offer, gone))
        self.assertEqual(len(stage_opportunities(self.offer, STAGE_POST_REGISTRATION)), 1)

    def test_an_offer_with_nothing_to_sell_offers_nothing(self):
        self.assertIsNone(post_registration_offer({}, self.products))


class ItCanNeverBeOneClickCharged(unittest.TestCase):
    """The load-bearing guarantee. Both allowlists, asserted separately."""

    def setUp(self):
        self.products = {"prod_kit": PREP_KIT}
        self.offer = {"purchase_opportunities": [
            {"stage": STAGE_POST_REGISTRATION, "product_id": "prod_kit", "price_id": "price_kit_reg",
             "quantity": 1, "placement": {"surface": "upsell"}},
        ]}

    def test_the_post_purchase_plan_does_not_see_it(self):
        # post_purchase_plan feeds the one-click charge. It selects on upsell/downsell contexts, and
        # `offer_product_ids` hands it EVERY product the offer touches -- including this one -- so the
        # context is the only thing keeping it out.
        plan = post_purchase_plan(self.offer, self.products)
        self.assertEqual(plan["upsells"], [])

    def test_the_one_click_handler_refuses_the_context(self):
        # process_upsell builds its charge with allowed_price_contexts; anything outside is rejected by
        # resolve_offer_item before a card is touched.
        import inspect

        from handlers import upsell

        source = inspect.getsource(upsell.process_upsell)
        self.assertIn('"allowed_price_contexts": ["upsell", "downsell"]', source)
        self.assertNotIn(POST_REGISTRATION_CONTEXT, source)

    def test_a_product_that_is_both_still_upsells_normally(self):
        # Selling the same product in two places is legitimate. The post-purchase upsell must keep working,
        # and must quote its OWN price rather than the registration one.
        both = {"prod_kit": _product("prod_kit", [
            {"price_id": "price_kit_reg", "context": "post_registration", "unit_amount": 2700, "currency": "usd"},
            {"price_id": "price_kit_up", "context": "upsell", "unit_amount": 4700, "currency": "usd"},
        ])}
        plan = post_purchase_plan(self.offer, both)
        self.assertEqual([u["price_id"] for u in plan["upsells"]], ["price_kit_up"])
        self.assertEqual(post_registration_offer(self.offer, both)["price_id"], "price_kit_reg")


class ItNeverLeaksOntoThePage(unittest.TestCase):
    def test_the_listicle_denylist_knows_about_it(self):
        # The one place a new context leaks rather than being refused: landing resolution allowlists
        # standard/sale/flash_sale, but listicle slides are chosen by EXCLUSION. A context missing from that
        # set becomes a buyable slide on the registration page itself -- the offer shown before the
        # registration it is supposed to follow.
        self.assertIn(POST_REGISTRATION_CONTEXT, _LISTICLE_EXCLUDED_CONTEXTS)

    def test_the_stage_is_not_a_landing_opportunity(self):
        offer = {"purchase_opportunities": [
            {"stage": STAGE_POST_REGISTRATION, "product_id": "prod_kit", "price_id": "price_kit_reg",
             "quantity": 1},
        ]}
        self.assertEqual(stage_opportunities(offer, "landing"), [])
        self.assertEqual(len(opportunities_from_offer(offer)), 1)


if __name__ == "__main__":
    unittest.main()
