"""Postage folded into an order bump's price, and tracked back out of it.

A pre-purchase order bump is ticked by the buyer on Stripe's own hosted Checkout page, as an
`optional_items` line. That happens strictly AFTER `shipping_options` are fixed at session creation, and
Stripe cannot re-rate shipping when an optional item is added — so a bump's size and weight never reach
the postage quote.

Measured on a real order (2026-10-05): a cart quoted at 620c needed a bigger box and cost 669c once the
bump was in it, and the tenant absorbed the 49c. The same cart with five bump units cost 1354c against
the same 620c quote. Box sizes are cliffs, so the exposure is not bounded by pennies.

`shipping_surcharge` closes that gap the only way `optional_items` allow: by riding inside the bump's own
pre-synced Stripe Price, so only the buyers who TAKE the bump pay it.
"""
import json
import unittest

from handlers.checkout import order_bump_optional_items
from handlers.stripe_webhook import (
    bump_postage_collected,
    bump_postage_from_metadata,
    order_line_items_from_stripe,
)
from stripe_link.domain.ledger import sale_entry_from_order


BUMP_PRICE = "price_stripe_bump"


def _offer():
    return {"offer_id": "offer_1", "funnel": {"order_bumps": [{"product_id": "prod_1", "price_id": "pr_bump"}]}}


def _products(surcharge=49):
    price = {"price_id": "pr_bump", "currency": "usd", "unit_amount": 953,
             "context": "order_bump", "stripe_price_id": BUMP_PRICE}
    if surcharge is not None:
        price["shipping_surcharge"] = surcharge
    return {"prod_1": {"product_id": "prod_1", "stripe_mode": "test", "prices": [price]}}


class BumpSurchargeResolutionTests(unittest.TestCase):
    def test_the_resolver_reports_the_surcharge_alongside_the_price(self):
        bumps = order_bump_optional_items(_offer(), _products(49), "test")
        self.assertEqual(bumps, [(BUMP_PRICE, "pr_bump", 49)])

    def test_a_bump_without_a_surcharge_reports_zero(self):
        bumps = order_bump_optional_items(_offer(), _products(None), "test")
        self.assertEqual(bumps, [(BUMP_PRICE, "pr_bump", 0)])


class BumpPostageMetadataTests(unittest.TestCase):
    def test_round_trips_a_single_bump(self):
        self.assertEqual(bump_postage_from_metadata(f"{BUMP_PRICE}:49"), {BUMP_PRICE: 49})

    def test_round_trips_several(self):
        self.assertEqual(
            bump_postage_from_metadata("price_a:49,price_b:120"), {"price_a": 49, "price_b": 120})

    def test_an_absent_stamp_is_no_postage(self):
        for raw in (None, "", "   "):
            with self.subTest(raw=raw):
                self.assertEqual(bump_postage_from_metadata(raw), {})

    def test_a_malformed_pair_is_skipped_not_raised(self):
        """Classification must never cost the order.

        This stamp decides whether an amount is recorded as postage or as merchandise. Nothing about it
        should be able to stop a paid order being written, so a junk pair is dropped and the rest stands.
        """
        self.assertEqual(bump_postage_from_metadata("price_a:nope,price_b:120"), {"price_b": 120})


class BumpPostageCollectedTests(unittest.TestCase):
    def _lines(self, quantity=1, taken=True):
        stripe_lines = [
            {"description": "Creatine Gummies", "amount_total": 3900, "quantity": 1,
             "price": {"id": "price_main"}},
        ]
        if taken:
            stripe_lines.append({"description": "Protein Shaker Bottle", "amount_total": 1002 * quantity,
                                 "quantity": quantity, "price": {"id": BUMP_PRICE}})
        return order_line_items_from_stripe(stripe_lines, {BUMP_PRICE}, "usd")

    def test_counts_the_surcharge_when_the_bump_was_taken(self):
        self.assertEqual(bump_postage_collected(self._lines(), {BUMP_PRICE: 49}), 49)

    def test_counts_nothing_when_the_bump_was_declined(self):
        """The whole point of charging it this way: decliners are untouched."""
        self.assertEqual(bump_postage_collected(self._lines(taken=False), {BUMP_PRICE: 49}), 0)

    def test_scales_with_quantity(self):
        """The surcharge is per unit because the parcel growth that justified it is per unit."""
        self.assertEqual(bump_postage_collected(self._lines(quantity=3), {BUMP_PRICE: 49}), 147)

    def test_a_non_bump_line_never_contributes(self):
        lines = self._lines()
        self.assertEqual(bump_postage_collected(lines, {"price_main": 49}), 0)


