"""Promises about things going WRONG (plans/REFUND_POLICY_AND_GUARANTEES.md P4-P7).

A refund policy answers one question -- may I send this back, and by when. Price match, non-delivery and
no-tracking-movement are not rules about returning an item, and no window/condition/return-method
vocabulary can express one. So they are a SECOND primitive rather than more fields on the first.
"""

import json
import pathlib
import unittest

from stripe_link.domain.buyer_guarantees import (
    GUARANTEES,
    SPECS,
    clamp_days,
    normalize,
    resolve,
    sentence,
    vocabulary,
)
from stripe_link.domain.documents import DocumentValidationError, validate_buyer_guarantees

ROOT = pathlib.Path(__file__).resolve().parents[1]


def config(**guarantees):
    return {"legal_defaults": {"buyer_guarantees": guarantees}}


class TheVocabulary(unittest.TestCase):
    def test_the_five_the_plan_names(self):
        self.assertEqual(set(GUARANTEES), {
            "damaged_in_transit", "no_delivery_refund", "no_tracking_update_refund",
            "price_match", "price_adjustment"})

    def test_late_delivery_credit_is_absent(self):
        """A store credit needs a buyer balance and this platform has no buyer accounts at all. A credit
        we cannot issue is a promise we cannot keep."""
        self.assertNotIn("late_delivery_credit", GUARANTEES)

    def test_free_returns_is_not_here(self):
        """It is `return_shipping: seller_pays` on the refund policy. Two places to say one thing is the
        duplicate-source fault this repo keeps paying for."""
        self.assertNotIn("free_returns", GUARANTEES)
        from stripe_link.domain.refund_policy import RETURN_SHIPPING_OPTIONS
        self.assertIn("seller_pays", RETURN_SHIPPING_OPTIONS)

    def test_only_the_timed_promises_carry_a_clock(self):
        self.assertIsNone(SPECS["damaged_in_transit"]["days"])
        for key in ("no_delivery_refund", "no_tracking_update_refund", "price_match", "price_adjustment"):
            with self.subTest(key=key):
                self.assertTrue(SPECS[key]["days"])


class TheCopyIsTheTenantsVoice(unittest.TestCase):
    """Temu's list works because Temu is a marketplace guaranteeing on its sellers' behalf. Here the
    tenant IS the merchant, and a sentence naming the platform would claim a guarantee it does not
    stand behind."""

    def test_every_promise_is_first_person(self):
        for key in GUARANTEES:
            with self.subTest(key=key):
                self.assertIn(" we ", f" {sentence(key)} ".lower())

    def test_the_platform_is_never_named(self):
        for key in GUARANTEES:
            with self.subTest(key=key):
                text = sentence(key).lower()
                self.assertNotIn("junior bay", text)
                self.assertNotIn("juniorbay", text)
                self.assertNotIn("the seller", text)

    def test_the_number_reaches_the_sentence(self):
        self.assertIn("45 days", sentence("price_match", 45))
        self.assertIn("7 days", sentence("no_delivery_refund", 7))

    def test_an_unknown_key_says_nothing(self):
        self.assertEqual(sentence("not_a_guarantee"), "")


class TheNumberIsHeldInsideWhatItCanMean(unittest.TestCase):
    def test_a_silly_number_is_clamped_not_refused(self):
        """A screen that rejects 400 teaches the tenant to fight the form, and "within 400 days" is not
        a promise anyone acts on."""
        self.assertEqual(clamp_days("price_match", 9999), 365)

    def test_zero_and_negatives_fall_back_to_the_default(self):
        """"Refund if not delivered within 0 days" is a sentence with no behaviour behind it."""
        for bad in (0, -5, "", None, "soon"):
            with self.subTest(bad=bad):
                self.assertEqual(clamp_days("no_delivery_refund", bad), 20)

    def test_a_promise_with_no_clock_takes_no_number(self):
        self.assertIsNone(clamp_days("damaged_in_transit", 30))


class OnlyWhatTheTenantEnabled(unittest.TestCase):
    def test_nothing_enabled_renders_nothing(self):
        self.assertEqual(resolve({}), [])
        self.assertEqual(resolve(config(price_match={"enabled": False})), [])

    def test_canonical_order_not_storage_order(self):
        """The rendered list follows the module's order so two tenants' pages are comparable and a buyer
        who has read one knows where to look on the next."""
        stored = config(price_adjustment={"enabled": True}, damaged_in_transit={"enabled": True},
                        price_match={"enabled": True})
        self.assertEqual([g["key"] for g in resolve(stored)],
                         ["damaged_in_transit", "price_match", "price_adjustment"])

    def test_a_retired_key_stops_rendering(self):
        """Rather than printing a promise nothing can explain."""
        self.assertEqual(resolve(config(some_old_key={"enabled": True})), [])

    def test_the_sentence_is_regenerated_not_trusted(self):
        """A tenant who enabled this in October and a wording fix made in November cannot disagree on
        the page."""
        stored = config(price_match={"enabled": True, "days": 45, "sentence": "Whatever I like."})
        self.assertNotIn("Whatever I like", resolve(stored)[0]["sentence"])
        self.assertIn("45 days", resolve(stored)[0]["sentence"])

    def test_decimal_days_survive_a_dynamo_round_trip(self):
        from decimal import Decimal
        stored = config(price_match={"enabled": True, "days": Decimal("45")})
        self.assertEqual(resolve(stored)[0]["days"], 45)

    def test_normalize_never_raises(self):
        for junk in (None, "", 5, [], {"price_match": "yes"}, {"price_match": {"enabled": "x"}}):
            normalize(junk)


