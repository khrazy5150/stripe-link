"""A bridge page is never indexed, whatever the Site's eligibility says.

plans/LEAD_GEN_PAGES.md §5. Every other robots input in the publisher is a CONDITION the tenant can
eventually satisfy -- verify the domain, connect Stripe, write more content. This one never becomes true,
because it is a statement about what the page IS: a page whose whole purpose is to send the visitor
somewhere else has no content of its own to rank, and is the thin doorway shape search engines penalise.

The honest uses do not want it indexed either. Forwarding a stale but popular domain to a new one is a real
need (author, 2026-09-10), and there the DESTINATION should rank -- indexing the bridge would put the Site's
whole reputation behind a page that is one button.

Two surfaces, because saying noindex in the meta tag and then advertising the URL to crawlers is a
contradiction we send at our own expense -- and Search Console reports it back to the tenant as an error.
"""
import copy
import unittest
from unittest.mock import patch

from stripe_link.domain.composition import composition_forbids_indexing, composition_key
from stripe_link.runtime.publishing import publish_page_document

from tests.test_page_publishing import FakeRepository, FakeS3Client, FakeSitesRepository, load_fixture


def _as_bridge(offer):
    """The fixture offer, re-cast as a bridge. `checkout` has to go: a lead-gen offer that carries one fails
    validation, because an offer that sells nothing has nothing to check out."""
    offer["product_intent"] = "lead_gen"
    offer["lead_capture_action"] = "external_url"
    offer.pop("checkout", None)
    return offer


def _offer(**overrides):
    offer = {"offer_id": "off_1", "items": [{"product_id": "p1"}], "presentation": {}}
    offer.update(overrides)
    return offer


class ForbidsIndexingTests(unittest.TestCase):
    def test_only_the_bridge_shape_is_forbidden(self):
        # The rule is scoped to the ONE shape that exists to forward. A capture page has a form and a promise
        # on it, a call page carries the NAP a local search wants, and a link-in-bio hub is a real destination
        # -- all three are ordinary pages whose indexing is the Site's decision, not ours.
        self.assertTrue(composition_forbids_indexing(
            _offer(product_intent="lead_gen", lead_capture_action="external_url")))
        for action in ("capture_email", "capture_phone", "capture_email_phone", "call_number", "social_redirect"):
            self.assertFalse(composition_forbids_indexing(
                _offer(product_intent="lead_gen", lead_capture_action=action)), action)

    def test_a_transactional_offer_is_untouched(self):
        self.assertFalse(composition_forbids_indexing(_offer()))
        self.assertFalse(composition_forbids_indexing(_offer(product_intent="transaction")))

    def test_it_reads_the_composition_not_the_action(self):
        # Phrased against composition_key so a future shape that also forwards inherits the rule by being
        # named in NEVER_INDEXED_COMPOSITIONS, rather than by someone remembering to add an action here.
        self.assertEqual(
            composition_key(_offer(product_intent="lead_gen", lead_capture_action="external_url")),
            "lead_bridge")


class BridgePublishTests(unittest.TestCase):
    def setUp(self):
        self.page = load_fixture("page-simple-coffee.json")
        self.page["stripe_mode"] = "live"
        self.page["status"] = "published"
        # Past the SEO-08 thin-content floor, so that if this page publishes as noindex it is because of the
        # bridge rule and not because the gate demoted it -- the fixture alone would pass for the wrong reason.
        self.page.setdefault("sections", []).append({
            "id": "about", "type": "content_block",
            "blocks": [{"title": "About", "text": " ".join(["freshly roasted single origin beans"] * 30)}],
        })
        self.offer = load_fixture("offer-simple-coffee.json")
        self.product = load_fixture("product-simple-coffee.json")
        self.s3 = FakeS3Client()
        self.site = {
            "tenant_id": "tenant_demo", "site_id": "site_x",
            "hosting": {"type": "custom", "custom_domain": "shop.example.com", "verification": {"verified": True}},
            "indexing": {"eligibility": "eligible"},
            "seo": {"indexnow_key": "k1abc"},
            "pages": {"/": {"page_id": "page_simple_coffee"}},
        }

    def _publish(self, offer):
        with patch("stripe_link.runtime.publishing.submit_indexnow", return_value=True) as ping:
            publish_page_document(
                copy.deepcopy(self.page),
                offers_repository=FakeRepository("offer_id", [offer]),
                products_repository=FakeRepository("product_id", [self.product]),
                sites_repository=FakeSitesRepository([copy.deepcopy(self.site)]),
                s3_client=self.s3, pages_bucket="pages", preview_bucket="preview", environment="prod",
                pages_domain="pages.example.com", preview_domain="preview.example.com",
                checkout_url="https://checkout.stripe.com/c/pay/demo",
            )
        published = [p for p in self.s3.puts if p["Key"] == "page_simple_coffee/index.html"][0]
        sitemap = [p for p in self.s3.puts if p["Key"].endswith("sitemap.xml")]
        return published["Body"].decode(), (sitemap[0]["Body"].decode() if sitemap else ""), ping

    def test_the_same_page_indexes_when_it_is_not_a_bridge(self):
        # The control. Everything about this publish is identical except the offer's action, so a failure
        # below cannot be blamed on the domain, the eligibility or the word count.
        html, sitemap, ping = self._publish(copy.deepcopy(self.offer))
        self.assertIn('content="index,follow', html)
        self.assertIn("<loc>https://shop.example.com/</loc>", sitemap)
        ping.assert_called_once()

    def test_a_bridge_page_publishes_noindex_on_a_verified_domain(self):
        offer = copy.deepcopy(self.offer)
        offer = _as_bridge(offer)
        html, _, _ = self._publish(offer)
        self.assertIn('content="noindex,nofollow', html)
        self.assertNotIn('content="index,follow', html)

    def test_a_bridge_homepage_is_not_advertised_to_crawlers(self):
        # The second surface. A bridge is the SHAPE most likely to be a homepage -- an old domain forwarding
        # to a new one is exactly that -- so leaving the sitemap alone would have leaked the main case.
        offer = copy.deepcopy(self.offer)
        offer = _as_bridge(offer)
        _, sitemap, ping = self._publish(offer)
        self.assertNotIn("<loc>", sitemap)
        ping.assert_not_called()

    def test_robots_txt_still_allows_the_rest_of_the_domain(self):
        # Only the HOMEPAGE is known noindex here; the Site's other pages may be perfectly indexable. A
        # disallow-all robots.txt would take them down with it, which is a Site-level decision (archived, or
        # SEO switched off) and not something one page's shape may trigger.
        offer = copy.deepcopy(self.offer)
        offer = _as_bridge(offer)
        self._publish(offer)
        robots = [p for p in self.s3.puts if p["Key"].endswith("robots.txt")][0]["Body"].decode()
        self.assertIn("Allow: /", robots)
        self.assertNotIn("Disallow: /", robots)


