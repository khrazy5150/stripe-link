"""What a Social Page is made of: brand glyphs, no nominated destination, and a page that starts furnished.

plans/LEAD_GEN_PAGES.md §8. Three changes that look unrelated and are the same thing -- a link-in-bio page
was being built out of checkout-page parts, and each part carried an assumption that only holds when the
page has ONE thing it wants you to do.
"""
import pathlib
import unittest

from stripe_link.domain.documents import DocumentValidationError, validate_product_lead_capture
from stripe_link.domain.network_icons import NETWORK_ICON_PATHS as GENERATED_ICON_PATHS
from stripe_link.domain.network_icons_manual import MANUAL_ICON_PATHS
from stripe_link.domain.social_links import (
    NETWORK_ICON_PATHS,
    NETWORK_LABELS,
    SAME_AS_HOSTS,
    network_icon_path,
    network_label,
)

DASHBOARD = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src"
BUILDER = (DASHBOARD / "components" / "LandingPages.vue").read_text(encoding="utf-8")
PRODUCTS_VUE = (DASHBOARD / "components" / "Products.vue").read_text(encoding="utf-8")
PRODUCTS_STORE = (DASHBOARD / "stores" / "products.js").read_text(encoding="utf-8")

# The hosts with no mark at all, and why. Named here rather than left as a silent gap so that a later "why is
# this one a text pill?" has an answer that does not require re-deriving it. twitter.com is NOT on this list
# -- it wears the X mark. Neither is linkedin.com any more: upstream cannot ship it, so it is DRAWN, see
# ManualIconTests below.
NO_MARK = {
    "bbb.org": "never in the upstream set, and not worth hand-drawing for its traffic",
}


class GlyphTableTests(unittest.TestCase):
    def test_every_glyph_belongs_to_a_host_we_recognise(self):
        # A glyph for a host outside NETWORK_LABELS could never be reached: the lookup walks the label table
        # first. This is the direction that actually rots -- adding an icon is easy, adding it for a host
        # nobody allowlisted is easier.
        for host in NETWORK_ICON_PATHS:
            self.assertIn(host, NETWORK_LABELS, host)
            self.assertIn(host, SAME_AS_HOSTS, host)

    def test_the_hosts_without_a_mark_are_the_expected_ones(self):
        missing = set(NETWORK_LABELS) - set(NETWORK_ICON_PATHS)
        self.assertEqual(missing, set(NO_MARK), "a host gained or lost a glyph -- update NO_MARK and say why")

    def test_twitter_wears_the_x_mark(self):
        # Same service under a new name; a twitter.com URL redirects to x.com today. Rendering an obsolete
        # bird beside a modern X for what is one account would be the confusing answer, not the faithful one.
        self.assertEqual(NETWORK_ICON_PATHS["twitter.com"], NETWORK_ICON_PATHS["x.com"])
        self.assertEqual(network_label("https://twitter.com/acme"), "Twitter")

    def test_path_data_is_path_data(self):
        # Guards the generator's output shape: an SVG path starts with a moveto and carries no markup. If the
        # upstream package ever returns a whole <svg> document this catches it before it reaches a page.
        for host, path in NETWORK_ICON_PATHS.items():
            self.assertTrue(path[:1] in "Mm", host)
            self.assertNotIn("<", path, host)

    def test_lookup_matches_subdomains_and_is_forgiving_of_unknowns(self):
        self.assertTrue(network_icon_path("https://www.youtube.com/@acme"))
        self.assertEqual(network_icon_path("https://example.org/acme"), "")
        self.assertEqual(network_label("https://example.org/acme"), "example.org")

    def test_the_label_and_the_icon_agree_on_the_network(self):
        # They share one matcher on purpose. A link showing the Facebook mark labelled "Instagram" would be
        # worse than either signal alone, and two near-identical host loops is exactly how that happens.
        self.assertIn("_network_lookup(url, NETWORK_LABELS)", _social_links_source())
        self.assertIn("_network_lookup(url, NETWORK_ICON_PATHS)", _social_links_source())


class ManualIconTests(unittest.TestCase):
    """Hand-drawn marks, for networks the generated set cannot supply.

    LinkedIn asked to be removed from simple-icons. That request is about one library redistributing the mark
    as a downloadable asset -- it was never a rule that nobody may show a LinkedIn icon on a link to a LinkedIn
    profile, which is ordinary nominative use and what every product in this category does. So the answer was
    "do not lift it from that library", not "do not show it".
    """

    def test_the_manual_table_is_layered_over_the_generated_one(self):
        # Manual wins, because it exists precisely for what upstream cannot supply: a later regeneration must
        # not be able to take a mark away again.
        for host, path in MANUAL_ICON_PATHS.items():
            self.assertEqual(NETWORK_ICON_PATHS[host], path, host)

    def test_it_lives_outside_the_generated_file(self):
        # scripts/generate_network_icons.py rewrites network_icons.py wholesale, so anything hand-authored
        # there would be destroyed by the next refresh.
        self.assertNotIn("linkedin.com", GENERATED_ICON_PATHS)
        self.assertIn("linkedin.com", MANUAL_ICON_PATHS)

    def test_a_hand_drawn_mark_meets_the_same_contract(self):
        # Same shape as the generated ones: 24x24, single path, no fill-rule -- the renderer supplies a bare
        # <svg fill="currentColor"> wrapper and would silently mis-fill anything that needed more.
        for host, path in MANUAL_ICON_PATHS.items():
            self.assertTrue(path[:1] in "Mm", host)
            self.assertNotIn("<", path, host)
            self.assertNotIn("fill-rule", path, host)

    def test_linkedin_now_renders_as_a_glyph(self):
        # The reported symptom: one worded pill in a row of glyphs, visibly wider than its neighbours.
        self.assertTrue(network_icon_path("https://www.linkedin.com/in/keith-harris-interactive"))
        self.assertEqual(network_label("https://www.linkedin.com/in/x"), "LinkedIn")


