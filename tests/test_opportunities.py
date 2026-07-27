import unittest

from stripe_link.domain.opportunities import (
    STAGE_CHECKOUT,
    STAGE_LANDING,
    STAGE_POST_PURCHASE,
    derived_offer_type,
    landing_presentation,
    opportunities_from_offer,
    stage_opportunities,
)


def _legacy_offer(items, funnel=None):
    offer = {"offer_id": "offer_x", "items": items}
    if funnel is not None:
        offer["funnel"] = funnel
    return offer


class LegacyAdapterTests(unittest.TestCase):
    def test_items_become_landing_primary_opportunities_preserving_fields(self):
        offer = _legacy_offer([
            {"product_id": "p1", "price_id": "price_1", "quantity": 2, "label": "Two"},
        ])
        opps = opportunities_from_offer(offer)
        self.assertEqual(len(opps), 1)
        opp = opps[0]
        self.assertEqual(opp["stage"], STAGE_LANDING)
        self.assertEqual(opp["placement"]["surface"], "primary")
        self.assertEqual(opp["placement"]["order"], 0)
        # item fields preserved verbatim
        self.assertEqual(opp["product_id"], "p1")
        self.assertEqual(opp["price_id"], "price_1")
        self.assertEqual(opp["quantity"], 2)
        self.assertEqual(opp["label"], "Two")

    def test_funnel_maps_to_checkout_and_post_purchase_stages(self):
        offer = _legacy_offer(
            [{"product_id": "main", "price_id": "price_main", "quantity": 1}],
            funnel={
                "order_bumps": [{"product_id": "bump", "price_id": "price_bump"}],
                "upsells": [{"product_id": "up", "price_id": "price_up"}],
                "downsells": [{"product_id": "down", "price_id": "price_down"}],
            },
        )
        by_surface = {o["placement"]["surface"]: o for o in opportunities_from_offer(offer)}
        self.assertEqual(by_surface["order_bump"]["stage"], STAGE_CHECKOUT)
        self.assertEqual(by_surface["upsell"]["stage"], STAGE_POST_PURCHASE)
        self.assertEqual(by_surface["upsell"]["placement"]["strategy"], "sequence")  # default per plan
        self.assertEqual(by_surface["downsell"]["stage"], STAGE_POST_PURCHASE)
        self.assertEqual(by_surface["order_bump"]["product_id"], "bump")
        # Funnel opportunities carry a single-unit quantity so each is a valid offer item.
        self.assertEqual(by_surface["order_bump"]["quantity"], 1)
        self.assertEqual(by_surface["upsell"]["quantity"], 1)

    def test_stage_filter(self):
        offer = _legacy_offer(
            [{"product_id": "m", "price_id": "pm", "quantity": 1}],
            funnel={"order_bumps": [{"product_id": "b", "price_id": "pb"}]},
        )
        self.assertEqual(len(stage_opportunities(offer, STAGE_LANDING)), 1)
        self.assertEqual(len(stage_opportunities(offer, STAGE_CHECKOUT)), 1)
        self.assertEqual(stage_opportunities(offer, STAGE_POST_PURCHASE), [])


class DerivationTests(unittest.TestCase):
    def test_single_product_single_price(self):
        offer = _legacy_offer([{"product_id": "p", "price_id": "pr", "quantity": 1}])
        self.assertEqual(landing_presentation(offer), {"kind": "single", "checkout": "single"})
        self.assertEqual(derived_offer_type(offer), "single")

    def test_single_product_tiered(self):
        offer = _legacy_offer([{"product_id": "p", "default_price_id": "a", "selectable_prices": [
            {"price_id": "a", "quantity": 1}, {"price_id": "b", "quantity": 3},
        ]}])
        self.assertEqual(landing_presentation(offer), {"kind": "tiered", "checkout": "single"})
        self.assertEqual(derived_offer_type(offer), "bundle")

    def test_multiple_products_carousel_cart(self):
        offer = _legacy_offer([
            {"product_id": "a", "price_id": "pa", "quantity": 1},
            {"product_id": "b", "price_id": "pb", "quantity": 1},
        ])
        self.assertEqual(landing_presentation(offer), {"kind": "carousel", "checkout": "cart"})
        self.assertEqual(derived_offer_type(offer), "listicle")

    def test_stored_offer_type_wins_when_present(self):
        # Migration shim: an explicit stored offer_type is preserved (behavior-preserving), even if the
        # opportunities alone would derive differently.
        self.assertEqual(derived_offer_type({"offer_type": "listicle", "items": []}), "listicle")
        self.assertEqual(derived_offer_type({"offer_type": "bundle", "items": [{"product_id": "p", "price_id": "x", "quantity": 1}]}), "bundle")

    def test_derived_type_matches_legacy_inference_ignoring_funnel(self):
        # A bump/upsell must NOT inflate the landing presentation (they aren't landing opportunities).
        offer = _legacy_offer(
            [{"product_id": "p", "price_id": "pr", "quantity": 1}],
            funnel={"order_bumps": [{"product_id": "b", "price_id": "pb"}], "upsells": [{"product_id": "u", "price_id": "pu"}]},
        )
        self.assertEqual(derived_offer_type(offer), "single")


class NewModelTests(unittest.TestCase):
    def test_existing_purchase_opportunities_are_returned_and_normalized(self):
        offer = {"purchase_opportunities": [
            {"stage": "landing", "product_id": "p", "price_id": "pr"},  # missing placement
            {"stage": "post_purchase", "placement": {"surface": "upsell", "strategy": "carousel"}, "product_id": "u", "price_id": "pu"},
        ]}
        opps = opportunities_from_offer(offer)
        self.assertEqual(len(opps), 2)
        self.assertEqual(opps[0]["placement"]["surface"], "primary")  # defaulted
        self.assertEqual(opps[1]["placement"]["strategy"], "carousel")  # preserved

    def test_empty_or_bad_offer(self):
        self.assertEqual(opportunities_from_offer({}), [])
        self.assertEqual(opportunities_from_offer(None), [])
        self.assertEqual(landing_presentation({}), {"kind": "none", "checkout": "single"})


class DualWriteValidityTests(unittest.TestCase):
    """The P2b editor writes purchase_opportunities as the adapter would derive them (a JS mirror of
    opportunities_from_offer). This guards that mirror's target: every opportunity the adapter produces from a
    legacy offer is itself a VALID purchase opportunity — so the dual-written array always validates."""

    def test_adapter_output_passes_opportunity_validation(self):
        from stripe_link.domain.documents import validate_purchase_opportunities

        offer = _legacy_offer(
            [
                {"product_id": "p1", "price_id": "price_1", "quantity": 1},
                {"product_id": "p2", "default_price_id": "a", "selectable_prices": [
                    {"price_id": "a", "quantity": 1}, {"price_id": "b", "quantity": 3},
                ]},
            ],
            funnel={
                "order_bumps": [{"product_id": "bump", "price_id": "price_bump"}],
                "upsells": [{"product_id": "up", "price_id": "price_up"}],
                "downsells": [{"product_id": "down", "price_id": "price_down"}],
            },
        )
        opps = opportunities_from_offer(offer)
        # Must not raise — the exact array the editor dual-writes onto the document.
        validate_purchase_opportunities({"product_intent": "transaction"}, opps)


if __name__ == "__main__":
    unittest.main()
