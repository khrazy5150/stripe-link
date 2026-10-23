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

    def test_it_lives_with_the_brand_mark_it_renders_above(self):
        # Author's placement, and the right one: the breadcrumb renders IMMEDIATELY above the brand mark, so
        # they are one header and are edited in one place. It shipped in "Appearance / Theme preset and colour
        # overrides" first, where the author looked on the Site, looked on the page, and reasonably never
        # opened it -- a control nobody can find is not a control.
        brand = BUILDER.split("sectionEditor.row.editor === 'brand_label'", 1)[1].split("trust_badges'", 1)[0]
        self.assertIn('v-model="breadcrumbOn"', brand)
        # Split on the NEXT editor, not on "</template>": the breadcrumb note contains a nested <template>,
        # and slicing at the first closer cuts the block in half. That mis-slice is exactly what corrupted
        # this file when the two controls were reordered.
        self.assertIn("Brand name", brand)

    def test_the_editor_is_ordered_the_way_the_header_renders(self):
        # The trail sits above the brand mark on the page, so reading the two controls top to bottom should
        # match reading the page top to bottom (author, 2026-09-12).
        brand = BUILDER.split("sectionEditor.row.editor === 'brand_label'", 1)[1].split("trust_badges'", 1)[0]
        self.assertLess(brand.index('v-model="breadcrumbOn"'), brand.index("Brand name"))

    def test_it_is_offered_in_exactly_one_place(self):
        # Two copies of a setting is the drift pattern this codebase keeps paying for.
        self.assertEqual(BUILDER.count('v-model="breadcrumbOn"'), 1)

    def test_the_default_mirrors_the_server(self):
        self.assertIn('LEAD_COMPOSITION_TYPES = new Set(["lead_capture", "lead_call", "lead_bridge", "lead_social"])',
                      BUILDER)

    def test_the_builder_default_consults_the_goal_too(self):
        """Otherwise the preview shows a trail the published page will not have, which is the exact
        preview/publish disagreement the parity tests in this file exist for."""
        body = BUILDER.split("const breadcrumbDefault = computed(", 1)[1].split("\n});", 1)[0]
        self.assertIn('goalChrome(builderGoal.value, "breadcrumb")', body)
        self.assertIn("LEAD_COMPOSITION_TYPES", body)


