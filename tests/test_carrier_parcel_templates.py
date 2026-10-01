"""Carrier-supplied packaging: the one container whose price really is destination-independent.

plans/LIVE_SHIPPING_RATES.md phase 7. The rating path has forwarded a box's `template` to the provider
since `_shippo_parcel` was written -- nothing ever told a tenant WHICH templates exist, so the feature was
unreachable. This is the missing half, and it complements live rating rather than replacing it.
"""
import json
import pathlib
import unittest

from handlers.shipping import list_parcel_templates
from stripe_link.domain.shipping_providers import MockProvider, ShippingProvider, _shippo_parcel

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCREEN = (ROOT / "dashboard/src/components/Shipping.vue").read_text(encoding="utf-8")


class Repo:
    def __init__(self, config):
        self.config = config

    def get(self, tenant_id, doc_id=None):
        return self.config


class Cipher:
    def decrypt(self, ref, **_kwargs):
        return "mock_key"


EVENT = {"requestContext": {"authorizer": {"claims": {"sub": "t1"}}}}
CONNECTED = {"provider": {"name": "mock", "api_key_ref": "ref_1"}}


class TheProviderCanBeAsked(unittest.TestCase):
    def test_a_provider_with_no_templates_answers_empty_rather_than_raising(self):
        # A provider offering no carrier packaging is a true answer, not a crash.
        class Bare(ShippingProvider):
            name = "bare"

        self.assertEqual(Bare().parcel_templates(), [])

    def test_the_token_is_what_the_rating_path_already_forwards(self):
        # Adopting a template needs NO change to rating: `_shippo_parcel` has always passed `template`.
        template = MockProvider().parcel_templates()[0]["template"]
        self.assertEqual(_shippo_parcel({"length": 1, "width": 1, "height": 1, "weight": 1,
                                         "template": template})["template"], template)

    def test_templates_carry_what_a_picker_needs(self):
        for entry in MockProvider().parcel_templates():
            for field in ("template", "name", "carrier", "length", "width", "height"):
                self.assertIn(field, entry)


class TheEndpoint(unittest.TestCase):
    def body(self, config):
        return json.loads(list_parcel_templates(EVENT, Repo(config), Cipher())["body"])

    def test_it_lists_the_carriers_own_packaging(self):
        body = self.body(CONNECTED)
        self.assertTrue(body["templates"])
        self.assertEqual(body["reason"], "")

    def test_no_carrier_is_a_reason_not_an_error(self):
        # A 4xx here would read as "something is broken" rather than "connect a carrier first".
        body = self.body({})
        self.assertEqual(body["templates"], [])
        self.assertEqual(body["reason"], "no_provider")

    def test_a_provider_failure_still_returns_a_usable_answer(self):
        class Broken:
            def decrypt(self, *a, **k):
                raise RuntimeError("kms down")

        body = json.loads(list_parcel_templates(EVENT, Repo(CONNECTED), Broken())["body"])
        self.assertEqual(body["templates"], [])
        self.assertTrue(body["reason"])

    def test_it_is_routed(self):
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        self.assertIn("/shipping/parcel-templates", template)
        source = (ROOT / "src/handlers/shipping.py").read_text(encoding="utf-8")
        self.assertIn('_action(event) == "parcel-templates"', source)


class TheScreenOffersThem(unittest.TestCase):
    def test_a_box_can_adopt_carrier_packaging(self):
        self.assertIn("Carrier packaging", SCREEN)
        self.assertIn("useParcelTemplate(box", SCREEN)

    def test_the_default_says_what_an_own_box_actually_is(self):
        # Never implying a tenant's own carton has a flat rate.
        self.assertIn("My own box — rated on size, weight and distance", SCREEN)

    def test_adopting_one_takes_the_carriers_dimensions(self):
        block = SCREEN.split("function useParcelTemplate", 1)[1][:500]
        for field in ("length", "width", "height"):
            self.assertIn(f"box.{field} = Number(tpl.{field})", block)

    def test_carrier_dimensions_cannot_be_edited(self):
        # They are facts about the container. A tenant who edits them is describing a box that does not exist.
        self.assertEqual(SCREEN.count(':disabled="!!box.template"'), 3)

    def test_clearing_it_hands_the_dimensions_back(self):
        block = SCREEN.split("function useParcelTemplate", 1)[1][:400]
        self.assertIn('box.template = "";', block)

    def test_a_failed_fetch_leaves_the_tenant_where_they_were(self):
        block = SCREEN.split("async function loadParcelTemplates", 1)[1][:400]
        self.assertIn("parcelTemplates.value = []", block)
