"""The shipping element on the thank-you page.

plans/THANK_YOU_PAGE.md P2. The page is a static artifact serving every buyer, so the DATE cannot be baked
in — the shell renders with a neutral line and an island fills it from the order behind the `session_id`
already in the URL.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from stripe_link.runtime.html import render_shipping_eta
from stripe_link.runtime.upsell_pages import synthesize_thank_you_page

NODE = shutil.which("node")


class ItComesFirstTests(unittest.TestCase):
    """The author's requirement: *"the shipping element for physical products must be the very first thing
    that appears after the headline and subheadline."* It is the one thing a buyer opened this page to find
    out, and burying it under a paragraph of reassurance is how it ends up unread."""

    def _types(self, page_override=None):
        page = {"theme": {}}
        if page_override:
            page["post_checkout"] = {"thank_you_page": page_override}
        rendered, _offer = synthesize_thank_you_page(page, {"offer_id": "o1", "tenant_id": "t1"})
        return [s["type"] for s in rendered["sections"]]

    def test_it_sits_between_the_subheadline_and_the_message(self):
        types = self._types()
        self.assertEqual(types.index("shipping_eta"), types.index("subheadline") + 1)
        self.assertLess(types.index("shipping_eta"), types.index("content_block"))

    def test_it_is_above_the_next_steps_cards(self):
        types = self._types()
        self.assertLess(types.index("shipping_eta"), types.index("next_steps"))

    def test_a_tenant_may_turn_it_off(self):
        self.assertNotIn("shipping_eta", self._types({"enable_shipping_eta": False}))

    def test_the_tenant_owns_the_icon_and_title(self):
        page = {"theme": {}, "post_checkout": {"thank_you_page": {
            "shipping_eta_icon": "🚚", "shipping_eta_title": "On its way"}}}
        rendered, _ = synthesize_thank_you_page(page, {"offer_id": "o1", "tenant_id": "t1"})
        card = next(s for s in rendered["sections"] if s["type"] == "shipping_eta")
        self.assertEqual((card["icon"], card["title"]), ("🚚", "On its way"))


class TheShellIsTrueWithoutJavaScriptTests(unittest.TestCase):
    """A buyer whose script never runs must not read a date nobody computed for them — nor the "Free
    Shipping / arrives within 5-7 business days" this element exists to delete."""

    HTML = render_shipping_eta({"icon": "📦", "title": "Shipping"})

    def test_it_promises_tracking_rather_than_a_date(self):
        self.assertIn("We&#x27;ll email tracking details as soon as it ships.", self.HTML)

    def test_it_invents_no_number_of_days(self):
        self.assertNotIn("business days", self.HTML)
        self.assertNotIn("Free Shipping", self.HTML)

    def test_the_body_is_generated_not_typed(self):
        # The section carries no `desc` the tenant could fill with a claim about delivery.
        rendered = render_shipping_eta({"title": "Shipping", "desc": "Arrives tomorrow, guaranteed!"})
        self.assertNotIn("guaranteed", rendered)


class ThePreviewShowsAMarkedExampleTests(unittest.TestCase):
    """The builder has no order. Without a visible example the first thing every tenant does is report the
    thank-you page as broken."""

    EXAMPLE = render_shipping_eta({"title": "Shipping",
                                   "example": "Estimated to arrive Thursday, October 8."})

    def test_the_example_renders(self):
        self.assertIn("Estimated to arrive Thursday, October 8.", self.EXAMPLE)

    def test_it_is_labelled_as_one(self):
        self.assertIn("your buyers see their own date", self.EXAMPLE)

    def test_a_preview_does_not_try_to_fetch_an_order(self):
        self.assertNotIn("<script>", self.EXAMPLE)


class TheIslandTests(unittest.TestCase):
    HTML = render_shipping_eta({"icon": "📦", "title": "Shipping"})
    JS = re.search(r"<script>(.*)</script>", HTML, re.S).group(1)

    def test_one_fetch_serves_both_the_element_and_the_token(self):
        """They are the same promise worded differently. Two requests could disagree, and a date that
        disagrees with itself on one page is worse than no date."""
        self.assertEqual(self.JS.count("fetch("), 1)
        self.assertIn("{{arrival}}", self.JS)
        self.assertIn("sl-ship-eta-line", self.JS)

    def test_no_parcel_removes_the_element_entirely(self):
        """Only the ORDER knows whether anything ships, and this page is one artifact serving every buyer.
        A digital order must not be reassured about a delivery it is not expecting."""
        self.assertIn("box.remove()", self.JS)

    def test_a_missing_session_leaves_the_shell_alone(self):
        # A preview or a direct visit: do not ask about an order that does not exist.
        self.assertIn("if (!api || !tenant || !session) return;", self.JS)

    def test_it_fails_silently(self):
        self.assertIn(".catch(function(){});", self.JS)

    def test_it_does_not_word_the_date_itself(self):
        """`promise_sentence` and `arrival_phrase` are the one formatter. A JS copy would be a second way
        to say the same date."""
        for leak in ("January", "Monday", "Estimated to arrive", "business day"):
            self.assertNotIn(leak, self.JS)

    @unittest.skipIf(NODE is None, "node is not installed; cannot parse the emitted JavaScript")
    def test_it_is_valid_javascript(self):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
            handle.write(self.JS)
            path = handle.name
        try:
            result = subprocess.run([NODE, "--check", path], capture_output=True, text=True)
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class TheEndpointWordsItTests(unittest.TestCase):
    SOURCE = (Path(__file__).resolve().parents[1] / "src" / "handlers" / "upsell.py").read_text()

    def test_the_promise_is_read_not_recomputed(self):
        """Settled when the order was written. A date that moves on a page refresh is not a promise."""
        block = self.SOURCE.split("def _delivery_promise", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('order.get("delivery_estimate")', block)
        self.assertNotIn("promise_for(", block)

    def test_it_sends_the_worded_strings(self):
        block = self.SOURCE.split("def _delivery_promise", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("promise_sentence(promise)", block)
        self.assertIn("arrival_phrase(promise)", block)

    def test_the_order_is_found_by_key_not_by_scan(self):
        block = self.SOURCE.split("def _delivery_promise", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('f"order_{session_id}"', block)

    def test_an_unreachable_order_is_an_empty_dict(self):
        block = self.SOURCE.split("def _delivery_promise", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("except Exception", block)
