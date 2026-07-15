"""expand_offer denormalizes each offer item into a self-contained {product, pricing} snapshot the
landing-page renderers consume without lookups — the ExpandedOffer contract (plans/CONVERSION_CONTEXT.md)."""
import json
import unittest

from handlers.offers import handler
from stripe_link.domain.pricing import expand_offer
from tests.fakes import FakeDocumentRepository


class ExpandOfferTests(unittest.TestCase):
    def _offer(self):
        return {
            "offer_id": "o", "tenant_id": "t1", "offer_type": "listicle", "product_intent": "transaction",
            "presentation": {"cta": {"type": "buy"}},
            "items": [
                {"product_id": "p1", "price_id": "pr1", "quantity": 1},
                {"product_id": "p2", "selectable_prices": [{"price_id": "pr2a", "label": "1 pack"}], "default_price_id": "pr2a"},
            ],
        }

    def _products(self):
        return {
            "p1": {"product_id": "p1", "name": "Briefs", "description": "12 pack", "images": ["https://i/a.jpg", "https://i/a2.jpg"],
                   "default_price_id": "pr1", "prices": [
                       {"price_id": "pr1", "currency": "usd", "unit_amount": 5201, "compare_at_amount": 6900, "quantity": 1, "context": "standard"},
                       {"price_id": "prbundle", "currency": "usd", "unit_amount": 9000, "quantity": 2, "context": "standard"}]},
            "p2": {"product_id": "p2", "name": "NAD+", "description": "aging", "images": ["https://i/b.jpg"],
                   "default_price_id": "pr2a", "prices": [
                       {"price_id": "pr2a", "currency": "usd", "unit_amount": 5317, "quantity": 1, "context": "standard"}]},
        }

    def test_each_item_becomes_a_snapshot(self):
        expanded = expand_offer(self._offer(), self._products(), {})
        self.assertEqual(expanded["offer_id"], "o")
        self.assertEqual(expanded["presentation"]["cta"]["type"], "buy")  # non-item fields pass through
        self.assertEqual(len(expanded["items"]), 2)

        first = expanded["items"][0]
        self.assertEqual(first["product"]["headline"], "Briefs")
        self.assertEqual(first["product"]["subheadline"], "12 pack")
        self.assertEqual(first["product"]["hero_image"], "https://i/a.jpg")
        self.assertEqual(first["product"]["gallery"], ["https://i/a.jpg", "https://i/a2.jpg"])
        # single-unit price ignores the 2-pack bundle
        self.assertEqual(first["pricing"]["single_unit_price"]["unit_amount"], 5201)
        self.assertEqual(first["pricing"]["single_unit_price"]["compare_at_amount"], 6900)

    def test_single_unit_price_prefers_default_over_sale(self):
        # Real-world NAD case: standard=default $53.17, sale $37.09, flash $31.35, all quantity 1, all sharing
        # compare_at_unit_amount $79. The listicle must show the DEFAULT ($53.17) with its discount — not the
        # cheaper sale/flash the merchant didn't designate (khrazy's NAD bug: published showed $37.09).
        from stripe_link.domain.pricing import single_unit_price
        product = {"product_id": "nad", "name": "NAD+", "default_price_id": "std", "prices": [
            {"price_id": "std", "currency": "usd", "unit_amount": 5317, "compare_at_unit_amount": 7900, "quantity": 1, "context": "standard"},
            {"price_id": "sale", "currency": "usd", "unit_amount": 3709, "compare_at_unit_amount": 7900, "quantity": 1, "context": "sale"},
            {"price_id": "flash", "currency": "usd", "unit_amount": 3135, "compare_at_unit_amount": 7900, "quantity": 1, "context": "flash_sale"},
        ]}
        selectable = ["std", "sale", "flash"]
        self.assertEqual(single_unit_price(product, selectable, "std")["unit_amount"], 5317)
        offer = {"offer_id": "o", "items": [{
            "product_id": "nad", "default_price_id": "std",
            "selectable_prices": [{"price_id": "std"}, {"price_id": "sale"}, {"price_id": "flash"}],
        }]}
        pricing = expand_offer(offer, {"nad": product}, {})["items"][0]["pricing"]
        self.assertEqual(pricing["single_unit_price"]["unit_amount"], 5317)
        # compare comes from compare_at_unit_amount (was silently read from the wrong field -> no discount).
        self.assertEqual(pricing["single_unit_price"]["compare_at_amount"], 7900)

    def test_single_unit_price_empty_selection_uses_item_price(self):
        # Whey case: selectable_prices empty, item carries price_id -> that price is used (preview showed $0).
        product = {"product_id": "whey", "name": "Whey", "default_price_id": "std",
                   "prices": [{"price_id": "std", "currency": "usd", "unit_amount": 6006, "quantity": 1, "context": "standard"}]}
        offer = {"offer_id": "o", "items": [{"product_id": "whey", "price_id": "std", "selectable_prices": []}]}
        pricing = expand_offer(offer, {"whey": product}, {})["items"][0]["pricing"]
        self.assertEqual(pricing["single_unit_price"]["unit_amount"], 6006)

    def test_selectable_prices_carry_labels(self):
        expanded = expand_offer(self._offer(), self._products(), {})
        selectable = expanded["items"][1]["pricing"]["selectable_prices"]
        self.assertEqual(len(selectable), 1)
        self.assertEqual(selectable[0]["price_id"], "pr2a")
        self.assertEqual(selectable[0]["label"], "1 pack")

    def test_service_item_expands_too(self):
        offer = {"offer_id": "o", "tenant_id": "t1", "items": [{"service_id": "s1", "price_id": "sp1"}]}
        services = {"s1": {"service_id": "s1", "name": "Consult", "description": "45m",
                           "presentation": {"hero_image_url": "https://i/svc.jpg"},
                           "prices": [{"price_id": "sp1", "currency": "usd", "unit_amount": 15000}]}}
        expanded = expand_offer(offer, {}, services)
        item = expanded["items"][0]
        self.assertEqual(item["kind"], "service")
        self.assertEqual(item["product"]["headline"], "Consult")
        self.assertEqual(item["product"]["hero_image"], "https://i/svc.jpg")
        self.assertEqual(item["pricing"]["single_unit_price"]["unit_amount"], 15000)


