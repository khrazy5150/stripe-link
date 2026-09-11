"""A slim list row must carry every field the dashboard BRANCHES on.

Twice in one day a projection was missing a field the UI decides with:

* `product_index` carried `lead_capture` but not `product_intent` — the lead-gen DETAIL without the flag
  saying it was lead-gen. The dashboard defaults a missing intent to "transaction", so a lead-gen product
  was badged "Transaction" in the offer selector, indistinguishable from the rest, and the offer built
  from it was stamped transaction — which the backend then rejected against the product's real intent.
* `offer_index` carries `product_intent` correctly, which is why the same bug did not appear one layer up.

The failure is quiet by construction: a projection drops a field, the client falls back to a DEFAULT, and
the default is wrong rather than absent. Nothing errors until a validator two systems away disagrees.
"""
import unittest

from stripe_link.domain.offer_index import offer_index_entry
from stripe_link.domain.product_index import product_index_entry


class ProductIndexTests(unittest.TestCase):
    def _row(self, **overrides):
        product = {"product_id": "p1", "name": "My Links", "status": "active",
                   "product_intent": "lead_gen",
                   "lead_capture": {"action": "social_redirect", "title": "T", "description": "D"}}
        product.update(overrides)
        return product_index_entry(product)

    def test_the_row_says_what_intent_the_product_has(self):
        self.assertEqual(self._row()["product_intent"], "lead_gen")

    def test_a_transactional_product_says_so_explicitly(self):
        # Not merely "absent means transaction" -- that is the assumption that broke.
        self.assertEqual(self._row(product_intent="transaction")["product_intent"], "transaction")

    def test_the_intent_travels_with_its_detail(self):
        """lead_capture without product_intent is the incoherent shape: the row described HOW the product
        captures leads while denying that it does."""
        row = self._row()
        self.assertIn("lead_capture", row)
        self.assertIn("product_intent", row)


class OfferIndexTests(unittest.TestCase):
    def test_the_offer_row_carries_intent_and_action(self):
        """The offer row drives composition selection in the builder: intent picks lead-vs-checkout, the
        action picks which of the four lead shapes."""
        row = offer_index_entry({
            "offer_id": "o1", "name": "Links", "product_intent": "lead_gen",
            "lead_capture_action": "social_redirect", "items": [], "presentation": {},
        })
        self.assertEqual(row.get("product_intent"), "lead_gen")
        self.assertEqual(row.get("lead_capture_action"), "social_redirect")


if __name__ == "__main__":
    unittest.main()
