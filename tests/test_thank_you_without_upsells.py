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
        tail = before[before.rindex("synthesize_thank_you_page(page, offer)"):]
        self.assertNotIn("if upsell_entries", tail,
                         "the thank-you terminus must not be conditional on upsells existing")
