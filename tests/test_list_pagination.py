"""Paged list contract: GET /offers?limit=&cursor=.

Why this exists: `list_for_tenant` is unbounded, and offer documents run ~2.9KB. Around 2,000 records the
response breaches the 6MB Lambda proxy limit and the screen stops loading entirely — a cliff, not a slope.
The paged shape is added now, pre-launch, because the API CONTRACT is the expensive thing to change once
anything depends on the unbounded one. Behaviour is unchanged for clients that do not paginate.
"""

import base64
import json
import unittest

from handlers.offers import MAX_OFFERS_PAGE, handler
from stripe_link.repositories.documents import _query_page, decode_cursor, encode_cursor
from tests.fakes import FakeDocumentRepository


class CursorCodecTests(unittest.TestCase):
    def test_round_trip(self):
        key = {"PK": "TENANT#t1", "SK": "OFFER#abc"}
        self.assertEqual(decode_cursor(encode_cursor(key)), key)

    def test_empty_key_encodes_to_no_cursor(self):
        self.assertEqual(encode_cursor(None), "")
        self.assertEqual(encode_cursor({}), "")

    def test_a_malformed_cursor_reads_as_no_bookmark_rather_than_raising(self):
        # A stale bookmark in a URL must not 500.
        for junk in ("", "not-base64!!", base64.urlsafe_b64encode(b"[]").decode(),
                     base64.urlsafe_b64encode(b"not json").decode()):
            with self.subTest(cursor=junk):
                self.assertIsNone(decode_cursor(junk))


class FakeDynamoTable:
    """A table that returns SHORT pages, like the real thing.

    DynamoDB applies Limit to items READ and stops at 1MB, so a query can come back with fewer items than
    asked while more remain. Code that treats a short page as end-of-list silently drops records; code that
    treats it as "ask again" is correct. This fake always hands back one item at a time to force that path.
    """

    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def query(self, **request):
        self.calls += 1
        start = int(request.get("ExclusiveStartKey", {}).get("n", 0))
        chunk = self.rows[start:start + 1]          # deliberately short
        end = start + len(chunk)
        response = {"Items": chunk}
        if end < len(self.rows):
            response["LastEvaluatedKey"] = {"n": end}
        return response


class QueryPageTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"PK": "TENANT#t1", "SK": f"OFFER#{i}", "offer_id": f"offer_{i}"} for i in range(10)]

    def test_short_pages_are_followed_until_the_limit_is_filled(self):
        table = FakeDynamoTable(self.rows)
        items, cursor = _query_page(table, limit=4, cursor="")
        self.assertEqual([i["offer_id"] for i in items], [f"offer_{i}" for i in range(4)])
        self.assertTrue(cursor, "more rows remain, so a cursor is required")
        self.assertGreater(table.calls, 1, "a short page must be followed, not treated as the end")

    def test_a_page_never_overshoots_its_limit(self):
        items, _ = _query_page(FakeDynamoTable(self.rows), limit=3, cursor="")
        self.assertEqual(len(items), 3)

    def test_walking_the_cursors_yields_every_row_once(self):
        table = FakeDynamoTable(self.rows)
        seen, cursor, guard = [], "", 0
        while guard < 50:
            guard += 1
            items, cursor = _query_page(table, limit=3, cursor=cursor)
            seen.extend(i["offer_id"] for i in items)
            if not cursor:
                break
        self.assertEqual(seen, [f"offer_{i}" for i in range(10)])

    def test_no_limit_drains_the_partition(self):
        items, cursor = _query_page(FakeDynamoTable(self.rows), limit=None, cursor="")
        self.assertEqual(len(items), 10)
        self.assertEqual(cursor, "")


class ListOffersPagingTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeDocumentRepository("offer_id")
        for index in range(7):
            self.repository.put({"tenant_id": "t1", "offer_id": f"offer_{index}", "name": f"Offer {index}"})
        self.repository.put({"tenant_id": "other", "offer_id": "nope", "name": "Other tenant"})

    def _get(self, query=None):
        event = {"httpMethod": "GET", "queryStringParameters": {"tenant_id": "t1", **(query or {})}}
        return json.loads(handler(event, None, repository=self.repository)["body"])

    def test_no_limit_returns_everything_and_no_cursor(self):
        # The contract exists, but nothing changes for a client that ignores it.
        body = self._get()
        self.assertEqual(len(body["offers"]), 7)
        self.assertNotIn("next_cursor", body)

    def test_a_page_carries_a_cursor_and_the_last_page_does_not(self):
        first = self._get({"limit": "3"})
        self.assertEqual(len(first["offers"]), 3)
        self.assertIn("next_cursor", first)

        second = self._get({"limit": "3", "cursor": first["next_cursor"]})
        self.assertEqual(len(second["offers"]), 3)
        third = self._get({"limit": "3", "cursor": second["next_cursor"]})
        self.assertEqual(len(third["offers"]), 1)
        # Absence of next_cursor is the unambiguous end-of-list signal.
        self.assertNotIn("next_cursor", third)

    def test_paging_covers_every_record_exactly_once(self):
        seen, cursor, guard = [], "", 0
        while guard < 20:
            guard += 1
            body = self._get({"limit": "2", **({"cursor": cursor} if cursor else {})})
            seen.extend(o["offer_id"] for o in body["offers"])
            cursor = body.get("next_cursor", "")
            if not cursor:
                break
        self.assertEqual(sorted(seen), sorted(f"offer_{i}" for i in range(7)))
        self.assertEqual(len(seen), len(set(seen)), "a record was returned twice")

    def test_another_tenants_rows_are_never_in_a_page(self):
        body = self._get({"limit": str(MAX_OFFERS_PAGE)})
        self.assertNotIn("nope", [o["offer_id"] for o in body["offers"]])

    def test_limit_is_capped_so_a_client_cannot_ask_for_a_6mb_response(self):
        body = self._get({"limit": "100000"})
        self.assertLessEqual(len(body["offers"]), MAX_OFFERS_PAGE)

    def test_a_nonsense_limit_falls_back_to_everything(self):
        for bad in ("abc", "-5", "0"):
            with self.subTest(limit=bad):
                self.assertEqual(len(self._get({"limit": bad})["offers"]), 7)


if __name__ == "__main__":
    unittest.main()
