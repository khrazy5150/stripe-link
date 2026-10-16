"""A Page Ribbon can carry no button at all, or the page's own ask.

Author, 2026-10-15: *"most landing pages, especially long ones, have several buttons that act like the CTA
button for variety."* Two actions came out of that (plans/RIBBON_ACTIONS.md §6, §7).

`none` was already honoured by the renderer and had simply never been offered in the builder.

`cta` is the interesting one, and its whole design is that there is ONE emitter. `render_buy_cta` resolves
the price, the Stripe mode, the coupon, the cart endpoint, the post-purchase funnel and the BNPL methods
into its button; a ribbon that re-derived any of that would disagree the first time one changed. So both
call `page_ask_attrs`, and on a lead page both open the same single form.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from stripe_link.runtime import html as html_mod  # noqa: E402
from stripe_link.runtime.html import (  # noqa: E402
    RIBBON_ACTIONS, page_ask_attrs, render_buy_cta, render_email_cta, render_page_ribbon,
)

BUY = {"product_intent": "transaction"}
LEAD = {"offer_id": "o1", "product_intent": "lead_gen", "items": [{"product_id": "pr1"}]}
PRODUCTS = {"pr1": {"lead_capture": {"action": "capture_email", "title": "Save your seat",
                                     "fields": [{"name": "email", "type": "email", "required": True}]}}}
DIALOG_PAGE = {"tenant_id": "t1", "page_id": "p1",
               "sections": [{"type": "checkout_cta", "id": "c", "form_presentation": "dialog"}]}
INLINE_PAGE = {"tenant_id": "t1", "page_id": "p1",
               "sections": [{"type": "checkout_cta", "id": "c"}]}


def ribbon(action, page=None, offer=None, **kw):
    section = {"id": "r", "headline": "Ready?", "cta": {"action": action, "label": "Get access"}}
    return render_page_ribbon(section, page or {}, None, offer=offer, **kw)


class NoActionTests(unittest.TestCase):
    def test_none_is_a_real_action(self):
        self.assertIn("none", RIBBON_ACTIONS)

    def test_it_renders_the_banner_without_a_button(self):
        markup = ribbon("none")
        self.assertIn("sl-page-ribbon", markup)
        self.assertNotIn("sl-ribbon-cta", markup)

    def test_the_builder_now_offers_it(self):
        """It was honoured by the server and absent from the dropdown, which is a capability nobody could
        reach. That is the whole of §6."""
        builder = (pathlib.Path(__file__).resolve().parents[1]
                   / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")
        self.assertIn('<option value="none">', builder)
        self.assertIn('<option value="cta">', builder)


class ActsLikeTheBuyButtonTests(unittest.TestCase):
    def test_it_carries_the_checkout_action(self):
        markup = ribbon("cta", offer=BUY, resolved_offer={"subtotal": 1450, "currency": "usd"},
                        checkout_url="https://pay.example/c")
        self.assertIn("sl-ribbon-cta-ask", markup)
        self.assertIn("https://pay.example/c", markup)
        self.assertIn("data-checkout-base-url", markup)

    def test_it_is_the_SAME_action_the_page_cta_uses(self):
        """The point of the shared emitter: not similar markup, the same answer."""
        shared = page_ask_attrs({}, BUY, {"subtotal": 1450, "currency": "usd"}, "https://pay.example/c", None)
        self.assertIsNotNone(shared)
        attrs, tag = shared
        self.assertEqual(tag, "a")
        markup = ribbon("cta", offer=BUY, resolved_offer={"subtotal": 1450, "currency": "usd"},
                        checkout_url="https://pay.example/c")
        self.assertIn(attrs, markup)

    def test_it_keeps_its_own_label_and_never_appends_the_price(self):
        """Variety is the point — a mid-page button rarely wants the same words, and a second button
        showing a stale amount is its own bug."""
        markup = ribbon("cta", offer=BUY, resolved_offer={"subtotal": 1450, "currency": "usd"},
                        checkout_url="https://pay.example/c")
        self.assertIn(">Get access<", markup)
        self.assertNotIn("14.50", markup)

    def test_it_mirrors_the_page_cta_even_when_that_is_a_placeholder(self):
        """With no checkout_url the page CTA emits `#checkout` for the island to resolve. The ribbon emits
        the same thing, because mirroring the page's ask is the entire contract — including when the page's
        ask is itself deferred. Asserted against `render_buy_cta` rather than a hardcoded string, so the two
        cannot drift apart without this failing."""
        import re

        page_cta = render_buy_cta({}, {"label": "Buy"}, BUY, {"subtotal": 1450, "currency": "usd"}, None)
        expected = re.search(r'<a class="sl-cta" href="([^"]*)"', page_cta).group(1)
        markup = ribbon("cta", offer=BUY, resolved_offer={"subtotal": 1450, "currency": "usd"},
                        checkout_url=None)
        self.assertIn(f'href="{expected}"', markup)

    def test_a_lead_offer_never_gets_the_checkout_action(self):
        """The buy branch must not catch a lead page: its ask is a form, not a link."""
        self.assertIsNone(page_ask_attrs(INLINE_PAGE, LEAD, {}, "https://pay.example/c", None, PRODUCTS))


class ActsLikeTheLeadButtonTests(unittest.TestCase):
    def setUp(self):
        html_mod._RENDER_LEAD_DIALOG.clear()
        html_mod._RENDER_EVENTS.clear()

    def render_cta(self, page):
        return render_email_cta(page, LEAD, {"label": "Reserve"}, PRODUCTS, "https://api.example",
                                section=next(s for s in page["sections"] if s["type"] == "checkout_cta"))

    def test_dialog_mode_gives_the_ribbon_something_to_open(self):
        self.render_cta(DIALOG_PAGE)
        markup = ribbon("cta", page=DIALOG_PAGE, offer=LEAD, products_by_id=PRODUCTS)
        self.assertIn("data-lead-open", markup)
        self.assertIn("<button", markup)

    def test_inline_mode_renders_no_ribbon_button(self):
        """There is no button to copy and a second form would never be bound — the lead handler is
        querySelector('[data-lead-form]'), singular. An ask that cannot be honoured is worse than none."""
        self.render_cta(INLINE_PAGE)
        self.assertNotIn("sl-ribbon-cta", ribbon("cta", page=INLINE_PAGE, offer=LEAD, products_by_id=PRODUCTS))

    def test_the_form_stays_a_single_instance(self):
        markup = self.render_cta(DIALOG_PAGE)
        self.assertEqual(markup.count("data-lead-form"), 1)
        self.assertEqual(markup.count("<dialog"), 1)

    def test_the_answer_does_not_depend_on_render_order(self):
        """A tenant may drag a ribbon ABOVE the CTA. The mode is read from the PAGE, so the ribbon gets the
        same answer whichever renders first."""
        self.assertTrue(html_mod.lead_dialog_enabled(DIALOG_PAGE))
        self.assertFalse(html_mod.lead_dialog_enabled(INLINE_PAGE))


class TheClosedGateIsSharedTests(unittest.TestCase):
    """A ribbon must not open a registration modal for a webinar that ran last week."""

    def setUp(self):
        html_mod._RENDER_LEAD_DIALOG.clear()
        html_mod._RENDER_EVENTS.clear()

    def test_a_passed_event_turns_off_the_ribbon_button_too(self):
        html_mod._RENDER_EVENTS["ev1"] = {
            "event_id": "ev1", "title": "Webinar",
            "occurrences": [{"occurrence_id": "o", "starts_at": 1, "status": "scheduled"}],
        }
        products = {"pr1": {"lead_capture": {"action": "register_event", "event_id": "ev1",
                                             "fields": [{"name": "email", "type": "email"}]}}}
        self.assertFalse(html_mod.lead_form_is_open(LEAD, products))
        self.assertNotIn("sl-ribbon-cta",
                         ribbon("cta", page=DIALOG_PAGE, offer=LEAD, products_by_id=products))

    def test_an_offer_with_no_event_always_has_a_form(self):
        self.assertTrue(html_mod.lead_form_is_open(LEAD, PRODUCTS))


if __name__ == "__main__":
    unittest.main()


class TheBuilderActuallySavesThemTests(unittest.TestCase):
    """Both new actions have no TARGET, and the serializer's closing rule is "no target, no button".

    It discarded the whole cta object, so the section stored `cta: null`, and on reload the editor fell
    back to `section.cta?.action || "redirect"`. The tenant picked an option, saved, and found it had
    reverted to "Opens a link" — reported as the dropdown being stuck (2026-10-15). Shipping an option the
    save path throws away is worse than not shipping it.
    """

    BUILDER = None

    @classmethod
    def setUpClass(cls):
        cls.BUILDER = (pathlib.Path(__file__).resolve().parents[1]
                       / "dashboard" / "src" / "components" / "LandingPages.vue").read_text(encoding="utf-8")

    def serializer(self):
        body = self.BUILDER.split("function ribbonCta(cta) {", 1)[1]
        return body[:body.index("\n}")]

    def test_both_targetless_actions_survive_the_save(self):
        body = self.serializer()
        self.assertIn('if (action === "none") return', body)
        self.assertIn('if (action === "cta") return { cta: { label, action } };', body)

    def test_they_are_handled_BEFORE_the_target_rule(self):
        """The rule that discarded them is still correct for everything that needs a destination."""
        body = self.serializer()
        self.assertLess(body.index('action === "cta"'), body.index('const target = (cta.target'))
        self.assertLess(body.index('action === "none"'), body.index('const target = (cta.target'))

    def test_a_banner_needs_no_label(self):
        """`none` renders no button, so requiring a label to store the choice would lose it again."""
        body = self.serializer()
        self.assertLess(body.index('action === "none"'), body.index("if (!label) return {};"))

    def test_a_link_without_a_url_still_renders_no_button(self):
        self.assertIn("return target ? { cta: { label, action, target } } : {};", self.serializer())

    def test_neither_is_asked_for_a_destination(self):
        """An empty Link box beside an action that never reads one is a question with no answer."""
        self.assertIn("element.cta.action === 'none'", self.BUILDER)
        self.assertIn("element.cta.action === 'cta'", self.BUILDER)
