"""Floats must become Decimal on the way into DynamoDB.

DynamoDB has no float type and boto3 refuses one outright. The exception escapes the handler, so API
Gateway answers with a gateway 5xx carrying no CORS headers -- which a browser reports as "Failed to
fetch", naming neither the field nor the document. That is what a page carrying a crop did in production.

The unit tests could not see it: they inject fake repositories, so nothing ever reached the type check in
boto3. Same blind spot as the leads_repository TypeError earlier -- injecting a dependency proves the logic
and proves nothing about the boundary.
"""

import json
import unittest
from decimal import Decimal

from stripe_link.common import json_response
from stripe_link.repositories.documents import DynamoDocumentRepository, dynamo_safe


class ConversionTests(unittest.TestCase):
    def test_a_float_becomes_a_decimal(self):
        self.assertEqual(dynamo_safe(1.3333333333), Decimal("1.3333333333"))

    def test_conversion_goes_through_str_not_the_binary_value(self):
        # Decimal(0.1) is 0.1000000000000000055511151231257827; the stored document should read the way
        # the author wrote it.
        self.assertEqual(str(dynamo_safe(0.1)), "0.1")

    def test_a_crop_rect_converts_whole(self):
        crop = {"x": 0.25, "y": 0.1, "w": 0.5, "h": 0.5, "ar": 1.3333333333}
        converted = dynamo_safe(crop)
        for key, value in converted.items():
            with self.subTest(key=key):
                self.assertIsInstance(value, Decimal)

    def test_it_reaches_floats_nested_anywhere(self):
        doc = {"sections": [{"type": "before_after", "ratio": 1.7777, "crop": {"x": 0.2}}]}
        section = dynamo_safe(doc)["sections"][0]
        self.assertIsInstance(section["ratio"], Decimal)
        self.assertIsInstance(section["crop"]["x"], Decimal)

    def test_bools_are_left_alone(self):
        # bool is an int subclass; DynamoDB stores it natively and coercing it would change the type.
        for value in (True, False):
            with self.subTest(value=value):
                self.assertIs(dynamo_safe(value), value)

    def test_ints_and_strings_are_left_alone(self):
        self.assertIsInstance(dynamo_safe(50), int)
        self.assertIsInstance(dynamo_safe("0.5"), str)

    def test_nan_and_infinity_are_dropped_rather_than_raised_on(self):
        # They have no DynamoDB representation, and a nonsensical coordinate must not be the reason a
        # tenant cannot save their page.
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.assertIsNone(dynamo_safe(value))


class BoundaryTests(unittest.TestCase):
    """The conversion has to happen at the WRITE, not in each caller that happens to remember."""

    class RecordingTable:
        def __init__(self):
            self.items = []

        def put_item(self, Item):  # noqa: N803 - boto3's signature
            # Reproduce boto3's actual refusal, which is what production hit.
            def check(value):
                if isinstance(value, float):
                    raise TypeError("Float types are not supported. Use Decimal types instead.")
                if isinstance(value, dict):
                    for item in value.values():
                        check(item)
                if isinstance(value, (list, tuple)):
                    for item in value:
                        check(item)

            check(Item)
            self.items.append(Item)

    def _repo(self, table):
        return DynamoDocumentRepository("jb-pages-test", document_type="page",
                                        id_field="page_id", table=table)

    def test_a_page_carrying_a_crop_saves(self):
        table = self.RecordingTable()
        self._repo(table).put({
            "tenant_id": "t1", "page_id": "p1",
            "sections": [{"id": "ba", "type": "before_after", "ratio": 4 / 3, "start": 50,
                          "before_crop": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5, "ar": 4 / 3}}],
        })
        self.assertEqual(len(table.items), 1)

    def test_the_stored_item_round_trips_back_to_json_numbers(self):
        # A Decimal that cannot serialize would move the failure from save to load.
        table = self.RecordingTable()
        self._repo(table).put({"tenant_id": "t1", "page_id": "p1", "ratio": 1.3333333333})
        body = json.loads(json_response({"page": table.items[0]})["body"])
        self.assertAlmostEqual(body["page"]["ratio"], 1.3333333333, places=9)

    def test_the_document_handed_back_is_not_mutated_into_decimals(self):
        # The caller keeps working with the document after put(); handing back Decimals would leak the
        # storage concern into every consumer.
        table = self.RecordingTable()
        document = {"tenant_id": "t1", "page_id": "p1", "ratio": 1.5}
        returned = self._repo(table).put(document)
        self.assertIsInstance(returned["ratio"], float)


if __name__ == "__main__":
    unittest.main()
