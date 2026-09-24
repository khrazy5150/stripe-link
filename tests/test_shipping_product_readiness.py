"""What is still missing on the PRODUCTS before an order can be packed (plans/SHIPPING_PROVIDERS.md).

The companion to `label_readiness`, and it exists for the same reason that one does: item dimensions are
OPTIONAL to create a product — a tenant who walks their parcels to the post office is a first-class
tenant, and the shipping module must never become compulsory by the back door — but they are NECESSARY to
pack an order into one box.

That is a readiness question, not a validation one. Answering it by refusing the SAVE is how a tenant ends
up unable to list a product until they have found a tape measure.

It is worth saying out loud rather than leaving silent: measured 2026-09-24, 0 of 4 production and 1 of 11
sandbox shippable products carried item dimensions, so the packer's multi-item branch had never run and
every bundle quoted one parcel per item. Nothing announced that.
"""
import json
import os
import pathlib
import unittest
from unittest import mock

from tests.fakes import FakeSimpleRepository
from handlers.shipping import handler as shipping_handler
from stripe_link.domain.shipping import product_readiness

ROOT = pathlib.Path(__file__).resolve().parents[1]

FULL = {"length_in": 8, "width_in": 5, "height_in": 2, "weight_lb": 0.9}
SIZED = {"length_in": 8, "width_in": 5, "height_in": 2}


def _product(name, **fulfillment):
    return {"name": name, "fulfillment": {"requires_shipping": True, **fulfillment}}


class ReadinessTests(unittest.TestCase):
    def test_a_fully_measured_catalogue_is_ready(self):
        self.assertEqual(product_readiness([_product("A", item_dimensions=FULL)]), [])

    def test_nothing_at_all_is_ready(self):
        self.assertEqual(product_readiness([]), [])
        self.assertEqual(product_readiness(None), [])

    def test_an_unmeasured_product_says_what_it_costs(self):
        [line] = product_readiness([_product("Beta Alanine")])

        self.assertIn("Beta Alanine", line)
        self.assertIn("one parcel per item", line)

    def test_it_reads_correctly_for_one_and_for_many(self):
        [one] = product_readiness([_product("Beta Alanine")])
        [many] = product_readiness([_product("A"), _product("B")])

        self.assertIn("has no size of its own", one)
        self.assertIn("containing it ship", one)
        self.assertIn("have no size of their own", many)
        self.assertIn("containing them ship", many)

    def test_a_long_list_names_a_few_and_counts_the_rest(self):
        # A readiness line listing forty products is not actionable.
        [line] = product_readiness([_product(name) for name in "ABCDE"])

        self.assertIn("A, B, C and 2 more", line)

    def test_measured_but_not_weighed_is_mentioned_NOT_blocked(self):
        # It still packs; the weight falls back to the packed figure, which over-estimates. Worth saying,
        # not worth treating as unready in the same breath as having no size at all.
        [line] = product_readiness([_product("Beta Alanine", item_dimensions=SIZED)])

        self.assertIn("not weighed", line)
        self.assertIn("over-estimated", line)

    def test_a_download_is_not_a_parcel_and_is_never_mentioned(self):
        digital = {"name": "ebook", "fulfillment": {"requires_shipping": False}}

        self.assertEqual(product_readiness([digital]), [])

    def test_the_two_problems_are_reported_separately(self):
        lines = product_readiness([_product("Unmeasured"),
                                   _product("Unweighed", item_dimensions=SIZED)])

        self.assertEqual(len(lines), 2)

    def test_a_product_with_no_name_still_produces_an_actionable_line(self):
        nameless = {"product_id": "local_abc", "fulfillment": {"requires_shipping": True}}

        self.assertIn("local_abc", product_readiness([nameless])[0])


class HandlerSurfacesReadinessTests(unittest.TestCase):
    """The advice is only worth computing if it reaches a screen, and the Shipping screen is its home.

    It rides on the shipping response rather than getting its own endpoint because it answers the question
    that screen already asks -- "what still stops this from working?" -- and because a second round trip
    for a hint is a round trip nobody makes.
    """

    def _config(self):
        return json.loads((ROOT / "schemas" / "examples" / "shipping-config-demo.json").read_text())

    def test_the_get_carries_what_the_catalogue_still_needs(self):
        repository = FakeSimpleRepository("tenant_id")
        config = self._config()
        shipping_handler({"httpMethod": "PUT", "body": json.dumps(config)}, None,
                         repository=repository, products_repo=FakeProducts([_product("Creatine")]))

        fetched = shipping_handler({"httpMethod": "GET",
                                    "queryStringParameters": {"tenant_id": config["tenant_id"]}}, None,
                                   repository=repository,
                                   products_repo=FakeProducts([_product("Creatine")]))

        [line] = json.loads(fetched["body"])["product_readiness"]
        self.assertIn("Creatine", line)

    def test_the_save_answers_too_so_the_screen_updates_without_a_reload(self):
        repository = FakeSimpleRepository("tenant_id")

        saved = shipping_handler({"httpMethod": "PUT", "body": json.dumps(self._config())}, None,
                                 repository=repository,
                                 products_repo=FakeProducts([_product("Creatine")]))

        self.assertEqual(saved["statusCode"], 201)
        self.assertIn("Creatine", json.loads(saved["body"])["product_readiness"][0])

    def test_it_stays_separate_from_label_readiness(self):
        # Merging them would file "add a weight" under "before you can buy labels", which is untrue: an
        # unmeasured catalogue costs postage, it does not stop a label.
        repository = FakeSimpleRepository("tenant_id")

        saved = shipping_handler({"httpMethod": "PUT", "body": json.dumps(self._config())}, None,
                                 repository=repository,
                                 products_repo=FakeProducts([_product("Creatine")]))

        body = json.loads(saved["body"])
        self.assertTrue(body["product_readiness"])
        # The catalogue never appears in the list headed "before you can buy labels", whatever else does.
        self.assertNotIn("Creatine", " ".join(body["readiness"]))
        self.assertFalse(set(body["product_readiness"]) & set(body["readiness"]))

    def test_a_products_table_that_will_not_read_never_costs_the_tenant_their_save(self):
        """The whole point of the hint is that it is optional. A hint must not be able to fail a save."""
        repository = FakeSimpleRepository("tenant_id")

        saved = shipping_handler({"httpMethod": "PUT", "body": json.dumps(self._config())}, None,
                                 repository=repository, products_repo=ExplodingProducts())

        self.assertEqual(saved["statusCode"], 201)
        self.assertEqual(json.loads(saved["body"])["product_readiness"], [])

    def test_with_no_products_table_configured_it_simply_says_nothing(self):
        repository = FakeSimpleRepository("tenant_id")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PRODUCTS_TABLE", None)
            saved = shipping_handler({"httpMethod": "PUT", "body": json.dumps(self._config())}, None,
                                     repository=repository)

        self.assertEqual(json.loads(saved["body"])["product_readiness"], [])


class FakeProducts:
    def __init__(self, products):
        self.products = products

    def list_for_tenant(self, tenant_id):  # noqa: ARG002 - the fake answers for whoever asks
        return self.products


class ExplodingProducts:
    def list_for_tenant(self, tenant_id):  # noqa: ARG002
        raise RuntimeError("ResourceNotFoundException")

if __name__ == "__main__":
    unittest.main()
