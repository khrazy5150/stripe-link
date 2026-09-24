"""Two bugs that together made a save look like it worked when it had 500'd.

Found in PROD, 2026-09-21: clicking "Start with common sizes" and saving showed a green
"Ready to buy labels", and a refresh showed no boxes at all.

1. `SimpleKeyRepository.put` called `put_item` RAW, without dynamodb_safe_document(). boto3 refuses
   Python floats ("Float types are not supported"), so the whole save 500'd. Nothing had noticed because a
   shipping config only ever held strings and WHOLE numbers -- JSON `10` arrives as a Python int -- and a
   box's empty_weight of 0.35 was the first fractional value one of these documents had ever carried.

2. The screen computed readiness from the FORM, so the banner went green the instant boxes appeared on
   screen, before any save, and stayed green when the save failed. Readiness now travels with the server's
   response: one implementation, and it describes what is SAVED.
"""
import json
import pathlib
import unittest
from decimal import Decimal

from stripe_link.repositories.documents import SimpleKeyRepository

ROOT = pathlib.Path(__file__).resolve().parents[1]


class FakeTable:
    """Rejects floats exactly as boto3 does, so this test fails without the fix."""

    def __init__(self):
        self.item = None

    @staticmethod
    def _reject_floats(value):
        if isinstance(value, float):
            raise TypeError("Float types are not supported. Use Decimal types instead.")
        if isinstance(value, dict):
            for item in value.values():
                FakeTable._reject_floats(item)
        if isinstance(value, list):
            for item in value:
                FakeTable._reject_floats(item)

    def put_item(self, Item):  # noqa: N803 - boto3's own signature
        self._reject_floats(Item)
        self.item = Item

    def get_item(self, Key):  # noqa: N803
        return {"Item": self.item} if self.item else {}


class FloatsSurviveTests(unittest.TestCase):
    def _repo(self):
        return SimpleKeyRepository("jb-shipping-config-test", key_field="tenant_id", table=FakeTable())

    def test_a_fractional_box_weight_can_be_saved(self):
        """0.35 lb of cardboard is what broke it."""
        repo = self._repo()
        repo.put({"tenant_id": "t1", "boxes": [{"name": "Medium", "length": 10, "empty_weight": 0.35}]})
        self.assertEqual(repo.table.item["boxes"][0]["empty_weight"], Decimal("0.35"))

    def test_whole_numbers_still_pass_through(self):
        # Why nothing noticed for so long: JSON `10` is an int, and ints were always fine.
        repo = self._repo()
        repo.put({"tenant_id": "t1", "boxes": [{"name": "M", "length": 10}]})
        self.assertEqual(repo.table.item["boxes"][0]["length"], 10)

    def test_floats_nested_anywhere_are_converted(self):
        repo = self._repo()
        repo.put({"tenant_id": "t1", "a": 1.5, "b": {"c": [2.5, {"d": 3.5}]}})
        stored = repo.table.item
        self.assertEqual(stored["a"], Decimal("1.5"))
        self.assertEqual(stored["b"]["c"][0], Decimal("2.5"))
        self.assertEqual(stored["b"]["c"][1]["d"], Decimal("3.5"))

    def test_the_caller_still_gets_its_own_document_back(self):
        # put() returns the ORIGINAL, so a handler echoing it to the client does not leak Decimals into
        # JSON that cannot serialise them.
        repo = self._repo()
        document = {"tenant_id": "t1", "empty_weight": 0.35}
        self.assertIs(repo.put(document)["empty_weight"], document["empty_weight"])


class ReadinessComesFromTheServerTests(unittest.TestCase):
    SCREEN = (ROOT / "dashboard/src/components/Shipping.vue").read_text(encoding="utf-8")
    HANDLER = (ROOT / "src/handlers/shipping.py").read_text(encoding="utf-8")

    def test_the_screen_no_longer_computes_it_from_the_form(self):
        """Computed from the form, the banner went green the moment boxes appeared on screen -- before any
        save, and while the save was failing."""
        self.assertNotIn("const readiness = computed", self.SCREEN)
        self.assertIn("const readiness = ref([])", self.SCREEN)

    def test_every_response_carries_it(self):
        self.assertEqual(self.HANDLER.count("label_readiness("), 3)  # GET, PUT, and the connection test

    def test_the_screen_reads_it_from_each_response(self):
        """Counting the calls asserted only that there were four of them, and the comment naming which
        four was wrong: `load` was not among them, so a SAVED config that was missing its ship-from
        address loaded reading "Ready to buy labels" until the tenant happened to press Save. Name the
        call sites instead of counting them."""
        for path, body in (("load", "applyReadiness(body)"),
                           ("save", "applyReadiness(body)"),
                           ("testConnection", "applyReadiness(body)")):
            source = self.SCREEN.split(f"function {path}", 1)
            self.assertEqual(len(source), 2, f"no {path}() on the screen")
            self.assertIn(body, source[1].split("\nasync function", 1)[0].split("\nfunction", 1)[0])
        # Including the FAILED connection test, whose 502 body still describes what is missing.
        self.assertIn("applyReadiness(err.body)", self.SCREEN)

    def test_an_unanswered_screen_does_not_claim_to_be_ready(self):
        """An empty readiness list means READY; an absent one means UNKNOWN -- the state of a tenant whose
        GET 404'd because they have saved nothing at all. Those must not both render the green banner."""
        self.assertIn('v-else-if="readinessKnown"', self.SCREEN)

    def test_a_response_without_readiness_leaves_the_last_answer_alone(self):
        block = self.SCREEN.split("function applyReadiness", 1)[1][:200]
        self.assertIn("Array.isArray(body?.readiness)", block)


class EndToEndShapeTests(unittest.TestCase):
    """The save path a tenant actually takes, with the starter boxes that broke it."""

    class Repo:
        def __init__(self):
            self.table = FakeTable()
            self.doc = None

        def get(self, tenant_id):
            return self.doc

        def put(self, document):
            SimpleKeyRepository("jb-shipping-config-test", key_field="tenant_id",
                                table=self.table).put(document)
            self.doc = document
            return document

    class Cipher:
        def encrypt(self, value, **kwargs):
            return "kms:v1:" + value

    def test_saving_the_starter_boxes_succeeds_and_reports_readiness(self):
        from handlers import shipping
        from stripe_link.domain.shipping import starter_boxes

        config = {
            "schema_version": "2026-05-29", "document_type": "shipping_config", "tenant_id": "t1",
            "provider": {"name": "shippo", "api_key_ref": "kms:v1:x", "connection_status": "connected"},
            "ship_from_address": {"name": "A", "street1": "1 St", "city": "Cheyenne", "state": "WY",
                                  "postal_code": "82009", "country": "US"},
            "boxes": starter_boxes(),
        }
        repo = self.Repo()
        response = shipping.handler(
            {"httpMethod": "PUT", "path": "/shipping", "body": json.dumps(config), "headers": {}},
            None, repository=repo, secret_cipher=self.Cipher())
        self.assertEqual(response["statusCode"], 201, response["body"])
        body = json.loads(response["body"])
        self.assertEqual(len(body["shipping_config"]["boxes"]), len(starter_boxes()))
        self.assertEqual(body["readiness"], [])  # nothing left to do


if __name__ == "__main__":
    unittest.main()
