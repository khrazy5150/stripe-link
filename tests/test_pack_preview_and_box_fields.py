"""P0c: show what was worked out, and stop collecting what is never read.

plans/SHIPPING_BEYOND_THE_FIRST_SALE.md. The product form promised *"Normally we work the box out from the
sizes above"* and then never showed what it worked out, so a tenant overriding it was guessing against an
invisible answer. Meanwhile the four Shipping Box fields were read by nothing in the common case -- verified
against the author's own screenshot, where item dimensions won and the declared box went unused.
"""
import json
import pathlib
import unittest

from handlers.shipping import pack_preview

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIELD = (ROOT / "dashboard/src/components/products/ProductVariantsField.vue").read_text(encoding="utf-8")

BOXES = [{"name": "Small (6x4x4)", "length": 6, "width": 4, "height": 4, "empty_weight": 0.15},
         {"name": "Medium (10x8x6)", "length": 10, "width": 8, "height": 6, "empty_weight": 0.35}]


class Repo:
    def __init__(self, boxes=None):
        self.config = {"boxes": boxes if boxes is not None else BOXES}

    def get(self, tenant_id, doc_id=None):
        return self.config


def preview(items, boxes=None):
    event = {"requestContext": {"authorizer": {"claims": {"sub": "t1"}}},
             "body": json.dumps({"items": items})}
    return json.loads(pack_preview(event, Repo(boxes))["body"])


class PackPreviewTests(unittest.TestCase):
    def test_it_names_the_tenants_own_box(self):
        body = preview([{"length": 3.3, "width": 5, "height": 1.8, "weight": 2.5}])
        self.assertEqual(body["parcels"][0]["box_name"], "Small (6x4x4)")
        self.assertEqual(body["parcels"][0]["weight"], 2.65)

    def test_it_takes_dimensions_INLINE_so_the_wizard_can_ask(self):
        # A preview that only worked for saved products would be absent exactly where the decision is made.
        self.assertTrue(preview([{"length": 3.3, "width": 5, "height": 1.8, "weight": 2.5}])["parcels"])

    def test_an_unmeasured_item_packs_into_nothing_and_says_so(self):
        body = preview([{"weight": 1}])
        self.assertEqual(body["parcels"], [])
        self.assertEqual(body["reason"], "no_dimensions")

    def test_it_makes_no_carrier_call(self):
        # A price needs a destination this form has no business asking for; the BOX is the answer here.
        import inspect

        source = inspect.getsource(pack_preview)
        self.assertNotIn("provider_for", source)
        self.assertNotIn("rate_parcels", source)
        self.assertNotIn("decrypt", source)

    def test_a_bigger_item_picks_a_bigger_box(self):
        body = preview([{"length": 9, "width": 7, "height": 5, "weight": 3}])
        self.assertEqual(body["parcels"][0]["box_name"], "Medium (10x8x6)")

    def test_with_no_boxes_it_still_answers(self):
        body = preview([{"length": 3.3, "width": 5, "height": 1.8, "weight": 2.5}], boxes=[])
        self.assertEqual(body["box_count"], 0)
        self.assertTrue(body["parcels"])
        self.assertEqual(body["parcels"][0]["box_name"], "")

    def test_no_items_is_not_an_error(self):
        self.assertEqual(preview([])["reason"], "no_items")

    def test_it_is_routed(self):
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        self.assertIn("/shipping/pack-preview", template)
        source = (ROOT / "src/handlers/shipping.py").read_text(encoding="utf-8")
        self.assertIn('_action(event) == "pack-preview"', source)


class TheFormShowsAndHidesTests(unittest.TestCase):
    def test_the_derived_parcel_is_displayed(self):
        self.assertIn("derivedParcel", FIELD)
        self.assertIn("This ships in", FIELD)

    def test_the_box_fields_appear_only_when_the_tenant_ticked_ships_alone(self):
        # With the silent-fallback path gone (P0a), that is the only case they are read in. Showing them
        # otherwise collects four numbers that go nowhere.
        self.assertIn('<template v-if="form.ships_alone">', FIELD)
        box_block = FIELD.split('<template v-if="form.ships_alone">', 1)[1].split("</template>", 1)[0]
        for field in ("form.length_in", "form.width_in", "form.height_in", "form.weight_lb"):
            self.assertIn(field, box_block)

    def test_a_parcel_cannot_weigh_less_than_its_contents(self):
        # Seen in real data: 1 lb packed on an item weighing 2.5 lb, and nothing rejected it.
        self.assertIn("packedWeightTooLight", FIELD)
        self.assertIn("The box cannot weigh less than what goes in it.", FIELD)

    def test_the_check_only_fires_once_both_numbers_exist(self):
        block = FIELD.split("const packedWeightTooLight = computed", 1)[1][:300]
        self.assertIn("packed > 0 && item > 0", block)

    def test_the_lookup_is_debounced(self):
        # The fields fire per keystroke; the answer only changes when a measurement does.
        self.assertIn("clearTimeout(packTimer)", FIELD)

    def test_an_unmeasured_product_asks_for_nothing(self):
        block = FIELD.split("async function refreshDerivedParcel", 1)[1][:260]
        self.assertIn("if (unmeasured.value)", block)

    def test_a_failed_lookup_shows_no_figure(self):
        # A derived number this form could not verify is worse than no number.
        block = FIELD.split("async function refreshDerivedParcel", 1)[1][:1400]
        self.assertIn('derivedParcel.value = "";', block.split("} catch", 1)[1][:200])
