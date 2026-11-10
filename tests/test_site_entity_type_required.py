"""A Site must not be silently typed as something with no premises.

`organization.entity_type` is the switch for every local-SEO signal: `_org_is_local` gates the locality
anchor woven into image alt and the NAP figcaption on it, and `resolve_entity_type` emits it as the
JSON-LD `@type`. It defaulted to `OnlineStore` in three places in the dashboard, so a local business that
never touched the field got none of those signals and a structured-data block saying it has no premises.

Nothing reported it. The only symptom was not ranking, which looks like SEO being hard rather than a
setting being wrong (found 2026-11-10 on a real massage practice in St. George, UT).

The dashboard has no JS suite, so this guards the source the way `test_dashboard_api_routes` guards
routes: by reading what ships.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITES_VUE = ROOT / "dashboard" / "src" / "components" / "Sites.vue"
SITES_STORE = ROOT / "dashboard" / "src" / "stores" / "sites.js"


def _code(path):
    """The file with // line comments stripped, so a comment MENTIONING the old default cannot pass or
    fail these assertions."""
    return "\n".join(re.sub(r"//.*$", "", line) for line in path.read_text(encoding="utf-8").splitlines())


class NoSilentDefaultTests(unittest.TestCase):
    def test_the_store_does_not_default_the_entity_type(self):
        self.assertNotIn('entity_type: "OnlineStore"', _code(SITES_STORE))

    def test_neither_form_defaults_it(self):
        code = _code(SITES_VUE)
        self.assertNotIn('entity_type: "OnlineStore"', code)
        self.assertNotIn('entity_type: org.entity_type || "OnlineStore"', code)

    def test_the_picker_offers_an_unchosen_state(self):
        self.assertIn('<option value="">Select one', SITES_VUE.read_text(encoding="utf-8"))

    def test_saving_is_blocked_until_a_type_is_chosen(self):
        """An unanswered question beats a wrong answer nobody was asked."""
        code = _code(SITES_VUE)
        self.assertIn("Choose a business type", code)
        self.assertIn("saveEditBlockedReason", code)


class TheContradictionIsSurfacedTests(unittest.TestCase):
    """A Site with a street address typed as OnlineStore/Organization is almost certainly misclassified.
    Derived from the live form rather than stored, so it withdraws itself when corrected -- a stored
    notice would outlive its cause."""

    def test_the_mismatch_is_computed_from_the_address(self):
        code = _code(SITES_VUE)
        self.assertIn("localTypeMismatch", code)
        self.assertIn("NON_LOCAL_TYPES", code)
        self.assertIn('"OnlineStore", "Organization"', code)

    def test_it_is_shown_next_to_the_field_it_is_about(self):
        self.assertIn('v-if="localTypeMismatch"', SITES_VUE.read_text(encoding="utf-8"))


class TheGateStillAgreesWithTheTypesTests(unittest.TestCase):
    """The reason this field matters at all -- if these ever diverge, the warning above is pointing at
    the wrong thing."""

    def test_the_non_local_types_really_are_non_local(self):
        from stripe_link.runtime.html import _LOCAL_BUSINESS_TYPES

        for t in ("OnlineStore", "Organization"):
            self.assertNotIn(t, _LOCAL_BUSINESS_TYPES)

    def test_a_chosen_local_type_switches_the_signals_on(self):
        from stripe_link.runtime.html import _org_is_local

        self.assertFalse(_org_is_local({"entity_type": "OnlineStore"}))
        self.assertTrue(_org_is_local({"entity_type": "HealthAndBeautyBusiness"}))
        self.assertTrue(_org_is_local({"entity_type": "OnlineStore", "business_type": "DaySpa"}))


if __name__ == "__main__":
    unittest.main()
