"""The Shipping screen: the box catalog, and a Test connection button that finally does something.

`connection_status` has been rendered on this screen since it was written, reading "Not configured"
forever, because nothing could advance it. The button is the other half of POST /shipping/test.

The box catalog is what the packer packs into. With no boxes, every multi-item order ships one parcel per
item, which usually costs more — so an empty table is a real state the screen has to explain rather than
leave blank.
"""
import json
import pathlib
import re
import unittest

from stripe_link.domain.shipping import STARTER_BOXES

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCREEN = (ROOT / "dashboard/src/components/Shipping.vue").read_text(encoding="utf-8")


class TestConnectionButtonTests(unittest.TestCase):
    def test_the_button_calls_the_endpoint(self):
        self.assertIn('apiRequest("/shipping/test", { method: "POST" })', SCREEN)

    def test_a_failure_is_shown_as_an_answer_not_swallowed(self):
        """The backend returns 502 with the provider's own words, and those words are how a tenant learns
        what is wrong with their key. Catching and discarding them would leave "it didn't work"."""
        block = SCREEN.split("async function testConnection()", 1)[1][:900]
        self.assertIn("catch (err)", block)
        self.assertIn("err.body?.connection?.message", block)
        self.assertIn('status: "failed"', block)

    def test_it_says_the_test_uses_the_SAVED_key(self):
        # A tenant typing a key and clicking Test without saving would otherwise test the old one and be
        # told their new key is broken.
        self.assertIn("the test uses the key that is stored", SCREEN)

    def test_the_button_is_disabled_without_a_provider(self):
        self.assertIn('="testing || !form.provider.name"', SCREEN)


class BoxCatalogTests(unittest.TestCase):
    def test_an_empty_catalog_is_explained_rather_than_blank(self):
        """Empty is a real state with a real consequence, so the screen says what it costs."""
        self.assertIn('v-if="!form.boxes.length"', SCREEN)
        self.assertIn("every item ships in its own parcel, which usually costs more", SCREEN)

    def test_a_tenant_can_seed_and_then_edit(self):
        self.assertIn("useStarterBoxes", SCREEN)
        self.assertIn("then edit them to match what you actually use", SCREEN)

    def test_the_js_seed_matches_the_python_one(self):
        """Two seeds that drift would offer boxes the backend has never heard of."""
        names = re.findall(r'\{ name: "([^"]+)"', SCREEN.split("const STARTER_BOXES", 1)[1][:900])
        self.assertEqual(names, [box["name"] for box in STARTER_BOXES])

    def test_the_seed_is_not_carrier_packaging(self):
        # Same rule as the backend seed: carrier boxes are fetched, never hand-copied.
        seed = SCREEN.split("const STARTER_BOXES", 1)[1][:900].lower()
        for word in ("flat rate", "usps", "fedex", "priority"):
            with self.subTest(word=word):
                self.assertNotIn(word, seed)

    def test_the_form_explains_what_the_numbers_mean(self):
        # Inside vs outside measurements is the difference between a box that fits and one that does not.
        self.assertIn("Inside measurements", SCREEN)
        self.assertIn("the carrier bills the cardboard too", SCREEN)

    def test_max_weight_is_presented_as_optional(self):
        # Absent means "no stated limit", the common case for a tenant's own carton.
        self.assertIn("leave it blank unless the box has a stated limit", SCREEN)


