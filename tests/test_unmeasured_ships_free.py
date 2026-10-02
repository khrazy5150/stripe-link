"""No measurements, no price: an unmeasured product ships free rather than being charged for.

plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P0a. The calculator did not invent a parcel from nothing -- which
was worse, because the result looked legitimate. `shipping_packing`'s `declared` strategy fired as a SILENT
fallback whenever item dimensions were missing, reading `fulfillment.dimensions` even with `ships_alone`
unchecked. Dev data carried the identical 10x8x4 @ 1 lb on a paint set, a shaker bottle and whey protein,
and a real buyer was quoted and charged $6.57 rated from it.
"""
import json
import unittest

import handlers.checkout as checkout_module
from handlers.checkout import shipping_quote
from stripe_link.domain.shipping import packable_items
from stripe_link.domain.shipping_packing import pack

BOXES = [{"name": "Small", "length": 6, "width": 4, "height": 4, "empty_weight": 0.15}]
DECLARED = {"length_in": 10.0, "width_in": 8.0, "height_in": 4.0}


def product(**fulfillment):
    return {"product_id": "p1", "name": "Thing", "product_type": "physical",
            "fulfillment": {"requires_shipping": True, **fulfillment},
            "prices": [{"price_id": "pr1", "unit_amount": 2000, "currency": "usd"}]}


def parcels_for(prod):
    return pack(packable_items([{"product_id": "p1", "quantity": 1}], {"p1": prod}), BOXES)


class ThePackerRefusesToGuessTests(unittest.TestCase):
    def test_a_leftover_declared_box_no_longer_becomes_a_priced_parcel(self):
        self.assertEqual(parcels_for(product(weight_lb=1.0, dimensions=DECLARED)), [])

    def test_a_declared_box_still_works_when_the_tenant_SAID_ships_alone(self):
        parcels = parcels_for(product(weight_lb=1.0, dimensions=DECLARED, ships_alone=True))
        self.assertEqual(parcels[0]["strategy"], "declared")

    def test_a_measured_item_still_packs(self):
        parcels = parcels_for(product(
            weight_lb=1.0, item_dimensions={"length_in": 3.3, "width_in": 5, "height_in": 1.8,
                                            "weight_lb": 2.5}))
        self.assertEqual(parcels[0]["strategy"], "packed")

    def test_the_items_own_size_beats_a_declared_box_when_both_exist(self):
        # The inversion, in the only direction that is correct.
        parcels = parcels_for(product(
            weight_lb=1.0, dimensions={"length_in": 24, "width_in": 24, "height_in": 24},
            item_dimensions={"length_in": 3.3, "width_in": 5, "height_in": 1.8, "weight_lb": 2.5}))
        self.assertLess(parcels[0]["length"], 24)

    def test_nothing_at_all_yields_nothing(self):
        self.assertEqual(parcels_for(product()), [])


class Repo:
    def __init__(self, docs):
        self.docs = docs

    def get(self, tenant, doc_id=None):
        return self.docs.get(doc_id or tenant)


class Cipher:
    def decrypt(self, ref, **_kwargs):
        return "mock_key"


OFFER = {"offer_id": "o1", "tenant_id": "t1", "items": [{"product_id": "p1", "price_id": "pr1"}]}
LIVE_CONFIG = {
    "boxes": BOXES,
    "ship_from_address": {"postal_code": "80301", "country": "US", "city": "Denver", "state": "CO"},
    "provider": {"name": "mock", "api_key_ref": "ref_1"},
    "enabled_services": [{"service_token": "usps_ground", "label": "Ground"}],
    "zones": [{"destinations": [{"country": "US"}], "rule": {"type": "live"}}],
}
BY_BOX_CONFIG = dict(LIVE_CONFIG, zones=[
    {"destinations": [{"country": "US"}], "rule": {"type": "flat_rate_box"}}])


class TheBuyerSeesFreeNotAnErrorTests(unittest.TestCase):
    """A buyer cannot act on a measurement they have never heard of. Showing them an error over it costs
    the tenant the sale for no possible benefit."""

    def setUp(self):
        self._real = checkout_module._tenant_shipping_config
        self.config = dict(LIVE_CONFIG)
        checkout_module._tenant_shipping_config = lambda tenant_id: self.config
        self.product = product(weight_lb=1.0, dimensions=DECLARED)

    def tearDown(self):
        checkout_module._tenant_shipping_config = self._real

    def quote(self, postal_code="80202"):
        return json.loads(shipping_quote(
            tenant_id="t1", offer_id="o1", product_id="p1", price_id="pr1", quantity="1",
            country="US", postal_code=postal_code, region="CO", mode="test",
            offers_repo=Repo({"o1": OFFER}), products_repo=Repo({"p1": self.product}),
            quotes_repo=None, secret_cipher=Cipher())["body"])

    def test_a_live_zone_with_unmeasured_goods_quotes_free(self):
        body = self.quote()
        self.assertEqual(body["mode"], "free")
        self.assertEqual([o["amount"] for o in body["options"]], [0])
        self.assertTrue(body["unmeasured"])

    def test_it_is_not_presented_as_an_error(self):
        # The old behaviour: needs=carrier + rate_error, which the element renders as a red failure state
        # with a retry button for something retrying cannot fix.
        body = self.quote()
        self.assertEqual(body["needs"], "")
        self.assertNotIn("rate_error", body)

    def test_a_by_box_zone_behaves_the_same_way(self):
        self.config = dict(BY_BOX_CONFIG)
        body = self.quote()
        self.assertEqual(body["mode"], "free")
        self.assertTrue(body["unmeasured"])

    def test_the_response_says_WHY_so_the_dashboard_can_too(self):
        self.assertEqual(self.quote()["source"], "unmeasured")

    def test_a_measured_product_is_still_charged(self):
        self.product = product(weight_lb=1.0,
                               item_dimensions={"length_in": 3.3, "width_in": 5, "height_in": 1.8,
                                                "weight_lb": 2.5})
        body = self.quote()
        self.assertEqual(body["mode"], "charged")
        self.assertGreater(body["options"][0]["amount"], 0)
        self.assertNotIn("unmeasured", body)

    def test_a_real_carrier_failure_is_still_an_error_with_a_retry(self):
        # The distinction that makes P0a a refinement rather than a reversal: ours and transient stays
        # loud; theirs and structural goes quiet.
        self.product = product(weight_lb=1.0,
                               item_dimensions={"length_in": 3.3, "width_in": 5, "height_in": 1.8,
                                                "weight_lb": 2.5})
        self.config = dict(LIVE_CONFIG, provider={"name": "mock", "api_key_ref": ""})
        body = self.quote()
        self.assertEqual(body["needs"], "carrier")
        self.assertEqual(body["rate_error"], "no_provider")
        self.assertNotEqual(body["mode"], "free")

    def test_a_missing_postcode_is_still_a_question_not_free_shipping(self):
        body = self.quote(postal_code="")
        self.assertEqual(body["needs"], "postal_code")
        self.assertNotEqual(body["mode"], "free")
