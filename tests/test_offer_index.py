"""The slim list projection: GET /offers?view=index.

Why it exists: full offer documents (~2.9KB) breach the 6MB Lambda response limit around 2,000 records.
Paginating them instead would break search, which is client-side and would then cover only the fetched
pages. An index entry is ~10% of a document, so the whole set still loads at once and substring search
stays instant AND complete. plans/OFFER_ITEM_VISIBILITY.md §7.
"""

import json
import unittest

from handlers.offers import handler
from stripe_link.domain.offer_index import offer_index_entry
from tests.fakes import FakeDocumentRepository

FULL_OFFER = {
    "tenant_id": "t1", "offer_id": "offer_1", "name": "Workout Bundle", "slug": "workout-bundle",
    "offer_type": "bundle", "product_intent": "transaction", "status": "active",
    "created_at": "1788225549", "updated_at": "1788225549",
    "presentation": {"image_url": "https://img/x.jpg", "headline": "Creatine Gummies",
                     "subheadline": "5000mg of pure creatine monohydrate."},
    "checkout": {"mode": "payment"}, "eligibility": {"allowed_price_contexts": ["standard"]},
    "purchase_opportunities": [
        {"stage": "landing", "product_id": "p1", "price_id": "s1", "placement": {"group": "main_offer"}},
        {"stage": "landing", "product_id": "p2", "price_id": "s2", "placement": {"group": "main_offer"}},
        {"stage": "checkout", "product_id": "p4", "price_id": "b1", "placement": {"group": "order_bump"}},
        {"stage": "post_purchase", "product_id": "p2", "price_id": "u1", "placement": {"group": "upsell"}},
    ],
}


class OfferIndexEntryTests(unittest.TestCase):
    def test_carries_what_a_card_needs_and_nothing_more(self):
        entry = offer_index_entry(FULL_OFFER)
        self.assertEqual(
            set(entry),
            # lead_capture_action joined 2026-09-10: the builder picks which of the four LEAD compositions
            # from this row, so without it a link-in-bio offer falls back to the capture page. It is a
            # selector, not display data -- which is exactly the bar for being here.
            {"offer_id", "name", "slug", "offer_type", "product_intent", "lead_capture_action", "status",
             "created_at", "updated_at", "item_ids", "landing_ids", "landing_tier_count", "image_url"},
        )

    def test_carries_NO_product_data_only_ids(self):
        # Names live in the catalog. Copying them here would be a second place for them to go stale --
        # the failure this codebase keeps hitting.
        blob = json.dumps(offer_index_entry(FULL_OFFER))
        for leaked in ("prices", "unit_amount", "headline", "monohydrate", "purchase_opportunities"):
            with self.subTest(field=leaked):
                self.assertNotIn(leaked, blob)

    def test_item_ids_span_every_stage_deduped_in_offer_order(self):
        # p2 is both a landing item and the upsell; it appears once. p4 is bump-only and must be present,
        # or the offer containing it becomes unsearchable — the original bug.
        self.assertEqual(offer_index_entry(FULL_OFFER)["item_ids"], ["p1", "p2", "p4"])

    def test_landing_tier_count_projects_a_fact_not_the_rule(self):
        # The card's single/bundle/selector RULE lives in the client. Only the facts it needs are
        # projected, so the rule is not implemented twice.
        self.assertEqual(offer_index_entry(FULL_OFFER)["landing_tier_count"], 0)
        tiered = {**FULL_OFFER, "purchase_opportunities": [
            {"stage": "landing", "product_id": "p1", "placement": {"group": "main_offer"},
             "selectable_prices": [{"price_id": "a"}, {"price_id": "b"}]}]}
        self.assertEqual(offer_index_entry(tiered)["landing_tier_count"], 2)

    def test_landing_ids_are_the_page_subset(self):
        # Landing membership is genuine offer data; funnel ROLES are derived from pricing, so they are not
        # stored here.
        self.assertEqual(offer_index_entry(FULL_OFFER)["landing_ids"], ["p1", "p2"])

    def test_image_url_omitted_when_absent_rather_than_empty(self):
        self.assertNotIn("image_url", offer_index_entry({**FULL_OFFER, "presentation": {}}))

    def test_a_legacy_document_without_opportunities_still_indexes(self):
        legacy = {"offer_id": "o2", "name": "Legacy", "items": [{"product_id": "p9"}],
                  "funnel": {"upsells": [{"product_id": "p8"}]}}
        entry = offer_index_entry(legacy)
        self.assertEqual(entry["landing_ids"], ["p9"])
        self.assertEqual(entry["item_ids"], ["p9", "p8"])

    def test_is_substantially_smaller_than_the_full_document(self):
        full = len(json.dumps(FULL_OFFER))
        slim = len(json.dumps(offer_index_entry(FULL_OFFER)))
        self.assertLess(slim, full * 0.5, f"index {slim}B vs document {full}B — projection is not paying off")


class ListOffersIndexViewTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeDocumentRepository("offer_id")
        for i in range(5):
            self.repository.put({**FULL_OFFER, "offer_id": f"offer_{i}", "name": f"Offer {i}"})

    def _get(self, query=None):
        event = {"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1", **(query or {})}}
        return json.loads(handler(event, None, repository=self.repository)["body"])

    def test_index_view_returns_slim_rows(self):
        rows = self._get({"view": "index"})["offers"]
        self.assertEqual(len(rows), 5)
        self.assertNotIn("purchase_opportunities", rows[0])
        self.assertIn("item_ids", rows[0])

    def test_default_view_is_still_the_full_document(self):
        rows = self._get()["offers"]
        self.assertIn("purchase_opportunities", rows[0])

    def test_index_view_paginates_like_the_full_list(self):
        first = self._get({"view": "index", "limit": "2"})
        self.assertEqual(len(first["offers"]), 2)
        self.assertIn("next_cursor", first)
        self.assertNotIn("purchase_opportunities", first["offers"][0])

    def test_an_unknown_view_falls_back_to_full_documents(self):
        self.assertIn("purchase_opportunities", self._get({"view": "nonsense"})["offers"][0])


if __name__ == "__main__":
    unittest.main()