class NoindexHomepageTests(unittest.TestCase):
    """The sitemap gate is read off the artifact's FINAL robots directive, so every reason a homepage can be
    noindex closes it -- not just the bridge rule that motivated the change."""

    def test_a_noindex_homepage_is_not_advertised_to_crawlers(self):
        # A thin homepage was previously demoted to noindex AND listed in its own sitemap, which is the
        # "Submitted URL marked noindex" error Search Console reports back to the tenant. No padding here: the
        # fixture is under the floor on its own.
        page = load_fixture("page-simple-coffee.json")
        page["stripe_mode"] = "live"
        page["status"] = "published"
        s3 = FakeS3Client()
        with patch("stripe_link.runtime.publishing.submit_indexnow") as ping:
            publish_page_document(
                page,
                offers_repository=FakeRepository("offer_id", [load_fixture("offer-simple-coffee.json")]),
                products_repository=FakeRepository("product_id", [load_fixture("product-simple-coffee.json")]),
                sites_repository=FakeSitesRepository([{
                    "tenant_id": "tenant_demo", "site_id": "site_x",
                    "hosting": {"type": "custom", "custom_domain": "shop.example.com",
                                "verification": {"verified": True}},
                    "indexing": {"eligibility": "eligible"},
                    "seo": {"indexnow_key": "k1abc"},
                    "pages": {"/": {"page_id": "page_simple_coffee"}},
                }]),
                s3_client=s3, pages_bucket="pages", preview_bucket="preview", environment="prod",
                pages_domain="pages.example.com", preview_domain="preview.example.com",
                checkout_url="https://checkout.stripe.com/c/pay/demo",
            )
        sitemap = [p for p in s3.puts if p["Key"].endswith("sitemap.xml")][0]["Body"].decode()
        self.assertNotIn("<loc>", sitemap)
        ping.assert_not_called()


class PageHealthTests(unittest.TestCase):
    """A notice has to name something the tenant can DO. plans/LEAD_GEN_PAGES.md §5 makes the bridge page
    permanently noindex, so the thin-content nudge -- "add an FAQ to make it eligible" -- is advice that would
    never work and, if followed, would break the one thing the shape is for."""

    THIN = "<html><body><p>Continue to our new site.</p></body></html>"

    def test_a_thin_ordinary_page_is_still_warned(self):
        from stripe_link.runtime.html import thin_content_warnings

        self.assertTrue(thin_content_warnings(self.THIN))
        self.assertTrue(thin_content_warnings(self.THIN, _offer()))

    def test_a_bridge_page_is_never_nagged_about_being_thin(self):
        from stripe_link.runtime.html import thin_content_warnings

        bridge = _offer(product_intent="lead_gen", lead_capture_action="external_url")
        self.assertEqual(thin_content_warnings(self.THIN, bridge), [])

    def test_no_lead_shape_is_nagged_about_being_thin(self):
        # Widened from bridge-only after the author saw it on a link-in-bio page: "lead-gen pages don't care
        # about word count" (2026-09-10). Being short is the FORM of these pages, not a defect in them -- a
        # squeeze page converts by asking one thing, a call page puts a number above the fold, a link hub is a
        # list of links. Padding any of them to 150 words would damage the page to silence a notice.
        from stripe_link.runtime.html import thin_content_warnings

        for action in ("capture_email", "capture_phone", "capture_email_phone",
                       "call_number", "external_url", "social_redirect"):
            self.assertEqual(
                thin_content_warnings(self.THIN, _offer(product_intent="lead_gen", lead_capture_action=action)),
                [], action)

    def test_a_checkout_page_still_keeps_it(self):
        # There thin really is thin: a product with no description is a page a crawler has no reason to rank,
        # and writing one is work worth doing.
        from stripe_link.runtime.html import thin_content_warnings

        self.assertTrue(thin_content_warnings(self.THIN, _offer(product_intent="transaction")))


if __name__ == "__main__":
    unittest.main()