class CopyBusinessAddressTests(unittest.TestCase):
    """Copy the ship-from address from the tenant's business profile.

    The two are the same place in two vocabularies: the profile stores a PostalAddress
    (street / locality / region) because it maps straight to LocalBusiness JSON-LD, and a carrier wants
    street1 / city / state. Spreading one into the other fills NOTHING, silently, and the tenant sees a
    button that appears to do nothing at all.
    """

    BLOCK = SCREEN.split("function businessAddressToShipFrom", 1)[1][:800]

    def test_the_vocabularies_are_translated_not_spread(self):
        for profile_field, carrier_field in (("street", "street1"), ("locality", "city"), ("region", "state")):
            with self.subTest(field=profile_field):
                self.assertIn(f"{carrier_field}: address.{profile_field}", self.BLOCK)

    def test_the_business_name_and_phone_come_from_the_business_not_the_address(self):
        # A carrier needs a contact name on the parcel; the PostalAddress has none.
        self.assertIn("name: business?.name", self.BLOCK)
        self.assertIn("phone: business?.phone", self.BLOCK)

    def test_an_unset_profile_says_where_to_fix_it(self):
        """Nothing to copy is a CONFIGURATION answer, not a failure. Without this the tenant cannot tell
        an empty profile from a broken button."""
        handler = SCREEN.split("async function copyBusinessAddress", 1)[1][:1200]
        self.assertIn("No business address is configured in your profile", handler)
        self.assertIn("Profile → Business", handler)

    def test_a_partial_address_is_copied_and_the_gap_named(self):
        # Half a business address is still worth having; the tenant just needs to know what is left.
        handler = SCREEN.split("async function copyBusinessAddress", 1)[1][:1200]
        self.assertIn("Still needed:", handler)

    def test_blank_profile_fields_do_not_wipe_what_is_already_typed(self):
        handler = SCREEN.split("async function copyBusinessAddress", 1)[1][:1200]
        self.assertIn("if (value) form.ship_from_address[key] = value", handler)

    def test_the_country_is_upper_cased_for_the_carrier(self):
        self.assertIn('(address.country || "US").toUpperCase()', self.BLOCK)


class SavedShapeTests(unittest.TestCase):
    BLOCK = SCREEN.split("doc.boxes = form.boxes", 1)[1][:900]

    def test_a_half_filled_row_is_not_saved(self):
        """An unnamed or sizeless box would fail validation on save and lose the whole form."""
        self.assertIn("String(box.name || \"\").trim()", self.BLOCK)
        self.assertIn("Number(box.length) > 0", self.BLOCK)

    def test_a_blank_max_weight_is_omitted_not_sent_as_zero(self):
        # Zero is refused by the validator; absent is the meaning intended.
        self.assertIn("if (Number(box.max_weight) > 0) entry.max_weight", self.BLOCK)

    def test_a_blank_box_weight_is_omitted_too(self):
        self.assertIn("if (Number(box.empty_weight) > 0) entry.empty_weight", self.BLOCK)

    def test_saved_boxes_are_loaded_back(self):
        self.assertIn("Array.isArray(config.boxes)", SCREEN)


class SchemaAgreementTests(unittest.TestCase):
    SCHEMA = json.loads((ROOT / "schemas/ShippingConfig.schema.json").read_text(encoding="utf-8"))

    def test_the_form_only_sends_fields_the_schema_allows(self):
        allowed = set(self.SCHEMA["$defs"]["box"]["properties"])
        sent = set(re.findall(r"entry\.(\w+) =", SavedShapeTests.BLOCK)) | {"name", "length", "width", "height"}
        self.assertEqual(sent - allowed, set())

    def test_every_seeded_box_would_validate(self):
        from stripe_link.domain.documents import validate_shipping_config
        validate_shipping_config({
            "schema_version": "2026-05-29", "document_type": "shipping_config", "tenant_id": "t1",
            "provider": {"name": "shippo"},
            "ship_from_address": {"name": "A", "street1": "1", "city": "X", "state": "CA",
                                  "postal_code": "9", "country": "US"},
            "return_address": {"name": "A", "street1": "1", "city": "X", "state": "CA",
                               "postal_code": "9", "country": "US"},
            "default_parcel": {"length": 1, "width": 1, "height": 1, "weight": 1,
                               "distance_unit": "in", "mass_unit": "lb"},
            "boxes": [dict(box) for box in STARTER_BOXES],
        })


if __name__ == "__main__":
    unittest.main()


