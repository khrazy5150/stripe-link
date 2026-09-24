"""The tenant's box catalog — what the packer packs into.

Without it, every order falls back to one parcel per item, which over-estimates. With it, a bundle goes in
one box, which is the whole reason the packer exists.

Deliberately NOT carrier packaging. USPS Flat Rate, UPS Express and FedEx Box dimensions belong to the
carriers and are fetched from the provider as parcel templates; hand-copying them here would go stale the
moment a size is retired, and a stale box is a label at the wrong postage. The packer works against the
union of the two.
"""
import json
import pathlib
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_shipping_config
from stripe_link.domain.shipping import BOX_FIELDS, starter_boxes, tenant_boxes
from stripe_link.domain.shipping_packing import pack

ROOT = pathlib.Path(__file__).resolve().parents[1]

CONFIG = {
    "schema_version": "2026-05-29", "document_type": "shipping_config", "tenant_id": "t1",
    "provider": {"name": "shippo"},
    "ship_from_address": {"name": "A", "street1": "1 St", "city": "X", "state": "CA",
                          "postal_code": "90001", "country": "US"},
    "return_address": {"name": "A", "street1": "1 St", "city": "X", "state": "CA",
                       "postal_code": "90001", "country": "US"},
    "default_parcel": {"length": 10, "width": 8, "height": 4, "weight": 1,
                       "distance_unit": "in", "mass_unit": "lb"},
}


class StarterListTests(unittest.TestCase):
    def test_the_seed_is_generic_cartons_not_carrier_packaging(self):
        """If this ever lists a carrier's box, the argument against hand-maintaining them was lost."""
        names = " ".join(box["name"] for box in starter_boxes()).lower()
        for carrier_word in ("flat rate", "usps", "ups", "fedex", "priority", "express"):
            with self.subTest(word=carrier_word):
                self.assertNotIn(carrier_word, names)

    def test_the_seed_validates_as_saved_config(self):
        validate_shipping_config({**CONFIG, "boxes": starter_boxes()})

    def test_each_seed_box_carries_its_own_weight(self):
        # A carrier bills the cardboard too; a seed with no empty weight teaches the wrong shape.
        for box in starter_boxes():
            with self.subTest(box=box["name"]):
                self.assertGreater(box["empty_weight"], 0)

    def test_the_seed_cannot_be_edited_by_a_caller(self):
        mine = starter_boxes()
        mine[0]["length"] = 999
        self.assertNotEqual(starter_boxes()[0]["length"], 999)

    def test_the_seed_only_uses_fields_the_schema_allows(self):
        schema = json.loads((ROOT / "schemas/ShippingConfig.schema.json").read_text(encoding="utf-8"))
        allowed = set(schema["$defs"]["box"]["properties"])
        self.assertEqual(set(BOX_FIELDS) - allowed, set())
        for box in starter_boxes():
            self.assertEqual(set(box) - allowed, set())


class ValidationTests(unittest.TestCase):
    def _refuses(self, boxes):
        with self.assertRaises(DocumentValidationError):
            validate_shipping_config({**CONFIG, "boxes": boxes})

    def test_two_boxes_with_one_name_are_refused(self):
        # A table a tenant cannot tell apart is a table they cannot edit with any confidence.
        self._refuses([{"name": "Mailer", "length": 9, "width": 6, "height": 1},
                       {"name": "mailer", "length": 12, "width": 9, "height": 3}])

    def test_a_box_with_no_size_is_refused(self):
        self._refuses([{"name": "Mystery"}])
        for field in ("length", "width", "height"):
            with self.subTest(field=field):
                self._refuses([{"name": "Bad", "length": 1, "width": 1, "height": 1, field: 0}])

    def test_a_max_weight_of_zero_is_refused_but_absence_is_not(self):
        """Absent means no stated limit, which is the common case for a tenant's own carton. Refusing
        those would be worse than trusting them."""
        self._refuses([{"name": "Bad", "length": 1, "width": 1, "height": 1, "max_weight": 0}])
        validate_shipping_config({**CONFIG, "boxes": [{"name": "Fine", "length": 1, "width": 1, "height": 1}]})

    def test_no_boxes_at_all_is_valid(self):
        validate_shipping_config(CONFIG)
        validate_shipping_config({**CONFIG, "boxes": []})


