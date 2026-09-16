"""The Tip Jar, and what a link hub is allowed to contain.

Author, 2026-09-13: remove the sales-page furniture from Social Pages and add a Tip Jar for this type only.
"""
import json
import os
import pathlib
import unittest
from unittest import mock

from stripe_link.domain.composition import excluded_sections
from stripe_link.domain import tips
from stripe_link.domain.documents import DocumentValidationError, validate_page_document
from stripe_link.domain.social_links import linkable_on_platform_host
from stripe_link.runtime import html as html_module

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES = json.loads((ROOT / "src" / "stripe_link" / "composition_rules.json").read_text(encoding="utf-8"))
BUILDER = (ROOT / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")

LEAD_SOCIAL_BANNED = ("product_details", "related_products", "price_highlight", "content_block", "quote",
                      "testimonials", "rating", "client_marquee", "faq", "before_after")


class LinkHubContentsTests(unittest.TestCase):
    def test_the_sales_page_furniture_is_excluded(self):
        # A link hub is an identity page and a list of destinations. Testimonials, ratings, client logos, an
        # FAQ, a before/after -- these persuade someone of something, and there is nothing here to persuade
        # them of. The name and slogan under the avatar cover the one line of prose these pages want.
        excluded = excluded_sections("lead_social")
        for key in LEAD_SOCIAL_BANNED:
            self.assertIn(key, excluded, key)

    def test_what_a_link_hub_keeps(self):
        # Asserted so a later widening of the exclude list has to be deliberate rather than incidental.
        excluded = excluded_sections("lead_social")
        for key in ("social_links", "link_cards", "tip_jar", "video", "author_bio",
                    "bragging_points", "numbered_list", "page_ribbon", "catalog_grid"):
            self.assertNotIn(key, excluded, key)

    def test_the_add_menu_honours_the_exclusions(self):
        # Three of these (product details, related products, price highlight) were ALREADY excluded and still
        # offered -- is_section_visible short-circuits on excludes, so the button appeared to work and then
        # produced nothing. The list and the rule now come from the same place.
        block = BUILDER.split("const ELEMENT_TYPES = computed(", 1)[1][:400]
        self.assertIn("excludedSections(builderOfferType.value)", block)
        self.assertIn("addableElements().filter", block)


class TipJarAvailabilityTests(unittest.TestCase):
    def test_it_is_offered_on_the_link_hub_and_nowhere_else(self):
        # Expressed as an exclusion everywhere else -- the mechanism the builder already honours, so there is
        # no second list to keep in step. Asserted as an exact set, so a NEW offer type that forgets to
        # exclude it fails here instead of quietly inheriting a tip jar.
        allowed = {key for key, rule in RULES["offer_types"].items()
                   if "tip_jar" not in (rule.get("excludes") or [])}
        self.assertEqual(allowed, {"lead_social"})

    def test_it_has_a_baseline_slot_after_the_links(self):
        # The destinations come first, then the ask: a tip jar above someone's links is begging before
        # introducing yourself.
        order = RULES["default_order"]
        self.assertIn("tip_jar", order)
        self.assertGreater(order.index("tip_jar"), order.index("link_cards"))


class TipJarRenderTests(unittest.TestCase):
    def tearDown(self):
        html_module._RENDER_STATE.pop("own_domain", None)

    def test_no_url_renders_nothing(self):
        # An element that renders a dead control is worse than one that renders nothing.
        self.assertEqual(html_module.render_tip_jar({"id": "tj"}), "")

    def test_it_is_a_link_not_a_checkout(self):
        # This page sells nothing -- lead_social has no checkout_cta and its product carries no price -- so
        # the tip lands wherever the creator already accepts money. Building a payment flow here would give a
        # page that takes no money a way to take money.
        html_module._RENDER_STATE["own_domain"] = True
        markup = html_module.render_tip_jar({"id": "tj", "url": "https://ko-fi.com/acme"})
        self.assertIn('href="https://ko-fi.com/acme"', markup)
        self.assertIn('rel="nofollow ugc noopener"', markup)
        self.assertNotIn("checkout", markup)

    def test_the_default_label_is_not_blank(self):
        html_module._RENDER_STATE["own_domain"] = True
        self.assertIn(">Leave a tip<", html_module.render_tip_jar({"id": "tj", "url": "https://ko-fi.com/a"}))

    def test_a_payment_handle_is_inert_on_a_shared_host(self):
        # §7 and CREATOR_LINK_POLICY §4: payment handles are deliberately off the platform allowlist, because
        # a payment request is the highest-value phishing target there is and one on a shared domain is the
        # single thing most likely to cost us the domain. Inert, not hidden -- the tenant can see why.
        html_module._RENDER_STATE["own_domain"] = False
        markup = html_module.render_tip_jar({"id": "tj", "url": "https://paypal.me/acme"})
        self.assertIn("is-unlinked", markup)
        self.assertNotIn("<a ", markup)

    def test_the_same_handle_works_on_the_tenants_own_domain(self):
        html_module._RENDER_STATE["own_domain"] = True
        markup = html_module.render_tip_jar({"id": "tj", "url": "https://paypal.me/acme"})
        self.assertIn('href="https://paypal.me/acme"', markup)

    def test_its_clicks_are_counted_like_any_other_link(self):
        html_module._RENDER_STATE["own_domain"] = True
        self.assertIn("data-sl-link=", html_module.render_tip_jar({"id": "tj", "url": "https://ko-fi.com/a"}))


class TipJarValidationTests(unittest.TestCase):
    def _page(self, **tip):
        return {"schema_version": "1", "document_type": "page", "tenant_id": "t", "page_id": "p1",
                "name": "P", "offer_id": "o1", "route": {"slug": "p"},
                "sections": [{"id": "tj", "type": "tip_jar", **tip}]}

    def test_a_url_is_required(self):
        validate_page_document(self._page(url="https://ko-fi.com/acme"))
        with self.assertRaises(DocumentValidationError):
            validate_page_document(self._page(label="Leave a tip"))

    def test_the_label_and_note_are_capped(self):
        validate_page_document(self._page(url="https://ko-fi.com/a", label="x" * 40, note="y" * 120))
        with self.assertRaises(DocumentValidationError):
            validate_page_document(self._page(url="https://ko-fi.com/a", label="x" * 41))


class TipJarDestinationTests(unittest.TestCase):
    """Author, 2026-09-15: the element stopped being "paste a URL" and became a picker.

    Four destinations, three of which take a HANDLE rather than a URL. That is the whole security argument:
    a handle cannot be a phishing link, cannot carry a scheme, and builds a host the platform allowlist
    already accepts -- so the free-tier link gate never has to make a judgement call about it.
    """

    def test_every_offered_destination_is_one_the_free_host_can_actually_link(self):
        # An element whose destination renders as an inert button is worse than one we never offered.
        for key, entry in tips.DESTINATIONS.items():
            url = tips.destination_url(key, "someone")
            if not url:
                continue  # junior_bay and other carry no template; they are covered below
            self.assertTrue(linkable_on_platform_host(url), f"{key} is not linkable on a platform host")

    def test_a_handle_is_a_handle_not_a_pasted_url(self):
        self.assertEqual(tips.destination_url("ko_fi", "nora"), "https://ko-fi.com/nora")
        self.assertEqual(tips.destination_url("ko_fi", "@nora"), "https://ko-fi.com/nora")
        for pasted in ("https://ko-fi.com/nora", "ko-fi.com/nora", "nora/tips", "a b", "x?y", "a#b"):
            self.assertEqual(tips.destination_url("ko_fi", pasted), "", pasted)

    def test_a_missing_handle_builds_nothing(self):
        # Which is what makes buildSection drop the element rather than render https://ko-fi.com/ .
        self.assertEqual(tips.destination_url("ko_fi", ""), "")
        self.assertEqual(tips.destination_url("junior_bay", "nora"), "")

    def test_our_own_pages_are_linkable_from_our_own_pages(self):
        # The one destination we can genuinely vouch for was the one the gate refused, because the allowlist
        # was built to answer "which OTHER platforms are safe" and nobody had asked about ours.
        with mock.patch.dict(os.environ, {"PLATFORM_HOSTING_DOMAIN": "jbay.uk"}):
            self.assertTrue(linkable_on_platform_host("https://nora.jbay.uk/tips"))
            self.assertTrue(linkable_on_platform_host("https://juniorbay.com/x"))
            self.assertFalse(linkable_on_platform_host("https://evil.example/x"))

    def test_the_validator_only_accepts_destinations_that_exist(self):
        def page(**tip):
            return {"schema_version": "1", "document_type": "page", "tenant_id": "t", "page_id": "p1",
                    "name": "P", "offer_id": "o1", "route": {"slug": "p"},
                    "sections": [{"id": "tj", "type": "tip_jar", "url": "https://ko-fi.com/nora", **tip}]}

        validate_page_document(page(destination="ko_fi", handle="nora"))
        validate_page_document(page())  # absent is fine: pages predate the picker
        with self.assertRaises(DocumentValidationError):
            validate_page_document(page(destination="venmo"))

    def test_the_builder_resolves_the_url_again_on_save(self):
        # A page whose slug or domain moved leaves a dead button the tenant never sees, because they are not
        # the ones tapping it. So buildSection re-resolves rather than trusting element.url.
        build = BUILDER.split('if (element.type === "tip_jar")', 1)[1][:900]
        self.assertIn("tipDestinationUrl(destination, element.handle)", build)
        self.assertIn("pageUrl(page)", build)

    def test_the_builder_reopens_the_choice_the_tenant_made(self):
        # Without the round-trip a saved Ko-fi button reopens as "Junior Bay" with an empty picker, and the
        # next save silently drops it.
        load = BUILDER.split('type: "tip_jar", heading:', 1)[1][:400]
        for field in ("destination:", "handle:", "page_id:"):
            self.assertIn(field, load)

    def test_a_pre_picker_page_reopens_as_another_link(self):
        # It had a URL and no destination, which is exactly what "Another link" means. Reassigning it to a
        # platform would put someone else's handle in the box.
        load = BUILDER.split('type: "tip_jar", heading:', 1)[1][:400]
        self.assertIn('section.destination || "other"', load)


class TipJarPresentationTests(unittest.TestCase):
    """Author, 2026-09-15: the section read as the least deliberate thing on the page."""

    def _render(self, **section):
        return html_module.render_tip_jar({"id": "tj", "url": "https://ko-fi.com/nora", **section})

    def test_the_button_carries_the_gesture_it_is_asking_for(self):
        markup = self._render(label="Leave a tip")
        self.assertIn("sl-tip-jar-icon", markup)
        self.assertIn("<span>Leave a tip</span>", markup)
        # Announced once, by the label. The drawing repeating it just makes the button take twice as long.
        self.assertIn('aria-hidden="true"', markup)

    def test_the_icon_is_there_when_the_destination_is_not_linkable(self):
        # One glyph, not two states to keep in sync: it inherits currentColor either way.
        markup = html_module.render_tip_jar({"id": "tj", "url": "https://paypal.me/nora"})
        self.assertIn("is-unlinked", markup)
        self.assertIn("sl-tip-jar-icon", markup)

    def test_the_section_is_a_panel_and_follows_the_theme(self):
        css = "\n".join(html_module.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
        rule = [line for line in css.splitlines() if ".sl-tip-jar{" in line][0]
        self.assertIn("padding:", rule)
        self.assertIn("border-radius:", rule)
        # Mixed from the accent, not a picked colour: a fixed tint fights every preset it was not drawn for.
        self.assertIn("var(--sl-accent)", rule)
        self.assertIn("@supports not (background:color-mix", css)

    def test_the_pitch_offers_a_button_rather_than_a_link(self):
        # An action that takes the tenant somewhere and changes what they have is the one thing a phrase in
        # a paragraph reads as least like.
        pitch = BUILDER.split("tip-jar-pitch", 1)[1][:1200]
        self.assertIn("<button", pitch)
        # It is handed THIS element, because provisioning ends by selecting the page it just made -- a
        # button that creates a page and then leaves the picker empty has done half a job.
        self.assertIn("startTipJarProduct(element)", pitch)
        # Disabled while it runs: four documents take a moment, and a second click during it is the one
        # input most likely to happen.
        self.assertIn(":disabled=\"tipJarCreating\"", pitch)


class LinkCardNoteTests(unittest.TestCase):
    def test_the_note_uses_the_one_colour_the_theme_guarantees(self):
        # It inherited the card's ink at 80% and was very nearly invisible on a dark card. --sl-legal-link is
        # legible against the page ground by construction, because the footer's links depend on it.
        css = "\n".join(html_module.UNIVERSAL_BUNDLE_TEMPLATE_STYLES)
        note = [line for line in css.splitlines() if ".sl-link-card-note{" in line][0]
        self.assertIn("color:var(--sl-legal-link)", note)
        self.assertNotIn("opacity:.8", note)


if __name__ == "__main__":
    unittest.main()