class TheDocumentIsCheckedOnTheWayIn(unittest.TestCase):
    def test_an_unknown_guarantee_is_refused(self):
        """A promise this platform cannot explain must not reach a settings document -- and the renderer
        drops it anyway, so accepting it would store something that silently does nothing."""
        with self.assertRaises(DocumentValidationError):
            validate_buyer_guarantees({"free_puppies": {"enabled": True}}, "g")

    def test_a_number_on_a_clockless_promise_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_buyer_guarantees({"damaged_in_transit": {"enabled": True, "days": 5}}, "g")

    def test_an_out_of_range_number_is_refused(self):
        with self.assertRaises(DocumentValidationError):
            validate_buyer_guarantees({"price_match": {"enabled": True, "days": 9999}}, "g")

    def test_absent_is_fine(self):
        validate_buyer_guarantees(None, "g")

    def test_the_schema_knows_the_same_five(self):
        schema = json.loads((ROOT / "schemas" / "TenantConfig.schema.json").read_text(encoding="utf-8"))
        props = (schema["properties"]["legal_defaults"]["properties"]["buyer_guarantees"]["properties"])
        self.assertEqual(sorted(props), sorted(GUARANTEES))


class TheyRenderAsANumberedList(unittest.TestCase):
    def _html(self, **guarantees):
        from stripe_link.runtime.html import render_buyer_guarantees
        return render_buyer_guarantees({"id": "bg", "type": "buyer_guarantees",
                                        "guarantees": resolve(config(**guarantees))})

    def test_nothing_enabled_renders_nothing_at_all(self):
        """Not an empty box with a heading over it."""
        self.assertEqual(self._html(), "")

    def test_the_order_is_in_the_markup(self):
        """An <ol> because assistive technology announces the position -- the same reason the listicle
        grid uses one rather than styling numbers on."""
        html = self._html(damaged_in_transit={"enabled": True}, price_match={"enabled": True})
        self.assertIn("<ol", html)
        self.assertLess(html.index("lost or arrives damaged"), html.index("cheaper elsewhere"))

    def test_the_section_is_disableable_like_any_other(self):
        from stripe_link.runtime.html import render_buyer_guarantees
        section = {"id": "bg", "enabled": False, "guarantees": resolve(config(price_match={"enabled": True}))}
        self.assertEqual(render_buyer_guarantees(section), "")


class TheCompositionOwnsWhetherItAppears(unittest.TestCase):
    def test_it_is_a_governed_section(self):
        """So one entry governs the builder palette and the published page together."""
        from stripe_link.domain.composition import RULES
        self.assertIn("buyer_guarantees", RULES["governed_sections"])
        self.assertIn("buyer_guarantees", RULES["elements"])

    def test_it_is_off_until_the_tenant_asks(self):
        from stripe_link.domain.composition import is_section_visible
        self.assertFalse(is_section_visible("single", "buyer_guarantees"))
        self.assertTrue(is_section_visible("single", "buyer_guarantees",
                                           {"buyer_guarantees": {"enabled": True}}))

    def test_the_ai_may_never_author_one(self):
        """A guarantee is the same kind of thing as a refund window and a worse one to invent: it
        promises behaviour when something goes wrong, and the tenant has to honour it."""
        from stripe_link.domain.ai_floor import FLOOR_SECTIONS
        self.assertIn("buyer_guarantees", FLOOR_SECTIONS)


class PublishComposesThem(unittest.TestCase):
    SOURCE = (ROOT / "src" / "stripe_link" / "runtime" / "publishing.py").read_text(encoding="utf-8")

    def test_the_section_is_filled_from_the_live_settings(self):
        self.assertIn("buyer_guarantees_module.resolve(tenant_config)", self.SOURCE)
        self.assertIn('section.get("type") == "buyer_guarantees"', self.SOURCE)


class TheScreenPreviewsTheServersWords(unittest.TestCase):
    VUE = (ROOT / "dashboard" / "src" / "components" / "Configuration.vue").read_text(encoding="utf-8")

    def test_the_card_exists(self):
        self.assertIn("Buyer guarantees", self.VUE)
        self.assertIn('v-for="item in guaranteeOptions"', self.VUE)

    def test_the_sentence_comes_from_the_server(self):
        """A browser composing a commercial promise is how every live page came to carry a refund
        sentence nobody chose."""
        self.assertIn("function guaranteePreview(item)", self.VUE)
        self.assertIn("item.sentence", self.VUE)

    def test_the_tenant_is_told_they_honour_them(self):
        self.assertIn("we do not check or enforce", self.VUE)

    def test_return_postage_is_asked_only_when_something_comes_back(self):
        """P1's leftover UI. On a revoked download or a keep-it refund the question does not arise."""
        self.assertIn("Who pays return postage?", self.VUE)
        self.assertIn("form.refund_policies[cls].return_method === 'return_required'", self.VUE)
