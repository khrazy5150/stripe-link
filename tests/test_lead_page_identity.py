"""Why a link-in-bio page rendered nothing, and why it was told off for it.

From a live sandbox report (2026-09-10): a Social Page with `social_links` added showed an empty preview and
two page-health notices. Three separate causes, all of them the page being judged by checkout-page rules.

1. The section renders from the SITE, and a page is attached to its Site on SAVE. So a page under
   construction had no Site, no Organization, and therefore no profiles -- while the editor beside it
   explained what it would show. On a checkout page the same gap is nearly invisible (the product carries
   the content); here it was the whole page.
2. The thin-content notice told the tenant to pad a page whose form is to be short.
3. The missing-H1 notice named a heading the COMPOSITION had removed, so there was nothing the tenant
   could do about it.
"""
import pathlib
import unittest

from stripe_link.domain.composition import is_lead_composition
from stripe_link.runtime import html as html_module

DASHBOARD = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src"
BUILDER = (DASHBOARD / "components" / "LandingPages.vue").read_text(encoding="utf-8")
RENDER_HANDLER = (pathlib.Path(__file__).resolve().parents[1]
                  / "src" / "handlers" / "page_render.py").read_text(encoding="utf-8")


def _offer(**overrides):
    offer = {"offer_id": "off_1", "items": [{"product_id": "p1"}], "presentation": {}}
    offer.update(overrides)
    return offer


def _lead(action):
    return _offer(product_intent="lead_gen", lead_capture_action=action)


class ThinContentTests(unittest.TestCase):
    THIN = "<html><body><p>Tap a link below.</p></body></html>"

    def test_no_lead_shape_is_told_to_add_words(self):
        for action in ("capture_email", "capture_phone", "capture_email_phone",
                       "call_number", "external_url", "social_redirect"):
            self.assertTrue(is_lead_composition(_lead(action)), action)
            self.assertEqual(html_module.thin_content_warnings(self.THIN, _lead(action)), [], action)

    def test_a_checkout_page_still_gets_the_notice(self):
        # The scope of the change. There thin really is thin -- a product with no description is a page a
        # crawler has no reason to rank, and writing one is work worth doing.
        self.assertTrue(html_module.thin_content_warnings(self.THIN, _offer(product_intent="transaction")))
        self.assertTrue(html_module.thin_content_warnings(self.THIN))  # no offer given: unchanged behaviour