class BumpPostageReachesTheLedgerTests(unittest.TestCase):
    """Because the point of collecting it is to see whether postage paid for itself."""

    def _order(self, **extra):
        return {"tenant_id": "t", "order_id": "order_1", "payment_intent_id": "pi_1",
                "amount_total": 15225, "currency": "usd", "created_at": 1700000000,
                "shipping_amount": 620, **extra}

    def test_bump_postage_is_shipping_revenue_not_product_revenue(self):
        entry = sale_entry_from_order(self._order(bump_shipping_amount=49), now_epoch=1700000000)
        self.assertEqual(entry["amounts"]["shipping_revenue"], 669)

    def test_an_order_without_a_bump_surcharge_is_unchanged(self):
        entry = sale_entry_from_order(self._order(), now_epoch=1700000000)
        self.assertEqual(entry["amounts"]["shipping_revenue"], 620)

    def test_it_does_not_inflate_gross(self):
        """`shipping_revenue` is a PARTITION of gross, so adding to it must not add to the total.

        The buyer paid the surcharge inside the bump's line, which `amount_total` already contains.
        """
        with_bump = sale_entry_from_order(self._order(bump_shipping_amount=49), now_epoch=1700000000)
        without = sale_entry_from_order(self._order(), now_epoch=1700000000)
        self.assertEqual(with_bump["amounts"]["gross"], without["amounts"]["gross"])


if __name__ == "__main__":
    unittest.main()


class BumpExposureSeesTheBoxTests(unittest.TestCase):
    """The exposure metric has to catch a bump that grows the box without adding a parcel.

    That is the case that actually produced a loss on 2026-10-05: one parcel before, one parcel after, and
    49c more postage because the one parcel had to be a Large instead of a Medium. A parcel COUNT reports
    zero exposure there, which is the most misleading possible answer — it says "free" about the only
    situation where the tenant is silently paying.
    """

    BOXES = [
        {"name": "Medium box (10x8x6)", "length": 10, "width": 8, "height": 6, "empty_weight": 0.35},
        {"name": "Large box (14x11x8)", "length": 14, "width": 11, "height": 8, "empty_weight": 0.6},
    ]

    def _product(self, product_id, length, width, height, weight=0.5):
        return {"product_id": product_id, "name": product_id, "product_type": "physical",
                "fulfillment": {"item_dimensions": {
                    "length_in": length, "width_in": width, "height_in": height, "weight_lb": weight}}}

    def test_a_bump_that_only_grows_the_box_is_still_reported(self):
        from handlers.shipping import _bump_exposure

        products = {"base": self._product("base", 9, 7, 5), "bump": self._product("bump", 6, 5, 4)}
        exposure = _bump_exposure([{"product_id": "base", "quantity": 1}],
                                  [{"product_id": "bump", "quantity": 1}], products, self.BOXES)
        self.assertEqual(exposure["bump_parcel_delta"], 0, "precondition: the parcel count must not move")
        self.assertIn("bump_box_change", exposure)
        self.assertEqual(exposure["bump_box_change"]["from"], ["Medium box (10x8x6)"])
        self.assertEqual(exposure["bump_box_change"]["to"], ["Large box (14x11x8)"])

    def test_a_bump_that_changes_nothing_reports_no_box_change(self):
        from handlers.shipping import _bump_exposure

        products = {"base": self._product("base", 9, 7, 5), "bump": self._product("bump", 5, 4, 3)}
        exposure = _bump_exposure([{"product_id": "base", "quantity": 1}],
                                  [{"product_id": "bump", "quantity": 1}], products, self.BOXES)
        self.assertEqual(exposure["bump_parcel_delta"], 0)
        self.assertNotIn("bump_box_change", exposure)

    def test_an_offer_without_bumps_reports_nothing(self):
        from handlers.shipping import _bump_exposure

        self.assertEqual(_bump_exposure([{"product_id": "base", "quantity": 1}], [], {}, self.BOXES), {})