def _social_links_source():
    return (pathlib.Path(__file__).resolve().parents[1]
            / "src" / "stripe_link" / "domain" / "social_links.py").read_text(encoding="utf-8")


class SocialRedirectTargetTests(unittest.TestCase):
    """A Social Page has no single destination -- its cards are the actions."""

    def _capture(self, **extra):
        base = {"action": "social_redirect", "title": "My Links", "description": "Find me online."}
        base.update(extra)
        return {"product_intent": "lead_gen", "lead_capture": base}

    def test_a_social_page_needs_no_target(self):
        validate_product_lead_capture(self._capture())  # must not raise

    def test_a_target_is_still_validated_when_present(self):
        # Optional, not ignored. Products created under the old rule carry one, and there is no reason to
        # make them invalid -- but a malformed one is still malformed.
        validate_product_lead_capture(self._capture(
            target={"type": "social", "value": "https://instagram.com/acme", "platform": "instagram"}))
        with self.assertRaises(DocumentValidationError):
            validate_product_lead_capture(self._capture(target={"type": "url", "value": "https://x.com/a"}))
        with self.assertRaises(DocumentValidationError):
            validate_product_lead_capture(self._capture(target={"type": "social", "platform": "instagram"}))

    def test_the_other_target_actions_still_require_one(self):
        # The relaxation is scoped to the shape that genuinely has no single destination. A call page with no
        # number and a bridge page with no URL are pages with nothing to do.
        for action in ("call_number", "external_url"):
            with self.assertRaises(DocumentValidationError, msg=action):
                validate_product_lead_capture(
                    {"product_intent": "lead_gen",
                     "lead_capture": {"action": action, "title": "t", "description": "d"}})

    def test_the_form_stops_demanding_one_too(self):
        # Server-side relaxation alone would still leave the tenant stuck: leadTargetLabelFor doubles as the
        # required-field check, so a Social Page could not be saved from the form no matter what the API
        # accepted. The same list drives both, which is what keeps them from drifting apart again.
        self.assertNotIn('if (action === "social_redirect") return "Social profile URL"', PRODUCTS_VUE)
        self.assertIn('if (action === "external_url") return "Destination URL"', PRODUCTS_VUE)

    def test_an_empty_target_is_not_written(self):
        # `value` is required whenever the object exists, so writing {type:"social", value:""} would fail
        # validation on save -- the relaxation has to reach the payload builder, not just the form check.
        self.assertIn('base.action === "social_redirect" && action.target', PRODUCTS_STORE)


class SeedingTests(unittest.TestCase):
    """A brand-new Social Page must not open empty.

    With no checkout_cta and no seeds it rendered a hero image, a footer, and nothing a visitor could act
    on -- the tenant had to guess that the links were two "+ Add element" clicks away. The machinery already
    existed (the subheadline is auto-filled from the action's description); it was seeding the OLD meaning.
    """

    def test_a_social_page_is_seeded_with_its_links(self):
        self.assertIn("const SHAPE_SEEDS = {", BUILDER)
        self.assertIn('lead_social: ["social_links", "link_cards"]', BUILDER)
        self.assertIn("seedShapeElements();", BUILDER)

    def test_seeding_never_duplicates_what_is_already_there(self):
        # Same contract as the goal seeds: a create-time starting point that becomes the tenant's the moment
        # it exists. Re-running must be a no-op, or reopening the builder grows a second links row each time.
        block = BUILDER.split("function seedShapeElements()", 1)[1][:400]
        self.assertIn("builder.elements.some((element) => element.type === type)", block)
        self.assertIn("continue", block)

    def test_only_the_link_hub_is_seeded(self):
        # lead_call is deliberately absent even though seller_profile belongs on that shape: it is an
        # ungoverned addable element that renders the Site's NAP whether or not the page asks for it, so
        # seeding one would put the same block on the page twice.
        block = BUILDER.split("const SHAPE_SEEDS = {", 1)[1].split("}", 1)[0]
        for shape in ("lead_call", "lead_bridge", "lead_capture", "single", "bundle", "listicle"):
            self.assertNotIn(shape + ":", block, shape)


if __name__ == "__main__":
    unittest.main()
