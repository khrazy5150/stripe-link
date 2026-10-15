"""Product details is offered only where it has a job: a page selling more than one thing.

Author, 2026-10-15: *"I can't see one for a single product because the same description and image are found
on the price card."* Correct. The block's entire value is that it is bound to `currentTarget` — on a
carousel it SWAPS as the visitor swipes, which is why it and the price card are the only two things that
track the current item while the hero stays fixed (plans/CONVERSION_CONTEXT.md). With one target there is
nothing to swap between and nothing the price card has not already said.

No new axis was needed: `offer_type` already IS the product count. Offers.vue infers it from the landing
items — `total > 1 -> listicle`, one product with 2+ selectable prices -> `bundle`, otherwise `single`.
"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from stripe_link.domain.composition import compose_page, is_section_visible  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES = json.loads((ROOT / "src" / "stripe_link" / "composition_rules.json").read_text())
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")


def offered(offer_type):
    return "product_details" not in (RULES["offer_types"][offer_type].get("excludes") or [])


class WhereItIsOfferedTests(unittest.TestCase):
    def test_only_the_multi_product_type_offers_it(self):
        self.assertTrue(offered("listicle"), "listicle is the >1 product type — this is where it works")

    def test_a_single_product_page_does_not(self):
        """One target, nothing to swap, and the price card already carries the description and image."""
        for offer_type in ("single", "bundle"):
            with self.subTest(offer_type=offer_type):
                self.assertFalse(offered(offer_type))

    def test_an_offer_with_no_product_at_all_does_not(self):
        """A tip jar sells nothing, so there are no details to show. It was offered until 2026-10-15."""
        self.assertFalse(offered("tip_jar"))

    def test_no_lead_type_offers_it(self):
        for offer_type in [t for t in RULES["offer_types"] if t.startswith("lead_")]:
            with self.subTest(offer_type=offer_type):
                self.assertFalse(offered(offer_type))

    def test_exactly_one_type_offers_it(self):
        self.assertEqual([t for t in RULES["offer_types"] if offered(t)], ["listicle"])


class ExistingPagesKeepTheirBlockTests(unittest.TestCase):
    """The gate governs the PALETTE and the default. A tenant who already added the block keeps it:
    an explicit section beats a default, and withdrawing an element must never silently delete content
    from a page that is already live."""

    PAGE = {"sections": [{"type": "hero", "id": "h"}, {"type": "product_details", "id": "pd"}]}

    def test_it_still_renders_on_a_single_offer(self):
        offer = {"offer_type": "single", "product_intent": "transaction"}
        self.assertTrue(is_section_visible("product_details", offer, self.PAGE))
        self.assertIn("pd", [s["id"] for s in compose_page(offer, self.PAGE)])

    def test_a_page_that_never_had_it_does_not_gain_it(self):
        offer = {"offer_type": "single", "product_intent": "transaction"}
        page = {"sections": [{"type": "hero", "id": "h"}]}
        self.assertNotIn("product_details", [s["type"] for s in compose_page(offer, page)])


class TheModalSaysWhatItIsForTests(unittest.TestCase):
    def test_it_explains_the_carousel_rather_than_the_plumbing(self):
        """It used to describe what the block READS ("pulled from the offer and synced to the carousel"),
        which tells a tenant nothing about whether to add it."""
        self.assertIn("On a page selling several products, this block follows the carousel", BUILDER)
        self.assertNotIn("pulled from the offer and synced to the carousel", BUILDER)


if __name__ == "__main__":
    unittest.main()
