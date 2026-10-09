"""A buyer of a digital product must never be told to wait for a package.

Seen on a live purchase, 2026-10-09. The shipping ETA element removed itself correctly — only the ORDER
knows whether a parcel exists, and the island asks. But the no-parcel branch did `box.remove(); return;`
and returned BEFORE the `{{arrival}}` substitution, so the card below it stayed on screen reading

    Wait for Your Package
    Your order is expected to arrive {{arrival}}.

with the template token unsubstituted, in front of someone who had bought a download.

Two fixes, because there are two different situations:

- **A digital-only offer** has no ambiguity: nobody who buys it will ever get a parcel. Publish omits the
  element and the arrival cards entirely, which also fixes the builder preview, where there is no order
  to remove anything and the tenant was shown a package card for a download.
- **A mixed offer** is one artifact serving buyers who may or may not get a parcel, so the decision stays
  with the island — which now removes the arrival cards as well as the element.
"""
import unittest

from stripe_link.runtime.upsell_pages import synthesize_thank_you_page

CARDS = [
    {"icon": "📧", "title": "Look for an Email", "desc": "Your receipt is on the way to your inbox."},
    {"icon": "📦", "title": "Wait for Your Package", "desc": "Your order is expected to arrive {{arrival}}."},
    {"icon": "💬", "title": "Tell Us if Anything's Wrong", "desc": "Get in touch if you find any issues."},
]
PAGE = {"page_id": "page_x", "tenant_id": "t_1", "template": "universal_bundle",
        "post_checkout": {"thank_you_page": {"page_id": "page_ty", "next_steps": CARDS}}}


def sections(ships, *, preview=False):
    page, _offer = synthesize_thank_you_page(
        PAGE, {"offer_id": "o1", "tenant_id": "t_1", "ships_physical": ships}, preview=preview)
    return page.get("sections") or []


def card_titles(sections_):
    for section in sections_:
        if section.get("type") == "next_steps":
            return [c.get("title") for c in section.get("cards") or []]
    return []


class ADigitalOnlyOfferShowsNoShipping(unittest.TestCase):
    def test_the_shipping_element_is_not_rendered_at_all(self):
        self.assertNotIn("shipping_eta", [s.get("type") for s in sections(False)])

    def test_the_package_card_is_dropped(self):
        titles = card_titles(sections(False))
        self.assertNotIn("Wait for Your Package", titles)
        self.assertEqual(titles, ["Look for an Email", "Tell Us if Anything's Wrong"],
                         "the other cards must survive")

    def test_no_unsubstituted_token_can_reach_the_buyer(self):
        """The literal failure: a raw {{arrival}} on screen."""
        blob = str(sections(False))
        self.assertNotIn("{{arrival}}", blob)

    def test_the_builder_preview_matches_what_the_buyer_sees(self):
        """The tenant was shown a package card for a download, with no order to remove it."""
        self.assertNotIn("shipping_eta", [s.get("type") for s in sections(False, preview=True)])
        self.assertNotIn("Wait for Your Package", card_titles(sections(False, preview=True)))


class AShippingOfferKeepsEverything(unittest.TestCase):
    def test_the_element_and_the_card_both_survive(self):
        self.assertIn("shipping_eta", [s.get("type") for s in sections(True)])
        self.assertIn("Wait for Your Package", card_titles(sections(True)))

    def test_the_token_is_left_for_the_island_to_substitute(self):
        """A mixed offer's page is one artifact; only the order knows. The token must still be there."""
        self.assertIn("{{arrival}}", str(sections(True)))


class TheIslandAlsoClearsTheCards(unittest.TestCase):
    """For the mixed case, where publish cannot decide and the browser must."""

    def test_the_no_parcel_branch_removes_arrival_cards_before_returning(self):
        from stripe_link.runtime.html import _shipping_eta_island
        script = _shipping_eta_island()
        branch = script[script.index("Object.keys(promise).length"):]
        branch = branch[:branch.index("return;")]
        self.assertIn("box.remove()", branch)
        self.assertIn("{{arrival}}", branch)
        self.assertIn("card.remove()", branch,
                      "the element went but the card stayed, leaving a raw token on a live page")
