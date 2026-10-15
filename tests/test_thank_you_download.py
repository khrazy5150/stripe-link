"""The thank-you page hands the buyer their file.

Reported 2026-10-14 alongside the download-link failure: a real live purchase of a digital product landed
on "Thank You for Your Purchase!" with no download anywhere on it. The receipt email was the only delivery,
and that link was refusing (see test_download_live_mode).

The element works like the shipping one -- rendered into a page that serves every buyer, filled in from the
ORDER behind `session_id` -- with one deliberate difference: it starts HIDDEN. The shipping element has an
honest fallback sentence to show while it waits ("we'll email tracking details"); a download has none.
"Your download is ready" above no link is a broken promise, so nothing appears until there is a verified
link to put under it.
"""
import unittest

from stripe_link.runtime.html import render_digital_download
from stripe_link.runtime.publishing import _products_deliver_file
from stripe_link.runtime.upsell_pages import synthesize_thank_you_page

PAGE = {"page_id": "p1", "tenant_id": "t1", "theme": {}, "post_checkout": {}}
OFFER = {"offer_id": "o1", "tenant_id": "t1", "items": []}


def sections(**kwargs):
    page, _ = synthesize_thank_you_page(PAGE, OFFER, **kwargs)
    return page["sections"]


def types(**kwargs):
    return [s["type"] for s in sections(**kwargs)]


class CompositionTests(unittest.TestCase):
    def test_it_is_emitted_when_the_offer_delivers_a_file(self):
        self.assertIn("digital_download", types(delivers_file=True))

    def test_it_is_absent_when_nothing_on_the_offer_has_one(self):
        """The same judgement the shipping element learned the hard way: an offer that can never deliver a
        file must not carry a placeholder for one, in the published page or in the builder preview."""
        self.assertNotIn("digital_download", types())

    def test_it_sits_above_the_message(self):
        """It is what the buyer opened this page for, so it goes where the shipping promise goes -- not
        under a paragraph of reassurance that nobody reads."""
        order = types(delivers_file=True)
        self.assertIn("digital_download", order)
        if "content_block" in order:
            self.assertLess(order.index("digital_download"), order.index("content_block"))
        self.assertLess(order.index("digital_download"), len(order))

    def test_the_preview_shows_an_example(self):
        """The Live Preview has no order to ask, and a tenant who cannot see the element cannot know
        their buyers get one."""
        section = [s for s in sections(delivers_file=True, preview=True) if s["type"] == "digital_download"][0]
        self.assertTrue(section.get("example"))

    def test_the_published_page_carries_no_example(self):
        section = [s for s in sections(delivers_file=True) if s["type"] == "digital_download"][0]
        self.assertNotIn("example", section)


class DerivationTests(unittest.TestCase):
    def test_a_product_with_an_uploaded_file_counts(self):
        self.assertTrue(_products_deliver_file(
            {"p": {"digital_asset": {"bucket_key": "downloads/t1/p/a/g.pdf", "filename": "g.pdf"}}}))

    def test_an_empty_asset_does_not(self):
        """A product can carry a `digital_asset` with no `bucket_key` -- the upload was started and never
        finished. There is no file behind that, so there is nothing to promise."""
        self.assertFalse(_products_deliver_file({"p": {"digital_asset": {}}}))
        self.assertFalse(_products_deliver_file({"p": {"digital_asset": {"filename": "g.pdf"}}}))
        self.assertFalse(_products_deliver_file({"p": {}}))
        self.assertFalse(_products_deliver_file({}))


class RenderTests(unittest.TestCase):
    def test_the_published_element_starts_hidden(self):
        html = render_digital_download({"id": "dl"})
        self.assertIn('class="sl-ty-dl"', html)
        self.assertIn(" hidden>", html)

    def test_it_carries_the_island_that_fills_it(self):
        html = render_digital_download({"id": "dl"})
        self.assertIn("/upsell/session?session_id=", html)
        self.assertIn("body.download", html)
        self.assertIn("box.removeAttribute('hidden')", html)

    def test_no_order_means_no_element(self):
        """Every path that cannot produce a verified link removes the element rather than leaving an
        empty promise: no session on the URL, no file on the order, or a fetch that failed."""
        html = render_digital_download({"id": "dl"})
        self.assertIn("if (!api || !tenant || !session) { box.remove(); return; }", html)
        self.assertIn("if (!file || !file.url) { box.remove(); return; }", html)
        self.assertIn(".catch(function(){ box.remove(); })", html)

    def test_the_preview_is_visible_and_asks_nothing(self):
        html = render_digital_download({"id": "dl", "example": "your-file.pdf"})
        self.assertNotIn(" hidden>", html)
        self.assertNotIn("/upsell/session", html)
        self.assertIn("your-file.pdf", html)
        self.assertIn("Example", html)

    def test_the_preview_offers_no_clickable_link(self):
        """A placeholder href on the builder's own screen is a link the tenant will click and a 404 they
        will report. The example is marked as one and is not a link at all."""
        html = render_digital_download({"id": "dl", "example": "your-file.pdf"})
        self.assertNotIn("<a ", html)

    def test_the_element_is_registered_for_rendering(self):
        from stripe_link.runtime.html import SECTION_REGISTRY

        self.assertIn("digital_download", SECTION_REGISTRY)


if __name__ == "__main__":
    unittest.main()
