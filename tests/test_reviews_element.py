"""The reviews block is a SECTION, and the tenant can place it (plans/REVIEWS.md Phase 2.5).

Two defects and one capability, all from the same cause. The block was appended after the whole body, so
it rendered BELOW the footer -- `legal_footer` is a `pinned_bottom` element *inside* the body -- and a
tenant could neither move it, retitle it, nor take it off a page. Registering it as an element fixes all
three at once.

The constraint that matters: hiding it drops the markup too. `AggregateRating` left in the head while the
visible reviews are gone is exactly the mismatch Google's guidelines forbid, and it is the one way this
element could do real harm.
"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from stripe_link.domain.composition import baseline_order, element_placement  # noqa: E402
from stripe_link.runtime.html import SECTION_REGISTRY, _RENDER_REVIEWS, render_reviews_section  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES = json.loads((ROOT / "src" / "stripe_link" / "composition_rules.json").read_text())
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
OFFER = {"items": [{"product_id": "p1"}]}
PRODUCTS = {"p1": {"product_id": "p1"}}
APPROVED = [{"status": "approved", "source": "first_party", "rating": 5, "author": "A", "body": "Great."}]


class ItIsAnOrderedElementTests(unittest.TestCase):
    def test_it_is_in_the_catalog_and_the_baseline(self):
        self.assertIn("reviews", RULES["elements"])
        self.assertIn("reviews", baseline_order())

    def test_it_is_movable(self):
        """It was unreachable — appended after everything, with nothing in the builder to grab."""
        self.assertEqual(element_placement("reviews"), "free")

    def test_it_sits_in_PROOF_next_to_the_rating(self):
        """A hard constraint, not a preference: the rating and the reviews are ONE claim, and Google
        requires the visible text to match the AggregateRating."""
        order = baseline_order()
        self.assertEqual(RULES["elements"]["reviews"]["slot"], "proof")
        self.assertEqual(order[order.index("rating") + 1], "reviews")

    def test_it_renders_BEFORE_the_footer(self):
        """The defect this fixes. legal_footer is pinned_bottom inside the body; the block used to be
        appended after the body entirely."""
        order = baseline_order()
        self.assertLess(order.index("reviews"), order.index("legal_footer"))

    def test_it_is_registered_for_rendering(self):
        self.assertIn("reviews", SECTION_REGISTRY)


class TheTenantCanRetitleItTests(unittest.TestCase):
    def setUp(self):
        _RENDER_REVIEWS.clear()
        _RENDER_REVIEWS["p1"] = list(APPROVED)

    def test_the_default_heading(self):
        self.assertIn("Customer reviews", render_reviews_section({"id": "r"}, OFFER, PRODUCTS))

    def test_a_tenants_heading_wins(self):
        markup = render_reviews_section({"id": "r", "heading": "What buyers say"}, OFFER, PRODUCTS)
        self.assertIn("What buyers say", markup)
        self.assertNotIn("Customer reviews", markup)

    def test_the_heading_is_escaped(self):
        markup = render_reviews_section({"id": "r", "heading": "<script>x</script>"}, OFFER, PRODUCTS)
        self.assertNotIn("<script>x", markup)

    def test_no_reviews_means_no_section(self):
        _RENDER_REVIEWS.clear()
        self.assertEqual(render_reviews_section({"id": "r"}, OFFER, PRODUCTS), "")


class BusinessReviewsAreADifferentSurfaceTests(unittest.TestCase):
    """Reviews of the FIRM carry no markup (the self-serving rule), so on a checkout page they compete
    with the one set that can earn a snippet."""

    def test_they_are_not_a_placed_element(self):
        self.assertEqual(RULES["elements"]["business_reviews"]["ui"], "internal")

    def test_they_render_only_on_an_offerless_page(self):
        from stripe_link.runtime.html import _RENDER_BUSINESS_REVIEWS, render_business_reviews_block

        _RENDER_BUSINESS_REVIEWS[:] = list(APPROVED)
        try:
            self.assertEqual(render_business_reviews_block(
                {"sections": [{"type": "hero"}, {"type": "checkout_cta"}]}), "")
            self.assertIn("sl-business-reviews", render_business_reviews_block(
                {"sections": [{"type": "seller_profile", "id": "sp"}]}))
        finally:
            _RENDER_BUSINESS_REVIEWS.clear()

    def test_the_gate_is_the_page_not_the_offer_type(self):
        """An offerless page has no meaningful offer_type and falls back to `single`, so gating there
        would have withheld them from the one surface they belong on."""
        for config in RULES["offer_types"].values():
            self.assertNotIn("business_reviews", config.get("excludes") or [])


class TheRatingElementIsNotThisTests(unittest.TestCase):
    def test_it_is_renamed(self):
        """"Rating" read as the reviews system. It is an external rating the tenant cites, with no markup
        — and renaming it to "Reviews" would put two different star displays on one page."""
        self.assertEqual(RULES["elements"]["rating"]["label"], "Star-rating badge")

    def test_the_editor_says_what_it_is_not(self):
        # Fragments, not sentences: the template wraps the copy across lines.
        self.assertIn("It carries no search", BUILDER)
        self.assertIn("add <strong>Customer reviews</strong>", BUILDER)


class TheBuilderRoundTripsItTests(unittest.TestCase):
    def test_a_new_element_carries_only_a_heading(self):
        """The reviews are the customers' words, not content typed here."""
        new_element = BUILDER.split('if (type === "reviews") return', 1)[1].split(";", 1)[0]
        self.assertIn("heading", new_element)

    def test_it_serializes_and_loads(self):
        self.assertIn('return { id: element.id, type: "reviews", heading: element.heading || undefined };',
                      BUILDER)
        self.assertIn('} else if (section.type === "reviews") {', BUILDER)

    def test_the_editor_warns_that_removing_it_removes_the_stars(self):
        self.assertIn("the stars go with it", BUILDER)


if __name__ == "__main__":
    unittest.main()
