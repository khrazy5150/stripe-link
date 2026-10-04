"""The State / Province field is a CODE, not whatever the tenant says out loud.

It was free text with a "CA" placeholder, so tenants typed "Wyoming" and "Colorado" (2026-10-04). Three
things suffer for it at once:

- the **store timezone** is inferred from the region, and two letters of a state NAME is a different
  state: "Nevada" truncates to NE, which is Nebraska — Pacific against Central. The Python side carries a
  full-name table purely to survive this, and that table only exists because the form let names in;
- **NAP consistency and LocalBusiness JSON-LD**, where "Wyoming" and "WY" are different strings to a
  search engine reading two of your pages;
- **carriers**, which want the code.

Only US and CA get a list. Most countries have no subdivision set worth constraining a form to, and a
half-populated dropdown is worse than a text box.
"""
import pathlib
import re
import unittest

from stripe_link.domain.store_timezone import _CA_PROVINCE_NAMES, _US_STATE_NAMES, _US_STATE_ZONES

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUBDIVISIONS_JS = (ROOT / "dashboard" / "src" / "utils" / "subdivisions.js").read_text()
ADDRESS_VUE = (ROOT / "dashboard" / "src" / "components" / "AddressFields.vue").read_text()


def _js_list(name):
    block = SUBDIVISIONS_JS.split(f"export const {name} = [", 1)[1].split("\n];", 1)[0]
    return dict(re.findall(r'\["([A-Z]{2})",\s*"([^"]+)"\]', block))


class EveryStateTheBackendKnowsIsOfferableTests(unittest.TestCase):
    """A code the form cannot produce is a code the timezone table resolves for nobody."""

    def test_the_form_offers_every_state_with_a_timezone(self):
        offered = set(_js_list("US_STATES"))
        self.assertEqual(set(_US_STATE_ZONES) - offered, set())

    def test_and_every_state_offered_has_one(self):
        self.assertEqual(set(_js_list("US_STATES")) - set(_US_STATE_ZONES), set())

    def test_the_names_agree_with_the_pythons_full_name_table(self):
        """That table is the fallback for rows stored before the field was a list. If the two spellings
        disagree, a healed value and a legacy value resolve to different timezones."""
        js = {name.upper(): code for code, name in _js_list("US_STATES").items()}
        for name, code in _US_STATE_NAMES.items():
            self.assertEqual(js.get(name), code, f"{name} disagrees")

    def test_the_provinces_agree_too(self):
        js = {name.upper(): code for code, name in _js_list("CA_PROVINCES").items()}
        for name, code in _CA_PROVINCE_NAMES.items():
            if name == "QUÉBEC":
                continue       # an accented alias the Python side accepts; the picker offers one spelling
            self.assertEqual(js.get(name), code, f"{name} disagrees")


class ItHealsWhatIsAlreadyStoredTests(unittest.TestCase):
    """"Wyoming" becomes "WY" the moment the form can tell which country it belongs to, so the next save
    stores a code without the tenant doing anything."""

    def test_the_component_normalises_on_load_and_on_country_change(self):
        self.assertIn("normalizeSubdivision(props.address.state, props.address.country)", ADDRESS_VUE)
        self.assertIn("{ immediate: true }", ADDRESS_VUE)

    def test_an_unrecognised_value_is_KEPT_not_blanked(self):
        """Losing a tenant's address because a list was incomplete would be a worse bug than the one this
        fixes, so the select offers the stored value as its own option."""
        self.assertIn("return raw;", SUBDIVISIONS_JS)
        self.assertIn("unlistedState", ADDRESS_VUE)

    def test_a_country_with_no_list_keeps_a_text_box(self):
        self.assertIn('<input v-else v-model.trim="address.state"', ADDRESS_VUE)
        self.assertIn("return null;", SUBDIVISIONS_JS)


class TheTimezoneInferenceNowGetsCodesTests(unittest.TestCase):
    """The whole reason this is critical: the inference is only as good as the string it is given."""

    def test_a_code_resolves(self):
        from stripe_link.domain.store_timezone import suggest_timezone

        self.assertEqual(suggest_timezone({"region": "WY", "country": "US"}), "America/Denver")

    def test_and_the_legacy_name_still_does(self):
        # Rows stored before the field was a list must not break on the way through.
        from stripe_link.domain.store_timezone import suggest_timezone

        self.assertEqual(suggest_timezone({"region": "Wyoming", "country": "US"}), "America/Denver")