class BrandLabelHeadingTests(unittest.TestCase):
    """The missing H1 is FIXED, not silenced.

    Suppressing the notice would have left the page genuinely without a main heading, which is bad for search
    and worse for a screen reader. A link hub does have a heading -- the creator's name -- it just was not
    marked as one. So the brand mark becomes the H1 exactly when no other section claims it.
    """

    PAGE = {"page_id": "p1", "name": "My Links"}

    def _brand(self, has_h1_elsewhere):
        html_module._RENDER_STATE["brand_label_is_h1"] = not has_h1_elsewhere
        return html_module.render_brand_label({"id": "b1", "label": "Poliaxis"}, self.PAGE)

    def tearDown(self):
        html_module._RENDER_STATE.pop("brand_label_is_h1", None)

    def test_it_is_the_h1_when_nothing_else_is(self):
        markup = self._brand(has_h1_elsewhere=False)
        self.assertIn("<h1>", markup)
        self.assertNotIn("<p>", markup)

    def test_it_stays_a_paragraph_when_a_hero_owns_the_h1(self):
        markup = self._brand(has_h1_elsewhere=True)
        self.assertIn("<p>", markup)
        self.assertNotIn("<h1>", markup)

    def test_a_legacy_headline_section_still_counts(self):
        # Pages saved before the hero family merged store `headline` as its own section. Checking only for
        # "hero" would have handed the H1 to the brand mark on every one of them -- giving them TWO, which is
        # the notice this change exists to remove, inverted.
        self.assertEqual(html_module.H1_SECTION_TYPES, frozenset({"hero", "headline", "brand_hero"}))

    def test_the_styling_does_not_depend_on_the_tag(self):
        # Which tag it is says what the heading MEANS, never how it looks. A bare h1 would otherwise arrive
        # with the browser's default size and margin, and the brand mark would jump on exactly these pages.
        css = "\n".join(html_module.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
        self.assertIn(".sl-brand-label p,.sl-brand-label h1{", css)
        self.assertIn("margin:0}", css.split(".sl-brand-label p,.sl-brand-label h1{")[1][:400])


class PreviewSiteResolutionTests(unittest.TestCase):
    def test_the_preview_falls_back_to_the_named_site(self):
        self.assertIn('hint = str(body.get("site_id") or "").strip()', RENDER_HANDLER)
        self.assertIn("sites_repo.get(tenant_id, hint)", RENDER_HANDLER)

    def test_the_tenant_is_never_taken_from_the_request(self):
        # The whole safety of the hint. It names WHICH of the tenant's own Sites to read; the tenant comes
        # from the page document, and the repository is tenant-scoped, so a forged site_id resolves to
        # nothing rather than to someone else's Site.
        block = RENDER_HANDLER.split("hint = str(", 1)[1][:400]
        self.assertNotIn('body.get("tenant_id")', block)
        self.assertIn("sites_repo.get(tenant_id, hint)", block)

    def test_publish_does_not_take_the_hint(self):
        # Preview only. At publish, attachment decides whether the page serves at all, so inventing one
        # would make the publisher lie about where the page lives.
        publishing = (pathlib.Path(__file__).resolve().parents[1]
                      / "src" / "stripe_link" / "runtime" / "publishing.py").read_text(encoding="utf-8")
        self.assertNotIn('body.get("site_id")', publishing)

    def test_the_builder_sends_one(self):
        self.assertIn("site_id: builderSiteId.value || undefined,", BUILDER)
        self.assertIn("const builderSiteId = computed(", BUILDER)

    def test_the_builder_prefers_the_real_attachment(self):
        # Order matters: an attached page's own Site beats the wizard's leftover choice, and the
        # single-Site fallback only fires when there is nothing to get wrong.
        block = BUILDER.split("const builderSiteId = computed(", 1)[1][:500]
        self.assertLess(block.index("siteByPageId"), block.index("pendingSiteAttach"))
        self.assertLess(block.index("pendingSiteAttach"), block.index("sitesStore.sites.length === 1"))


class SocialLinksEmptyStateTests(unittest.TestCase):
    def test_the_editor_says_when_it_would_render_nothing(self):
        # A row that silently renders nothing, beside prose explaining what it WOULD render, is how a tenant
        # concludes the feature is broken.
        self.assertIn('v-else class="element-empty is-warning"', BUILDER)
        self.assertIn("No links yet, so this section shows nothing.", BUILDER)

    def test_the_editor_offers_both_directions(self):
        # Override and inherit are both one button, the way the page avatar already does it. A one-way door
        # would make trying the page-local list a decision rather than an experiment.
        self.assertIn("Use links just for this page", BUILDER)
        self.assertIn("Use my Site's profiles", BUILDER)

    def test_the_editor_reads_the_same_site_the_preview_does(self):
        # Both off builderSiteId. Two lookups would eventually disagree about whether there is anything to
        # show, and the editor is precisely where the tenant would be told the wrong one.
        block = BUILDER.split("const builderSiteProfiles = computed(", 1)[1][:300]
        self.assertIn("builderSiteId.value", block)


class UnattachedPublishTests(unittest.TestCase):
    """Publishing a link hub with no Site is an ERROR, not a degraded page.

    Every other page type publishes fine without a Site -- it loses the store's name and its Organization
    graph, which degrades the page. A link hub loses everything it has, because the Site is not the identity
    around the content, it IS the content.
    """

    PUBLISHING = (pathlib.Path(__file__).resolve().parents[1]
                  / "src" / "stripe_link" / "runtime" / "publishing.py").read_text(encoding="utf-8")

    def test_the_guard_is_scoped_to_the_link_hub(self):
        self.assertIn('composition_key(offer) == "lead_social"', self.PUBLISHING)

    def test_a_draft_may_still_be_incomplete(self):
        # publish_page_document also runs on a draft save (it always writes the preview artifact). Without the
        # status gate a Social Page would have been unsaveable until its Site existed, which is worse than the
        # bug it fixes -- a draft is allowed to be unfinished, that is what a draft is.
        guard = self.PUBLISHING.split("if (site is None", 1)[1][:300]
        self.assertIn('page.get("status") == "published"', guard)

    def test_a_page_with_its_own_links_needs_no_site(self):
        # The guard's real subject is "would render nothing", not "has a Site". A creator who lists their links
        # on the page has a working hub without ever opening the Sites screen, which is the whole point of the
        # page-local override.
        guard = self.PUBLISHING.split("if (site is None", 1)[1][:300]
        self.assertIn("not page_has_own_social_links(page)", guard)

    def test_the_message_names_both_ways_out(self):
        # Either fix works, so the message says both. Naming only one would send a creator to the Sites screen
        # they were deliberately spared.
        self.assertIn("list them on the page itself", self.PUBLISHING)
        self.assertIn("attach the page to a", self.PUBLISHING)

    def test_the_builder_warns_before_publish_is_reached(self):
        # The server guard is the backstop. The tenant should learn this from the pane that is showing them
        # the comforting half of the truth, not from an error after they press Publish.
        self.assertIn('v-if="previewNeedsSite"', BUILDER)
        self.assertIn("const previewNeedsSite = computed(", BUILDER)
        block = BUILDER.split("const previewNeedsSite = computed(", 1)[1][:300]
        self.assertIn('builderOfferType.value === "lead_social"', block)
        self.assertIn("siteByPageId.value[builder.page_id]", block)


if __name__ == "__main__":
    unittest.main()


class BrandLabelResolutionTests(unittest.TestCase):
    """The brand label is DERIVED, not frozen.

    Found 2026-09-11 by rendering a real sandbox page: a link hub headed "Junior Bay". The wizard's draft
    hardcoded `label: formatHeadline("Junior Bay")` -- the PLATFORM's name, written into the tenant's document
    as though they had typed it. A stored label beats every fallback, so it outlived attaching a Site, filling
    in the Business Profile, and both of this week's fixes to the render-time chain.

    Same by-reference rule the page avatar already follows: store the override, resolve the default.
    """

    PAGE = {"page_id": "p1", "name": "My Links Landing Page", "seo": {}}

    def tearDown(self):
        html_module._RENDER_ORG.clear()
        html_module._RENDER_STATE.pop("brand_label_is_h1", None)

    def _render(self, section, org=None):
        html_module._RENDER_ORG.clear()
        html_module._RENDER_ORG.update(org or {})
        return html_module.render_brand_label({"id": "b1", **section}, self.PAGE)

    def test_the_tenants_own_words_always_win(self):
        self.assertIn("Poliaxis", self._render({"label": "Poliaxis"}, {"name": "Other Co"}))

    def test_it_falls_back_to_the_site_not_the_page_name(self):
        # A brand label names the BUSINESS, not the document. Falling through to the page name showed a
        # visitor a filename -- "My Links Landing Page" -- on the one page type where the heading is the
        # creator's identity.
        markup = self._render({}, {"name": "Poliaxis Nutrition"})
        self.assertIn("Poliaxis Nutrition", markup)
        self.assertNotIn("Landing Page", markup)

    def test_the_page_name_is_still_the_last_resort(self):
        self.assertIn("My Links Landing Page", self._render({}))

    def test_the_wizard_no_longer_bakes_the_platform_name_in(self):
        self.assertNotIn('label: formatHeadline("Junior Bay")', BUILDER)

    def test_only_typed_text_is_persisted(self):
        # Storing the RESOLVED default would freeze today's answer into the document: rename the business or
        # attach a Site and the page would go on showing whatever was true when it was first saved.
        block = BUILDER.split('type: "brand_label",\n      enabled: true,\n      // ONLY what the tenant typed', 1)
        self.assertEqual(len(block), 2, "the brand_label push no longer writes a resolved default")
        self.assertIn('label: formatHeadline(builder.brand_label_text || "") || undefined,', BUILDER)