class ReachesThePackerTests(unittest.TestCase):
    JAR = {"product_id": "gummies", "quantity": 2, "weight": 1.0, "length": 4, "width": 4, "height": 5}

    def test_a_configured_catalog_packs_a_bundle_into_one_box(self):
        parcels = pack([self.JAR], tenant_boxes({**CONFIG, "boxes": starter_boxes()}))
        self.assertEqual(len(parcels), 1)
        self.assertEqual(parcels[0]["strategy"], "packed")

    def test_an_empty_catalog_falls_back_rather_than_inventing_a_box(self):
        parcels = pack([self.JAR], tenant_boxes(CONFIG))
        self.assertEqual({p["strategy"] for p in parcels}, {"per_item"})
        self.assertEqual(len(parcels), 2)

    def test_junk_entries_are_ignored_not_crashed_on(self):
        self.assertEqual(tenant_boxes({"boxes": ["nope", {}, {"name": ""}]}), [])
        self.assertEqual(tenant_boxes({"boxes": "nope"}), [])


if __name__ == "__main__":
    unittest.main()


class BoxKindTests(unittest.TestCase):
    """A padded mailer is not a one-inch carton.

    The catalog has listed one since it was written, and until 2026-09-24 the packer treated it as a rigid
    box — so an 8x5x2 pouch failed it on `2 > 1` and climbed to a carton, overcharging every order with
    one in it.
    """

    import pathlib as _pathlib
    ROOT = _pathlib.Path(__file__).resolve().parents[1]
    SCREEN = (ROOT / "dashboard/src/components/Shipping.vue").read_text(encoding="utf-8")

    def test_the_seeded_mailer_declares_itself_a_soft_pack(self):
        from stripe_link.domain.shipping import starter_boxes

        mailer = next(box for box in starter_boxes() if "mailer" in box["name"].lower())
        self.assertEqual(mailer["kind"], "soft_pack")

    def test_every_seeded_carton_is_still_a_box(self):
        from stripe_link.domain.shipping import starter_boxes

        cartons = [box for box in starter_boxes() if "mailer" not in box["name"].lower()]
        self.assertTrue(cartons)
        self.assertEqual({box.get("kind", "box") for box in cartons}, {"box"})

    def test_kind_survives_a_round_trip_through_the_field_list(self):
        from stripe_link.domain.shipping import BOX_FIELDS

        self.assertIn("kind", BOX_FIELDS)
        self.assertIn("template", BOX_FIELDS)

    def test_the_editor_offers_the_choice_in_the_tenants_words(self):
        # "soft_pack" is our word. A tenant recognises an envelope.
        self.assertIn('v-model="box.kind"', self.SCREEN)
        self.assertIn("Padded envelope or mailer", self.SCREEN)

    def test_a_new_box_defaults_to_rigid(self):
        """The safe direction: a mailer mistakenly treated as a carton just oversizes a parcel, while a
        carton treated as a mailer sends something the carrier refuses."""
        self.assertIn('kind: "box"', self.SCREEN)

    def test_the_carrier_template_is_NOT_a_free_text_field(self):
        """The schema records why: carrier packaging is fetched from the provider as parcel templates,
        because hand-copied carrier dimensions go stale the moment a size is retired. Asking a tenant to
        type "USPS_FlatRateEnvelope" would contradict that — the packer and adapter already pass one
        through when a box carries it."""
        self.assertNotIn('v-model="box.template"', self.SCREEN)
        self.assertNotIn("v-model.trim=\"box.template\"", self.SCREEN)
