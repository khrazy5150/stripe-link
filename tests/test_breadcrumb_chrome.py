"""Which pages show the Home > ... trail, and how a tenant turns it off.

Reported 2026-09-11: a link-in-bio page attached to a Site rendered "Home / My Links" above the brand mark,
and there was nowhere to turn it off. There genuinely was not: the only lever was the Site-wide "discover in
search" switch, which also forces noindex on every page of that Site -- a control that answers a much bigger
question than the one being asked.

A breadcrumb says "you are HERE in a hierarchy". True of a product inside a catalogue; false of the lead
shapes. A link hub is an identity page, not a node under a store, and a bridge page is noindex by rule, so a
crawlable trail on it has no reader at all. Hence a default per shape, plus a per-page override for the case
no rule settles: a standalone checkout page that happens to be attached to a Site.
"""
import pathlib
import unittest

from stripe_link.domain.composition import shows_breadcrumb
from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.runtime import html as html_module

BUILDER = (pathlib.Path(__file__).resolve().parents[1]
           / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")


def _offer(**kw):
    offer = {"offer_id": "o1", "items": [{"product_id": "p1"}], "presentation": {}}
    offer.update(kw)
    return offer


def _lead(action):
    return _offer(product_intent="lead_gen", lead_capture_action=action)


class DefaultTests(unittest.TestCase):
    def test_no_lead_shape_carries_a_breadcrumb(self):
        for action in ("capture_email", "capture_phone", "capture_email_phone",
                       "call_number", "external_url", "social_redirect"):
            self.assertFalse(shows_breadcrumb(_lead(action), {}), action)

    def test_a_transactional_page_still_does(self):
        self.assertTrue(shows_breadcrumb(_offer(), {}))
        self.assertTrue(shows_breadcrumb(_offer(product_intent="transaction"), {}))

    def test_absent_means_derive_not_off(self):
        # The distinction the whole design turns on. Every page saved before this existed has no `chrome`, and
        # must keep whatever its shape says rather than silently losing its breadcrumb.
        self.assertTrue(shows_breadcrumb(_offer(), {}))
        self.assertTrue(shows_breadcrumb(_offer(), {"chrome": {}}))


class OverrideTests(unittest.TestCase):
    def test_a_checkout_page_can_turn_it_off(self):
        # The case with no rule to settle it: a standalone checkout page that happens to be on a Site.
        self.assertFalse(shows_breadcrumb(_offer(), {"chrome": {"breadcrumb": False}}))

    def test_a_lead_page_can_turn_it_on(self):
        # The override runs both ways. A default nobody can overrule is a rule, and this is a preference.
        self.assertTrue(shows_breadcrumb(_lead("capture_email"), {"chrome": {"breadcrumb": True}}))

    def test_the_field_is_validated(self):
        page = {"schema_version": "1", "document_type": "page", "tenant_id": "t", "page_id": "p1",
                "name": "P", "offer_id": "o1", "route": {"slug": "p"},
                "sections": [{"id": "hero", "type": "hero", "headline": "Hi"}]}
        validate_page_document({**page, "chrome": {"breadcrumb": False}})
        validate_page_document({**page, "chrome": {}})
        with self.assertRaises(DocumentValidationError):
            validate_page_document({**page, "chrome": "yes"})
        with self.assertRaises(DocumentValidationError):
            validate_page_document({**page, "chrome": {"breadcrumb": "no"}})


class RenderTests(unittest.TestCase):
    """One gate, inside breadcrumb_trail, so the visible nav and the JSON-LD cannot disagree."""

    def setUp(self):
        html_module._RENDER_STATE["home_url"] = "https://shop.example.com/"
        html_module._RENDER_STATE["canonical"] = "https://shop.example.com/my-links"
        html_module._RENDER_STATE["page_type"] = "landing"

    def tearDown(self):
        html_module._RENDER_STATE["home_url"] = ""
        html_module._RENDER_STATE["canonical"] = ""
        html_module._RENDER_STATE.pop("breadcrumb", None)

    PRODUCTS = {"p1": {"product_id": "p1", "name": "Creatine Gummies"}}

    def test_switching_it_off_removes_the_trail(self):
        html_module._RENDER_STATE["breadcrumb"] = False
        self.assertEqual(html_module.breadcrumb_trail(_offer(), self.PRODUCTS), [])

    def test_it_takes_the_structured_data_with_it(self):
        # Google's guidelines want breadcrumb markup to describe what is ON the page. Emitting a BreadcrumbList
        # for a trail no visitor can see is exactly the mismatch they call out -- so ONE gate, inside the trail
        # both callers share, rather than a check beside each of them.
        html_module._RENDER_STATE["breadcrumb"] = False
        self.assertEqual(
            html_module.breadcrumb_json_ld(html_module.breadcrumb_trail(_offer(), self.PRODUCTS)), "")

    def test_an_unset_flag_behaves_as_before(self):
        # breadcrumb_trail is called from paths that never set the key; it must not start returning nothing.
        html_module._RENDER_STATE.pop("breadcrumb", None)
        self.assertNotEqual(html_module.breadcrumb_trail(_offer(), self.PRODUCTS), [])


class BuilderTests(unittest.TestCase):
    def test_the_control_exists_and_is_reachable(self):
        self.assertIn('v-model="breadcrumbOn"', BUILDER)
        self.assertIn("Show breadcrumb trail", BUILDER)

    def test_the_checkbox_shows_the_effective_value(self):
        # builder.breadcrumb is undefined until touched -- that IS "derive from the shape" -- and an undefined
        # v-model renders unchecked, which would show every checkout page as breadcrumb-off while it rendered
        # one.
        block = BUILDER.split("const breadcrumbOn = computed(", 1)[1][:300]
        self.assertIn("breadcrumbDefault.value", block)

    def test_only_a_deviation_is_stored(self):
        # Writing the resolved value would freeze today's answer into the document -- the mistake the brand
        # label made, where a stored default outlived every later fix.
        self.assertIn("breadcrumbOn.value === breadcrumbDefault.value ? {} :", BUILDER)

    def test_the_accordion_says_what_is_inside_it(self):
        # It shipped inside "Appearance / Theme preset and colour overrides", and the author looked on the
        # Site, looked on the page, and could not find it -- reasonably, because nothing on the closed
        # accordion suggested header furniture was in there. A control nobody can find is not a control.
        self.assertIn('hint="Theme, colours, and the header breadcrumb"', BUILDER)
        self.assertNotIn('hint="Theme preset and colour overrides"', BUILDER)

    def test_it_is_offered_in_exactly_one_place(self):
        # Two copies of a setting is the drift pattern this codebase keeps paying for.
        self.assertEqual(BUILDER.count('v-model="breadcrumbOn"'), 1)

    def test_the_default_mirrors_the_server(self):
        self.assertIn('LEAD_COMPOSITION_TYPES = new Set(["lead_capture", "lead_call", "lead_bridge", "lead_social"])',
                      BUILDER)


if __name__ == "__main__":
    unittest.main()


class PreviewParityTests(unittest.TestCase):
    """The preview has to anchor the page at the SAME origin the published artifact will.

    Asked 2026-09-12: "the breadcrumbs don't show in the Preview (they never did) -- is that by design?" It
    was not. render_page's fallback -- used whenever the caller passes no home_url -- resolves only a VERIFIED
    CUSTOM DOMAIN, while publishing resolves the free platform host too. So a Site serving on *.jbay.uk shipped
    a breadcrumb and a storefront header the tenant could never see before publishing.

    Third instance of one shape this week: the preview and the publisher deriving the same fact separately.
    The social row that rendered in the preview and vanished on the saved page was the first; the link trust
    boundary reading home_url instead of the tenant's own domain was the second.
    """

    HANDLER = (pathlib.Path(__file__).resolve().parents[1]
               / "src" / "handlers" / "page_render.py").read_text(encoding="utf-8")

    def test_the_preview_resolves_the_serving_origin(self):
        self.assertIn("site_serving_origin(site, page_site_slug)", self.HANDLER)
        self.assertIn("home_url=preview_home_url", self.HANDLER)

    def test_it_uses_the_publishers_own_helper(self):
        # Not a second derivation that has to agree -- literally the function publishing calls.
        self.assertIn("site_serving_origin", self.HANDLER.split("import", 1)[1][:2000])

    def test_no_site_still_means_derive_rather_than_none(self):
        # None tells render_page "work it out yourself"; "" would assert there IS no origin and kill the
        # chrome on a page whose Site simply was not resolved. The distinction is load-bearing.
        block = self.HANDLER.split("serving_origin = site_serving_origin", 1)[1][:500]
        self.assertIn("preview_home_url = None", block)
