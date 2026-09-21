"""The business address form is the same form as the Shipping one.

Two address editors looked and behaved differently for no reason a tenant could see: Shipping had labelled
Street 1 / Street 2 / City / State / Postal / Country, and Profile had four unlabelled placeholders and no
suite line at all.

The DOCUMENT shapes stay different on purpose. `business.address` is PostalAddress-shaped
(street / locality / region) because it feeds LocalBusiness JSON-LD, the localized image alt text and the
figcaption NAP; a carrier wants street1 / city / state. So the form speaks one vocabulary and storage the
other, translated at the two edges -- rather than changing what search engines read to match a form.
"""
import json
import pathlib
import re
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_user_profile
from stripe_link.runtime.html import _postal_address_ld

ROOT = pathlib.Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard" / "src"
PROFILE = (DASH / "components/Profile.vue").read_text(encoding="utf-8")
FIELDS = (DASH / "components/AddressFields.vue").read_text(encoding="utf-8")


class SharedComponentTests(unittest.TestCase):
    def test_profile_uses_the_shipping_screens_component(self):
        self.assertIn('<AddressFields :address="form.business.address" :contact="false" />', PROFILE)

    def test_the_old_hand_rolled_inputs_are_gone(self):
        """Duplicated markup is how the two drifted apart in the first place."""
        for field in ("address.locality", "address.region", "address.street\""):
            with self.subTest(field=field):
                self.assertNotIn(f'form.business.{field}', PROFILE)

    def test_a_business_address_hides_the_carrier_only_fields(self):
        """A business address is a PLACE. Its name and phone are fields above it on the same screen, and
        "residential" is a carrier's pricing question, not something true of a business."""
        for guard in ('<div v-if="contact" class="offer-two-column">',
                      '<label v-if="contact" class="checkbox-row offer-checkbox-inline">'):
            with self.subTest(guard=guard[:40]):
                self.assertIn(guard, FIELDS)

    def test_both_screens_now_get_the_named_country_list(self):
        """Matching could have meant dragging Profile down to a two-letter text box. A tenant typing "UK"
        (not a code) produced an address the carrier rejected, so the better control went the other way."""
        self.assertIn("COUNTRIES", FIELDS)
        self.assertNotIn('maxlength="2"', FIELDS)


class TranslationTests(unittest.TestCase):
    """The form's vocabulary and the document's, mapped at load and save."""

    def test_every_form_field_maps_both_ways(self):
        to_doc = PROFILE.split("function placeToDocument", 1)[1][:400]
        from_doc = PROFILE.split("function placeFromDocument", 1)[1][:400]
        for form_field, doc_field in (("street1", "street"), ("city", "locality"), ("state", "region")):
            with self.subTest(field=form_field):
                self.assertIn(f"{doc_field}: place.{form_field}", to_doc)
                self.assertIn(f"{form_field}: address.{doc_field}", from_doc)

    def test_the_suite_line_survives_the_round_trip(self):
        # The field that did not exist before; without it a business with a unit number had nowhere to
        # put one, and appending it to `street` would corrupt the JSON-LD streetAddress.
        self.assertIn("street2: place.street2", PROFILE.split("function placeToDocument", 1)[1][:400])
        self.assertIn("street2: address.street2", PROFILE.split("function placeFromDocument", 1)[1][:400])


class DocumentUnchangedTests(unittest.TestCase):
    """Storage keeps its PostalAddress shape, so local SEO reads exactly what it always did."""

    # A COMPLETE profile, so a refusal below is this rule failing and not a missing required field.
    BASE = {"schema_version": "2026-05-29", "document_type": "user_profile", "tenant_id": "t1",
            "user_id": "u1", "email": "a@b.c", "display_name": "Keith"}

    def test_the_fixture_is_valid_to_begin_with(self):
        validate_user_profile({**self.BASE, "business": {}})

    def test_the_postal_shape_still_validates(self):
        validate_user_profile({**self.BASE, "business": {"address": {
            "street": "123 Main St", "locality": "Cheyenne", "region": "WY",
            "postal_code": "82009", "country": "US"}}})

    def test_a_suite_is_accepted_now(self):
        validate_user_profile({**self.BASE, "business": {"address": {
            "street": "123 Main St", "street2": "Suite 400", "locality": "Cheyenne", "country": "US"}}})

    def test_junk_is_still_refused_BY_THIS_RULE(self):
        with self.assertRaises(DocumentValidationError) as caught:
            validate_user_profile({**self.BASE, "business": {"address": {"street2": 400}}})
        self.assertIn("business.address.street2", str(caught.exception))


class StructuredDataTests(unittest.TestCase):
    def test_a_suite_joins_the_street_line(self):
        """schema.org has ONE streetAddress. Dropping the suite would hand a crawler an address a courier
        could not deliver to."""
        node = _postal_address_ld({"street": "123 Main St", "street2": "Suite 400", "locality": "Cheyenne"})
        self.assertEqual(node["streetAddress"], "123 Main St, Suite 400")

    def test_without_a_suite_nothing_changes(self):
        node = _postal_address_ld({"street": "123 Main St", "locality": "Cheyenne"})
        self.assertEqual(node["streetAddress"], "123 Main St")

    def test_a_suite_alone_still_produces_a_street(self):
        self.assertEqual(_postal_address_ld({"street2": "Suite 400", "locality": "X"})["streetAddress"],
                         "Suite 400")

    def test_an_empty_address_is_still_nothing(self):
        self.assertEqual(_postal_address_ld({}), {})
        self.assertEqual(_postal_address_ld({"street": "  "}), {})


if __name__ == "__main__":
    unittest.main()
