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
import unittest

from stripe_link.domain.shipping import product_readiness

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


if __name__ == "__main__":
    unittest.main()