class ExpandOfferHandlerTests(unittest.TestCase):
    def setUp(self):
        self.offers = FakeDocumentRepository("offer_id")
        self.products = FakeDocumentRepository("product_id")
        self.offers.put({"offer_id": "o", "tenant_id": "t1", "offer_type": "listicle",
                         "items": [{"product_id": "p1", "price_id": "pr1", "quantity": 1}]})
        self.products.put({"product_id": "p1", "tenant_id": "t1", "name": "Briefs", "images": ["https://i/a.jpg"],
                          "default_price_id": "pr1", "prices": [{"price_id": "pr1", "currency": "usd", "unit_amount": 5201, "quantity": 1, "context": "standard"}]})

    def _get(self, params):
        return handler({"httpMethod": "GET", "pathParameters": {"offer_id": "o"}, "queryStringParameters": params},
                       None, repository=self.offers, products_repo=self.products)

    def test_plain_get_returns_raw_offer(self):
        body = json.loads(self._get({"tenant_id": "t1"})["body"])
        self.assertEqual(body["offer"]["items"][0]["product_id"], "p1")  # raw item shape
        self.assertNotIn("product", body["offer"]["items"][0])

    def test_expand_get_returns_snapshot(self):
        body = json.loads(self._get({"tenant_id": "t1", "expand": "1"})["body"])
        item = body["offer"]["items"][0]
        self.assertEqual(item["product"]["headline"], "Briefs")
        self.assertEqual(item["pricing"]["single_unit_price"]["unit_amount"], 5201)


if __name__ == "__main__":
    unittest.main()