class BumpPostageIsDestinationBoundTests(unittest.TestCase):
    """The suggestion must say WHERE it is for, because a flat surcharge cannot track a zone.

    One real offer, measured across US zones on 2026-10-05: 49c to Denver, 105c to New York and Miami,
    108c to Chicago and Los Angeles, 452c to Anchorage. A bare number invites a tenant to read it as THE
    number, and the one they are most likely to generate is the worst to use — the preview defaults to
    their own area, and a shipment to your own postcode is the cheapest zone there is.
    """

    class _Provider:
        pass

    def _delta(self, origin_zip, dest_zip):
        import handlers.shipping as shipping

        parcels = [{"box_name": "Large", "length": 14, "width": 11, "height": 8, "weight": 4.2}]
        original_pack, original_rate = shipping.pack, shipping.rate_parcels
        shipping.pack = lambda *a, **k: parcels
        shipping.rate_parcels = lambda *a, **k: {"error": "", "options": [{"amount": 669, "currency": "usd"}]}
        try:
            return shipping._bump_postage_delta(
                self._Provider(),
                from_address={"postal_code": origin_zip},
                destination={"postal_code": dest_zip},
                lines=[{"product_id": "p", "quantity": 1}],
                bump_lines=[{"product_id": "b", "quantity": 1}],
                products={}, boxes=[],
                base_rates=[{"amount": 620, "currency": "usd"}],
            )
        finally:
            shipping.pack, shipping.rate_parcels = original_pack, original_rate

    def test_it_names_the_destination_it_priced(self):
        out = self._delta("82009", "10001")["bump_postage"]
        self.assertEqual(out["amount"], 49)
        self.assertEqual(out["postal_code"], "10001")
        self.assertNotIn("rated_to_origin", out)

    def test_it_flags_a_quote_to_the_tenants_own_postcode(self):
        """The cheapest zone there is, so a surcharge set from it under-collects on every real order."""
        self.assertTrue(self._delta("82009", "82009")["bump_postage"]["rated_to_origin"])

    def test_the_origin_check_ignores_case_and_spacing(self):
        self.assertTrue(self._delta(" 82009 ", "82009")["bump_postage"]["rated_to_origin"])


