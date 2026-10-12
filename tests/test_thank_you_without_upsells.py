"""A funnel with no upsells still has to end on a thank-you screen.

The builder's Purchase Flow draws `Offer -> Landing page -> ALWAYS Thank-you page` and its Live Preview
renders that screen from `page.post_checkout.thank_you_page`. Publish, however, synthesized the terminus
only `if upsell_entries:` — so an offer with a thank-you configured and NO upsells published nothing, and
the router, finding neither an artifact nor a Page document, returned the buyer to the landing page with
`?checkout=success`.

A real buyer hit this on 2026-10-08, at the end of a live purchase. It is not a test/live divergence: the
same offer would behave identically in test. It was invisible because every funnel exercised until then
happened to carry upsells, which is the branch that does synthesize the screen.
"""
import unittest

from stripe_link.runtime.upsell_pages import synthesize_thank_you_page, thank_you_config


LANDING = {
    "schema_version": "2026-05-29",
    "document_type": "page",
    "tenant_id": "t_1",
    "page_id": "page_x",
    "status": "published",
    "template": "universal_bundle",
    "post_checkout": {"thank_you_page": {"page_id": "page_never_created",
                                         "headline": "Thank You for Your Purchase!"}},
}
OFFER_NO_UPSELLS = {"offer_id": "off_1", "tenant_id": "t_1", "items": [], "stripe_mode": "live"}


class TheTerminusExistsWithoutUpsells(unittest.TestCase):
    def test_the_screen_is_synthesized_from_the_editor_copy(self):
        page, offer = synthesize_thank_you_page(LANDING, OFFER_NO_UPSELLS)
        self.assertEqual(page["page_id"], "page_x__thank_you",
                         "the router redirects to {page_id}__thank_you; the artifact must match")
        self.assertEqual(offer["presentation"]["headline"], "Thank You for Your Purchase!",
                         "the editor's copy is what the buyer should see")
        self.assertEqual(offer["items"], [], "the terminus sells nothing")

    def test_defaults_apply_when_the_editor_left_it_alone(self):
        bare = {**LANDING, "post_checkout": {"thank_you_page": {"page_id": "page_never_created"}}}
        config = thank_you_config(bare)
        self.assertTrue(config.get("headline"), "a page with no custom copy still needs a headline")


class PublishWritesItForEveryPage(unittest.TestCase):
    """The gate was `if upsell_entries:`. Guard the source so it cannot come back."""

    def test_publishing_does_not_gate_the_terminus_on_upsells(self):
        import pathlib
        src = pathlib.Path("src/stripe_link/runtime/publishing.py").read_text()
        marker = "_write_funnel_artifact(str(ty_page[\"page_id\"]), ty_html, \"thank_you\")"
        self.assertIn(marker, src)
        before = src[:src.index(marker)]
        # Anchored on the CALL, not on its exact arguments: the previous anchor was the literal
        # `synthesize_thank_you_page(page, offer)` and broke the moment the call gained a
        # `ships_physical=` argument, which has nothing to do with what this test guards.
        tail = before[before.rindex("synthesize_thank_you_page("):]
        self.assertNotIn("if upsell_entries", tail,
                         "the thank-you terminus must not be conditional on upsells existing")


class TheArrivalEstimateFollowsTheProductsNotJustTheOffer(unittest.TestCase):
    """A physical product's thank-you page lost its shipping ETA (reported 2026-10-12).

    `offer.ships_physical` is DENORMALISED by the builder, so it is absent on any offer saved before
    that field existed — and on at least one saved after. The thank-you synthesis trusted it alone,
    while the product it sells had `fulfillment.requires_shipping: true` and a real parcel on the way.

    `compose_page` has always ORed the offer's flag with what the renderer can actually see, and
    `offer_ships_physical`'s own docstring says why: *"The renderer passes the truth it can see (the
    products it loaded) on top, so an offer saved before this field existed still composes correctly."*
    This path did not, which is the whole defect.
    """

    OFFER = {"offer_id": "o1", "name": "Creatine Gummies"}
    PAGE = {"page_id": "p1", "tenant_id": "t1", "sections": [], "theme": {}}

    def _sections(self, **kwargs):
        from stripe_link.runtime.upsell_pages import synthesize_thank_you_page
        page, _offer = synthesize_thank_you_page(self.PAGE, self.OFFER, **kwargs)
        return [s.get("type") for s in page.get("sections") or []]

    def test_an_offer_with_no_flag_still_gets_an_eta_when_the_product_ships(self):
        self.assertIn("shipping_eta", self._sections(ships_physical=True))

    def test_the_offers_own_flag_still_works_on_its_own(self):
        from stripe_link.runtime.upsell_pages import synthesize_thank_you_page
        page, _ = synthesize_thank_you_page(self.PAGE, {**self.OFFER, "ships_physical": True})
        self.assertIn("shipping_eta", [s.get("type") for s in page["sections"]])

    def test_a_digital_offer_still_gets_no_package_card(self):
        """The fix must not undo 2026-10-08: a digital buyer was shown a package card, and the builder
        preview showed the tenant one with no order present to remove it."""
        self.assertNotIn("shipping_eta", self._sections())
        self.assertNotIn("shipping_eta", self._sections(ships_physical=False))

    def test_publishing_derives_it_from_the_products_it_loaded(self):
        from stripe_link.runtime.publishing import _products_ship_physical
        self.assertTrue(_products_ship_physical(
            {"p1": {"fulfillment": {"requires_shipping": True}}}))
        self.assertFalse(_products_ship_physical(
            {"p1": {"fulfillment": {"requires_shipping": False}}}))
        self.assertFalse(_products_ship_physical({}))
        self.assertFalse(_products_ship_physical(None))

    def test_both_publish_paths_pass_it(self):
        """The published artifact AND the builder preview, or the tenant sees one thing and the buyer
        another — which is the drift the page composer exists to stop."""
        import pathlib
        src = pathlib.Path("src/stripe_link/runtime/publishing.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("ships_physical=_products_ship_physical(products_by_id)"), 2)