class GoalDefaultTests(unittest.TestCase):
    """A goal may set the breadcrumb default (author, 2026-10-22).

    Ad traffic lands on a focused conversion page, and a trail back up into a catalogue is an exit from the
    thing the click paid for — so `paid_ads` turns it off. `search_seo` turns it on. Configuration, in
    composition_rules.json, so a new goal sets its own without a renderer change.
    """

    @staticmethod
    def _page(goal, **kw):
        page = {"page_id": "pg1", "sections": []}
        if goal:
            page["goal"] = goal
        page.update(kw)
        return page

    def test_paid_ads_turns_it_off_on_a_page_that_would_otherwise_have_one(self):
        self.assertTrue(shows_breadcrumb(_offer(), self._page("")))
        self.assertFalse(shows_breadcrumb(_offer(), self._page("paid_ads")))

    def test_search_seo_turns_it_on(self):
        self.assertTrue(shows_breadcrumb(_offer(), self._page("search_seo")))
        # And it HOLDS it on where the shape alone would have switched it off. A goal outranks the shape;
        # both are defaults, so the tenant still decides.
        self.assertFalse(shows_breadcrumb(_lead("capture_email"), self._page("")))
        self.assertTrue(shows_breadcrumb(_lead("capture_email"), self._page("search_seo")))

    def test_only_search_friendly_shows_a_breadcrumb(self):
        """The author's rule, and it reverses what this file used to assume: a breadcrumb is not something
        visitors want, it is an on-page SEO device. So the question is "did this page come from search?",
        not "is this page a node in a hierarchy?" -- and ad, social and email traffic all answer no."""
        from stripe_link.domain.composition import offerable_goals

        for goal in offerable_goals():
            expected = goal == "search_seo"
            for shape, offer in (("product", _offer()), ("lead", _lead("capture_email"))):
                with self.subTest(goal=goal, shape=shape):
                    self.assertIs(shows_breadcrumb(offer, self._page(goal)), expected)

    def test_every_goal_states_its_own_answer(self):
        """None of them may fall through to the shape. A goal that forgot to set it would silently take
        the old hierarchy-based default, which is the behaviour being replaced."""
        from stripe_link.domain.composition import goal_chrome, offerable_goals

        for goal in offerable_goals():
            with self.subTest(goal=goal):
                self.assertIsNotNone(goal_chrome(goal, "breadcrumb"))

    def test_a_page_with_no_goal_keeps_the_old_shape_default(self):
        """Pages created before the goal axis are not migrated, so nothing live moves on its own: the
        shape default is reached only by them."""
        self.assertTrue(shows_breadcrumb(_offer(), self._page("")))
        self.assertFalse(shows_breadcrumb(_lead("social_redirect"), self._page("")))

    def test_lead_pages_obey_the_goal_like_any_other(self):
        """The point of the change rather than a side effect (author: "please make sure that lead pages
        also obey the goal"). A lead page is usually fed by ads or a link, not search -- but when one IS
        built for search it gets the breadcrumb."""
        for action in ("capture_email", "capture_phone", "capture_email_phone",
                       "call_number", "external_url", "social_redirect", "register_event"):
            with self.subTest(action=action):
                self.assertFalse(shows_breadcrumb(_lead(action), self._page("paid_ads")))
                self.assertTrue(shows_breadcrumb(_lead(action), self._page("search_seo")))

    def test_the_tenants_own_tick_outranks_the_goal(self):
        for goal, override in (("paid_ads", True), ("search_seo", False)):
            with self.subTest(goal=goal, override=override):
                page = self._page(goal, chrome={"breadcrumb": override})
                self.assertIs(shows_breadcrumb(_offer(), page), override)

    def test_it_is_configuration_not_code(self):
        """The standing rule for this file's rules: a new goal sets its own chrome without a code change."""
        from stripe_link.domain.composition import RULES, goal_chrome

        self.assertIs(RULES["goals"]["paid_ads"]["chrome"]["breadcrumb"], False)
        self.assertIs(RULES["goals"]["search_seo"]["chrome"]["breadcrumb"], True)
        # No goal set / an unknown goal returns None, which is what leaves the shape in charge for a page
        # that predates the goal axis.
        self.assertIsNone(goal_chrome("", "breadcrumb"))
        self.assertIsNone(goal_chrome("nonexistent_goal", "breadcrumb"))
        self.assertIsNone(goal_chrome("search_seo", "a_key_no_goal_sets"))

    def test_nothing_is_written_into_the_document(self):
        """Stored as a DEFAULT, not baked into each new page: a page whose goal changes later has to move
        with it. Writing the resolved value would freeze today's answer, the mistake the brand label made."""
        page = self._page("paid_ads")
        self.assertNotIn("chrome", page)
        self.assertFalse(shows_breadcrumb(_offer(), page))
        page["goal"] = "search_seo"
        self.assertTrue(shows_breadcrumb(_offer(), page))

    def test_the_visible_trail_and_its_markup_move_together(self):
        """Markup for a breadcrumb a visitor cannot see is the mismatch Google's guidelines call out, so
        the two must never disagree -- checked on rendered HTML, not on the predicate."""
        import copy
        import json

        root = pathlib.Path(__file__).resolve().parents[1]
        fx = lambda n: json.loads((root / "schemas" / "examples" / n).read_text())
        product, offer, base = (fx("product-creatine-gummies.json"),
                                fx("offer-creatine-standard.json"),
                                fx("page-creatine-standard.json"))
        site = {
            "document_type": "site", "tenant_id": product["tenant_id"], "site_id": "s1",
            "name": "Probe Store", "hostname": "probestore.com",
            "hosting": {"custom_domain": "probestore.com", "verification": {"verified": True}},
            "indexing": {"eligibility": "eligible"}, "status": "active",
            "organization": {"name": "Probe Store"},
            "pages": {"/": {"page_id": "pg_home", "page_type": "homepage", "enabled": True},
                      "/gummies": {"page_id": base["page_id"], "offer_id": offer["offer_id"],
                                   "page_type": "landing", "enabled": True}},
        }
        for goal, expected in (("paid_ads", False), ("search_seo", True)):
            with self.subTest(goal=goal):
                page = copy.deepcopy(base)
                page["goal"], page["route"] = goal, {"slug": "gummies"}
                rendered = html_module.render_page(
                    page, offer, {product["product_id"]: product},
                    canonical_url="https://probestore.com/gummies", indexable=True, site=site,
                    page_type="landing", home_url="https://probestore.com/",
                    api_base_url="https://api.example.com")
                self.assertIs('class="sl-breadcrumb"' in rendered, expected)
                # search_seo also switches structured_data on, so its trail is the one that gets markup.
                self.assertIs('"BreadcrumbList"' in rendered, expected)


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