class SuggestBumpPostageTests(unittest.TestCase):
    """Working the surcharge out instead of asking a tenant to type it.

    The number is the difference between two carrier quotes on two different box sizes, sampled across
    destinations. Nobody can estimate that, which made the manual field the weakest part of the remedy.
    """

    def setUp(self):
        import handlers.shipping as shipping

        self.shipping = shipping
        self.config = {
            "ship_from_address": {"postal_code": "82009", "country": "US", "city": "Cheyenne"},
            "provider": {"name": "shippo", "api_key_ref": "ref"},
            "boxes": [{"name": "Medium", "length": 10, "width": 8, "height": 6}],
        }
        self.offer = {
            "offer_id": "offer_1", "name": "Workout Bundle",
            "items": [{"product_id": "base", "quantity": 1}],
            "funnel": {"order_bumps": [{"product_id": "bump", "price_id": "pr_bump"}]},
        }
        self._pack = shipping.pack
        self._rate = shipping.rate_parcels
        self._provider_for = shipping.provider_for
        shipping.pack = lambda items, boxes: [{"box_name": "Medium"}]
        shipping.provider_for = lambda name, key: object()

    def tearDown(self):
        self.shipping.pack = self._pack
        self.shipping.rate_parcels = self._rate
        self.shipping.provider_for = self._provider_for

    def _call(self, body=None):
        class Repo:
            def __init__(self, config): self.config = config
            def get(self, tenant_id): return self.config

        class Cipher:
            def decrypt(self, *a, **k): return "key"

        class Offers:
            def __init__(self, offers): self.offers = offers
            def list_for_tenant(self, tenant_id): return self.offers

        class Products:
            def get(self, tenant_id, product_id):
                return {"product_id": product_id, "name": product_id, "product_type": "physical"}

        subject = body if body is not None else {"product_id": "bump"}
        event = {"httpMethod": "POST", "path": "/shipping/rate-preview",
                 "queryStringParameters": {"tenant_id": "t"},
                 "body": json.dumps({"bump_postage_for": subject})}
        return self.shipping.handler(event, None, repository=Repo(self.config), secret_cipher=Cipher(),
                                     products_repo=Products(), offers_repo=Offers([self.offer]))

    def test_it_suggests_the_widest_sampled_result(self):
        """The widest, so the one flat figure covers the sampled range rather than its luckiest corner."""
        deltas = {"10001": 105, "90012": 108, "60602": 108, "33133": 105}

        # Keyed on WHAT is in the parcel, not on call order: the samples are rated in parallel, so a
        # fake that alternates would be racing the thread pool and could pass by luck.
        self.shipping.pack = lambda items, boxes: [{"box_name": "Medium", "items": len(items)}]

        def fake(provider, *, from_address, to_address, parcels):
            with_bump = parcels[0]["items"] > 1
            amount = 1000 + (deltas[str(to_address.get("postal_code"))] if with_bump else 0)
            return {"error": "", "options": [{"amount": amount, "currency": "usd"}]}

        self.shipping.rate_parcels = fake
        response = self._call()
        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["offer"]["name"], "Workout Bundle")
        self.assertEqual(len(body["samples"]), 4)
        self.assertEqual(body["suggested"], 108)
        self.assertEqual(body["lowest"], 105)
        self.assertEqual({s["postal_code"]: s["amount"] for s in body["samples"]}, deltas)

    def test_it_never_rates_to_the_tenants_own_postcode(self):
        """A shipment to your own door is the cheapest zone there is; a surcharge from it under-collects."""
        self.config["ship_from_address"]["postal_code"] = "10001"
        seen = []

        def fake(provider, *, from_address, to_address, parcels):
            seen.append(str(to_address.get("postal_code")))
            return {"error": "", "options": [{"amount": 1000, "currency": "usd"}]}

        self.shipping.rate_parcels = fake
        self._call()
        self.assertNotIn("10001", seen)
        self.assertTrue(seen, "it must still rate the other samples")

    def test_a_product_that_is_not_a_bump_anywhere_is_told_why(self):
        """Postage for a bump is meaningless without the order it rides in, so this is a real answer."""
        response = self._call({"product_id": "not_a_bump"})
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "no_bump_offer")

    def test_one_dead_sample_does_not_lose_the_others(self):
        def fake(provider, *, from_address, to_address, parcels):
            if str(to_address.get("postal_code")) == "60602":
                return {"error": "carrier said no", "options": []}
            return {"error": "", "options": [{"amount": 1000, "currency": "usd"}]}

        self.shipping.rate_parcels = fake
        body = json.loads(self._call()["body"])
        self.assertEqual(len(body["samples"]), 3)

    def test_every_sample_failing_is_an_error_not_a_zero(self):
        """A silent 0 here would be written into the price and charged forever."""
        self.shipping.rate_parcels = lambda *a, **k: {"error": "down", "options": []}
        self.assertEqual(self._call()["statusCode"], 502)

    def test_nothing_measurable_ships_free_rather_than_erroring(self):
        self.shipping.pack = lambda items, boxes: []
        body = json.loads(self._call()["body"])
        self.assertTrue(body["ships_free"])
        self.assertEqual(body["suggested"], 0)


class BumpPostageSharesTheRatePreviewRouteTests(unittest.TestCase):
    """Two questions on one route, because a second route does not fit.

    Adding `/shipping/bump-postage` as its own endpoint made the transformed stack exceed
    CloudFormation's hard 1,000,000-byte SAM limit — the deploy was refused outright on 2026-10-05. The
    split therefore lives in the body, and the ordinary rate preview must keep working untouched.
    """

    def _event(self, body):
        return {"httpMethod": "POST", "path": "/shipping/rate-preview",
                "queryStringParameters": {"tenant_id": "t"}, "body": json.dumps(body)}

    def test_a_plain_preview_still_reaches_preview_rates(self):
        import handlers.shipping as shipping

        seen = {}
        original = shipping.preview_rates
        shipping.preview_rates = lambda *a, **k: seen.setdefault("called", True)
        try:
            shipping.handler(self._event({"offer_id": "offer_1"}), None,
                             repository=type("R", (), {"get": lambda s, t: {}})(),
                             secret_cipher=object())
        finally:
            shipping.preview_rates = original
        self.assertTrue(seen.get("called"), "a body without bump_postage_for is an ordinary rate preview")

    def test_the_bump_question_reaches_the_suggester(self):
        import handlers.shipping as shipping

        seen = {}
        original = shipping.suggest_bump_postage
        shipping.suggest_bump_postage = lambda *a, **k: seen.setdefault("called", True)
        try:
            shipping.handler(self._event({"bump_postage_for": {"product_id": "bump"}}), None,
                             repository=type("R", (), {"get": lambda s, t: {}})(),
                             secret_cipher=object())
        finally:
            shipping.suggest_bump_postage = original
        self.assertTrue(seen.get("called"))