class MinimumRequiredTests(unittest.TestCase):
    """Only the provider is required to SAVE.

    The config used to require a provider AND two addresses AND a parcel before it would store anything, so
    testing a key -- the first thing anyone wants to do -- was gated behind the most tedious part of the
    form. Whether a config is WELL-FORMED and whether it is COMPLETE enough to buy a label are different
    questions; answering the second by refusing the save is what made the screen hostile.
    """

    SCHEMA = json.loads((ROOT / "schemas/ShippingConfig.schema.json").read_text(encoding="utf-8"))

    def test_the_schema_requires_only_the_provider(self):
        self.assertEqual(self.SCHEMA["required"],
                         ["schema_version", "document_type", "tenant_id", "provider"])

    def test_a_provider_only_config_validates(self):
        from stripe_link.domain.documents import validate_shipping_config
        validate_shipping_config({"schema_version": "2026-05-29", "document_type": "shipping_config",
                                  "tenant_id": "t1", "provider": {"name": "shippo"}})

    def test_a_STARTED_address_must_still_be_finished(self):
        """Half an address buys a label that cannot be delivered. Untouched is "not set yet"; partial is
        broken, and the two must not be confused."""
        from stripe_link.domain.documents import DocumentValidationError, validate_shipping_config
        with self.assertRaises(DocumentValidationError):
            validate_shipping_config({"schema_version": "2026-05-29", "document_type": "shipping_config",
                                      "tenant_id": "t1", "provider": {"name": "shippo"},
                                      "ship_from_address": {"name": "A", "street1": "1 Main"}})

    def test_the_form_only_blocks_a_save_on_the_provider(self):
        block = SCREEN.split("function validationErrors()", 1)[1][:900]
        self.assertIn('if (!form.provider.name) errors.push("Provider")', block)
        self.assertIn("if (!started) return;", block)

    def test_the_screen_says_what_is_still_needed_instead_of_refusing(self):
        self.assertIn("Before you can buy labels:", SCREEN)
        self.assertIn("const readiness = ref([])", SCREEN)

    def test_the_advice_has_exactly_one_implementation(self):
        """It used to be written twice -- once in Python, once in the component -- and kept in step by a
        test comparing strings. Worse, the component's copy read the FORM, so the banner went green before
        any save and stayed green when the save failed. The server now sends the list."""
        from stripe_link.domain.shipping import label_readiness
        for item in label_readiness({}):
            with self.subTest(item=item):
                self.assertNotIn(item, SCREEN, "the screen is hardcoding advice the server already sends")
        self.assertIn("applyReadiness(body)", SCREEN)


class DeprecatedDefaultParcelTests(unittest.TestCase):
    """`default_parcel` was required and read by NOTHING.

    It predates the box catalog and per-product dimensions, which is how a parcel is actually decided now.
    The convenience case for it -- a tenant with a single product -- is already served by that product's own
    Package Dimensions; duplicating it at config level only creates a second answer that can drift.
    """

    def test_the_form_no_longer_asks_for_it(self):
        self.assertNotIn("Default Parcel", SCREEN)
        self.assertNotIn("form.default_parcel", SCREEN)

    def test_it_is_not_sent_on_save(self):
        self.assertIn("default_parcel is deliberately NOT sent", SCREEN)

    def test_the_property_survives_so_saved_documents_still_validate(self):
        # additionalProperties is false, so REMOVING it would strand every config saved before today.
        schema = json.loads((ROOT / "schemas/ShippingConfig.schema.json").read_text(encoding="utf-8"))
        self.assertIn("default_parcel", schema["properties"])
        self.assertIn("DEPRECATED", schema["properties"]["default_parcel"]["description"])

    def test_nothing_in_the_codebase_reads_it(self):
        """If this ever fails, something started depending on a field the form no longer collects."""
        readers = []
        for path in list((ROOT / "src").rglob("*.py")) + list((ROOT / "dashboard/src").rglob("*.vue")):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if "default_parcel" in line and "DEPRECATED" not in line and "deliberately NOT sent" not in line:
                    if "documents.py" in str(path):
                        continue  # the validator still accepts it for back-compat
                    readers.append(f"{path.name}: {line.strip()[:70]}")
        self.assertEqual(readers, [])


class DerivedReturnAddressTests(unittest.TestCase):
    ADDRESS = {"name": "Shop", "street1": "1 Main", "city": "LA", "state": "CA",
               "postal_code": "90001", "country": "US"}

    def test_returns_go_to_the_ship_from_address_by_default(self):
        """Most sellers take returns where they ship from. Asking twice is typing that exists only to
        satisfy a validator, and a duplicate that can drift."""
        from stripe_link.domain.shipping import return_address
        self.assertEqual(return_address({"ship_from_address": self.ADDRESS})["street1"], "1 Main")

    def test_an_explicit_return_address_wins(self):
        from stripe_link.domain.shipping import return_address
        config = {"ship_from_address": self.ADDRESS,
                  "return_address": {**self.ADDRESS, "street1": "9 Returns Rd"}}
        self.assertEqual(return_address(config)["street1"], "9 Returns Rd")

    def test_nothing_configured_is_empty_rather_than_invented(self):
        from stripe_link.domain.shipping import return_address
        self.assertEqual(return_address({}), {})
